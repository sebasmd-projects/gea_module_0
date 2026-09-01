# apps/common/utils/functions/safe_redirect.py
"""
A donde se puede mandar a alguien despues de una accion.

Un ``?next=`` sin comprobar es un redirector abierto: el enlace se manda con
una excusa creible --"registrate aqui", "inicia sesion para ver esto"--, la
victima hace lo que se le pide de verdad **en esta plataforma**, y acaba en
un sitio ajeno. Los dos agravantes de aqui:

* Varias de estas vistas **abren la sesion** antes de redirigir, asi que quien
  llega al sitio ajeno es un usuario recien autenticado.
* La ``Referer`` que ve el destino es la de esta plataforma, que es lo que
  hace creible una pantalla de "vuelve a escribir tu contrasena".

El chequeo en si es una linea de Django. Lo que faltaba no era la
comprobacion sino tenerla en un solo sitio: estaba escrita tres veces --en
``set_language``, en ``assets/views.py`` y no estaba en el wizard de
registro-- y la que faltaba era justo la del formulario por el que se crean
cuentas.

Dos formas que se escapan de una comprobacion hecha a ojo, y que esta funcion
rechaza:

* ``//otro-sitio/`` no lleva esquema y parece una ruta, pero el navegador la
  resuelve como otro dominio.
* ``https:/otro-sitio`` con una sola barra, que algunos navegadores corrigen.
"""

from django.utils.http import url_has_allowed_host_and_scheme


def safe_next(request, candidate: str = None, *, fallback: str = '') -> str:
    """
    Devuelve ``candidate`` solo si apunta a este mismo sitio.

    Parameters:
        request: la peticion, de la que salen el host y si es HTTPS.
        candidate (str | None): el destino pedido. Si es ``None`` se toma de
            ``next`` en POST o en GET, en ese orden.
        fallback (str): que devolver cuando el destino no vale.

    Returns:
        str: el destino, o ``fallback`` si no es de fiar.
    """
    if candidate is None:
        candidate = request.POST.get('next') or request.GET.get('next') or ''

    candidate = (candidate or '').strip()

    if not candidate:
        return fallback

    allowed = url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )

    return candidate if allowed else fallback
