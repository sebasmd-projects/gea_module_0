# apps/project/common/account/urls.py

from django.urls import path

from .views import (
    GeaUserRegisterWizardView,
    UserLogoutView,
    ForgotPasswordFormView,
    ChangePasswordFormView
)

app_name = "account"


urlpatterns = [
    path(
        'account/register/',
        GeaUserRegisterWizardView.as_view(),
        name='register'
    ),
    path(
        'account/logout/',
        UserLogoutView.as_view(),
        name='logout'
    ),
    path(
        'account/change/password/',
        ChangePasswordFormView.as_view(),
        name='change_password'
    ),
    path(
        'account/forgot/password/',
        ForgotPasswordFormView.as_view(),
        name='forgot_password'
    )
]
