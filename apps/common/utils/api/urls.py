
from django.urls import path

from ..views import (DecoratedTokenObtainPairView, DecoratedTokenRefreshView,
                     DecoratedTokenVerifyView)
from .views import RequestLogDestroyAPIView, RequestLogListView

urlpatterns = [
    path(
        'login/',
        DecoratedTokenObtainPairView.as_view(),
        name='token_obtain_pair'
    ),
    path(
        'refresh/',
        DecoratedTokenRefreshView.as_view(),
        name='token_refresh'
    ),
    path(
        'verify/',
        DecoratedTokenVerifyView.as_view(),
        name='token_verify'
    )
]

log_urlpattern = [
    path(
        'log/',
        RequestLogListView.as_view(),
        name='utils_log'
    ),
    path(
        'log/remove/<pk>/',
        RequestLogDestroyAPIView.as_view(),
        name='utils_log_delete'
    )
]
