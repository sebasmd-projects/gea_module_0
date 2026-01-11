from django.urls import path

from .views import (DocumentVerificationDetailView, EmployeeIPCONDetailView,
                    InputDocumentVerificationFormView,
                    InputEmployeeIPCONFormView)

app_name = 'certificates'

urlpatterns = [
    path(
        'ipcon/verify/',
        InputEmployeeIPCONFormView.as_view(),
        name='input_employee_verification_ipcon'
    ),
    path(
        'ipcon/verify/<uuid:pk>/',
        EmployeeIPCONDetailView.as_view(),
        name='detail_employee_verification_ipcon'
    ),
    path(
        'verify/aegis/asset/certification/',
        InputDocumentVerificationFormView.as_view(),
        name='input_document_verification_aegis'
    ),
    path(
        'verify/aegis/asset/certification/<uuid:pk>/',
        DocumentVerificationDetailView.as_view(),
        name='detail_document_verification_aegis'
    )
]
