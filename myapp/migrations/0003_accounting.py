from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0002_school_fees'),
    ]

    operations = [
        migrations.AlterField(
            model_name='student',
            name='fee_total',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('15580.00'),
                max_digits=10,
                validators=[MinValueValidator(Decimal('0.00'))],
            ),
        ),
        migrations.AddField(
            model_name='payment',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('cash', 'Cash'),
                    ('bank_transfer', 'Bank transfer'),
                    ('mobile_money', 'Mobile money'),
                    ('card', 'Card'),
                    ('cheque', 'Cheque'),
                    ('other', 'Other'),
                ],
                default='other',
                max_length=20,
            ),
            preserve_default=False,
        ),
    ]
