# apps/project/specific/documents/certificates/external.py
"""
Certificacion para emisores externos (otra plataforma que manda PDF por servidor).

Tres endpoints JSON, sin Django REST Framework (el proyecto no lo usa):

* ``POST /api/certificates/external/``                       certificar
* ``GET  /api/certificates/external/<id>/public-copy/``      bajar la copia
* ``POST /api/certificates/external/<id>/revoke/``           revocar

Autenticacion: cabecera ``X-Issuer-Key`` comparada en tiempo constante con la
clave del emisor de ``settings.GEA_EXTERNAL_ISSUERS``. El emisor se indica en
el campo ``issuer`` (POST) o en la cabecera ``X-Issuer``. Un fallo de cualquier
tipo --clave mala, emisor inexistente, emisor sin clave-- responde el mismo
403 generico, para que no sirva de oraculo.

El cupo es de ``RateLimit`` (falla cerrado si la cache cae) y se consume
**despues** de autenticar: quien no tiene la clave no puede gastar el cupo del
emisor. Los intentos fallidos se cuentan aparte, por IP.

Propietario: ``DocumentVerificationModel`` no exige usuario --los titulares son
un M2M opcional (``holders``)--, asi que estos documentos quedan sin titulares
y se asocian al emisor por ``external_issuer``. No hay usuario de servicio.
"""

import hmac
import json
import logging
import math
from io import BytesIO
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from pypdf import PdfReader

from apps.common.utils.throttling import RateLimit
from apps.project.specific.internal.code_gen.constants import (
    CERTIFIABLE_EXTENSIONS, MAX_UPLOAD_BYTES)
from apps.project.specific.internal.code_gen.services.certification import (
    CertificationError, CodeOptions, build_verification_url, certify_document,
    public_base_url)
from apps.project.specific.internal.code_gen.services.codes import \
    validate_barcode_payload
from apps.project.specific.internal.code_gen.services.pdf_stamp import \
    StampSpec
from apps.project.specific.internal.code_gen.services.render import (
    render_barcode_png, render_qr_png)

from .files import KIND_PUBLIC, serve
from .models import (CertificationStatusChoices, DocumentCertificateTypeChoices,
                     DocumentVerificationModel)

logger = logging.getLogger(__name__)

MAX_TEXT = 200
MAX_IDEMPOTENCY_KEY = 128
MAX_QR_PAYLOAD = 1000      # el QR de correccion H no cabe mucho mas
MAX_REASON = 1000
EPSILON = 0.01             # tolerancia de coma flotante al medir contra la pagina

# Cupos por emisor y hora. Fallan cerrado (defecto de RateLimit): si la cache
# cae, se rechaza; emitir sin freno es peor que esperar a que vuelva.
issue_limit = RateLimit('external_issue', limit=60, window=3600)
access_limit = RateLimit('external_access', limit=300, window=3600)
# Intentos con credenciales malas, por IP.
auth_failures = RateLimit('external_auth_failures', limit=30, window=3600)


class InvalidRequest(Exception):
    def __init__(self, field, detail):
        super().__init__(detail)
        self.field = field
        self.detail = detail


class _Replay(Exception):
    def __init__(self, document):
        super().__init__('replay')
        self.document = document


def _json(payload, status=200):
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def _forbidden():
    return _json({'error': 'forbidden'}, status=403)


def _throttled():
    return _json({'error': 'rate_limited'}, status=429)


def _not_found():
    return _json({'error': 'not_found'}, status=404)


# ==========================================================
# Autenticacion
# ==========================================================

def _issuer_slug(request) -> str:
    return (
        request.POST.get('issuer')
        or request.headers.get('X-Issuer')
        or ''
    ).strip()


def authenticate_issuer(request):
    """
    Devuelve el slug del emisor autenticado, o ``None``.

    Compara siempre, aunque el emisor no exista o no tenga clave, para no
    delatar por el tiempo cual de los tres casos fue.
    """
    slug = _issuer_slug(request)
    issuers = getattr(settings, 'GEA_EXTERNAL_ISSUERS', None) or {}
    issuer = issuers.get(slug) if slug else None

    expected = str((issuer or {}).get('key') or '')
    given = request.headers.get('X-Issuer-Key') or ''

    matches = hmac.compare_digest(
        given.encode('utf-8'),
        (expected or 'no-key-configured').encode('utf-8'),
    )

    if issuer is None or not expected or not matches:
        return None

    return slug


def _gate(request, limit):
    """Autentica y aplica el cupo. Devuelve ``(slug, respuesta_de_error)``."""
    slug = authenticate_issuer(request)

    if slug is None:
        if not auth_failures.consume(request):
            return None, _throttled()
        return None, _forbidden()

    if not limit.consume(request, scope=slug):
        return None, _throttled()

    return slug, None


# ==========================================================
# Validacion
# ==========================================================

def _text(data, name, maximum):
    value = (data.get(name) or '').strip()

    if not value:
        raise InvalidRequest(name, 'This field is required.')

    if len(value) > maximum or any(ord(c) < 32 for c in value):
        raise InvalidRequest(name, 'Invalid value.')

    return value


def _read_source(request):
    upload = request.FILES.get('source')

    if upload is None:
        raise InvalidRequest('source', 'A PDF file is required.')

    if not str(upload.name or '').lower().endswith(CERTIFIABLE_EXTENSIONS):
        raise InvalidRequest('source', 'Only PDF files can be certified.')

    if upload.size > MAX_UPLOAD_BYTES:
        raise InvalidRequest('source', 'The file is too large.')

    data = upload.read()

    if not data.startswith(b'%PDF'):
        raise InvalidRequest('source', 'The file is not a readable PDF.')

    return data


def _page_sizes(pdf: bytes):
    """Ancho y alto visuales de cada pagina, o ``None`` si no se lee."""
    try:
        sizes = []

        for page in PdfReader(BytesIO(pdf)).pages:
            box = page.mediabox
            width = abs(float(box.right) - float(box.left))
            height = abs(float(box.top) - float(box.bottom))

            # El estampado normaliza la rotacion antes de dibujar.
            if int(page.get('/Rotate') or 0) % 180 == 90:
                width, height = height, width

            sizes.append((width, height))
    except Exception:
        return None

    return sizes or None


def _number(block, key, path, *, positive):
    value = block.get(key)

    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise InvalidRequest(
            'placement', f'{path}.{key} must be a finite number.')

    if value < 0 or (positive and value <= 0):
        raise InvalidRequest('placement', f'{path}.{key} is out of range.')

    return float(value)


def _box(placement, name, sizes, *, dims):
    block = placement.get(name)

    if not isinstance(block, dict):
        raise InvalidRequest('placement', f'"{name}" is required.')

    page = block.get('page')

    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise InvalidRequest(
            'placement', f'{name}.page must be an integer >= 1.')

    if page > len(sizes):
        raise InvalidRequest(
            'placement', f'{name}.page is beyond the last page ({len(sizes)}).'
        )

    x = _number(block, 'x', name, positive=False)
    y = _number(block, 'y', name, positive=False)
    width = _number(block, dims[0], name, positive=True)
    height = width if len(dims) == 1 else _number(
        block, dims[1], name, positive=True)

    page_width, page_height = sizes[page - 1]

    if x + width > page_width + EPSILON or y + height > page_height + EPSILON:
        raise InvalidRequest('placement', f'{name} falls outside page {page}.')

    return {'page': page, 'x': x, 'y': y, 'width': width, 'height': height}


def _placement(raw, pdf):
    try:
        placement = json.loads(raw or '')
    except (TypeError, ValueError):
        raise InvalidRequest('placement', 'It must be valid JSON.')

    if not isinstance(placement, dict):
        raise InvalidRequest('placement', 'It must be a JSON object.')

    sizes = _page_sizes(pdf)

    if not sizes:
        raise InvalidRequest('source', 'The file is not a readable PDF.')

    return {
        'qr': _box(placement, 'qr', sizes, dims=('size',)),
        'barcode': _box(placement, 'barcode', sizes, dims=('width', 'height')),
    }


def _qr_payload(value):
    value = (value or '').strip()
    parsed = urlparse(value)

    if (parsed.scheme != 'https' or not parsed.netloc
            or len(value) > MAX_QR_PAYLOAD
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise InvalidRequest('qr_payload', 'It must be an https URL.')

    return value


def _barcode_text(value):
    try:
        return validate_barcode_payload((value or '').strip())
    except ValidationError as error:
        raise InvalidRequest('barcode_text', ' '.join(error.messages))


# ==========================================================
# Respuesta y estampado
# ==========================================================

def _body(document):
    return {
        'document_id': str(document.pk),
        'code': document.public_code or '',
        'verification_url': build_verification_url(document),
        'source_hash': document.source_hash,
        'public_copy_hash': document.public_copy_hash,
        'public_copy_url': public_base_url() + reverse(
            'certificates:external_public_copy',
            kwargs={'document_id': document.pk},
        ),
        'issued_at': (document.certified_at or document.created).isoformat(),
    }


def _stamp_builder(placement, qr_payload, barcode_text):
    """
    Posiciones del ``placement`` de quien emite, en vez de las de un layout.

    El QR es el de gea con su logo por defecto y el contenido recibido; el
    Code128 lleva exactamente ``barcode_text``. Las coordenadas van en puntos
    con origen abajo a la izquierda: el ancla ``BL`` de ``StampSpec``.
    """
    def build(document, page_count):
        qr = placement['qr']
        bar = placement['barcode']

        return [
            StampSpec(
                image_png=render_qr_png(qr_payload),
                pages=[qr['page'] - 1],
                anchor='BL',
                offset_x=qr['x'],
                offset_y=qr['y'],
                width=qr['width'],
                height=qr['height'],
                label='QR (external issuer)',
            ),
            StampSpec(
                image_png=render_barcode_png(barcode_text),
                pages=[bar['page'] - 1],
                anchor='BL',
                offset_x=bar['x'],
                offset_y=bar['y'],
                width=bar['width'],
                height=bar['height'],
                label='Barcode (external issuer)',
            ),
        ]

    return build


def _existing(slug, key):
    return DocumentVerificationModel.objects.filter(
        external_issuer=slug, external_idempotency_key=key,
    ).first()


def _create(slug, key, reference, title, qr_payload, barcode_text, placement,
            pdf):
    document = DocumentVerificationModel(
        document_title=title,
        certificate_type=DocumentCertificateTypeChoices.GENERIC,
        issued_at=timezone.localdate(),
        external_issuer=slug,
        external_reference=reference,
        external_idempotency_key=key,
    )

    try:
        with transaction.atomic():
            document.source_file.save(
                f'{document.pk}.pdf', ContentFile(pdf), save=False,
            )
            document.save()

            # Que el codigo de gea sea el del Code128: sin NIT, hash, fecha ni
            # aleatorio, ``code_payload`` queda igual a ``barcode_text``.
            certify_document(
                document,
                options=CodeOptions(
                    include_nit=False,
                    custom_text=barcode_text,
                    include_initials_sequence=False,
                    include_document_hash=False,
                    include_date=False,
                    include_random_code=False,
                ),
                qr_payload=qr_payload,
                specs_builder=_stamp_builder(
                    placement, qr_payload, barcode_text),
            )
    except IntegrityError:
        # Dos peticiones con la misma clave a la vez: gana la primera.
        winner = _existing(slug, key)

        if winner is None:
            raise

        raise _Replay(winner)

    return document


# ==========================================================
# Vistas
# ==========================================================

@csrf_exempt
@require_POST
def issue_document(request):
    slug, error = _gate(request, issue_limit)

    if error is not None:
        return error

    try:
        key = _text(request.POST, 'idempotency_key', MAX_IDEMPOTENCY_KEY)

        # Un reintento devuelve lo ya emitido, sea lo que sea lo que traiga:
        # mirar el resto antes obligaria a repetir bit a bit la peticion.
        existing = _existing(slug, key)

        if existing is not None:
            return _json(_body(existing), status=200)

        reference = _text(request.POST, 'reference', MAX_TEXT)
        title = _text(request.POST, 'title', MAX_TEXT)
        qr_payload = _qr_payload(request.POST.get('qr_payload'))
        barcode_text = _barcode_text(request.POST.get('barcode_text'))
        pdf = _read_source(request)
        placement = _placement(request.POST.get('placement'), pdf)
    except InvalidRequest as invalid:
        return _json(
            {'error': 'invalid_request', 'field': invalid.field,
             'detail': invalid.detail},
            status=400,
        )

    try:
        document = _create(
            slug, key, reference, title, qr_payload, barcode_text, placement,
            pdf,
        )
    except _Replay as replay:
        return _json(_body(replay.document), status=200)
    except (CertificationError, ValidationError) as failure:
        logger.warning('External certification refused (%s): %s', slug, failure)
        return _json({'error': 'certification_failed'}, status=422)
    except Exception:
        logger.exception('External certification failed (%s)', slug)
        return _json({'error': 'server_error'}, status=500)

    return _json(_body(document), status=201)


@require_GET
def public_copy(request, document_id):
    slug, error = _gate(request, access_limit)

    if error is not None:
        return error

    document = DocumentVerificationModel.objects.filter(
        pk=document_id, external_issuer=slug,
    ).first()

    if document is None:
        return _not_found()

    try:
        return serve(document, KIND_PUBLIC)
    except Http404:
        return _not_found()


@csrf_exempt
@require_POST
def revoke_document(request, document_id):
    slug, error = _gate(request, access_limit)

    if error is not None:
        return error

    document = DocumentVerificationModel.objects.filter(
        pk=document_id, external_issuer=slug,
    ).first()

    if document is None:
        return _not_found()

    reason = (request.POST.get('reason') or '').strip()[:MAX_REASON]

    # Idempotente: revocar lo ya revocado no cambia la fecha ni el motivo.
    if document.certification_status != CertificationStatusChoices.REVOKED:
        document.certification_status = CertificationStatusChoices.REVOKED
        document.revoked_at = timezone.now()
        document.revocation_reason = reason
        document.save(update_fields=[
            'certification_status', 'revoked_at', 'revocation_reason',
            'updated',
        ])

    return _json({
        'document_id': str(document.pk),
        'status': document.certification_status,
        'revoked_at': document.revoked_at.isoformat(),
        'verification_url': build_verification_url(document),
    })
