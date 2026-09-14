from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.common.core'
    verbose_name = _('Legal documents')

    def ready(self):
        # La señal que registra la aceptacion por uso continuado. El import va
        # aqui y no arriba porque a nivel de modulo se cargaria antes de que
        # las apps esten listas.
        from . import signals  # noqa: F401
