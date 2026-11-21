from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import migrations, models
import django.db.models.deletion


def create_existing_student_accounts(apps, schema_editor):
    Student = apps.get_model('myapp', 'Student')
    PortalAccount = apps.get_model('myapp', 'StudentPortalAccount')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    database = schema_editor.connection.alias

    for student in Student.objects.using(database).iterator():
        username = f'bvs-student-{student.pk}'
        user = User(
            username=username,
            first_name=student.name[:150],
            email=student.email,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        user.password = make_password(f'{student.admission_number}/BVS')
        user.save(using=database)
        PortalAccount.objects.using(database).create(student=student, user=user)


def remove_existing_student_accounts(apps, schema_editor):
    PortalAccount = apps.get_model('myapp', 'StudentPortalAccount')
    database = schema_editor.connection.alias
    user_ids = list(
        PortalAccount.objects.using(database).values_list('user_id', flat=True)
    )
    PortalAccount.objects.using(database).all().delete()
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    User.objects.using(database).filter(pk__in=user_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0003_accounting'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentPortalAccount',
            fields=[
                ('id', models.BigAutoField(
                    auto_created=True,
                    primary_key=True,
                    serialize=False,
                    verbose_name='ID',
                )),
                ('must_change_password', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('student', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='portal_account',
                    to='myapp.student',
                )),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='student_portal_account',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
        ),
        migrations.RunPython(
            create_existing_student_accounts,
            remove_existing_student_accounts,
        ),
    ]
