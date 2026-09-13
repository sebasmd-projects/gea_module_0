# apps/common/utils/testing.py
"""
Ayudas para las pruebas. No se importa desde codigo de produccion.

Desde que el admin exige segundo factor verificado (``app_core/admin.py``),
``client.login()`` ya no basta para llegar a ninguna pagina que cuelgue de el:
deja la sesion autenticada, pero no verificada, que es justo la diferencia que
el panel comprueba. Reproducirlo a mano son cuatro lineas y estaban a punto de
copiarse en cada fichero de pruebas que toque el admin; viven aqui una vez.
"""

import os
import unittest

from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice

def posix_only_because(reason: str):
    """
    Marca una prueba que solo tiene sentido en un sistema POSIX, con su motivo.

    La suite se ejecuta tambien en portatiles Windows, y ahi hay cosas que no
    es que fallen: es que **no existen**. Se marcan en vez de borrarse porque
    la propiedad si importa en el servidor, que es Linux: saltarla en un
    portatil dice la verdad, quitarla diria que a nadie le importa.

    El motivo se pasa y no se fija porque no siempre es el mismo, y un `skip`
    que explica mal es peor que uno que no explica: manda a quien lo lee a
    buscar en la direccion equivocada.
    """
    return unittest.skipUnless(
        os.name == 'posix', f'solo tiene sentido en POSIX: {reason}')


#: Permisos de fichero. Windows no tiene el modo `rw-------` de Unix, y
#: `os.open` con 0o600 alli solo controla el bit de solo lectura, asi que una
#: asercion sobre `0o600` falla sin que nada este roto.
posix_only = posix_only_because(
    'Windows no tiene permisos de fichero de Unix')

#: Renombrar un fichero que esta abierto. En POSIX no afecta a quien ya lo
#: tiene abierto --el descriptor sigue apuntando al mismo inodo, que es lo que
#: sostiene la rotacion del log--; Windows lo bloquea y levanta `WinError 32`.
#: La documentacion de Python lo dice de `WatchedFileHandler`: no sirve en
#: Windows por exactamente esto.
posix_rename_only = posix_only_because(
    'Windows no deja renombrar un fichero abierto (WinError 32)')


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
