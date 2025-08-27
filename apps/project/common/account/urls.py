from django.urls import path

from .views import (GeaUserRegisterView, PropensionesUserRegisterView,
                    UserLogoutView)

app_name = "account"


urlpatterns = [
    path(
        'account/register/',
        GeaUserRegisterView.as_view(),
        name='register'
    ),
    path(
        'account/register/propensiones/',
        PropensionesUserRegisterView.as_view(),
        name='register-propensiones'
    ),
    path(
        'account/logout/',
        UserLogoutView.as_view(),
        name='logout'
    )
]
