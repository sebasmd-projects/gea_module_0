from django.urls import path

from .views import (AegisSummaryAnchorView, AegisSummaryDetailView,
                    CertificatesLandingTemplateView, CertificationRecordView,
                    DocumentFileView, DocumentVerificationDetailView,
                    EmployeeIPCONDetailView, EmployeePhotoView,
                    InputDocumentVerificationFormView,
                    InputEmployeeIPCONFormView, certification_public_key,
                    summary_master_payload)

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
        'verify/ipcon/<uuid:pk>/photo/',
        EmployeePhotoView.as_view(),
        name='employee_photo'
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
    # Resumen AEGIS (la caja completa).
    path(
        'verify/aegis/summary/<uuid:pk>/',
        AegisSummaryDetailView.as_view(),
        name='summary_detail'
    ),
    # Destino del QR del anclaje: publico, sin OTP, y se actualiza solo.
    path(
        'verify/aegis/summary/<uuid:pk>/anchor/',
        AegisSummaryAnchorView.as_view(),
        name='summary_anchor'
    ),
    path(
        'verify/aegis/summary/<uuid:pk>/payload/',
        summary_master_payload,
        name='summary_master_payload'
    ),

    path(
        'verify/aegis/certification/key/',
        certification_public_key,
        name='certification_public_key'
    ),
]
