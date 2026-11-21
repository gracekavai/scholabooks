from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


PAYMENT_METHOD_CHOICES = [
    ('cash', 'Cash'),
    ('bank_transfer', 'Bank transfer'),
    ('mobile_money', 'Mobile money'),
    ('card', 'Card'),
    ('cheque', 'Cheque'),
    ('other', 'Other'),
]


class Student(models.Model):
    admission_number = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    class_name = models.CharField(max_length=64)
    admission_date = models.DateField(default=timezone.localdate)
    age = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    email = models.EmailField(blank=True)
    guardian_name = models.CharField(max_length=100, blank=True)
    guardian_phone = models.CharField(max_length=30, blank=True)
    fee_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('15580.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )

    class Meta:
        ordering = ['name', 'admission_number']

    def __str__(self):
        return f'{self.name} ({self.admission_number})'

    @property
    def paid_total(self):
        annotated_total = getattr(self, 'paid_total_value', None)
        if annotated_total is not None:
            return annotated_total
        return self.payments.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    @property
    def balance(self):
        return self.fee_total - self.paid_total


class Payment(models.Model):
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='payments',
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    receipt_number = models.CharField(max_length=50, unique=True)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_date = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=250, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='school_fee_payments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date', '-pk']

    def __str__(self):
        return f'{self.receipt_number} - {self.student.name}'

    def clean(self):
        super().clean()
        if self.payment_method and self.payment_method not in dict(PAYMENT_METHOD_CHOICES):
            raise ValidationError({'payment_method': 'Select a valid payment method.'})


class FeePaymentRequest(models.Model):
    METHOD_STK = 'stk_push'
    METHOD_PAYBILL = 'paybill'
    METHOD_CHOICES = [
        (METHOD_STK, 'M-Pesa STK Push'),
        (METHOD_PAYBILL, 'M-Pesa Paybill'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending verification'),
        (STATUS_CONFIRMED, 'Confirmed'),
        (STATUS_FAILED, 'Failed'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name='fee_payment_requests',
    )
    method = models.CharField(max_length=16, choices=METHOD_CHOICES)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
    )
    phone_number = models.CharField(max_length=16, blank=True)
    paybill_reference = models.CharField(max_length=32, blank=True, unique=True, null=True)
    checkout_request_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    merchant_request_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    status_message = models.CharField(max_length=250, blank=True)
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name='student_request',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return f'{self.get_method_display()} {self.amount} for {self.student}'


class StudentPortalAccount(models.Model):
    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name='portal_account',
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='student_portal_account',
    )
    must_change_password = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Student portal account: {self.student.admission_number}'
