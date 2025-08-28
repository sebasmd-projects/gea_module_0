
from django.urls import path

from ..views import (DecoratedTokenObtainPairView, DecoratedTokenRefreshView,
                     DecoratedTokenVerifyView)

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