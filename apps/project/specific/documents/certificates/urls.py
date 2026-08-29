from django.urls import path

from .views import (CertificatesLandingTemplateView, CertificationRecordView,
                    DocumentFileView, DocumentVerificationDetailView,
                    EmployeeIPCONDetailView, InputDocumentVerificationFormView,
                    InputEmployeeIPCONFormView, certification_public_key)

app_name = 'certificates'

urlpatterns = [
    path(
        'certificates/',
        CertificatesLandingTemplateView.as_view(),
        name='certificates_landing'
    ),

    # Users
    path(
        'verify/ipcon/',
        InputEmployeeIPCONFormView.as_view(),
        name='input_employee_verification_ipcon'
    ),
    path(
        'verify/ipcon/<uuid:pk>/',
        EmployeeIPCONDetailView.as_view(),
        name='detail_employee_verification_ipcon'
    ),

    # Documents
    path(
        'verify/aegis/asset/certification/',
        InputDocumentVerificationFormView.as_view(),
        name='input_document_verification_aegis'
    ),
    path(
        'verify/aegis/asset/certification/<uuid:pk>/',
        DocumentVerificationDetailView.as_view(),
        name='detail_document_verification_aegis'
    ),

    # Descarga controlada de los PDF. Sustituye a los enlaces directos a
    # MEDIA_URL, que no tenian ningun control de acceso.
    path(
        'verify/aegis/asset/certification/<uuid:pk>/file/<str:kind>/',
        DocumentFileView.as_view(),
        name='document_file'
    ),

    # Registro de certificacion (auditoria)
    path(
        'verify/aegis/asset/certification/<uuid:pk>/record/',
        CertificationRecordView.as_view(),
        name='certification_record'
    ),
    path(
        'verify/aegis/certification/key/',
        certification_public_key,
        name='certification_public_key'
    ),
]
