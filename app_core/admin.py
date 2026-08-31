# app_core/admin.py
"""
El admin deja de defenderse con una URL secreta.

Hasta ahora lo unico que separaba a un desconocido del panel era no saber la
ruta: ``ADMIN_URL`` viene de entorno y no aparece en el codigo. Eso es
seguridad por oscuridad, y una URL no es un secreto que aguante. Viaja en el
historial del navegador, en los logs del proxy, en la cabecera ``Referer`` de
cualquier enlace externo que alguien abra desde el panel, y en la primera
captura de pantalla que se comparta por chat. Cuando se filtra no queda nada
detras: quien la tenga solo necesita credenciales.

A partir de aqui el control es la **sesion**, no la ruta:

* Solo entra quien ya ha pasado por el login de la plataforma **y** por el
  segundo factor, y ademas es personal activo. Es lo que aporta
  ``AdminSiteOTPRequiredMixin`` de ``two_factor``, que ademas quita el
  formulario de login propio del admin: no hay una segunda puerta con sus
  propias reglas.
* A quien no cumple no se le dice que hay un panel: se responde **404**, no
  403 ni una redireccion al login. Un 403 o un formulario de login confirman
  que la ruta existe, que es justo lo que se acaba de dejar de proteger. Es
  el mismo criterio que ya usa la consola de operaciones.
* La excepcion es el personal legitimo a medio camino: autenticado, con
  permiso, pero sin segundo factor verificado. A ese no se le esconde nada
  -- ya sabe que el panel existe -- y devolverle un 404 solo le haria perder
  la tarde. Se le manda a verificar el segundo factor.

Lo que **no** cambia: ``ADMIN_URL`` sigue viniendo de entorno y sigue sin
escribirse en el codigo. Deja de ser el control de acceso y pasa a ser lo que
siempre debio ser, una molestia mas para el escaner automatico.

La forma de instalarlo es la que documenta Django -- ``AdminConfig.default_site``
en ``app_core/apps.py`` -- y no una instancia nueva de ``AdminSite``: asi
``admin.site`` sigue siendo el mismo objeto de siempre y ni un solo
``@admin.register`` del proyecto se entera del cambio.
"""

import logging
from functools import update_wrapper

from django.contrib.admin import AdminSite
from django.http import Http404
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from two_factor.admin import AdminSiteOTPRequiredMixin

logger = logging.getLogger(__name__)


class GeaAdminSite(AdminSiteOTPRequiredMixin, AdminSite):
    """
    El admin del proyecto: se entra con sesion, no con la URL.

    ``has_permission`` lo aporta el mixin de ``two_factor`` (personal activo
    **y** segundo factor verificado). Aqui se decide que se responde cuando no
    se cumple, que es la mitad que importa.
    """

    def _is_internal_staff(self, request) -> bool:
        """
        Si quien pide ya sabe legitimamente que este panel existe.

        No comprueba el segundo factor a proposito: separa "no tienes nada que
        hacer aqui" de "te falta un paso", que son dos respuestas distintas.
        """
        user = getattr(request, 'user', None)

        if user is None or not user.is_authenticated:
            return False

        return bool(user.is_active and (user.is_staff or user.is_superuser))

    def _deny(self, request):
        """
        Que se responde a quien no puede pasar.

        Returns:
            Una redireccion al segundo factor si es personal interno a medio
            camino.

        Raises:
            Http404: para todos los demas. Sin 403 y sin formulario de login,
                que confirmarian la existencia de la ruta.
        """
        if self._is_internal_staff(request):
            return redirect(f"{reverse('two_factor:setup')}?next={request.path}")

        raise Http404

    def admin_view(self, view, cacheable=False):
        """
        Igual que el de Django, pero sin la redireccion al login del admin.

        El original manda a ``admin:login`` con un ``next``; esa redireccion es
        precisamente la que revela la ruta a cualquiera que la tantee.
        """
        def inner(request, *args, **kwargs):
            if not self.has_permission(request):
                return self._deny(request)

            return view(request, *args, **kwargs)

        if not cacheable:
            inner = never_cache(inner)

        if not getattr(view, 'csrf_exempt', False):
            inner = csrf_protect(inner)

        return update_wrapper(inner, view)

    def get_app_list(self, request, app_label=None):
        """
        El listado del panel, con la consola de operaciones dentro.

        La consola no es un modelo, asi que no aparecia por si sola: el admin
        solo lista lo registrado, y sus paginas cuelgan de ``get_urls`` de
        ``CommandRunModelAdmin``. Se llegaba escribiendo la URL a mano, que es
        tanto como no tenerla -- una herramienta que hay que recordar de
        memoria no la usa nadie, y su ausencia del menu hacia pensar que no
        existia.

        Va junto al historial de ejecuciones, que es su otra mitad: la consola
        lanza, el historial dice que se lanzo.
        """
        app_list = super().get_app_list(request, app_label)

        if not (request.user.is_active and request.user.is_superuser):
            return app_list

        try:
            console_url = reverse('admin:ops_console', current_app=self.name)
        except NoReverseMatch:
            # La app de operaciones puede no estar instalada. No es motivo
            # para tumbar el panel entero.
            logger.debug('The operations console is not installed')
            return app_list

        for app in app_list:
            models = app.get('models') or []

            for entry in models:
                if entry.get('object_name') != 'CommandRunModel':
                    continue

                if any(m.get('admin_url') == console_url for m in models):
                    return app_list

                models.insert(models.index(entry), {
                    'name': _('Operations console'),
                    'object_name': 'OpsConsole',
                    'admin_url': console_url,
                    'add_url': None,
                    'view_only': True,
                    'perms': {'view': True, 'add': False,
                              'change': False, 'delete': False},
                })

                return app_list

        return app_list

    def login(self, request, extra_context=None):
        """
        El admin no tiene login propio.

        Quien llega aqui sin sesion no ve un formulario: ve un 404. El personal
        interno a medio camino va al segundo factor. Quien ya cumple todo no
        pasa nunca por esta vista.
        """
        if self.has_permission(request):
            return redirect(reverse('admin:index', current_app=self.name))

        return self._deny(request)
