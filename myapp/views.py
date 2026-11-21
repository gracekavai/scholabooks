import json
import logging
from os import getenv
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    CashBookFilterForm,
    PaymentForm,
    StudentAuthenticationForm,
    StudentFeePaymentForm,
    StudentForm,
    StudentPasswordChangeForm,
)
from .daraja import DarajaError, initiate_stk_push, normalize_phone_number
from .models import FeePaymentRequest, Payment, Student


logger = logging.getLogger(__name__)
staff_required = user_passes_test(lambda user: user.is_staff, login_url='login')


def student_portal_required(view):
    @wraps(view)
    def wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f'{reverse("student-login")}?next={request.path}')
        if request.user.is_staff:
            return redirect('student-login')
        account = getattr(request.user, 'student_portal_account', None)
        if account is None:
            return redirect(f'{reverse("student-login")}?next={request.path}')
        if account.must_change_password and view.__name__ != 'student_password_change':
            return redirect('student-password-change')
        request.student = account.student
        return view(request, *args, **kwargs)

    return wrapped_view


def student_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('dashboard')
    if request.user.is_authenticated:
        account = getattr(request.user, 'student_portal_account', None)
        if account is not None:
            if account.must_change_password:
                return redirect('student-password-change')
            return redirect('student-portal')

    form = StudentAuthenticationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        student_user = form.get_user()
        login(request, student_user, backend='django.contrib.auth.backends.ModelBackend')
        if student_user.student_portal_account.must_change_password:
            return redirect('student-password-change')
        return redirect('student-portal')
    return render(request, 'student_login.html', {'form': form})


def student_logout(request):
    if (
        request.method == 'POST'
        and request.user.is_authenticated
        and not request.user.is_staff
        and hasattr(request.user, 'student_portal_account')
    ):
        logout(request)
    return redirect('student-portal')


@student_portal_required
def student_password_change(request):
    form = StudentPasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        request.student.portal_account.must_change_password = False
        request.student.portal_account.save(update_fields=['must_change_password'])
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, 'Your password has been updated.')
        return redirect('student-portal')
    return render(request, 'student_password_change.html', {'form': form})


@student_portal_required
def student_portal(request):
    payments = request.student.payments.order_by('-payment_date', '-pk')[:10]
    payment_requests = request.student.fee_payment_requests.filter(
        status=FeePaymentRequest.STATUS_PENDING,
    )
    return render(request, 'student_portal_home.html', {
        'student': request.student,
        'payments': payments,
        'payment_requests': payment_requests,
    })


@student_portal_required
def student_portal_statement(request):
    student = request.student
    payments = student.payments.order_by('payment_date', 'pk')
    running_balance = student.fee_total
    entries = [{
        'date': student.admission_date,
        'reference': student.admission_number,
        'description': 'School fees charged',
        'debit': student.fee_total,
        'credit': None,
        'balance': running_balance,
        'payment': None,
    }]
    for payment in payments:
        running_balance -= payment.amount
        entries.append({
            'date': payment.payment_date,
            'reference': payment.receipt_number,
            'description': f'Fee payment - {payment.get_payment_method_display()}',
            'debit': None,
            'credit': payment.amount,
            'balance': running_balance,
            'payment': payment,
        })
    return render(request, 'student_portal_statement.html', {
        'student': student,
        'entries': entries,
    })


@student_portal_required
def student_make_payment(request):
    form = StudentFeePaymentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        payment_request = form.save(commit=False)
        payment_request.student = request.student
        if payment_request.method == FeePaymentRequest.METHOD_PAYBILL:
            payment_request.phone_number = ''
            payment_request.paybill_reference = (
                form.cleaned_data['paybill_reference'] or None
            )
        else:
            payment_request.paybill_reference = None

        try:
            with transaction.atomic():
                payment_request.save()
        except IntegrityError:
            form.add_error(
                'paybill_reference',
                'This M-Pesa transaction code has already been submitted.',
            )
        else:
            if payment_request.method == FeePaymentRequest.METHOD_STK:
                try:
                    response = initiate_stk_push(payment_request)
                except DarajaError as error:
                    payment_request.status = FeePaymentRequest.STATUS_FAILED
                    payment_request.status_message = str(error)[:250]
                    payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
                else:
                    payment_request.checkout_request_id = response['CheckoutRequestID']
                    payment_request.merchant_request_id = response['MerchantRequestID']
                    payment_request.status_message = (
                        response.get('CustomerMessage')
                        or 'Check your phone and complete the M-Pesa prompt.'
                    )[:250]
                    payment_request.save(update_fields=[
                        'checkout_request_id',
                        'merchant_request_id',
                        'status_message',
                        'updated_at',
                    ])
            else:
                payment_request.status_message = (
                    'Submitted for school office verification. Your balance updates after confirmation.'
                )
                payment_request.save(update_fields=['status_message', 'updated_at'])
            return redirect('student-payment-status', pk=payment_request.pk)

    return render(request, 'student_payment_form.html', {
        'student': request.student,
        'form': form,
        'mpesa_paybill': getenv('SCHOOL_MPESA_PAYBILL', ''),
    })


@student_portal_required
def student_payment_status(request, pk):
    payment_request = get_object_or_404(
        FeePaymentRequest,
        pk=pk,
        student=request.student,
    )
    return render(request, 'student_payment_status.html', {
        'student': request.student,
        'payment_request': payment_request,
    })


@csrf_exempt
@require_POST
def daraja_stk_callback(request):
    try:
        payload = json.loads(request.body)
        callback = payload['Body']['stkCallback']
        checkout_id = callback['CheckoutRequestID']
        result_code = int(callback['ResultCode'])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning('Received malformed Daraja STK callback')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Invalid callback'}, status=400)

    try:
        payment_request = FeePaymentRequest.objects.get(
            checkout_request_id=checkout_id,
            method=FeePaymentRequest.METHOD_STK,
        )
    except FeePaymentRequest.DoesNotExist:
        logger.warning('Received Daraja callback for an unknown checkout request')
        return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Unknown checkout request'}, status=404)

    with transaction.atomic():
        payment_request = FeePaymentRequest.objects.select_for_update().get(pk=payment_request.pk)
        if payment_request.status != FeePaymentRequest.STATUS_PENDING:
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Already processed'})
        if callback.get('MerchantRequestID') != payment_request.merchant_request_id:
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = 'M-Pesa request could not be verified.'
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        if result_code != 0:
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = callback.get(
                'ResultDesc',
                'M-Pesa payment was not completed.',
            )[:250]
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        try:
            callback_items = callback['CallbackMetadata']['Item']
            metadata = {
                item['Name']: item.get('Value')
                for item in callback_items
                if isinstance(item, dict) and 'Name' in item
            }
            receipt_number = str(metadata['MpesaReceiptNumber']).strip().upper()
            callback_amount = Decimal(str(metadata['Amount']))
            callback_phone = normalize_phone_number(str(metadata['PhoneNumber']))
            expected_phone = normalize_phone_number(payment_request.phone_number)
        except (KeyError, TypeError, ValueError, InvalidOperation, DarajaError):
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = 'M-Pesa confirmation details could not be verified.'
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        expected_phone = normalize_phone_number(payment_request.phone_number)
        if (
            not receipt_number
            or receipt_number == 'NONE'
            or len(receipt_number) > 50
            or not callback_amount.is_finite()
            or callback_amount != payment_request.amount
            or callback_phone != expected_phone
        ):
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = 'M-Pesa confirmation did not match the requested payment.'
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        transaction_date = metadata.get('TransactionDate')
        try:
            paid_date = (
                datetime.strptime(str(transaction_date), '%Y%m%d%H%M%S').date()
                if transaction_date
                else timezone.localdate()
            )
        except ValueError:
            paid_date = timezone.localdate()

        if Payment.objects.filter(receipt_number=receipt_number).exists():
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = 'This M-Pesa receipt was already recorded.'
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        try:
            with transaction.atomic():
                payment = Payment.objects.create(
                    student=payment_request.student,
                    amount=payment_request.amount,
                    receipt_number=receipt_number,
                    payment_method='mobile_money',
                    payment_date=paid_date,
                    note='Confirmed by Daraja STK Push.',
                )
        except IntegrityError:
            payment_request.status = FeePaymentRequest.STATUS_FAILED
            payment_request.status_message = 'This M-Pesa receipt was already recorded.'
            payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
            return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})

        payment_request.payment = payment
        payment_request.status = FeePaymentRequest.STATUS_CONFIRMED
        payment_request.status_message = 'Payment confirmed by M-Pesa.'
        payment_request.save(update_fields=[
            'payment',
            'status',
            'status_message',
            'updated_at',
        ])

    return JsonResponse({'ResultCode': 0, 'ResultDesc': 'Accepted'})


@staff_required
def dashboard(request):
    search = request.GET.get('q', '').strip()
    students = Student.objects.annotate(
        paid_total_value=Coalesce(
            Sum('payments__amount'),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
    )
    if search:
        students = students.filter(
            Q(name__icontains=search)
            | Q(admission_number__icontains=search)
            | Q(class_name__icontains=search)
        )

    total_fees = Student.objects.aggregate(total=Sum('fee_total'))['total'] or Decimal('0.00')
    total_paid = Payment.objects.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    page_obj = Paginator(students, 25).get_page(request.GET.get('page'))

    return render(request, 'dashboard.html', {
        'page_obj': page_obj,
        'search': search,
        'student_count': Student.objects.count(),
        'total_fees': total_fees,
        'total_paid': total_paid,
        'total_balance': total_fees - total_paid,
    })


@staff_required
def cash_book(request):
    form = CashBookFilterForm(request.GET or None)
    payments = Payment.objects.select_related('student', 'recorded_by')
    if not form.is_bound or form.is_valid():
        filters = form.cleaned_data if form.is_bound else {}
        if filters.get('start_date'):
            payments = payments.filter(payment_date__gte=filters['start_date'])
        if filters.get('end_date'):
            payments = payments.filter(payment_date__lte=filters['end_date'])
        if filters.get('payment_method'):
            payments = payments.filter(payment_method=filters['payment_method'])
        if filters.get('search'):
            search = filters['search'].strip()
            payments = payments.filter(
                Q(student__name__icontains=search)
                | Q(student__admission_number__icontains=search)
                | Q(receipt_number__icontains=search)
            )

    total_received = payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    method_totals_by_code = dict(
        payments.values('payment_method')
        .annotate(total=Sum('amount'))
        .values_list('payment_method', 'total')
    )
    method_totals = [
        {'label': label, 'total': method_totals_by_code.get(code, Decimal('0.00'))}
        for code, label in Payment._meta.get_field('payment_method').choices
    ]
    page_obj = Paginator(payments, 50).get_page(request.GET.get('page'))

    def page_url(page_number):
        query = request.GET.copy()
        query['page'] = page_number
        return f'?{query.urlencode()}'

    return render(request, 'cash_book.html', {
        'form': form,
        'page_obj': page_obj,
        'total_received': total_received,
        'method_totals': method_totals,
        'pending_paybill_requests': FeePaymentRequest.objects.filter(
            method=FeePaymentRequest.METHOD_PAYBILL,
            status=FeePaymentRequest.STATUS_PENDING,
        ).select_related('student'),
        'previous_url': page_url(page_obj.previous_page_number()) if page_obj.has_previous() else None,
        'next_url': page_url(page_obj.next_page_number()) if page_obj.has_next() else None,
    })


@staff_required
@require_POST
def review_paybill_request(request, pk):
    if request.POST.get('decision') not in {'confirm', 'reject'}:
        messages.error(request, 'Choose whether to confirm or reject this Paybill submission.')
        return redirect('cash-book')

    try:
        with transaction.atomic():
            payment_request = FeePaymentRequest.objects.select_for_update().get(
                pk=pk,
                method=FeePaymentRequest.METHOD_PAYBILL,
                status=FeePaymentRequest.STATUS_PENDING,
            )
            if request.POST['decision'] == 'reject':
                payment_request.status = FeePaymentRequest.STATUS_FAILED
                payment_request.status_message = 'The school office could not verify this Paybill submission.'
                payment_request.save(update_fields=['status', 'status_message', 'updated_at'])
                message = 'Paybill submission rejected.'
            else:
                payment = Payment.objects.create(
                    student=payment_request.student,
                    amount=payment_request.amount,
                    receipt_number=payment_request.paybill_reference,
                    payment_method='mobile_money',
                    payment_date=timezone.localdate(),
                    recorded_by=request.user,
                    note='Paybill payment verified by staff.',
                )
                payment_request.payment = payment
                payment_request.status = FeePaymentRequest.STATUS_CONFIRMED
                payment_request.status_message = 'Paybill payment verified by the school office.'
                payment_request.save(update_fields=[
                    'payment',
                    'status',
                    'status_message',
                    'updated_at',
                ])
                message = 'Paybill payment verified and added to the student account.'
    except FeePaymentRequest.DoesNotExist:
        messages.error(request, 'This payment request is no longer pending.')
    except IntegrityError:
        messages.error(request, 'This M-Pesa transaction code is already recorded.')
    else:
        messages.success(request, message)
    return redirect('cash-book')


@staff_required
def student_create(request):
    form = StudentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        student = form.save()
        messages.success(request, f'{student.name} was admitted successfully.')
        return redirect('student-detail', pk=student.pk)
    return render(request, 'student_form.html', {'form': form})


@staff_required
def student_detail(request, pk):
    student = get_object_or_404(Student, pk=pk)
    payments = student.payments.select_related('recorded_by')
    return render(request, 'student_details.html', {
        'student': student,
        'payments': payments,
    })


@staff_required
def student_ledger(request, pk):
    student = get_object_or_404(Student, pk=pk)
    payments = student.payments.order_by('payment_date', 'pk')
    running_balance = student.fee_total
    entries = [{
        'date': student.admission_date,
        'reference': student.admission_number,
        'description': 'School fees charged',
        'debit': student.fee_total,
        'credit': None,
        'balance': running_balance,
        'payment': None,
    }]
    for payment in payments:
        running_balance -= payment.amount
        entries.append({
            'date': payment.payment_date,
            'reference': payment.receipt_number,
            'description': f'Fee payment - {payment.get_payment_method_display()}',
            'debit': None,
            'credit': payment.amount,
            'balance': running_balance,
            'payment': payment,
        })

    return render(request, 'student_ledger.html', {
        'student': student,
        'entries': entries,
    })


@staff_required
def record_payment(request, student_id):
    student = get_object_or_404(Student, pk=student_id)
    form = PaymentForm(request.POST or None, student=student)

    if request.method == 'POST' and form.is_valid():
        payment = form.save(commit=False)
        payment.recorded_by = request.user
        try:
            with transaction.atomic():
                locked_student = Student.objects.select_for_update().get(pk=student.pk)
                payment.student = locked_student
                payment.full_clean()
                payment.save()
        except ValidationError as error:
            for field, errors in error.message_dict.items():
                form_field = field if field in form.fields else None
                for message in errors:
                    form.add_error(form_field, message)
        except IntegrityError:
            receipt_number = form.cleaned_data['receipt_number']
            if Payment.objects.filter(receipt_number=receipt_number).exists():
                form.add_error('receipt_number', 'This receipt number has already been used.')
            else:
                raise

        if not form.errors:
            messages.success(request, 'Payment recorded successfully.')
            return redirect('payment-receipt', pk=payment.pk)

        student.refresh_from_db()

    return render(request, 'payment_form.html', {
        'form': form,
        'student': student,
    })


@staff_required
def payment_receipt(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related('student', 'recorded_by'),
        pk=pk,
    )
    payments_through_receipt = Payment.objects.filter(
        student=payment.student,
    ).filter(
        Q(payment_date__lt=payment.payment_date)
        | Q(payment_date=payment.payment_date, pk__lte=payment.pk)
    )
    paid_through_receipt = (
        payments_through_receipt.aggregate(total=Sum('amount'))['total']
        or Decimal('0.00')
    )
    return render(request, 'receipt.html', {
        'payment': payment,
        'balance_after_payment': payment.student.fee_total - paid_through_receipt,
    })
