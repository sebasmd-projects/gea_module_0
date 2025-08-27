from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CertificatesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.documents.certificates'
    verbose_name = _("Certificate")
    verbose_name_plural = _("Certificates")
