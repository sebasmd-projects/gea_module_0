from django.urls import path

from apps.common.core.views import (HealthCheckView, IndexTemplateView,
                                    PrivacyTemplateView, TermsTemplateView)

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
]
