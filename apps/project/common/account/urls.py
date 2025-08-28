from django.urls import path

from .views import (GeaUserRegisterView,
                    UserLogoutView)

app_name = "account"


urlpatterns = [
    path(
        'account/register/',
        GeaUserRegisterView.as_view(),
        name='register'
    ),
    path(
        'account/logout/',
        UserLogoutView.as_view(),
        name='logout'
    )
]
