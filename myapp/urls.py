from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('payments/<int:pk>/review/', views.review_paybill_request, name='review-paybill-request'),
    path('cash-book/', views.cash_book, name='cash-book'),
    path('students/add/', views.student_create, name='student-create'),
    path('students/<int:pk>/', views.student_detail, name='student-detail'),
    path('students/<int:pk>/ledger/', views.student_ledger, name='student-ledger'),
    path(
        'students/<int:student_id>/payments/add/',
        views.record_payment,
        name='record-payment',
    ),
    path('payments/<int:pk>/receipt/', views.payment_receipt, name='payment-receipt'),
]
