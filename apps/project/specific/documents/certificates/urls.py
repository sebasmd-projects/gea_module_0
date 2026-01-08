from django.urls import path

from .views import InputEmployeeVerificationIPCONFormView, InputEmployeeVerificationIPCONDetailView

app_name = 'certificates'

urlpatterns = [
    path(
        'ipcon/verify/',
        InputEmployeeVerificationIPCONFormView.as_view(),
        name='input_employee_verification_ipcon'
    ),
    path(
        'ipcon/verify/<uuid:pk>/',
        InputEmployeeVerificationIPCONDetailView.as_view(),
        name='detail_employee_verification_ipcon'
    )
]
