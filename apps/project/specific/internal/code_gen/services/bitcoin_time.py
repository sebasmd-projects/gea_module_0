"""
La hora que un bloque de Bitcoin acredita, y de donde se saca.

El problema
-----------
Una prueba de OpenTimestamps madura diciendo **una altura de bloque**, no una
fecha: `BitcoinBlockHeaderAttestation(964899)`. La fecha esta en la cabecera de
ese bloque, y la cabecera no viaja dentro de la prueba --seria redundante, la
tiene toda la red-- asi que hay que ir a buscarla. Por eso la columna «Attested
time» de la pagina de anclaje salia vacia con el anclaje **confirmado**: el dato
existia, en la cadena, y nadie iba a por el.

Cuando se va a buscar, y cuando no
----------------------------------
**Nunca dentro de una peticion.** Con `ATOMIC_REQUESTS` puesto, una llamada de
red en el camino de renderizar una pagina publica es una transaccion abierta
esperando a un tercero. Se resuelve **una sola vez**, en el cron que ya sale a
la red a madurar las pruebas (`upgrade_ots_anchors`), y se guarda en
`stamped_at`. Si falla, el anclaje se confirma igual y la fecha se queda vacia:
el cron la vuelve a intentar en la siguiente vuelta.

Por que dos fuentes y no una
----------------------------
Porque la pagina donde acaba esta fecha dice, literalmente, «un tercero
acredito la fecha; no es esta plataforma diciendolo». Una fecha sacada de un
solo explorador **si** es esta plataforma diciendolo, con un intermediario: si
ese explorador se equivoca o miente, la firma de un certificado lleva una fecha
que nadie comprobo.

Asi que se pregunta a dos exploradores independientes y **solo se guarda si
coinciden**. Si discrepan no se guarda nada y queda en el log: es la misma razon
por la que la prueba se manda a varios calendarios. Cuesta dos peticiones, una
vez en la vida de cada anclaje.

Lo que esta fecha es, exactamente
---------------------------------
Es la hora **declarada en la cabecera** del bloque, que es lo que acredita
OpenTimestamps y lo que enseña cualquier explorador. Las reglas de consenso la
acotan --posterior a la mediana de los once bloques anteriores, y no mas de dos
horas por delante del reloj de la red-- pero no la fijan al segundo. Sirve para
lo que se usa aqui: Bitcoin prueba un **techo**, que el contenido existia a mas
tardar entonces, nunca un suelo.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

#: Exploradores con API de Esplora (`/block-height/<n>` y `/block/<hash>`).
#: Son dos operadores distintos a proposito: de nada sirve corroborar una cifra
#: preguntando dos veces a la misma casa.
DEFAULT_EXPLORERS = (
    'https://mempool.space/api',
    'https://blockstream.info/api',
)

#: Corto: esto corre en un cron cada 15 minutos y no puede quedarse colgado.
TIMEOUT = 10


def _explorers() -> tuple:
    from django.conf import settings

    configured = getattr(settings, 'BITCOIN_BLOCK_EXPLORERS', None)

    return tuple(configured) if configured else DEFAULT_EXPLORERS


def _timestamp_from(base: str, height: int) -> Optional[int]:
    """
    La marca de tiempo de la cabecera segun un explorador, o `None`.

    Dos saltos porque la API de Esplora es asi: la altura da el hash del bloque
    y el hash da el bloque. Se comprueba de paso que el bloque devuelto sea el
    de la altura pedida, que es barato y descarta una respuesta cruzada.
    """
    import requests

    try:
        answer = requests.get(
            f'{base}/block-height/{height}', timeout=TIMEOUT)
        answer.raise_for_status()

        block_hash = answer.text.strip()

        if len(block_hash) != 64:
            logger.info(
                'Bitcoin explorer %s answered an unusable hash for block %s',
                base, height)
            return None

        answer = requests.get(f'{base}/block/{block_hash}', timeout=TIMEOUT)
        answer.raise_for_status()

        block = answer.json()
    except Exception as error:
        # Que un explorador no conteste no es un fallo de nada: se intenta en
        # la vuelta siguiente del cron.
        logger.info(
            'Bitcoin explorer %s did not answer for block %s: %s',
            base, height, error)
        return None

    if block.get('height') != height:
        logger.warning(
            'Bitcoin explorer %s answered block %s when asked for %s',
            base, block.get('height'), height)
        return None

    moment = block.get('timestamp')

    return moment if isinstance(moment, int) else None


def block_time(height: int) -> Optional[datetime]:
    """
    La hora de la cabecera del bloque, solo si dos fuentes dicen lo mismo.

    Args:
        height: altura del bloque, tal y como la acredita la prueba .ots.

    Returns:
        La fecha en UTC, o ``None`` si no se pudo establecer --porque no
        contestaron, o porque **no coincidieron**, que no es lo mismo pero se
        resuelve igual: no se escribe nada.
    """
    if not height:
        return None

    seen = {}

    for base in _explorers():
        moment = _timestamp_from(base, height)

        if moment is not None:
            seen.setdefault(moment, []).append(base)

    if not seen:
        return None

    agreed = [
        moment for moment, sources in seen.items() if len(sources) >= 2
    ]

    if not agreed:
        # O solo contesto uno, o contestaron cosas distintas. Lo segundo es
        # serio y se dice mas alto: significa que alguien esta equivocado sobre
        # un bloque de Bitcoin, y esa fecha iba a ir en un certificado.
        if len(seen) > 1:
            logger.error(
                'Bitcoin explorers disagree on the time of block %s: %s. '
                'No date recorded.',
                height,
                {moment: sources for moment, sources in seen.items()},
            )
        else:
            logger.info(
                'Only one source answered for block %s; not enough to record '
                'a date.', height)

        return None

    return datetime.fromtimestamp(min(agreed), tz=timezone.utc)
