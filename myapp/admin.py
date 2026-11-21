from django.contrib import admin
from .models import FeePaymentRequest, Payment, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('admission_number', 'name', 'class_name', 'admission_date', 'fee_total')
    search_fields = ('admission_number', 'name', 'class_name')
    list_filter = ('class_name', 'admission_date')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'receipt_number',
        'student',
        'amount',
        'payment_method',
        'payment_date',
        'recorded_by',
    )
    search_fields = ('receipt_number', 'student__name', 'student__admission_number')
    list_filter = ('payment_date', 'payment_method')
    readonly_fields = ('created_at',)


@admin.register(FeePaymentRequest)
class FeePaymentRequestAdmin(admin.ModelAdmin):
    list_display = ('student', 'method', 'amount', 'status', 'created_at')
    search_fields = ('student__name', 'student__admission_number', 'paybill_reference')
    list_filter = ('method', 'status', 'created_at')
    readonly_fields = ('created_at', 'updated_at')
