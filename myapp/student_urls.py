from django.urls import path

from . import views

urlpatterns = [
    path('login/', views.student_login, name='student-login'),
    path('logout/', views.student_logout, name='student-logout'),
    path('change-password/', views.student_password_change, name='student-password-change'),
    path('portal/', views.student_portal, name='student-portal'),
    path('portal/statement/', views.student_portal_statement, name='student-portal-statement'),
    path('portal/payments/add/', views.student_make_payment, name='student-make-payment'),
    path(
        'portal/payments/<int:pk>/status/',
        views.student_payment_status,
        name='student-payment-status',
    ),
]
