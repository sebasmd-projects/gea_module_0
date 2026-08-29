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

from apps.common.utils.blocking import capped_until, note_attempt
from apps.common.utils.client_ip import get_client_ip, is_exempt
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

# OJO: estos se buscan con `search`, o sea en cualquier posicion de la ruta.
# Aqui solo van patrones que de verdad identifiquen una ruta inocua.
#
# Habia un `r'^(?!api/).*'` en esta lista. Con `search`, eso casa con **toda**
# ruta que no empiece por `api/` -- es decir, con casi todas -- asi que
# `is_safe_path` devolvia True para `/wp-admin/`, `/phpmyadmin/` y `/.env`.
# Consecuencia: el middleware se saltaba cada peticion sin mirar los bloqueos,
# y la propia vista trampa se iba por su primera linea sin crear ninguno. La
# mitigacion anti-escaneo llevaba sin hacer absolutamente nada.
SAFE_PATH_REGEXES = [
    # Las URL de verificacion de certificados llevan un UUID: son legitimas.
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/400-error-bad-request.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/401-error-unauthorized.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/403-error-forbidden.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/404-error.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/500-internal-server-error.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/503-error-service-unavailable.svg',
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
            'error_image': 'https://geausa.propensionesabogados.com/public/static/assets/imgs/status_errors/504-error-gateway-timeout.svg',
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
        # Segmento completo o coincidencia exacta. El `startswith(pref)` que
        # habia aqui daba por buena `/apiXYZ/` por culpa del prefijo `api`.
        if p == pref or p.startswith(pref + '/'):
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
        """
        Una sola respuesta, compartida con el middleware que aplica el bloqueo.

        Antes se leia ``X-Forwarded-For`` aqui y ``REMOTE_ADDR`` alli, asi que
        se guardaba bajo una IP y se buscaba por otra. Y como la cabecera la
        pone el cliente, bastaba con mandarla con la IP de otro para que
        bloquearan a otro.
        """
        return get_client_ip(request)

    def get(self, request, *args, **kwargs):
        if self.is_safe_path(request.get_full_path()):
            return redirect('/')

        client_ip = self.get_client_ip(
            request) or request.META.get('REMOTE_ADDR')

        # Exenciones: lista blanca y personal interno autenticado. Las mismas
        # que aplica el middleware, para que no haya dos criterios.
        if is_exempt(request):
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
            info = note_attempt(blocked_entry.session_info, request)
            attempt_count = info['attempt_count']

            # El castigo crece con la insistencia, pero con techo: sin el,
            # seguir picando lo convertia en un bloqueo perpetuo.
            if attempt_count > 2:
                block_time = self.time_in_minutes * attempt_count
            else:
                block_time = self.time_in_minutes

            blocked_entry.session_info = info
            blocked_entry.blocked_until = capped_until(block_time)
            blocked_entry.save()

        return redirect('/')
