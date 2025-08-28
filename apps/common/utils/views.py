import logging
from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect, render
from django.utils import timezone, translation
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework_simplejwt.views import (TokenBlacklistView,
                                            TokenObtainPairView,
                                            TokenRefreshView, TokenVerifyView)

from .api import (TokenBlacklistResponseSerializer,
                  TokenObtainPairResponseSerializer,
                  TokenRefreshResponseSerializer,
                  TokenVerifyResponseSerializer)
from .backend import EmailOrUsernameModelBackend

logger = logging.getLogger(__name__)

try:
    template_name = settings.ERROR_TEMPLATE
except AttributeError:
    template_name = 'errors_template.html'
except SystemExit:
    raise
except Exception as e:
    logger.error(f"An unexpected error occurred: {e}")
    template_name = 'errors_template.html'


def handler400(request, exception, *args, **argv):
    status = 400
    return render(
        request,
        template_name,
        status=status,
        context={
            'exception': str(exception),
            'title': _('Error 400'),
            'error': _('Bad Request'),
            'status': status,
            'error_favicon': ''
        }
    )


def handler403(request, exception, *args, **argv):
    status = 403
    return render(
        request,
        template_name,
        status=status,
        context={
            'exception': str(exception),
            'title': _('Error 403'),
            'error': _('Prohibited Request'),
            'status': status,
            'error_favicon': ''
        }
    )


def handler404(request, exception, *args, **argv):
    status = 404
    return render(
        request,
        template_name,
        status=status,
        context={
            'exception': str(exception),
            'title': _('Error 404'),
            'error': _('Page not found'),
            'status': status,
            'error_favicon': ''
        }
    )


def handler500(request, *args, **argv):
    status = 500
    return render(
        request,
        template_name,
        status=500,
        context={
            'title': _('Error 500'),
            'error': _('Server error'),
            'status': status,
            'error_favicon': ''
        }
    )


def set_language(request):
    lang_code = request.GET.get('lang', None)
    if lang_code and lang_code in dict(settings.LANGUAGES).keys():
        translation.activate(lang_code)
        response = redirect(request.META.get('HTTP_REFERER'))
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang_code)
        return response
    else:
        return redirect(request.META.get('HTTP_REFERER'))


class DecoratedTokenObtainPairView(TokenObtainPairView):
    @swagger_auto_schema(
        responses={
            status.HTTP_200_OK: TokenObtainPairResponseSerializer,
        }
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        username_or_email = request.data.get('username')
        backend = EmailOrUsernameModelBackend()
        user = backend.authenticate(
            request,
            username=username_or_email,
            password=request.data.get(
                'password'
            )
        )

        if user:
            response.data['user_id'] = user.id

        return response


class DecoratedTokenRefreshView(TokenRefreshView):
    @swagger_auto_schema(
        responses={
            status.HTTP_200_OK: TokenRefreshResponseSerializer,
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class DecoratedTokenVerifyView(TokenVerifyView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(
        responses={
            status.HTTP_200_OK: TokenVerifyResponseSerializer,
        }
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)

        if response.status_code == status.HTTP_200_OK:
            response.data['detail'] = 'Token is valid'
            response.data['code'] = 'token_is_valid'

        return response


class DecoratedTokenBlacklistView(TokenBlacklistView):
    @swagger_auto_schema(
        responses={
            status.HTTP_200_OK: TokenBlacklistResponseSerializer,
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)