from django.urls import include, path

from apps.common.core.views import IndexTemplateView

app_name = 'core'

urlpatterns = [
    path(
        '',
        IndexTemplateView.as_view(),
        name='index'
    )
]
