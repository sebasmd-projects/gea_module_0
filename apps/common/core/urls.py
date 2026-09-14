from django.urls import path

from apps.common.core.views import (CookiesTemplateView, DataPolicyTemplateView,
                                    HealthCheckView, IndexTemplateView,
                                    LegalDocumentPDFView, PrivacyTemplateView,
                                    TermsTemplateView)

app_name = 'core'

urlpatterns = [
    path(
        'health/',
        HealthCheckView.as_view(),
        name='health_check'
    ),
    path(
        '',
        IndexTemplateView.as_view(),
        name='index'
    ),
    path(
        'privacy/',
        PrivacyTemplateView.as_view(),
        name='privacy'
    ),
    path(
        'terms/',
        TermsTemplateView.as_view(),
        name='terms'
    ),
    path(
        'cookies/',
        CookiesTemplateView.as_view(),
        name='cookies'
    ),
    # La politica de tratamiento de datos. Va en ruta propia y no dentro de
    # `privacy/` porque es el documento al que apunta la autorizacion que
    # firma cada titular: tiene que poder citarse por su URL.
    path(
        'data-policy/',
        DataPolicyTemplateView.as_view(),
        name='data_policy'
    ),

    # El mismo documento en PDF. Una sola ruta con la clave dentro en vez de
    # cuatro: lo que cambia es el documento, no la vista, y cuatro rutas serian
    # cuatro sitios donde olvidarse de añadir el quinto.
    path(
        'legal/<slug:document_key>.pdf',
        LegalDocumentPDFView.as_view(),
        name='legal_pdf'
    ),
]
