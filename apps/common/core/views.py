# apps/common/core/views.py

import logging

from django.conf import settings
from django.core.cache import caches
from django.core.mail import get_connection
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView, View

logger = logging.getLogger(__name__)


class IndexTemplateView(TemplateView):
    template_name = "core/index.html"


class LegalDocumentView(TemplateView):
    """
    Base de los documentos legales.

    Todos comparten dos cosas y por eso comparten vista: **la fecha de
    vigencia** y **la version**. No son adorno -- el articulo 18 de la propia
    politica obliga a publicar la fecha de entrada en vigor de cada
    modificacion, y sin version no se puede demostrar que texto acepto alguien
    el dia que se registro.

    Las fechas viven en ``settings`` y no en la plantilla para que cambiarlas
    no dependa de acordarse de tocar cuatro ficheros.
    """

    document_key = None

    def get_context_data(self, **kwargs):
        from django.conf import settings

        context = super().get_context_data(**kwargs)

        versions = getattr(settings, 'LEGAL_DOCUMENT_VERSIONS', {})
        current = versions.get(self.document_key, {})

        context['document_version'] = current.get('version', '1.0.0')
        context['document_date'] = current.get('date')
        context['document_key'] = self.document_key

        return context


class PrivacyTemplateView(LegalDocumentView):
    template_name = "core/tyc/privacy.html"
    document_key = 'privacy'


class TermsTemplateView(LegalDocumentView):
    template_name = "core/tyc/terms.html"
    document_key = 'terms'


class CookiesTemplateView(LegalDocumentView):
    template_name = "core/tyc/cookies.html"
    document_key = 'cookies'


class DataPolicyTemplateView(LegalDocumentView):
    template_name = "core/tyc/data_policy.html"
    document_key = 'data_policy'


class PortfolioTemplateView(TemplateView):
    template_name = "core/portfolio.html"


class HealthCheckView(View):
    """
    Health check de la aplicación.

    Respuesta JSON:
    {
        "response": "OK" | "Error" | "Other Error",
        "status": <status_code>,
        "checks": {
            "database": { "ok": true/false, "detail": "..." },
            "cache":    { "ok": true/false, "detail": "..." },
            "email":    { "ok": true/false, "detail": "..." }
        }
    }
    """

    def get(self, request, *args, **kwargs):
        try:
            checks = {
                "database": self._check_database(),
                "cache": self._check_cache(),
                "email": self._check_email(),
            }

            # Determinar estado global
            all_ok = all(v.get("ok", False) for v in checks.values())

            if all_ok:
                response_text = "OK"
                status_code = 200
            else:
                response_text = "Error"
                status_code = 503

            data = {
                "response": response_text,
                "status": status_code,
                "checks": checks,
            }

            return JsonResponse(data, status=status_code)

        except Exception as e:
            # Cualquier error no controlado
            logger.exception("HealthCheckView - unhandled exception: %s", e)
            data = {
                "response": "Other Error",
                "status": 500,
                "checks": {},
            }
            return JsonResponse(data, status=500)

    def _check_database(self):
        """
        Verifica que la conexión a la base de datos funcione.
        """
        try:
            # Esto fuerza a abrir conexión si está cerrada, sin hacer query pesada
            connection.ensure_connection()
            # Opcional: una consulta ultra ligera
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

            return {"ok": True, "detail": "Database OK"}
        except DatabaseError as e:
            logger.warning("HealthCheck - database error: %s", e)
            return {"ok": False, "detail": f"Database error: {e.__class__.__name__}"}
        except Exception as e:
            logger.exception("HealthCheck - unexpected DB error: %s", e)
            return {"ok": False, "detail": f"Unexpected DB error: {e.__class__.__name__}"}

    def _check_cache(self):
        """
        Verifica que el cache por defecto funcione (si está configurado).
        """
        try:
            if not hasattr(settings, "CACHES"):
                return {"ok": True, "detail": "Cache not configured (skipped)"}

            cache = caches["default"]
            test_key = "health_check_test_key"
            cache.set(test_key, "ok", timeout=10)
            value = cache.get(test_key)

            if value == "ok":
                return {"ok": True, "detail": "Cache OK"}
            else:
                return {"ok": False, "detail": "Cache set/get failed"}
        except Exception as e:
            logger.warning("HealthCheck - cache error: %s", e)
            return {"ok": False, "detail": f"Cache error: {e.__class__.__name__}"}

    def _check_email(self):
        """
        Verifica que el backend de email se pueda inicializar y abrir.
        No envía correos, solo abre/cierra conexión.
        """
        try:
            connection_email = get_connection()
            connection_email.open()
            connection_email.close()
            return {"ok": True, "detail": "Email backend OK"}
        except Exception as e:
            logger.warning("HealthCheck - email error: %s", e)
            return {"ok": False, "detail": f"Email error: {e.__class__.__name__}"}
