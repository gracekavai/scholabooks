import decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0004_student_portal_accounts'),
    ]

    operations = [
        migrations.CreateModel(
            name='FeePaymentRequest',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID',
                )),
                ('method', models.CharField(
                    choices=[
                        ('stk_push', 'M-Pesa STK Push'),
                        ('paybill', 'M-Pesa Paybill'),
                    ],
                    max_length=16,
                )),
                ('amount', models.DecimalField(
                    decimal_places=2,
                    max_digits=10,
                    validators=[MinValueValidator(decimal.Decimal('1.00'))],
                )),
                ('phone_number', models.CharField(blank=True, max_length=16)),
                ('paybill_reference', models.CharField(
                    blank=True,
                    max_length=32,
                    null=True,
                    unique=True,
                )),
                ('checkout_request_id', models.CharField(
                    blank=True,
                    max_length=100,
                    null=True,
                    unique=True,
                )),
                ('merchant_request_id', models.CharField(blank=True, max_length=100)),
                ('status', models.CharField(
                    choices=[
                        ('pending', 'Pending verification'),
                        ('confirmed', 'Confirmed'),
                        ('failed', 'Failed'),
                    ],
                    default='pending',
                    max_length=16,
                )),
                ('status_message', models.CharField(blank=True, max_length=250)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('payment', models.OneToOneField(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='student_request',
                    to='myapp.payment',
                )),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='fee_payment_requests',
                    to='myapp.student',
                )),
            ],
            options={
                'ordering': ['-created_at', '-pk'],
            },
        ),
    ]
