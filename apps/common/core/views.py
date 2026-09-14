# apps/common/core/views.py

import logging

from django.conf import settings
from django.core.cache import caches
from django.core.mail import get_connection
from django.db import DatabaseError, connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView, View

from .legal_html import sanitize_legal_html
from .legal_pdf import render_document_pdf
from .models import LegalDocumentModel

logger = logging.getLogger(__name__)


class IndexTemplateView(TemplateView):
    template_name = "core/index.html"


class LegalDocumentView(TemplateView):
    """
    Un documento legal, leido de la base y no de una plantilla.

    Los cuatro comparten vista y plantilla porque lo unico que los distingue es
    su clave: el texto, la version, la fecha de vigencia y el estado salen
    todos de la fila de `LegalDocumentVersionModel` que este vigente.

    **El aviso de borrador sale de `status`.** Antes estaba escrito a mano
    dentro de cada plantilla y ademas repetido en un ajuste de `settings.py`
    con un sufijo `-borrador`, o sea dos marcas que se podian desincronizar sin
    que nada lo impidiera. Ahora hay una.
    """

    template_name = 'core/tyc/legal_document.html'
    document_key = None

    def get_document(self):
        clave = self.kwargs.get('document_key') or self.document_key

        return get_object_or_404(
            LegalDocumentModel, key=clave, is_active=True
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        documento = self.get_document()
        version = documento.displayed_version()
        idioma = get_language() or 'es'

        context['document'] = documento
        context['document_key'] = documento.key
        context['document_name'] = documento.name_for(idioma)
        context['version'] = version

        if version is not None:
            context['document_version'] = version.version
            context['document_date'] = version.effective_from
            # Saneado antes de marcarlo como seguro. Estas paginas son
            # publicas y sin autenticar, y el editor tiene boton de codigo
            # fuente: `mark_safe` sobre lo que salga del admin pondria un
            # `<script>` a la vista de cualquier visitante. Ver `legal_html`.
            context['document_body'] = mark_safe(
                sanitize_legal_html(version.body_for(idioma))
            )
            context['is_draft'] = not version.is_approved
        else:
            # Un documento sin ninguna redaccion. No deberia pasar --la
            # semilla crea las cuatro-- pero un 500 aqui seria peor que una
            # pagina que dice honestamente que todavia no hay texto.
            context['document_body'] = ''
            context['is_draft'] = True

        return context


class LegalDocumentPDFView(LegalDocumentView):
    """
    El mismo documento, en PDF, generado al vuelo.

    No se guarda en disco a proposito: un `FileField` obligaria a decidir su
    carpeta en `deploy/media.htaccess` o declararla en
    `PUBLICLY_SERVABLE_MEDIA` (invariante 13), y a regenerarlo cada vez que
    cambia el texto. Para un documento que ya esta entero en la base y que se
    descarga de vez en cuando, generarlo es mas barato que mantenerlo.
    """

    def get(self, request, *args, **kwargs):
        documento = self.get_document()
        version = documento.displayed_version()

        if version is None:
            raise Http404('El documento no tiene ninguna redaccion.')

        idioma = get_language() or 'es'
        pdf = render_document_pdf(version, idioma)

        respuesta = HttpResponse(pdf, content_type='application/pdf')

        # `inline`: se abre en el navegador. Es un documento para leer, y
        # forzar la descarga de algo que se quiere consultar molesta.
        nombre = f'{documento.key}-{version.version}-{idioma}.pdf'
        respuesta['Content-Disposition'] = f'inline; filename="{nombre}"'

        return respuesta


class PrivacyTemplateView(LegalDocumentView):
    document_key = 'privacy'


class TermsTemplateView(LegalDocumentView):
    document_key = 'terms'


class CookiesTemplateView(LegalDocumentView):
    document_key = 'cookies'


class DataPolicyTemplateView(LegalDocumentView):
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
