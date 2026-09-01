# apps/common/utils/throttling.py
"""
Limite de intentos por IP para formularios publicos.

Existe porque ya habia tres implementaciones del mismo contador --en el mixin
de OTP, en el formulario de recuperacion de contrasena y en el de PQRS-- y
**faltaba en el sitio que mas lo necesitaba**: la consulta de certificados de
persona, que acepta un codigo de cuatro caracteres sin ningun freno.

Que un formulario publico responda "existe" o "no existe" lo convierte en un
oraculo. Con un codigo corto y sin limite, recorrer el espacio entero es
cuestion de horas, y lo que sale del otro lado no son codigos: son las
personas a las que pertenecen.

Sobre el almacen
----------------
El contador vive en la cache. Sin ``REDIS_URL`` Django cae en ``LocMemCache``,
que es **por proceso**: con cuatro workers, el limite real es cuatro veces el
configurado. Sigue siendo infinitamente mejor que ninguno --convierte un
barrido de horas en uno de dias-- pero conviene saberlo, y por eso
``check_cache`` comprueba justamente que la cache este compartida.

Se falla **abierto** a proposito: si la cache no responde, se deja pasar. Un
formulario publico que deja de funcionar porque Redis esta caido es una
denegacion de servicio que nos hacemos solos.
"""

import logging

from django.core.cache import cache

from .client_ip import get_client_ip

logger = logging.getLogger(__name__)


class RateLimit:
    """
    Un cubo de intentos, identificado por su nombre y por quien lo consume.

    Parameters:
        name (str): identifica al formulario. Dos formularios con el mismo
            nombre compartirian cupo.
        limit (int): cuantos intentos por ventana.
        window (int): duracion de la ventana, en segundos.
    """

    def __init__(self, name: str, *, limit: int, window: int):
        self.name = name
        self.limit = limit
        self.window = window

    def key_for(self, request) -> str:
        """
        Por IP, no por sesion.

        La sesion la controla quien ataca: tirar la cookie y volver a empezar
        es una linea de script. Un contador por sesion no limita nada frente a
        lo que este limite existe para frenar.
        """
        return f'throttle:{self.name}:{get_client_ip(request)}'

    def allows(self, request) -> bool:
        """Si queda cupo. Ante un fallo de la cache, deja pasar."""
        try:
            used = cache.get(self.key_for(request))
        except Exception:
            logger.warning('Rate limit cache unavailable for %s', self.name)
            return True

        return int(used or 0) < self.limit

    def record(self, request) -> None:
        """Anota un intento. Nunca levanta."""
        key = self.key_for(request)

        try:
            cache.add(key, 0, timeout=self.window)
            cache.incr(key)
        except Exception:
            logger.warning('Could not record a rate limited attempt for %s',
                           self.name)

    def consume(self, request) -> bool:
        """
        Comprueba y anota de una vez.

        Se anota **antes** de saber si el intento acierta, para que acertar y
        fallar cuesten lo mismo. Si solo se contaran los fallos, enumerar
        saldria gratis en cuanto se encuentra el primer valido.

        Returns:
            bool: ``True`` si el intento puede seguir adelante.
        """
        if not self.allows(request):
            logger.warning(
                'Rate limit hit on %s from %s',
                self.name, get_client_ip(request),
            )
            return False

        self.record(request)

        return True
