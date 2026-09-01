# apps/common/utils/throttling.py
"""
Limite de intentos por IP para formularios publicos.

Existe porque habia tres implementaciones del mismo contador --en el mixin de
OTP, en la recuperacion de contrasena y en el de PQRS-- y faltaba en el sitio
que mas lo necesitaba: la consulta de certificados de persona.

Por que el fallo por defecto es **cerrado**
-------------------------------------------
La primera version de este modulo fallaba abierta siempre, con este
razonamiento: "un formulario publico que deja de funcionar porque Redis esta
caido es una denegacion de servicio que nos hacemos solos". El razonamiento
vale, pero **no vale para todos los limites por igual**, y aplicarlo de forma
uniforme fue el error.

La pregunta que decide es que impide el limite:

* Si impide una **molestia que se acaba cuando se acaba el corte** --spam en
  un formulario-- fallar abierto es razonable: se absorbe la molestia y el
  servicio sigue de pie.
* Si el limite **es el control de seguridad** --lo unico que separa a un
  desconocido de recorrer un espacio de codigos, o de llenar el buzon de un
  tercero-- fallar abierto es un bypass. Y el dano no se acaba con el corte:
  una plantilla enumerada esta enumerada para siempre.

La asimetria es la que manda. Fallar cerrado cuesta que una funcion de
consulta no este disponible mientras dure una averia que ya es una averia.
Fallar abierto cuesta una fuga permanente, silenciosa, de la que nadie se
entera. Por eso el defecto es cerrado y ``fail_open=True`` hay que pedirlo a
mano, con su razon escrita al lado.

Como se detecta que la cache no responde
----------------------------------------
No con un ``try/except``, que es lo que hacia la primera version y **nunca se
ejecutaba**. La cache va con ``IGNORE_EXCEPTIONS`` a proposito (un Redis
caido no puede tumbar el login), y eso significa que ``django-redis``
**devuelve ``None`` en vez de lanzar**. El fallo abierto no pasaba por el
manejador de excepciones: pasaba porque ``cache.get`` devolvia ``None``,
``None or 0`` es ``0``, y ``0 < limite``.

Lo que si distingue una cache viva de una muerta es el valor que devuelve
``incr``: un entero cuando la operacion surtio efecto, ``None`` cuando se la
tragaron. De ahi sale el detector, y por eso se incrementa **antes** de
comparar en lugar de leer primero.
"""

import hashlib
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
        fail_open (bool): que hacer si la cache no responde. Por defecto
            ``False`` -- se rechaza. Ponerlo en ``True`` es decir "prefiero
            aguantar el abuso a cortar el servicio", y eso solo vale cuando lo
            que se evita es una molestia pasajera.
        reason (str): por que se eligio ``fail_open``. Obligatorio cuando se
            pone: sin razon escrita, la siguiente persona no sabe si fue
            deliberado o un descuido.
    """

    def __init__(self, name: str, *, limit: int, window: int,
                 fail_open: bool = False, reason: str = ''):
        if fail_open and not reason:
            raise ValueError(
                f'{name}: fail_open needs a written reason'
            )

        self.name = name
        self.limit = limit
        self.window = window
        self.fail_open = fail_open
        self.reason = reason

    def key_for(self, request, scope=None) -> str:
        """
        Por IP salvo que se diga otra cosa.

        Sin ``scope`` el cubo es de la direccion, no de la sesion: la sesion
        la controla quien ataca, y tirar la cookie para empezar de cero es una
        linea de script.

        Con ``scope`` el cubo es de **eso**, sea lo que sea, y la IP no entra.
        Es lo que hace falta cuando lo que se protege no es el servidor sino un
        tercero: el cupo de correos hacia un buzon concreto tiene que agotarse
        aunque quien los pida cambie de direccion en cada intento; si la IP
        formara parte de la llave, rotarla seria el bypass.

        El ``scope`` se guarda **hasheado**. Suele ser un correo o un numero de
        documento, y una llave de cache es un sitio donde nadie espera
        encontrar datos personales: quedan en Redis, salen en un ``KEYS`` y
        sobreviven al proceso. El hash conserva lo unico que hace falta --que
        dos valores iguales caigan en el mismo cubo-- y de paso evita los
        espacios y acentos que rompen las llaves en otros backends.
        """
        if scope is None:
            scope = get_client_ip(request)
        else:
            scope = hashlib.sha256(
                str(scope).strip().lower().encode()).hexdigest()[:32]

        return f'throttle:{self.name}:{scope}'

    def _bump(self, key):
        """
        Suma uno y devuelve el total, o ``None`` si la cache no responde.

        Ese ``None`` es el detector. Con ``IGNORE_EXCEPTIONS`` puesto,
        ``django-redis`` se traga el error de conexion y devuelve ``None`` en
        lugar de lanzar, asi que un ``try/except`` aqui no se enteraria de
        nada. Lo unico que distingue una cache viva es que ``incr`` devuelva
        un numero.
        """
        try:
            cache.add(key, 0, timeout=self.window)
            return cache.incr(key)
        except ValueError:
            # La clave expiro entre el `add` y el `incr`. Es una carrera
            # normal, no una averia: se cuenta como primer intento.
            return 1
        except Exception:
            return None

    def consume(self, request, scope=None) -> bool:
        """
        Anota un intento y dice si puede seguir adelante.

        Se anota **antes** de saber si el intento acierta, para que acertar y
        fallar cuesten lo mismo: contando solo los fallos, enumerar sale
        gratis en cuanto se encuentra el primer valor valido.

        Returns:
            bool: ``True`` si el intento puede continuar.
        """
        used = self._bump(self.key_for(request, scope))

        if used is None:
            return self._on_cache_down(request)

        if used > self.limit:
            logger.warning(
                'Rate limit hit on %s from %s (%s in %ss)',
                self.name, get_client_ip(request), used, self.window,
            )
            return False

        return True

    def _on_cache_down(self, request) -> bool:
        """
        Que hacer cuando el contador no se puede llevar.

        En los dos casos se registra a nivel de error, no de aviso: es una
        averia de infraestructura que ademas degrada una defensa, y tiene que
        salir en cualquier revision del log. `manage.py check_cache` dice si
        la cache esta viva y compartida.
        """
        if self.fail_open:
            logger.error(
                'Cache unavailable: %s is NOT being enforced right now. '
                'Allowing through by design (%s)',
                self.name, self.reason,
            )
            return True

        logger.error(
            'Cache unavailable: %s cannot be enforced, so the request from '
            '%s is refused rather than allowed through.',
            self.name, get_client_ip(request),
        )

        return False

    # Compatibilidad con el uso anterior, por si queda alguna llamada suelta.
    def allows(self, request, scope=None) -> bool:
        return self.consume(request, scope)
