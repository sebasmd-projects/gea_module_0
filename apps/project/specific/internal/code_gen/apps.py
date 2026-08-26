from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CodeGenConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.internal.code_gen'
    verbose_name = _('Code generation and document certification')
