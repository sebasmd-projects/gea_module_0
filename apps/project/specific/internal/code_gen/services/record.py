# apps/project/specific/internal/code_gen/services/record.py
"""
Registro de certificacion: el documento que lee un auditor.

Separa con claridad las dos mitades de lo que hay dentro de un certificado:

- **Contenido juridico**: lo que la firma declara sobre el activo. Eso lo
  aporta el documento en si y la firma del representante legal; la plataforma
  lo transporta, no lo produce ni lo avala.

- **Integridad digital**: la prueba de que el archivo que tienes delante es
  exactamente el que se registro. Eso es lo que acredita este registro.

El registro es un JSON deterministico y sellado. Un auditor puede:

1. calcular el SHA-256 del PDF que tiene en la mano,
2. compararlo con el que figura aqui,
3. comprobar el sello con la clave publica de la plataforma,

sin necesidad de conectarse a la plataforma ni de confiar en ella en el
momento de la comprobacion.
"""

import base64
import hashlib
import hmac
import json
import logging
from typing import Optional

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from .certification import public_base_url

logger = logging.getLogger(__name__)

RECORD_SCHEMA = 'gea.certification-record/1'

SEAL_ED25519 = 'Ed25519'
SEAL_HMAC = 'HMAC-SHA256'

HMAC_SEAL_INFO = b'gea-certification-record-seal-v1'

ISSUER_NAME = 'PROPENSIONES ABOGADOS INTERNACIONAL S.A.S.'
ISSUER_NIT = '901.409.813-7'

STATUS_VALID = 'VALID'
STATUS_EXPIRED = 'EXPIRED'
STATUS_REVOKED = 'REVOKED'
STATUS_NOT_CERTIFIED = 'NOT_CERTIFIED'


# ==========================================================
# Claves
# ==========================================================

def _signing_key():
    """
    Clave privada Ed25519 de la plataforma, si esta configurada.

    Se lee de ``CERTIFICATION_SIGNING_KEY`` (32 bytes en base64). Sin ella el
    registro se sella con HMAC, que solo la propia plataforma puede verificar.
    """
    raw = getattr(settings, 'CERTIFICATION_SIGNING_KEY', '') or ''

    if not raw:
        return None

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey

        return Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(raw)
        )
    except Exception:
        logger.exception(
            'CERTIFICATION_SIGNING_KEY is set but could not be loaded; '
            'falling back to the HMAC seal'
        )
        return None


def public_key_b64() -> Optional[str]:
    """Clave publica Ed25519 en base64, para publicarla."""
    key = _signing_key()

    if key is None:
        return None

    from cryptography.hazmat.primitives import serialization

    return base64.b64encode(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode('ascii')


def key_id() -> Optional[str]:
    """Identificador corto de la clave publica (SHA-256 truncado)."""
    public = public_key_b64()

    if not public:
        return None

    return hashlib.sha256(
        base64.b64decode(public)
    ).hexdigest()[:16]


def _hmac_seal_key() -> bytes:
    """Clave derivada para el sello HMAC, para no exponer SECRET_KEY."""
    return hmac.new(
        key=settings.SECRET_KEY.encode('utf-8'),
        msg=HMAC_SEAL_INFO,
        digestmod=hashlib.sha256,
    ).digest()


# ==========================================================
# Serializacion deterministica
# ==========================================================

def canonical_bytes(payload: dict) -> bytes:
    """
    Serializacion estable del registro, la que se firma.

    Claves ordenadas, sin espacios y en UTF-8: dos ejecuciones sobre el mismo
    documento producen exactamente los mismos bytes, de modo que el sello se
    puede recalcular y comparar.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
    ).encode('utf-8')


# ==========================================================
# Construccion del registro
# ==========================================================

def document_status(document) -> str:
    """Estado del certificado en el momento de emitir el registro."""
    from apps.project.specific.documents.certificates.models import \
        CertificationStatusChoices

    if document.certification_status == CertificationStatusChoices.REVOKED:
        return STATUS_REVOKED

    if document.certification_status != CertificationStatusChoices.CERTIFIED:
        return STATUS_NOT_CERTIFIED

    if document.is_expired:
        return STATUS_EXPIRED

    return STATUS_VALID


def _file_entry(sha256: str, content_sha256: str, role: str) -> dict:
    return {
        'role': role,
        'sha256': sha256 or None,
        'content_sha256': content_sha256 or None,
    }


def build_certification_record(document, request=None) -> dict:
    """
    Construye el registro de certificacion de un documento.

    Parameters:
        document: instancia de ``DocumentVerificationModel``.
        request: se acepta por comodidad de las vistas, pero NO influye en las
            URLs: estas se construyen siempre contra ``PUBLIC_BASE_URL`` para
            que el registro sea el mismo se pida desde donde se pida.

    Returns:
        dict: registro sellado, listo para serializar.
    """
    base = public_base_url()

    verification_url = document.qr_payload or (
        base + reverse(
            'certificates:detail_document_verification_aegis',
            kwargs={'pk': document.pk}
        )
    )

    payload = {
        'schema': RECORD_SCHEMA,
        'status': document_status(document),
        'algorithm': 'SHA-256',

        'certificate': {
            'id': str(document.pk),
            'public_code': document.public_code,
            'uuid_prefix': document.uuid_prefix,
            'title': document.document_title,
            'type': document.certificate_type,
            'code': document.code_payload or None,
            'sequence': document.code_sequence or None,
            'initials': document.code_initials or None,
        },

        'issuer': {
            'name': ISSUER_NAME,
            'nit': ISSUER_NIT,
        },

        'dates': {
            'issued_at': (
                document.issued_at.isoformat()
                if document.issued_at else None
            ),
            'certified_at': (
                document.certified_at.isoformat()
                if document.certified_at else None
            ),
            'expires_at': (
                document.expires_at.isoformat()
                if document.expires_at else None
            ),
            'record_generated_at': timezone.now().isoformat(),
        },

        'files': {
            'original': _file_entry(
                document.source_hash,
                document.source_content_hash,
                'Original document filed with the platform, without codes. '
                'Not distributed publicly.',
            ),
            'certified': _file_entry(
                document.document_hash,
                document.certified_content_hash,
                'The original with its QR and barcode embedded. This is the '
                'file the certification refers to.',
            ),
            'public_copy': _file_entry(
                document.public_copy_hash,
                document.public_copy_content_hash,
                'Distributable digital copy, visually identical to the '
                'certified file, carrying a hidden watermark. This is the one '
                'shared with third parties.',
            ),
        },

        'verification_url': verification_url,

        'scope': {
            'attests': (
                'That the files listed above are byte-for-byte the ones '
                'registered by the issuer on the certification date, and that '
                'any later alteration of their content is detectable.'
            ),
            'does_not_attest': (
                'The truthfulness of the statements contained in the document, '
                'nor the existence, ownership or valuation of the assets it '
                'describes. That is the legal content of the certificate and '
                'rests on the issuer, not on this integrity record.'
            ),
        },

        'how_to_verify': [
            'Compute the SHA-256 of the PDF you hold: '
            'sha256sum <file>.pdf   (Linux/macOS)   or   '
            'certutil -hashfile <file>.pdf SHA256   (Windows).',
            'Compare it against files.original.sha256, files.certified.sha256 '
            'or files.public_copy.sha256 in this record. A match on any of '
            'them identifies which of the three files you were given.',
            'Verify the seal of this record with the platform public key '
            '(see seal.public_key_url). Sign/verify covers every field except '
            '"seal" itself, serialised as compact JSON with sorted keys.',
            'Optionally, open verification_url to check the live status of '
            'the certificate (expiry or revocation are not frozen in this '
            'record).',
            'The content_sha256 values are computed by the platform over the '
            'renderable content of the PDF, ignoring document metadata. They '
            'are not reproducible with standard command-line tools; use the '
            'file upload at verification_url instead.',
        ],
    }

    return seal_record(payload, request=request)


# ==========================================================
# Sellado y verificacion
# ==========================================================

def seal_record(payload: dict, request=None) -> dict:
    """
    Anade el sello criptografico al registro.

    Con ``CERTIFICATION_SIGNING_KEY`` configurada, el sello es una firma
    Ed25519 que cualquiera puede verificar con la clave publica. Sin ella, se
    emite un HMAC que solo la plataforma puede comprobar, y el propio registro
    lo advierte.
    """
    payload = dict(payload)
    payload.pop('seal', None)

    message = canonical_bytes(payload)

    key = _signing_key()

    if key is not None:
        public = public_key_b64()

        payload['seal'] = {
            'algorithm': SEAL_ED25519,
            'key_id': key_id(),
            'public_key': public,
            'public_key_url': (
                public_base_url()
                + reverse('certificates:certification_public_key')
            ),
            'signature': base64.b64encode(key.sign(message)).decode('ascii'),
            'covers': (
                'Every field of this record except "seal", serialised as '
                'compact JSON with sorted keys, UTF-8.'
            ),
        }
        return payload

    payload['seal'] = {
        'algorithm': SEAL_HMAC,
        'key_id': 'platform-shared-secret',
        'signature': base64.b64encode(
            hmac.new(_hmac_seal_key(), message, hashlib.sha256).digest()
        ).decode('ascii'),
        'covers': (
            'Every field of this record except "seal", serialised as compact '
            'JSON with sorted keys, UTF-8.'
        ),
        'warning': (
            'This seal is symmetric: only the issuing platform can verify it. '
            'For a seal any third party can verify offline, the platform must '
            'be configured with an Ed25519 signing key.'
        ),
    }
    return payload


def verify_record(record: dict) -> bool:
    """
    Comprueba el sello de un registro.

    Returns:
        bool: True si el sello corresponde al contenido del registro.
    """
    if not isinstance(record, dict):
        return False

    seal = record.get('seal')

    if not isinstance(seal, dict):
        return False

    payload = {key: value for key, value in record.items() if key != 'seal'}
    message = canonical_bytes(payload)

    signature_b64 = seal.get('signature') or ''

    try:
        signature = base64.b64decode(signature_b64)
    except Exception:
        return False

    algorithm = seal.get('algorithm')

    if algorithm == SEAL_ED25519:
        public = seal.get('public_key') or public_key_b64()

        if not public:
            return False

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import \
                Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(public)
            ).verify(signature, message)
            return True
        except Exception:
            return False

    if algorithm == SEAL_HMAC:
        expected = hmac.new(
            _hmac_seal_key(), message, hashlib.sha256
        ).digest()
        return constant_time_compare(
            base64.b64encode(expected).decode('ascii'),
            signature_b64,
        )

    return False


def record_filename(document) -> str:
    """Nombre del archivo descargable."""
    reference = document.public_code or str(document.pk)[:8]
    return f'registro-certificacion-{reference}.json'


def record_json(document, request=None) -> str:
    """Registro serializado, legible para una persona."""
    return json.dumps(
        build_certification_record(document, request=request),
        indent=2,
        ensure_ascii=False,
    )
