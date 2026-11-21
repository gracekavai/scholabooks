from django.urls import path

from . import api_views

urlpatterns = [
    path('students/', api_views.student_list, name='api-student-list'),
    path('students/<int:pk>/', api_views.student_detail, name='api-student-detail'),
]
