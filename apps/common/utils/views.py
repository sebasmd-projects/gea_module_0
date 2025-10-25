import logging
import re
from datetime import timedelta
from ipaddress import ip_address
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest
from django.shortcuts import redirect, render, resolve_url
from django.utils import timezone, translation
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import View

from apps.common.utils.models import IPBlockedModel, WhiteListedIPModel

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

SAFE_PATH_PREFIXES = [
    'static',
    'media',
    'favicon.ico',
    'api',
]

SAFE_PATH_REGEXES = [
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
    r'^(?!api/).*'
]

SAFE_PATH_EXTENSIONS = [
    '.css', '.js', '.png',
    '.jpg', '.jpeg', '.gif',
    '.svg', '.ico', '.woff',
    '.woff2', '.ttf', '.eot',
    '.otf', '.mp4', '.webm',
    '.ogg', '.mp3', '.wav'
]

_COMPILED_SAFE_REGEXES = [re.compile(r) for r in SAFE_PATH_REGEXES]


def _msg_exception_for_staff(status: int, request: HttpRequest, exception: Exception) -> str:
    if (request.user.is_staff or request.user.is_superuser) and exception:
        logger.warning(f"{status}: {exception}")
        return str(exception)
    return ''


def handler400(request, exception, *args, **argv):
    status = 400

    return render(
        request,
        template_name,
        status=status,
        context={
            'exception': _msg_exception_for_staff(status, request, exception),
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
            'exception': _msg_exception_for_staff(status, request, exception),
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
            'exception': _msg_exception_for_staff(status, request, exception),
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
            'exception': _msg_exception_for_staff(status, request, exception),
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
    lang_code = (
        request.POST.get("lang")
        or request.GET.get("lang")
        or ""
    ).strip()

    supported = dict(getattr(settings, "LANGUAGES", ()))

    if lang_code in supported:
        translation.activate(lang_code)

        # 1) Preferir "next" explícito (POST/GET). 2) Si no, usar HTTP_REFERER. 3) Fallback seguro.
        next_url = request.POST.get("next") or request.GET.get(
            "next") or request.META.get("HTTP_REFERER")

        if not next_url or not url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            try:
                next_url = resolve_url("core:index")
            except Exception:
                next_url = "/"

        response = redirect(next_url)

        # Fijar cookie de idioma con opciones seguras
        response.set_cookie(
            settings.LANGUAGE_COOKIE_NAME,
            lang_code,
            max_age=getattr(settings, "LANGUAGE_COOKIE_AGE", None),
            path=getattr(settings, "LANGUAGE_COOKIE_PATH", "/"),
            domain=getattr(settings, "LANGUAGE_COOKIE_DOMAIN", None),
            secure=getattr(settings, "SESSION_COOKIE_SECURE", False),
            samesite=getattr(settings, "LANGUAGE_COOKIE_SAMESITE", "Lax"),
        )
        return response

    # Idioma inválido → redirección segura por defecto
    try:
        return redirect(resolve_url("core:index"))
    except Exception:
        return redirect("/")


def _normalize_request_path(path: str) -> str:
    """
    Extrae y normaliza la parte de path sin query ni slash inicial.
    Ej: '/static/img/foo.png?x=1' -> 'static/img/foo.png'
    """
    if not path:
        return ''
    parsed = urlparse(path)
    p = parsed.path or ''
    # quitar slash inicial si existe
    if p.startswith('/'):
        p = p[1:]
    return p


def is_safe_path(path: str) -> bool:
    """
    True si la ruta debe considerarse 'safe' (recursos estáticos, extensiones, uuid, etc).
    Usar desde vistas y middleware.
    """
    if not path:
        return False

    p = _normalize_request_path(path)  # sin leading slash, sin query

    # 1) prefijos (ej. static/, media/, favicon.ico)
    for pref in SAFE_PATH_PREFIXES:
        # aceptar coincidencia exacta de archivo (favicon.ico) o startswith para prefijos
        if p == pref or p.startswith(pref + '/') or p.startswith(pref):
            return True

    # 2) extensiones
    lower = p.lower()
    for ext in SAFE_PATH_EXTENSIONS:
        if lower.endswith(ext):
            return True

    # 3) regexes (buscar en todo el path)
    for cre in _COMPILED_SAFE_REGEXES:
        if cre.search(p):
            return True

    return False


class HttpRequestAttackView(View):
    time_in_minutes = timedelta(minutes=settings.IP_BLOCKED_TIME_IN_MINUTES)

    @classmethod
    def is_safe_path(cls, path: str) -> bool:
        return is_safe_path(path)

    def get_client_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            ip = xff.split(",")[0].strip()
        else:
            ip = request.META.get(
                "HTTP_CF_CONNECTING_IP") or request.META.get("REMOTE_ADDR", "")
        try:
            return str(ip_address(ip))
        except Exception:
            return "0.0.0.0"

    def get(self, request, *args, **kwargs):
        if self.is_safe_path(request.get_full_path()):
            return redirect('/')

        client_ip = self.get_client_ip(
            request) or request.META.get('REMOTE_ADDR')

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
                block_time = self.time_in_minutes * attempt_count
            else:
                block_time = self.time_in_minutes

            blocked_entry.blocked_until = timezone.now() + block_time
            blocked_entry.save()

        return redirect('/')
