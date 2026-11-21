
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from myapp.forms import StaffAuthenticationForm
from myapp import views as myapp_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path(
        'login/',
        auth_views.LoginView.as_view(
            authentication_form=StaffAuthenticationForm,
            template_name='login.html',
        ),
        name='login',
    ),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('api/', include('myapp.api_urls')),
    path('payments/daraja/stk-callback/', myapp_views.daraja_stk_callback, name='daraja-stk-callback'),
    path('student/', include('myapp.student_urls')),
    path('staff/', include('myapp.urls')),
    path('', RedirectView.as_view(pattern_name='student-login', permanent=False), name='home'),
]