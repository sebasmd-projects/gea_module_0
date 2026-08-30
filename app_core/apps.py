# app_core/apps.py
"""
Configuracion de apps del propio proyecto.

Solo hay una, y existe para instalar el admin del proyecto sin romper nada:
``AdminConfig.default_site`` es la forma que documenta Django para cambiar la
clase de ``admin.site`` **conservando el mismo objeto**. La alternativa --
crear una instancia nueva de ``AdminSite`` -- obligaria a volver a registrar
todos los modelos, porque cada ``@admin.register`` del proyecto apunta al
sitio por defecto.

Se activa sustituyendo ``django.contrib.admin`` por ``app_core.apps.GeaAdminConfig``
en ``INSTALLED_APPS``.
"""

from django.contrib.admin.apps import AdminConfig


class GeaAdminConfig(AdminConfig):
    """Usa ``GeaAdminSite`` como sitio de administracion por defecto."""

    default_site = 'app_core.admin.GeaAdminSite'
