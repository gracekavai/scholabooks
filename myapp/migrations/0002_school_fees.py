from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.utils import timezone


def backfill_admission_numbers(apps, schema_editor):
    Student = apps.get_model('myapp', 'Student')
    database = schema_editor.connection.alias
    for student in Student.objects.using(database).filter(admission_number='').iterator():
        student.admission_number = f'LEGACY-{student.pk:06d}'
        student.save(using=database, update_fields=['admission_number'])


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='admission_number',
            field=models.CharField(blank=True, default='', max_length=30),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='student',
            name='class_name',
            field=models.CharField(default='', max_length=64),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='student',
            name='admission_date',
            field=models.DateField(default=timezone.localdate),
        ),
        migrations.AddField(
            model_name='student',
            name='guardian_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='student',
            name='guardian_phone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='student',
            name='fee_total',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=10,
                validators=[MinValueValidator(Decimal('0.00'))],
            ),
        ),
        migrations.AlterField(
            model_name='student',
            name='age',
            field=models.IntegerField(
                blank=True,
                null=True,
                validators=[MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name='student',
            name='email',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.RunPython(backfill_admission_numbers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='student',
            name='admission_number',
            field=models.CharField(max_length=30, unique=True),
        ),
        migrations.AlterModelOptions(
            name='student',
            options={'ordering': ['name', 'admission_number']},
        ),
        migrations.CreateModel(
            name='Payment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(
                    decimal_places=2,
                    max_digits=10,
                    validators=[MinValueValidator(Decimal('0.01'))],
                )),
                ('receipt_number', models.CharField(max_length=50, unique=True)),
                ('payment_date', models.DateField(default=timezone.localdate)),
                ('note', models.CharField(blank=True, max_length=250)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('recorded_by', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=models.SET_NULL,
                    related_name='school_fee_payments',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('student', models.ForeignKey(
                    on_delete=models.PROTECT,
                    related_name='payments',
                    to='myapp.student',
                )),
            ],
            options={'ordering': ['-payment_date', '-pk']},
        ),
    ]
