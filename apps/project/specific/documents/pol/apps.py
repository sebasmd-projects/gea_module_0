from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class PolConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.documents.pol'
    verbose_name = _("Proof of life")
    verbose_name_plural = _("Proof of life")
