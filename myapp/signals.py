from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Student, StudentPortalAccount


@receiver(post_save, sender=Student)
@transaction.atomic
def create_student_portal_account(sender, instance, created, **kwargs):
    if not created:
        return

    user_model = get_user_model()
    username = f'bvs-student-{instance.pk}'
    user = user_model(
        username=username,
        first_name=instance.name[:150],
        email=instance.email,
        is_active=True,
        is_staff=False,
        is_superuser=False,
    )
    user.set_password(f'{instance.admission_number}/BVS')
    user.save()
    StudentPortalAccount.objects.create(student=instance, user=user)
