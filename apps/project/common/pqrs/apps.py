from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class PqrsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.common.pqrs'
    verbose_name = _('Requests and complaints (PQRS)')
