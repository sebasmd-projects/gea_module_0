from django.urls import path

from apps.common.core.views import IndexTemplateView, PrivacyTemplateView, TermsTemplateView

app_name = 'core'

urlpatterns = [
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
