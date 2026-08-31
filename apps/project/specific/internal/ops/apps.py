from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class OpsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.internal.ops'
    # "Operaciones" y no "Consola de operaciones": la consola es ahora una
    # entrada dentro de esta seccion, y repetir el mismo texto en el titulo y
    # en la linea de debajo se lee como un error de la pagina.
    verbose_name = _('Operations')
