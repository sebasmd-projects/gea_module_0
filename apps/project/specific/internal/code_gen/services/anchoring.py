# apps/project/specific/internal/code_gen/services/anchoring.py
"""
Anclaje temporal del master hash.

La pieza clave del diseno es que **el QR estampado en el resumen no contiene
la prueba**, sino la URL de una pagina que la muestra. La prueba de una TSA
llega al instante, pero la de OpenTimestamps tarda horas en madurar, y una
caja puede recibir anclajes nuevos anos despues. Si el PDF llevara el bloque
de Bitcoin impreso habria que reestampar cada vez; con la URL, el papel se
emite una sola vez y la pagina se actualiza sola.
"""

import logging
from typing import Optional

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .certification import public_base_url
from . import ots, tsa

logger = logging.getLogger(__name__)


def anchor_url(summary) -> str:
    """
    URL estable del anclaje: lo que va dentro del QR del resumen.

    Se construye con ``PUBLIC_BASE_URL``, nunca con el host de la peticion:
    este QR vive dentro de un PDF que circulara durante anos.
    """
    path = reverse(
        'certificates:summary_anchor',
        kwargs={'pk': summary.pk}
    )
    return f'{public_base_url()}{path}'


def summary_verification_url(summary) -> str:
    """URL publica de verificacion del resumen."""
    path = reverse(
        'certificates:summary_detail',
        kwargs={'pk': summary.pk}
    )
    return f'{public_base_url()}{path}'


def anchor_with_tsa(summary, *, url: Optional[str] = None):
    """
    Sella el master hash del resumen con la autoridad de sellado de tiempo.

    Returns:
        CertificationAnchorModel

    Raises:
        TSAError: si no hay TSA configurada o el sellado falla. No se guarda
        un anclaje a medias: o hay token valido o no hay anclaje.
    """
    from ..models import (AnchorStatusChoices, AnchorTypeChoices,
                          CertificationAnchorModel)

    if not summary.master_hash:
        raise tsa.TSAError(
            str(_('Seal the summary before anchoring it.'))
        )

    result = tsa.request_timestamp(summary.master_hash, url=url)

    anchor = CertificationAnchorModel.objects.create(
        summary=summary,
        anchor_type=AnchorTypeChoices.RFC3161,
        payload_hash=summary.master_hash,
        # Un sello RFC 3161 nace confirmado: la TSA ya lo firmo.
        status=AnchorStatusChoices.CONFIRMED,
        proof=result['token'],
        provider=result.get('tsa_name') or result.get('url', ''),
        stamped_at=result['gen_time'],
        serial=str(result['serial']),
        detail=str(
            _('Policy %(policy)s') % {'policy': result.get('policy', '')}
        ),
    )

    return anchor


def anchor_with_ots(summary):
    """
    Ancla el master hash en Bitcoin mediante OpenTimestamps.

    Nace **pendiente**: el compromiso esta hecho pero todavia no hay bloque.
    ``upgrade_pending_anchors()`` lo madura mas tarde. Certificar no espera a
    esto, y el papel no lleva el bloque impreso.
    """
    from ..models import (AnchorStatusChoices, AnchorTypeChoices,
                          CertificationAnchorModel)

    if not summary.master_hash:
        raise ots.OTSError(str(_('Seal the summary before anchoring it.')))

    result = ots.stamp(summary.master_hash)

    return CertificationAnchorModel.objects.create(
        summary=summary,
        anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
        payload_hash=summary.master_hash,
        status=AnchorStatusChoices.PENDING,
        proof=result['proof'],
        provider=', '.join(result['calendars']),
        detail=str(_('Waiting for inclusion in a Bitcoin block.')),
    )


def upgrade_pending_anchors(queryset=None) -> dict:
    """
    Madura las pruebas de OpenTimestamps que ya tengan bloque.

    Pensado para un cron: mientras la prueba no haya entrado en un bloque, el
    calendario responde que todavia no, y eso **no es un error**.
    """
    from ..models import (AnchorStatusChoices, AnchorTypeChoices,
                          CertificationAnchorModel)

    if queryset is None:
        queryset = CertificationAnchorModel.objects.filter(
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
            status=AnchorStatusChoices.PENDING,
        )

    checked = 0
    confirmed = 0

    for anchor in queryset:
        checked += 1

        try:
            outcome = ots.upgrade(bytes(anchor.proof or b''))
        except ots.OTSError as error:
            logger.warning('Could not upgrade anchor %s: %s', anchor.pk, error)
            continue

        if not outcome['upgraded']:
            continue

        state = ots.inspect(outcome['proof'], anchor.payload_hash)

        anchor.proof = outcome['proof']

        if state['confirmed']:
            anchor.status = AnchorStatusChoices.CONFIRMED
            anchor.detail = state['detail']
            anchor.serial = str(state['bitcoin_block'] or '')
            confirmed += 1

        anchor.save(update_fields=['proof', 'status', 'detail', 'serial',
                                   'updated'])

    return {'checked': checked, 'confirmed': confirmed}


def verify_anchor(anchor) -> dict:
    """
    Comprueba un anclaje contra el master hash actual de su resumen.

    Devuelve tanto si el token es internamente valido como si sigue
    correspondiendo al hash de hoy: un anclaje puede ser perfectamente valido
    y aun asi no acreditar el resumen actual, si esta se resello despues.
    """
    from ..models import AnchorTypeChoices

    summary = anchor.summary

    result = {
        'anchor': anchor,
        'type': anchor.anchor_type,
        'valid': False,
        'covers_current_master_hash': (
            bool(summary.master_hash)
            and anchor.payload_hash == summary.master_hash
        ),
        'detail': '',
        'stamped_at': anchor.stamped_at,
    }

    if anchor.anchor_type == AnchorTypeChoices.RFC3161:
        token = bytes(anchor.proof or b'')
        checked = tsa.verify_token(token, anchor.payload_hash)

        result['valid'] = checked['valid']
        result['detail'] = checked['detail']
        result['stamped_at'] = checked.get('gen_time') or anchor.stamped_at

    elif anchor.anchor_type == AnchorTypeChoices.OPENTIMESTAMPS:
        state = ots.inspect(bytes(anchor.proof or b''), anchor.payload_hash)

        # Una prueba pendiente es valida: el compromiso existe. Lo que aun no
        # hay es bloque, y eso se dice sin adornos.
        result['valid'] = state['valid']
        result['confirmed'] = state['confirmed']
        result['bitcoin_block'] = state['bitcoin_block']
        result['detail'] = state['detail']

    else:
        result['detail'] = str(
            _('This anchor type cannot be verified by the platform yet.')
        )

    if result['valid'] and not result['covers_current_master_hash']:
        result['detail'] = str(
            _('The anchor is valid, but it covers an earlier master hash: the '
              'summary was re-sealed after being anchored.')
        )

    return result


def summary_anchor_state(summary) -> dict:
    """
    Estado completo del anclaje, para la pagina publica.

    Es lo que ve quien escanea el QR del resumen.
    """
    from .master import verify_master_hash

    anchors = [
        verify_anchor(anchor)
        for anchor in summary.anchors.all().order_by('-created')
    ]

    confirmed = [
        item for item in anchors
        if item['valid']
        and item['covers_current_master_hash']
        # Un OTS pendiente todavia no acredita fecha: hay compromiso, no bloque.
        and item.get('confirmed', True)
    ]

    earliest = None
    for item in confirmed:
        moment = item.get('stamped_at')
        if moment and (earliest is None or moment < earliest):
            earliest = moment

    return {
        'summary': summary,
        'master': verify_master_hash(summary),
        'anchors': anchors,
        'anchored': bool(confirmed),
        'attested_since': earliest,
        'checked_at': timezone.now(),
    }
