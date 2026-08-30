# apps/common/utils/testing.py
"""
Ayudas para las pruebas. No se importa desde codigo de produccion.

Desde que el admin exige segundo factor verificado (``app_core/admin.py``),
``client.login()`` ya no basta para llegar a ninguna pagina que cuelgue de el:
deja la sesion autenticada, pero no verificada, que es justo la diferencia que
el panel comprueba. Reproducirlo a mano son cuatro lineas y estaban a punto de
copiarse en cada fichero de pruebas que toque el admin; viven aqui una vez.
"""

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice


def login_with_otp(client, user, *, device_name='test'):
    """
    Deja la sesion como la deja un login completo, con segundo factor.

    Args:
        client: el ``django.test.Client`` de la prueba.
        user: el usuario que inicia sesion.
        device_name: nombre del dispositivo OTP creado.

    Returns:
        StaticDevice: el dispositivo asociado, por si la prueba lo necesita.
    """
    device = StaticDevice.objects.create(user=user, name=device_name)

    client.force_login(user)

    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()

    return device
