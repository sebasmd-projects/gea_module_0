"""
Entrar despues de un cambio deja constancia de haberlo aceptado.

Por que en `user_logged_in` y no en un middleware
-------------------------------------------------
Un middleware que lo comprobara en cada peticion haria una consulta por
peticion para algo que solo cambia cuando se aprueba un documento — o sea,
tres o cuatro veces al año. La señal se dispara una vez por sesion, que es
exactamente la granularidad que tiene el hecho que se quiere registrar:
«volvio a entrar despues de que se le avisara».

Por que no puede fallar hacia fuera
-----------------------------------
Si esto lanza, el usuario no entra. Y un fallo registrando una constancia no
puede convertirse en una puerta cerrada: la plataforma se queda sin el apunte
--que se recupera en el siguiente acceso, porque `pending_for()` lo seguira
viendo pendiente-- pero el acceso funciona. De ahi el `except` ancho y el log.

`django-two-factor-auth` dispara `user_logged_in` igual que el acceso normal,
asi que los seis recorridos del asistente (§4-bis.D) pasan por aqui sin tener
que engancharse a ninguno en particular.
"""

import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(user_logged_in, dispatch_uid='core.legal.accept_on_login')
def record_continued_use(sender, request, user, **kwargs):
    from .legal import accept_on_login

    try:
        accept_on_login(user, request)
    except Exception:
        # Ancho a proposito: cualquier cosa que salga mal aqui es preferible a
        # no dejar entrar a alguien. Queda en el log con su traza.
        logger.exception(
            'No se pudo registrar la aceptacion por uso continuado del '
            'usuario %s. El acceso sigue adelante; se reintentara en el '
            'siguiente.',
            getattr(user, 'pk', None),
        )
