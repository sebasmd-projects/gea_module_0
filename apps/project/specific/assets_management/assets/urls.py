from django.urls import path

from .views import (
    HolderTemplateview,
)

app_name = 'assets'

urlpatterns = [
    path(
        'asset/holder/',
        HolderTemplateview.as_view(),
        name='holder_index'
    ),
]
