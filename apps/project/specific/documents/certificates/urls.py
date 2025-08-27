from django.urls import path

from .views import LockoutTimeView, CertificateInputView, CertificateDetailView, SovereignPurchaseCertificateDetailView, SovereignPurchaseCertificateInputView

app_name = 'certificates'

urlpatterns = [

    path(
        'lockout-time/',
        LockoutTimeView.as_view(),
        name='lockout_time'
    ),



    path(
        'certificate/',
        CertificateInputView.as_view(),
        name='input'
    ),
    path(
        'certificate/<uuid:pk>/',
        CertificateDetailView.as_view(),
        name='detail'
    ),



    path(
        'certificate/sovereign/',
        SovereignPurchaseCertificateInputView.as_view(),
        name='sovereign_input'
    ),
    path(
        'certificate/sovereign/<uuid:pk>/',
        SovereignPurchaseCertificateDetailView.as_view(),
        name='sovereign_detail'
    ),
]
