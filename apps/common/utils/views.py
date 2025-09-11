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

from apps.common.utils.models import IPBlockedModel, WhiteListedIPModel

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
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/400-error-bad-request.svg',
        }
    )


def handler401(request, exception, *args, **argv):
    status = 401
    return render(
        request,
        template_name,
        status=status,
        context={
            'exception': str(exception),
            'title': _('Error 401'),
            'error': _('Unauthorized Access'),
            'status': status,
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/401-error-unauthorized.svg',
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
            'error': _('Forbidden Access'),
            'status': status,
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/403-error-forbidden.svg',
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
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/404-error.svg',
        }
    )


def handler500(request, *args, **argv):
    status = 500
    return render(
        request,
        template_name,
        status=status,
        context={
            'title': _('Error 500'),
            'error': _('Server error'),
            'status': status,
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/500-internal-server-error.svg',
        }
    )


def handler503(request, *args, **argv):
    status = 503
    return render(
        request,
        template_name,
        status=status,
        context={
            'title': _('Error 503'),
            'error': _('Service Unavailable'),
            'status': status,
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/503-error-service-unavailable.svg',
        }
    )


def handler504(request, *args, **argv):
    status = 504
    return render(
        request,
        template_name,
        status=status,
        context={
            'title': _('Error 504'),
            'error': _('Gateway Timeout'),
            'status': status,
            'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/504-error-gateway-timeout.svg',
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


class HttpRequestAttakView(View):
    time_in_minutes = timedelta(
        seconds=60 * settings.IP_BLOCKED_TIME_IN_MINUTES
    )

    def get(self, request, *args, **kwargs):
        client_ip = request.META.get('REMOTE_ADDR')

        # Skip if IP is whitelisted
        if WhiteListedIPModel.objects.filter(current_ip=client_ip).exists():
            return redirect('/')

        resolver_match = getattr(request, 'resolver_match', None)
        view_name = resolver_match.view_name if resolver_match else None

        user_id = None
        if request.user and request.user.is_authenticated:
            user_id = str(request.user.id)

        query_params = dict(request.GET.lists())

        headers_info = {
            'accept_language': request.META.get('HTTP_ACCEPT_LANGUAGE'),
            'host': request.META.get('HTTP_HOST'),
        }

        # Prepare session data
        session_data = {
            'attempt_count': 1,
            'client_ip': client_ip,
            'paths': [request.path],
            'user_agent': request.META.get('HTTP_USER_AGENT'),
            'method': request.method,
            'referer': request.META.get('HTTP_REFERER'),
            'view_name': view_name,
            'user_id': user_id,
            'query_params': query_params,
            'headers': headers_info,
            'timestamp': timezone.now().isoformat(),
        }

        # Check if the IP is already blocked
        blocked_entry, created = IPBlockedModel.objects.get_or_create(
            current_ip=client_ip,
            defaults={
                'reason': IPBlockedModel.ReasonsChoices.SERVER_HTTP_REQUEST,
                'blocked_until': timezone.now() + self.time_in_minutes,
                'session_info': session_data
            }
        )

        if not created:
            # Update attempt count and paths
            attempt_count = blocked_entry.session_info.get(
                'attempt_count', 0) + 1
            blocked_entry.session_info['attempt_count'] = attempt_count
            blocked_entry.session_info['paths'].append(request.path)
            blocked_entry.session_info['timestamp'] = timezone.now(
            ).isoformat()

            # Calculate block time
            if attempt_count > 2:
                block_time = self.time_in_minutes * 3600 * attempt_count
            else:
                block_time = self.time_in_minutes

            blocked_entry.blocked_until = timezone.now() + block_time
            blocked_entry.save()

        return redirect('/')
