# apps/project/specific/internal/code_gen/services/ots.py
"""
Anclaje en Bitcoin con OpenTimestamps.

Por que sale gratis: unos servidores publicos («calendarios») juntan miles de
hashes de todo el mundo en un arbol Merkle y publican **una sola** transaccion
de Bitcoin con la raiz. La prueba de cada uno es el camino desde su hash hasta
esa transaccion, asi que el coste se reparte entre todos. Sin cartera, sin
dinero, sin claves que custodiar.

Lo que sube: **solo el hash**. Nunca el documento ni el payload.

Dos tiempos
-----------
1. Al sellar, el calendario devuelve al momento una prueba **pendiente**: el
   compromiso esta hecho, pero todavia no hay bloque.
2. Entre 1 y 6 horas despues la prueba **madura**: se le puede pedir al
   calendario el camino completo hasta una cabecera de bloque de Bitcoin.

De ahi que la certificacion **no pueda bloquearse esperando**, y de ahi que el
QR impreso apunte a una URL y no lleve el bloque dentro: la pagina se actualiza
sola cuando la prueba madura.
"""

import logging
from typing import List, Optional

from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

# Calendarios publicos. Se envia a varios: si uno desaparece, la prueba sigue
# siendo valida por los otros.
DEFAULT_CALENDARS = (
    'https://alice.btc.calendar.opentimestamps.org',
    'https://bob.btc.calendar.opentimestamps.org',
    'https://finney.calendar.eternitywall.com',
)

SUBMIT_TIMEOUT = 15


class OTSError(Exception):
    """El anclaje en Bitcoin no se pudo completar."""


def _attestation_uri(attestation) -> str:
    """
    URI de un calendario pendiente.

    Segun la version de la libreria puede venir como ``str`` o como ``bytes``;
    asumir solo una de las dos dejaba la lista de calendarios vacia sin dar
    ningun error.
    """
    uri = getattr(attestation, 'uri', '')

    if isinstance(uri, (bytes, bytearray)):
        try:
            return bytes(uri).decode('utf-8')
        except UnicodeDecodeError:
            return ''

    return str(uri or '')


def _calendars() -> tuple:
    from django.conf import settings

    configured = getattr(settings, 'OPENTIMESTAMPS_CALENDARS', None)

    if configured:
        return tuple(configured)

    return DEFAULT_CALENDARS


def serialize(detached) -> bytes:
    """Serializa un ``DetachedTimestampFile`` al formato .ots."""
    from opentimestamps.core.serialize import BytesSerializationContext

    ctx = BytesSerializationContext()
    detached.serialize(ctx)
    return ctx.getbytes()


def deserialize(blob: bytes):
    """Lee un .ots y devuelve el ``DetachedTimestampFile``."""
    from opentimestamps.core.serialize import BytesDeserializationContext
    from opentimestamps.core.timestamp import DetachedTimestampFile

    return DetachedTimestampFile.deserialize(
        BytesDeserializationContext(bytes(blob))
    )


def stamp(digest_hex: str, *, calendars: Optional[tuple] = None) -> dict:
    """
    Envia el hash a los calendarios y devuelve la prueba pendiente.

    Returns:
        dict: ``{'proof': bytes, 'calendars': [...], 'pending': True}``

    Raises:
        OTSError: si ningun calendario responde. Con que uno acepte, basta.
    """
    from opentimestamps.calendar import RemoteCalendar
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.timestamp import (DetachedTimestampFile,
                                               Timestamp)

    try:
        digest = bytes.fromhex(digest_hex)
    except ValueError as error:
        raise OTSError(str(_('The hash is not valid hexadecimal.'))) from error

    if len(digest) != 32:
        raise OTSError(str(_('Only SHA-256 digests are supported.')))

    timestamp = Timestamp(digest)
    reached = []

    for url in (calendars or _calendars()):
        try:
            remote = RemoteCalendar(url)
            remote.timeout = SUBMIT_TIMEOUT
            partial = remote.submit(digest)
            timestamp.merge(partial)
            reached.append(url)
        except Exception as error:
            # Un calendario caido no invalida el anclaje: se sigue con el resto.
            logger.warning('OpenTimestamps calendar %s failed: %s', url, error)

    if not reached:
        raise OTSError(
            str(_('No OpenTimestamps calendar could be reached.'))
        )

    detached = DetachedTimestampFile(OpSHA256(), timestamp)

    return {
        'proof': serialize(detached),
        'calendars': reached,
        'pending': True,
    }


def _walk(timestamp):
    """Recorre el arbol de la prueba y va soltando cada marca encontrada."""
    for attestation in timestamp.attestations:
        yield attestation

    for _op, sub in timestamp.ops.items():
        yield from _walk(sub)


def inspect(proof: bytes, digest_hex: str) -> dict:
    """
    Lee una prueba .ots y dice en que estado esta.

    Returns:
        dict: ``{'valid': bool, 'confirmed': bool, 'bitcoin_block': int|None,
        'pending_calendars': [...], 'detail': str}``
    """
    from opentimestamps.core.notary import (BitcoinBlockHeaderAttestation,
                                            PendingAttestation)

    result = {
        'valid': False,
        'confirmed': False,
        'bitcoin_block': None,
        'pending_calendars': [],
        'detail': '',
    }

    if not proof:
        result['detail'] = str(_('There is no OpenTimestamps proof stored.'))
        return result

    try:
        detached = deserialize(proof)
    except Exception:
        result['detail'] = str(_('The proof file could not be read.'))
        return result

    if detached.timestamp.msg.hex().lower() != (digest_hex or '').lower():
        result['detail'] = str(
            _('The proof covers a different hash: it does not attest this '
              'summary.')
        )
        return result

    result['valid'] = True

    heights = []

    for attestation in _walk(detached.timestamp):
        if isinstance(attestation, BitcoinBlockHeaderAttestation):
            heights.append(attestation.height)
        elif isinstance(attestation, PendingAttestation):
            uri = _attestation_uri(attestation)
            if uri:
                result['pending_calendars'].append(uri)

    if heights:
        result['confirmed'] = True
        # El bloque mas bajo es el que da la fecha mas temprana probada.
        result['bitcoin_block'] = min(heights)
        result['detail'] = str(
            _('Committed to Bitcoin block %(block)s.')
            % {'block': result['bitcoin_block']}
        )
    else:
        result['detail'] = str(
            _('The commitment is made; waiting for it to be included in a '
              'Bitcoin block (usually a few hours).')
        )

    return result


def upgrade(proof: bytes) -> dict:
    """
    Pide a los calendarios el camino completo hasta el bloque de Bitcoin.

    Returns:
        dict: ``{'upgraded': bool, 'proof': bytes}``. ``upgraded`` es falso
        cuando la prueba todavia no ha madurado, que no es un error.
    """
    from opentimestamps.calendar import RemoteCalendar
    from opentimestamps.core.notary import PendingAttestation

    try:
        detached = deserialize(proof)
    except Exception as error:
        raise OTSError(str(_('The proof file could not be read.'))) from error

    changed = False

    def walk_and_upgrade(timestamp):
        nonlocal changed

        pending = [
            attestation for attestation in timestamp.attestations
            if isinstance(attestation, PendingAttestation)
        ]

        for attestation in pending:
            try:
                url = _attestation_uri(attestation)
                if not url:
                    continue
                remote = RemoteCalendar(url)
                remote.timeout = SUBMIT_TIMEOUT
                upgraded = remote.get_timestamp(timestamp.msg)
                timestamp.merge(upgraded)
                changed = True
            except Exception as error:
                logger.info(
                    'OpenTimestamps not ready yet at %s: %s',
                    _attestation_uri(attestation), error
                )

        for _op, sub in list(timestamp.ops.items()):
            walk_and_upgrade(sub)

    walk_and_upgrade(detached.timestamp)

    return {
        'upgraded': changed,
        'proof': serialize(detached) if changed else bytes(proof),
    }
