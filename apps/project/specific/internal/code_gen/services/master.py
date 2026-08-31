# apps/project/specific/internal/code_gen/services/master.py
"""
Master hash de un resumen AEGIS.

Un resumen (AEGIS-6) integra N certificados. El master hash es la huella del
conjunto: una sola cifra que compromete transitivamente las huellas de todos
sus miembros, y que es lo unico que sale a anclarse.

**La circularidad**, otra vez y por escrito: el master hash cubre a los
miembros y **nunca al propio resumen**. El orden es

    1. sellar        -> master hash de los N miembros
    2. emitir        -> el PDF del resumen, llevando ese hash estampado
    3. registrar     -> la huella del propio resumen, ya como documento

Si el resumen entrara en su propio hash no habria forma de calcularlo. Es el
mismo patron que el codigo de barras con el hash del original.

Que huella de cada miembro entra
--------------------------------
``sha256`` es el **hash del archivo certificado** (``document_hash``), el que
lleva los codigos y el que hace fe. ``content_sha256`` va como campo aparte:
es la huella del contenido renderizable, tolerante a cambios de metadatos, y
sirve para reconocer el mismo documento tras pasar por un correo.
"""

import hashlib
import logging
from typing import Optional

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .jcs import canonicalize
from .record import ISSUER_NAME, ISSUER_NIT

logger = logging.getLogger(__name__)

MASTER_SCHEMA = 'AEGIS-MASTER-HASH-V1'
CANONICALIZATION = 'JCS/RFC8785'
HASH_ALGORITHM = 'SHA-256'


class MasterHashError(Exception):
    """No se puede sellar el resumen."""


def build_master_payload(summary) -> dict:
    """
    Construye el payload canonico de un resumen.

    Parameters:
        summary: instancia de ``AegisSummaryModel``.

    Returns:
        dict: el payload, listo para canonicalizar.

    Raises:
        MasterHashError: si algun miembro no esta certificado o le falta la
        huella. Sellar un resumen incompleta produciria un hash que no acredita
        lo que dice acreditar.
    """
    members = list(summary.ordered_members())

    if not members:
        raise MasterHashError(
            str(_('The summary has no member documents.'))
        )

    documents = []

    for member in members:
        document = member.document

        if not document.is_certified:
            raise MasterHashError(
                str(
                    _('%(code)s is not certified yet.')
                    % {'code': member.code}
                )
            )

        if not document.document_hash:
            raise MasterHashError(
                str(
                    _('%(code)s has no certified fingerprint.')
                    % {'code': member.code}
                )
            )

        documents.append({
            'code': member.code,
            'id': str(document.pk),
            'document_type': (
                member.document_type_label
                or str(document.get_certificate_type_display())
            ),
            'sha256': document.document_hash,
            'content_sha256': document.certified_content_hash or '',
        })

    issued_at = summary.issued_at or timezone.localdate()

    return {
        'schema': MASTER_SCHEMA,
        'canonicalization': CANONICALIZATION,
        'hash_algorithm': HASH_ALGORITHM,
        'issuer': {
            'name': ISSUER_NAME,
            'nit': ISSUER_NIT,
        },
        'aegis_summary_id': str(summary.pk),
        'asset': {
            # El vinculo es por UUID; la etiqueta es solo para leerlo.
            'id': str(summary.asset_id) if summary.asset_id else '',
            'label': summary.asset_label or '',
        },
        'issued_at': issued_at.isoformat(),
        'documents': documents,
    }


def compute_master_hash(payload: dict) -> tuple:
    """
    Canonicaliza el payload y lo hashea.

    Returns:
        tuple[str, str]: (master hash en hex, payload canonico como texto).
    """
    canonical = canonicalize(payload)
    digest = hashlib.sha256(canonical).hexdigest()
    return digest, canonical.decode('utf-8')


def seal_summary(summary, *, issued_at=None) -> str:
    """
    Sella el resumen: calcula el master hash y lo guarda con su payload exacto.

    El payload se almacena verbatim, no reconstruido: asi un auditor puede
    recalcular el hash sobre los mismos bytes anos despues, aunque para
    entonces los documentos hayan cambiado de nombre o el formato haya
    evolucionado.
    """
    from apps.project.specific.documents.certificates.models import \
        SummaryStatusChoices

    if issued_at:
        summary.issued_at = issued_at

    payload = build_master_payload(summary)
    digest, canonical = compute_master_hash(payload)

    summary.master_hash = digest
    summary.canonical_payload = canonical
    summary.sealed_at = timezone.now()

    if summary.status == SummaryStatusChoices.DRAFT:
        summary.status = SummaryStatusChoices.SEALED

    summary.save(update_fields=[
        'master_hash', 'canonical_payload', 'sealed_at',
        'status', 'issued_at', 'updated',
    ])

    return digest


def verify_master_hash(summary) -> dict:
    """
    Recalcula el master hash y lo compara con lo almacenado.

    Dos comprobaciones distintas, porque fallan por motivos distintos:

    - ``stored_matches_payload``: el hash guardado corresponde a los bytes
      guardados. Si falla, el registro esta corrupto.
    - ``payload_matches_members``: el payload guardado sigue describiendo a los
      miembros actuales. Si falla, el resumen cambio despues de sellarse — que es
      exactamente lo que el sello debe delatar.
    """
    result = {
        'sealed': bool(summary.master_hash),
        'stored_matches_payload': False,
        'payload_matches_members': False,
        'stored_hash': summary.master_hash,
        'recomputed_hash': None,
        'detail': None,
    }

    if not summary.master_hash or not summary.canonical_payload:
        result['detail'] = str(_('The summary has not been sealed yet.'))
        return result

    stored = hashlib.sha256(
        summary.canonical_payload.encode('utf-8')
    ).hexdigest()

    result['stored_matches_payload'] = (stored == summary.master_hash)

    try:
        payload = build_master_payload(summary)
        digest, _canonical = compute_master_hash(payload)
        result['recomputed_hash'] = digest
        result['payload_matches_members'] = (digest == summary.master_hash)
    except MasterHashError as error:
        result['detail'] = str(error)
        return result

    if not result['stored_matches_payload']:
        result['detail'] = str(
            _('The stored hash does not match the stored payload: the record '
              'is corrupt.')
        )
    elif not result['payload_matches_members']:
        result['detail'] = str(
            _('The summary changed after it was sealed: its members no longer '
              'match the sealed payload.')
        )
    else:
        result['detail'] = str(_('The master hash is consistent.'))

    return result
