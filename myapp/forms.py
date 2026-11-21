from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.exceptions import ValidationError

from .daraja import DarajaError, normalize_phone_number
from .models import FeePaymentRequest, Payment, Student, StudentPortalAccount


class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError('This account does not have school staff access.')


class StudentAuthenticationForm(forms.Form):
    student_name = forms.CharField(max_length=100, label='Student name')
    password = forms.CharField(
        label='Password',
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        student_name = cleaned_data.get('student_name', '').strip()
        password = cleaned_data.get('password')
        if not student_name or not password:
            return cleaned_data

        accounts = StudentPortalAccount.objects.filter(
            student__name__iexact=student_name,
            user__is_active=True,
        ).select_related('student', 'user')
        matched_account = next(
            (account for account in accounts if account.user.check_password(password)),
            None,
        )
        if matched_account is None:
            raise ValidationError('Student name or password is incorrect.')
        self.user = matched_account.user
        return cleaned_data

    def get_user(self):
        return self.user


class StudentPasswordChangeForm(SetPasswordForm):
    def clean_new_password1(self):
        password = self.cleaned_data.get('new_password1')
        if password and self.user.check_password(password):
            raise ValidationError('Choose a password different from your current password.')
        return password


class StudentForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields['fee_total'].initial = Student._meta.get_field('fee_total').default

    class Meta:
        model = Student
        fields = [
            'admission_number',
            'name',
            'class_name',
            'admission_date',
            'fee_total',
            'age',
            'email',
            'guardian_name',
            'guardian_phone',
        ]
        labels = {
            'class_name': 'Class / grade',
            'fee_total': 'School fees due',
        }
        widgets = {
            'admission_date': forms.DateInput(attrs={'type': 'date'}),
            'fee_total': forms.NumberInput(attrs={'min': '0', 'step': '0.01'}),
            'age': forms.NumberInput(attrs={'min': '1'}),
        }


class PaymentForm(forms.ModelForm):
    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)

    class Meta:
        model = Payment
        fields = ['amount', 'receipt_number', 'payment_method', 'payment_date', 'note']
        widgets = {
            'amount': forms.NumberInput(attrs={'min': '0.01', 'step': '0.01'}),
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_amount(self):
        return self.cleaned_data['amount']


class StudentFeePaymentForm(forms.ModelForm):
    class Meta:
        model = FeePaymentRequest
        fields = ['method', 'amount', 'phone_number', 'paybill_reference']
        widgets = {
            'amount': forms.NumberInput(attrs={'min': '1', 'step': '1'}),
            'phone_number': forms.TextInput(attrs={
                'placeholder': '07XXXXXXXX or 2547XXXXXXXX',
                'autocomplete': 'tel',
            }),
            'paybill_reference': forms.TextInput(attrs={
                'placeholder': 'M-Pesa transaction code',
                'autocomplete': 'off',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        amount = cleaned_data.get('amount')
        phone_number = cleaned_data.get('phone_number', '').strip()
        reference = cleaned_data.get('paybill_reference', '').strip().upper()
        if amount is not None and amount != amount.to_integral_value():
            self.add_error('amount', 'Enter a whole number of Kenyan shillings.')
        if method == FeePaymentRequest.METHOD_STK and not phone_number:
            self.add_error('phone_number', 'Enter the phone number to receive the STK prompt.')
        elif method == FeePaymentRequest.METHOD_STK and phone_number:
            try:
                cleaned_data['phone_number'] = normalize_phone_number(phone_number)
            except DarajaError as error:
                self.add_error('phone_number', str(error))
        if method == FeePaymentRequest.METHOD_PAYBILL and not reference:
            self.add_error('paybill_reference', 'Enter the M-Pesa transaction code.')
        if method == FeePaymentRequest.METHOD_STK:
            cleaned_data['paybill_reference'] = None
        elif method == FeePaymentRequest.METHOD_PAYBILL:
            cleaned_data['phone_number'] = phone_number
            cleaned_data['paybill_reference'] = reference
        return cleaned_data


class CashBookFilterForm(forms.Form):
    start_date = forms.DateField(
        required=False,
        label='From date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    end_date = forms.DateField(
        required=False,
        label='To date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    payment_method = forms.ChoiceField(
        required=False,
        label='Payment method',
        choices=[('', 'All methods')] + list(
            Payment._meta.get_field('payment_method').choices
        ),
    )
    search = forms.CharField(required=False, label='Search')

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        if start_date and end_date and start_date > end_date:
            self.add_error('end_date', 'End date must be on or after the start date.')
        return cleaned_data
