import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import FeePaymentRequest, Payment, Student


class SchoolFeesWorkflowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clerk = user_model.objects.create_user(
            username='clerk',
            password='test-password-123',
            is_staff=True,
        )
        self.client.force_login(self.clerk)
        self.student = Student.objects.create(
            admission_number='ADM-1001',
            name='Amina Example',
            class_name='Grade 5',
            fee_total='1000.00',
        )

    def test_dashboard_links_to_admission_and_student_detail(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('student-create'))
        self.assertContains(response, reverse('cash-book'))
        self.assertContains(response, reverse('student-detail', args=[self.student.pk]))
        detail_response = self.client.get(reverse('student-detail', args=[self.student.pk]))
        self.assertContains(
            detail_response,
            reverse('record-payment', args=[self.student.pk]),
        )
        self.assertContains(
            detail_response,
            reverse('student-ledger', args=[self.student.pk]),
        )

    def test_home_and_staff_login_do_not_offer_public_account_creation(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('student-login'))
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create account')
        self.assertEqual(self.client.get('/staff/create-account/').status_code, 404)

    def test_admission_form_creates_student(self):
        form_response = self.client.get(reverse('student-create'))
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, 'value="15580.00"')
        response = self.client.post(
            reverse('student-create'),
            {
                'admission_number': 'ADM-1003',
                'name': 'Lina Example',
                'class_name': 'Grade 2',
                'admission_date': '2026-11-20',
                'fee_total': '875.00',
                'age': '8',
                'email': '',
                'guardian_name': 'Parent Example',
                'guardian_phone': '555-0100',
            },
        )

        student = Student.objects.get(admission_number='ADM-1003')
        self.assertRedirects(response, reverse('student-detail', args=[student.pk]))
        self.assertEqual(student.portal_account.user.username, f'bvs-student-{student.pk}')
        self.assertFalse(student.portal_account.user.is_staff)
        self.assertTrue(student.portal_account.user.check_password('ADM-1003/BVS'))
        self.assertTrue(student.portal_account.must_change_password)

    def test_clerk_payment_updates_balance_and_shows_receipt(self):
        form_response = self.client.get(reverse('record-payment', args=[self.student.pk]))
        self.assertEqual(form_response.status_code, 200)
        response = self.client.post(
            reverse('record-payment', args=[self.student.pk]),
            {
                'amount': '250.00',
                'receipt_number': 'RCPT-1001',
                'payment_method': 'mobile_money',
                'payment_date': '2026-11-20',
                'note': '',
            },
        )

        payment = Payment.objects.get(receipt_number='RCPT-1001')
        self.assertEqual(payment.recorded_by, self.clerk)
        self.assertEqual(payment.payment_method, 'mobile_money')
        self.assertRedirects(
            response,
            reverse('payment-receipt', args=[payment.pk]),
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.paid_total, payment.amount)
        self.assertEqual(self.student.balance, 750)

        receipt_response = self.client.get(reverse('payment-receipt', args=[payment.pk]))
        self.assertContains(receipt_response, 'RCPT-1001')
        self.assertContains(receipt_response, 'Mobile money')
        self.assertContains(receipt_response, '750.00')

        cash_book_response = self.client.get(reverse('cash-book'))
        self.assertContains(cash_book_response, 'RCPT-1001')
        self.assertContains(cash_book_response, 'Mobile money')
        self.assertContains(cash_book_response, '250.00')

        ledger_response = self.client.get(reverse('student-ledger', args=[self.student.pk]))
        self.assertContains(ledger_response, 'RCPT-1001')
        self.assertContains(ledger_response, '750.00')

    def test_clerk_can_record_overpayment_and_balance_becomes_credit(self):
        response = self.client.post(
            reverse('record-payment', args=[self.student.pk]),
            {
                'amount': '1000.01',
                'receipt_number': 'RCPT-OVER',
                'payment_method': 'cash',
                'payment_date': '2026-11-20',
                'note': '',
            },
        )

        payment = Payment.objects.get(receipt_number='RCPT-OVER')
        self.assertRedirects(response, reverse('payment-receipt', args=[payment.pk]))
        self.student.refresh_from_db()
        self.assertEqual(self.student.balance, Decimal('-0.01'))
        portal_account = self.student.portal_account
        portal_account.must_change_password = False
        portal_account.save(update_fields=['must_change_password'])
        self.client.force_login(portal_account.user)
        self.assertContains(
            self.client.get(reverse('student-portal-statement')),
            '0.01',
        )

    def test_clerk_cannot_reuse_receipt_number(self):
        Payment.objects.create(
            student=self.student,
            amount='100.00',
            receipt_number='RCPT-DUPLICATE',
            payment_method='cash',
            recorded_by=self.clerk,
        )
        other_student = Student.objects.create(
            admission_number='ADM-1002',
            name='Noah Example',
            class_name='Grade 4',
            fee_total='500.00',
        )

        response = self.client.post(
            reverse('record-payment', args=[other_student.pk]),
            {
                'amount': '50.00',
                'receipt_number': 'RCPT-DUPLICATE',
                'payment_method': 'bank_transfer',
                'payment_date': '2026-11-20',
                'note': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.filter(receipt_number='RCPT-DUPLICATE').count(), 1)

    def test_dashboard_requires_staff_login(self):
        self.client.logout()
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_clerk_cannot_use_legacy_api(self):
        response = self.client.get(reverse('api-student-list'))
        self.assertEqual(response.status_code, 403)

    def test_logout_button_uses_post_and_returns_to_login(self):
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('login'))

    def test_student_login_changes_temporary_password_and_opens_only_student_portal(self):
        self.client.logout()
        response = self.client.post(
            reverse('student-login'),
            {
                'student_name': self.student.name,
                'password': 'ADM-1001/BVS',
            },
        )
        self.assertRedirects(response, reverse('student-password-change'))

        response = self.client.post(
            reverse('student-password-change'),
            {
                'new_password1': 'Student-Secure-Password-934!',
                'new_password2': 'Student-Secure-Password-934!',
            },
        )
        self.assertRedirects(response, reverse('student-portal'))
        self.student.portal_account.refresh_from_db()
        self.assertFalse(self.student.portal_account.must_change_password)

        portal_response = self.client.get(reverse('student-portal'))
        self.assertEqual(portal_response.status_code, 200)
        self.assertContains(portal_response, 'Brooksville Senior School')
        staff_response = self.client.get(reverse('dashboard'))
        self.assertEqual(staff_response.status_code, 302)
        self.assertIn(reverse('login'), staff_response.url)

    def test_staff_account_cannot_open_student_portal(self):
        response = self.client.get(reverse('student-portal'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse('student-login')))

    def test_student_name_and_admission_password_are_required(self):
        self.client.logout()
        response = self.client.post(
            reverse('student-login'),
            {
                'student_name': self.student.name,
                'password': 'wrong-password',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Student name or password is incorrect.')

    def test_paybill_submission_waits_for_staff_confirmation(self):
        account = self.student.portal_account
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        self.client.force_login(account.user)

        response = self.client.post(
            reverse('student-make-payment'),
            {
                'method': 'paybill',
                'amount': '300',
                'phone_number': '',
                'paybill_reference': 'QWE1234567',
            },
        )
        self.assertEqual(response.status_code, 302)
        payment_request = FeePaymentRequest.objects.get(paybill_reference='QWE1234567')
        self.assertEqual(payment_request.status, FeePaymentRequest.STATUS_PENDING)
        self.student.refresh_from_db()
        self.assertEqual(self.student.balance, Decimal('1000.00'))

        self.client.force_login(self.clerk)
        response = self.client.post(
            reverse('review-paybill-request', args=[payment_request.pk]),
            {'decision': 'confirm'},
        )
        self.assertRedirects(response, reverse('cash-book'))
        payment_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(payment_request.status, FeePaymentRequest.STATUS_CONFIRMED)
        self.assertEqual(self.student.balance, Decimal('700.00'))

    def test_student_cannot_confirm_own_paybill_submission(self):
        account = self.student.portal_account
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        self.client.force_login(account.user)
        payment_request = FeePaymentRequest.objects.create(
            student=self.student,
            method=FeePaymentRequest.METHOD_PAYBILL,
            amount='50.00',
            paybill_reference='QWE7654321',
        )

        response = self.client.post(
            reverse('review-paybill-request', args=[payment_request.pk]),
            {'decision': 'confirm'},
        )
        self.assertEqual(response.status_code, 302)
        payment_request.refresh_from_db()
        self.assertEqual(payment_request.status, FeePaymentRequest.STATUS_PENDING)
        self.assertFalse(Payment.objects.filter(receipt_number='QWE7654321').exists())

    @patch.dict('os.environ', {
        'DARAJA_CONSUMER_KEY': '',
        'DARAJA_CONSUMER_SECRET': '',
        'DARAJA_SHORTCODE': '',
        'DARAJA_PASSKEY': '',
        'DARAJA_CALLBACK_URL': '',
    })
    def test_stk_push_without_credentials_fails_without_changing_balance(self):
        account = self.student.portal_account
        account.must_change_password = False
        account.save(update_fields=['must_change_password'])
        self.client.force_login(account.user)

        response = self.client.post(
            reverse('student-make-payment'),
            {
                'method': 'stk_push',
                'amount': '300',
                'phone_number': '0712345678',
                'paybill_reference': '',
            },
        )
        self.assertRedirects(
            response,
            reverse(
                'student-payment-status',
                args=[FeePaymentRequest.objects.latest('created_at').pk],
            ),
        )
        payment_request = FeePaymentRequest.objects.latest('created_at')
        self.assertEqual(payment_request.status, FeePaymentRequest.STATUS_FAILED)
        self.assertContains(
            self.client.get(reverse('student-payment-status', args=[payment_request.pk])),
            'M-Pesa STK Push is not configured',
        )
        self.student.refresh_from_db()
        self.assertEqual(self.student.balance, Decimal('1000.00'))

    def test_successful_stk_callback_records_payment_once(self):
        payment_request = FeePaymentRequest.objects.create(
            student=self.student,
            method=FeePaymentRequest.METHOD_STK,
            amount='300.00',
            phone_number='254712345678',
            checkout_request_id='ws_CO_TEST_001',
            merchant_request_id='merchant-test-001',
        )
        callback = {
            'Body': {
                'stkCallback': {
                    'MerchantRequestID': 'merchant-test-001',
                    'CheckoutRequestID': 'ws_CO_TEST_001',
                    'ResultCode': 0,
                    'ResultDesc': 'The service request is processed successfully.',
                    'CallbackMetadata': {
                        'Item': [
                            {'Name': 'Amount', 'Value': 300},
                            {'Name': 'MpesaReceiptNumber', 'Value': 'QWE1234567'},
                            {'Name': 'TransactionDate', 'Value': 20261120221533},
                            {'Name': 'PhoneNumber', 'Value': 254712345678},
                        ],
                    },
                },
            },
        }

        response = self.client.post(
            reverse('daraja-stk-callback'),
            data=json.dumps(callback),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        payment_request.refresh_from_db()
        self.student.refresh_from_db()
        self.assertEqual(payment_request.status, FeePaymentRequest.STATUS_CONFIRMED)
        self.assertEqual(payment_request.payment.receipt_number, 'QWE1234567')
        self.assertEqual(self.student.balance, Decimal('700.00'))

        duplicate_response = self.client.post(
            reverse('daraja-stk-callback'),
            data=json.dumps(callback),
            content_type='application/json',
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertEqual(Payment.objects.filter(receipt_number='QWE1234567').count(), 1)
