import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import HttpResponsePermanentRedirect
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _

from ..models import IPBlockedModel

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

logger = logging.getLogger(__name__)

STATIC_PREFIXES = (
    getattr(settings, 'STATIC_URL', '/static/'),
    getattr(settings, 'MEDIA_URL', '/media/'),
    '/favicon.ico',
)

class DetectSuspiciousRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.block_step = timedelta(minutes=getattr(
            settings, 'IP_BLOCKED_TIME_IN_MINUTES', 15))

    def __call__(self, request):
        client_ip = request.META.get('REMOTE_ADDR')

        blocked_entry = IPBlockedModel.objects.filter(
            current_ip=client_ip,
            is_active=True,
            blocked_until__gte=timezone.now()
        ).first()

        if blocked_entry:
            path = request.path or ''
            if any(path.startswith(p) for p in STATIC_PREFIXES):
                return render(request, template_name, status=403, context={...})
            try:
                with transaction.atomic():
                    si = blocked_entry.session_info or {}
                    si['attempt_count'] = int(si.get('attempt_count', 0)) + 1
                    paths = si.get('paths', [])
                    paths.append(request.path)
                    si['paths'] = paths
                    si['timestamp'] = timezone.now().isoformat()
                    si['user_agent'] = request.META.get('HTTP_USER_AGENT')
                    si['referer'] = request.META.get('HTTP_REFERER')

                    # extiende el bloqueo en cada intento mientras está bloqueado
                    now = timezone.now()
                    base = blocked_entry.blocked_until if blocked_entry.blocked_until and blocked_entry.blocked_until > now else now
                    blocked_entry.blocked_until = base + self.block_step

                    blocked_entry.session_info = si
                    blocked_entry.save(update_fields=['session_info', 'blocked_until'])

            except Exception as e:
                logger.exception("Error updating attempt_count while blocked: %s", e)

            logger.warning(f"Blocked IP {client_ip} attempted access. Returning 403.")
            return render(
                request,
                template_name,
                status=403,
                context={
                    'exception': _('This IP is temporarily blocked due to suspicious activity.'),
                    'title': _('Error 403'),
                    'error': _('Access denied due to suspicious activity.'),
                    'status': 403,
                    'error_image': 'https://globalallianceusa.com/gea/public/static/assets/imgs/status_errors/403-error-forbidden.svg',
                    'attempt_count': blocked_entry.session_info.get('attempt_count', 1),
                }
            )

        response = self.get_response(request)

        if 400 < response.status_code < 500:
            logger.warning(f"Error {response.status_code} encountered for IP: {client_ip}")

        return response