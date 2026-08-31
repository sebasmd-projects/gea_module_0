# apps/project/specific/internal/code_gen/api.py
"""
Endpoints JSON de las disposiciones de estampado.

Los usa el generador de codigos para leer, actualizar (PATCH) y crear (POST)
una disposicion sin abandonar la pagina, mientras el operador arrastra las
cajas sobre la vista previa del PDF.

No hay DRF en el proyecto: son vistas Django normales que hablan JSON.
"""

import json
import logging

from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from .models import (AnchorChoices, CodeKindChoices, PageSelectorChoices,
                     StampLayoutModel, StampPlacementModel)

logger = logging.getLogger(__name__)

VALID_KINDS = {choice[0] for choice in CodeKindChoices.choices}
VALID_ANCHORS = {choice[0] for choice in AnchorChoices.choices}
VALID_SELECTORS = {choice[0] for choice in PageSelectorChoices.choices}

# Tipos que exigen decir de que miembro es el codigo.
MEMBER_KINDS = {CodeKindChoices.MEMBER_BARCODE}


def _forbidden():
    return JsonResponse(
        {'detail': str(_('You are not allowed to do this.'))},
        status=403
    )


def _is_internal(user) -> bool:
    return bool(
        user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def _parse_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}'), None
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse(
            {'detail': str(_('Malformed JSON body.'))},
            status=400
        )


def _wants_anchor(request) -> bool:
    """
    Si esta peticion de sellado pide ademas mandar el hash a Bitcoin.

    Ante un cuerpo ilegible se responde que no: dejar de anclar es un paso que
    se puede dar despues, y anclar por error no se deshace.
    """
    payload, _error = _parse_body(request)

    if not isinstance(payload, dict):
        return False

    return bool(payload.get('anchor'))


def _clean_placements(raw):
    """
    Valida y normaliza la lista de posiciones recibida.

    Returns:
        tuple[list | None, str | None]: posiciones limpias, o el mensaje de
        error si algo no encaja.
    """
    if not isinstance(raw, list):
        return None, str(_('"placements" must be a list.'))

    cleaned = []

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            return None, str(
                _('Placement %(number)s is not an object.')
                % {'number': index}
            )

        kind = item.get('kind')
        anchor = item.get('anchor')
        selector = item.get('page_selector')

        if kind not in VALID_KINDS:
            return None, str(
                _('Placement %(number)s: unknown code kind.')
                % {'number': index}
            )

        if anchor not in VALID_ANCHORS:
            return None, str(
                _('Placement %(number)s: unknown anchor.')
                % {'number': index}
            )

        if selector not in VALID_SELECTORS:
            return None, str(
                _('Placement %(number)s: unknown page selector.')
                % {'number': index}
            )

        try:
            numbers = {
                'offset_x': float(item.get('offset_x', 0)),
                'offset_y': float(item.get('offset_y', 0)),
                'width': float(item.get('width', 0)),
                'height': float(item.get('height', 0)),
                'opacity': float(item.get('opacity', 1) or 1),
            }
        except (TypeError, ValueError):
            return None, str(
                _('Placement %(number)s: the measurements must be numbers.')
                % {'number': index}
            )

        if numbers['width'] < 1 or numbers['height'] < 1:
            return None, str(
                _('Placement %(number)s: width and height must be at least 1 pt.')
                % {'number': index}
            )

        if not 0 < numbers['opacity'] <= 1:
            return None, str(
                _('Placement %(number)s: opacity must be between 0 and 1.')
                % {'number': index}
            )

        member_code = (item.get('member_code') or '').strip()

        if kind in MEMBER_KINDS and not member_code:
            return None, str(
                _('Placement %(number)s: a member barcode must say which '
                  'document of the summary it carries.')
                % {'number': index}
            )

        cleaned.append({
            'kind': kind,
            'member_code': member_code,
            'anchor': anchor,
            'page_selector': selector,
            'page_numbers': (item.get('page_numbers') or '').strip(),
            'is_active': bool(item.get('is_active', True)),
            **numbers,
        })

    return cleaned, None


def _write_placements(layout, placements):
    """
    Reemplaza el conjunto de posiciones de una disposicion.

    Se sustituyen todas de una vez, dentro de una transaccion: es lo que el
    editor envia, y evita tener que casar identificadores en el cliente.
    """
    with transaction.atomic():
        layout.placements.all().delete()

        for order, placement in enumerate(placements, start=1):
            StampPlacementModel.objects.create(
                layout=layout,
                default_order=order,
                **placement
            )


def _layout_payload(layout):
    return {
        'id': layout.pk,
        'name': layout.name,
        'description': layout.description or '',
        'is_default': layout.is_default,
        'placements': layout.placement_data(),
    }


@require_http_methods(['GET', 'PATCH'])
def layout_placements(request, pk):
    """
    GET: posiciones de una disposicion.
    PATCH: reemplaza sus posiciones con las recibidas.
    """
    if not _is_internal(request.user):
        return _forbidden()

    layout = get_object_or_404(StampLayoutModel, pk=pk)

    if request.method == 'GET':
        return JsonResponse({
            'layout': layout.name,
            **_layout_payload(layout),
        })

    body, error = _parse_body(request)
    if error:
        return error

    placements, message = _clean_placements(body.get('placements'))
    if message:
        return JsonResponse({'detail': message}, status=400)

    _write_placements(layout, placements)

    layout.refresh_from_db()

    return JsonResponse({
        'detail': str(_('Stamp layout updated.')),
        **_layout_payload(layout),
    })


@require_http_methods(['POST'])
def layout_create(request):
    """
    Crea una disposicion nueva con las posiciones actuales del editor.
    """
    if not _is_internal(request.user):
        return _forbidden()

    body, error = _parse_body(request)
    if error:
        return error

    name = (body.get('name') or '').strip()

    if not name:
        return JsonResponse(
            {
                'detail': str(_('The layout name is required.')),
                'field': 'name',
            },
            status=400
        )

    if StampLayoutModel.objects.filter(name__iexact=name).exists():
        return JsonResponse(
            {
                'detail': str(
                    _('A layout with this name already exists.')
                ),
                'field': 'name',
            },
            status=400
        )

    placements, message = _clean_placements(body.get('placements'))
    if message:
        return JsonResponse({'detail': message}, status=400)

    with transaction.atomic():
        layout = StampLayoutModel.objects.create(
            name=name,
            description=(body.get('description') or '').strip(),
            is_default=bool(body.get('is_default')),
        )
        _write_placements(layout, placements)

    layout.refresh_from_db()

    return JsonResponse(
        {
            'detail': str(_('Stamp layout created.')),
            **_layout_payload(layout),
        },
        status=201
    )


# ==========================================================
# Resumen AEGIS
# ==========================================================

def _summary_document_payload(summary):
    """
    El documento del resumen, si ya se emitio.

    Los archivos no se enlazan nunca por ``MEDIA_URL``: la unica via es
    ``certificates:document_file``, que comprueba permisos (invariante 13).
    Aqui se dan sus URL para que el compositor pueda ofrecerlas, no los
    ficheros.
    """
    from django.urls import reverse

    document = summary.summary_document

    if document is None:
        return None

    return {
        'id': str(document.pk),
        'public_code': document.public_code,
        'code_payload': document.code_payload,
        'sha256': document.document_hash,
        'certified_url': reverse(
            'certificates:document_file',
            kwargs={'pk': document.pk, 'kind': 'certified'},
        ),
        'public_url': reverse(
            'certificates:document_file',
            kwargs={'pk': document.pk, 'kind': 'public'},
        ),
        'verification_url': reverse(
            'certificates:summary_detail', kwargs={'pk': summary.pk}
        ),
    }


def _summary_payload(summary):
    from .services.anchoring import anchor_url, summary_anchor_state

    state = summary_anchor_state(summary)

    # Estado del envio a la cadena de bloques, tal como lo necesita el boton:
    # un resumen sellado y no enviada se puede enviar; una ya enviada no, hasta
    # que se vuelva a sellar con miembros distintos y cambie el master hash.
    sent = _ots_anchor_for_current_hash(summary)

    return {
        'id': str(summary.pk),
        'title': summary.title,
        'public_code': summary.public_code,
        'status': summary.status,
        'status_label': str(summary.get_status_display()),
        'master_hash': summary.master_hash,
        'sealed_at': (
            summary.sealed_at.isoformat() if summary.sealed_at else None
        ),
        'anchor_url': anchor_url(summary),
        'anchored': state['anchored'],
        'sent_to_blockchain': sent is not None,
        'blockchain_label': (
            str(sent.get_status_display()) if sent is not None
            else str(_('Not sent'))
        ),
        'can_send_to_blockchain': bool(summary.master_hash) and sent is None,

        # El documento del resumen. Emitirlo no espera al anclaje ni tiene por
        # que: el QR estampado lleva la URL de la pagina de anclaje, no la
        # prueba, y esa pagina se actualiza sola segun madura (invariante 16).
        # Por eso se puede emitir en cuanto el resumen esta sellada.
        'issued': summary.summary_document_id is not None,
        'can_issue': bool(summary.master_hash),
        'document': _summary_document_payload(summary),

        'members': [
            {
                'code': member.code,
                'document_id': str(member.document_id),
                'title': member.document.document_title,
                'document_type': member.document_type_label,
                'sha256': member.document.document_hash,
            }
            for member in summary.ordered_members()
        ],
    }


@require_http_methods(['GET', 'PATCH'])
def summary_members(request, pk):
    """
    GET: miembros del resumen. PATCH: reemplaza el conjunto.

    Igual que con las posiciones, el PATCH sustituye la lista entera: es lo
    que envia el compositor y evita casar identificadores en el cliente.
    """
    from apps.project.specific.documents.certificates.models import (
        AegisSummaryDocumentModel, AegisSummaryModel,
        DocumentVerificationModel, SummaryStatusChoices)

    if not _is_internal(request.user):
        return _forbidden()

    summary = get_object_or_404(AegisSummaryModel, pk=pk)

    if request.method == 'GET':
        return JsonResponse(_summary_payload(summary))

    body, error = _parse_body(request)
    if error:
        return error

    raw = body.get('members')

    if not isinstance(raw, list):
        return JsonResponse(
            {'detail': str(_('"members" must be a list.'))}, status=400
        )

    cleaned = []
    seen_codes = set()

    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            return JsonResponse(
                {'detail': str(
                    _('Member %(number)s is not an object.')
                    % {'number': index})},
                status=400
            )

        code = (item.get('code') or '').strip().upper()
        document_id = (item.get('document_id') or '').strip()

        if not code:
            return JsonResponse(
                {'detail': str(
                    _('Member %(number)s has no code.') % {'number': index})},
                status=400
            )

        if code in seen_codes:
            return JsonResponse(
                {'detail': str(
                    _('The code %(code)s is repeated in the summary.')
                    % {'code': code})},
                status=400
            )

        seen_codes.add(code)

        document = DocumentVerificationModel.objects.filter(
            pk=document_id
        ).first()

        if document is None:
            return JsonResponse(
                {'detail': str(
                    _('Member %(code)s points to a document that does not '
                      'exist.') % {'code': code})},
                status=400
            )

        if not document.is_certified:
            return JsonResponse(
                {'detail': str(
                    _('%(code)s is not certified: it has no fingerprint to '
                      'include.') % {'code': code})},
                status=400
            )

        cleaned.append({
            'document': document,
            'code': code,
            'document_type_label': (
                item.get('document_type')
                or str(document.get_certificate_type_display())
            ),
        })

    with transaction.atomic():
        summary.members.all().delete()

        for order, member in enumerate(cleaned, start=1):
            AegisSummaryDocumentModel.objects.create(
                summary=summary,
                default_order=order,
                **member
            )

        # Cambiar los miembros invalida el sello: el master hash describia
        # otra caja. Se limpia para que nadie lo confunda con vigente.
        if summary.master_hash:
            summary.master_hash = ''
            summary.canonical_payload = ''
            summary.sealed_at = None
            summary.status = SummaryStatusChoices.DRAFT
            summary.save(update_fields=[
                'master_hash', 'canonical_payload', 'sealed_at', 'status',
                'updated',
            ])

    summary.refresh_from_db()

    return JsonResponse({
        'detail': str(_('Members updated. The summary needs sealing again.')),
        **_summary_payload(summary),
    })


def _ots_anchor_for_current_hash(summary):
    """
    El anclaje en Bitcoin que ya cubre el master hash actual, si lo hay.

    Sirve para no mandar dos veces lo mismo. Se compara contra el hash
    **actual** a proposito: si el resumen se vuelve a sellar porque cambiaron sus
    miembros, el anclaje viejo cubre un hash que ya no es el suyo y hace falta
    uno nuevo.
    """
    from .models import AnchorStatusChoices, AnchorTypeChoices

    if not summary.master_hash:
        return None

    return summary.anchors.filter(
        anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
        payload_hash=summary.master_hash,
        status__in=(
            AnchorStatusChoices.PENDING,
            AnchorStatusChoices.CONFIRMED,
        ),
    ).first()


def _send_to_blockchain(summary):
    """
    Manda el master hash a los calendarios de OpenTimestamps.

    Nunca propaga el fallo. Es deliberado y es lo que hace viable el boton de
    «sellar y enviar»: el sellado es una escritura nuestra que ya esta hecha, y
    el envio es una llamada de red a servidores de terceros. Si los calendarios
    no responden, lo que no puede pasar es que se pierda el sello -- con
    ``ATOMIC_REQUESTS`` una excepcion aqui desharia tambien el sellado. Se
    informa de que quedo sin anclar y se ancla despues, que para eso el anclaje
    es un paso aparte.

    El mensaje de fallo lleva **la causa concreta**, no un «fallo» a secas.
    Esta pantalla solo la ve personal interno, asi que no hay nada que ocultar,
    y sin la causa el aviso obliga a ir a buscar ``stderr.log`` en el servidor
    para averiguar si lo que falta es una libreria o la salida a internet --
    que son dos arreglos completamente distintos. Para separarlas del todo hay
    ``manage.py check_anchoring``, disponible en la consola de operaciones.

    Returns:
        tuple[str, str]: (resultado, mensaje). El resultado es ``'anchored'``,
        ``'already'`` o ``'failed'``.
    """
    from .services import ots
    from .services.anchoring import anchor_with_ots

    if _ots_anchor_for_current_hash(summary) is not None:
        return 'already', str(_('It was already sent to the blockchain.'))

    try:
        anchor_with_ots(summary)
    except ots.OTSError as error:
        logger.warning('OTS anchoring failed for summary %s: %s',
                       summary.pk, error)
        return 'failed', str(
            _('Sealed, but the blockchain calendars did not answer (%(reason)s). '
              'The seal is saved; send it later with «Send to blockchain». '
              'Run «Blockchain anchoring» in the operations console to see '
              'whether this server has the library and outbound access.')
        ) % {'reason': error}
    except ImportError as error:
        logger.exception('OTS library missing for summary %s', summary.pk)
        return 'failed', str(
            _('Sealed, but the OpenTimestamps library is not installed on '
              'this server (%(reason)s). The seal is saved. This is fixed by '
              'installing requirements.txt with pip on the server, not from '
              'here — check first with «Dependencies» in the operations '
              'console that the package actually reached that file.')
        ) % {'reason': error}
    except Exception as error:  # noqa: BLE001
        logger.exception('Unexpected OTS failure for summary %s', summary.pk)
        return 'failed', str(
            _('Sealed, but sending to the blockchain failed: '
              '%(kind)s: %(reason)s. The seal is saved; send it later with '
              '«Send to blockchain». Run «Blockchain anchoring» in the '
              'operations console for a full diagnosis.')
        ) % {'kind': type(error).__name__, 'reason': error}

    return 'anchored', str(
        _('Sealed and sent to the blockchain. The proof is born pending: it '
          'matures into a Bitcoin block within a few hours, on its own.')
    )


@require_http_methods(['POST'])
def summary_seal(request, pk):
    """
    Sella el resumen y, si se pide, la manda a la cadena de bloques.

    Son dos actos separados a proposito, y el formulario ofrece los dos:

    * **Solo sellar** calcula el master hash y lo guarda. Es instantaneo y no
      depende de nadie de fuera.
    * **Sellar y enviar** hace lo anterior y ademas manda el hash a los
      calendarios de OpenTimestamps, que es gratis porque juntan miles de
      hashes en una sola transaccion de Bitcoin.

    Separarlos importa porque el envio sale a la red y puede fallar o tardar,
    mientras que el sellado no. Un resumen sellado sin enviar se puede enviar
    despues sin volver a sellarla: el hash es el mismo.
    """
    from apps.project.specific.documents.certificates.models import \
        AegisSummaryModel

    from .services.master import MasterHashError, seal_summary

    if not _is_internal(request.user):
        return _forbidden()

    summary = get_object_or_404(AegisSummaryModel, pk=pk)

    try:
        digest = seal_summary(summary)
    except MasterHashError as error:
        return JsonResponse({'detail': str(error)}, status=400)

    detail = str(_('Summary sealed.'))
    anchor_result = None

    if _wants_anchor(request):
        anchor_result, detail = _send_to_blockchain(summary)

    summary.refresh_from_db()

    return JsonResponse({
        'detail': detail,
        'master_hash': digest,
        'anchor_result': anchor_result,
        **_summary_payload(summary),
    })


@require_http_methods(['POST'])
def summary_anchor(request, pk):
    """
    Manda a la cadena de bloques un resumen que ya estaba sellada.

    Es el segundo tiempo de «solo sellar»: el hash ya existe, aqui solo se
    envia. Si el resumen no esta sellada no hay nada que enviar, y si ya se envio
    este mismo hash no se manda otra vez.
    """
    from apps.project.specific.documents.certificates.models import \
        AegisSummaryModel

    if not _is_internal(request.user):
        return _forbidden()

    summary = get_object_or_404(AegisSummaryModel, pk=pk)

    if not summary.master_hash:
        return JsonResponse(
            {'detail': str(_('Seal the summary before sending it.'))},
            status=400,
        )

    anchor_result, detail = _send_to_blockchain(summary)

    if anchor_result == 'anchored':
        detail = str(
            _('Sent to the blockchain. The proof is born pending: it matures '
              'into a Bitcoin block within a few hours, on its own.')
        )

    summary.refresh_from_db()

    return JsonResponse({
        'detail': detail,
        'anchor_result': anchor_result,
        **_summary_payload(summary),
    })


@require_http_methods(['POST'])
def summary_issue(request, pk):
    """
    Emite el documento del resumen: el PDF del resumen, ya certificado.

    Hasta ahora esto no existia como accion. El servicio que lo hace
    --``services.summary.certify_summary()``-- estaba escrito y completo desde
    el principio, pero no lo llamaba nadie: se sellaba el resumen, se anclaba, y
    ``summary_document`` se quedaba en ``null``. La caja no tenia papel.

    **No espera al anclaje, y no tiene por que.** El QR que se estampa lleva la
    URL de la pagina de anclaje, nunca la prueba (invariante 16). Esa pagina se
    actualiza sola segun madura el anclaje, asi que el PDF se emite una vez,
    con el resumen sellado, y no hay que reestamparlo cuando llegue el bloque de
    Bitcoin. Emitir «sin blockchain» y luego «con blockchain» seria hacer dos
    papeles con huellas distintas para el mismo resumen, y habria que decidir cual
    de los dos hace fe.

    Se sube el PDF del resumen sin codigos. Al reemitir se puede omitir: se
    conserva el original que ya estaba guardado, y se rehacen el estampado, las
    huellas y la copia publica.
    """
    from apps.project.specific.documents.certificates.models import \
        AegisSummaryModel

    from .services.certification import CertificationError
    from .services.summary import certify_summary

    if not _is_internal(request.user):
        return _forbidden()

    summary = get_object_or_404(AegisSummaryModel, pk=pk)

    if not summary.master_hash:
        return JsonResponse(
            {'detail': str(
                _('Seal the summary before issuing its document: it '
                  'carries the master hash inside.')
            )},
            status=400,
        )

    source_file = request.FILES.get('source_file')
    existing = summary.summary_document

    if source_file is None and (existing is None or not existing.source_file):
        return JsonResponse(
            {'detail': str(
                _('Upload the summary PDF without codes: there is no original '
                  'stored yet to stamp over.')
            )},
            status=400,
        )

    layout = _requested_layout(request, existing)

    if layout is None and (existing is None or existing.stamp_layout is None):
        return JsonResponse(
            {'detail': str(
                _('Choose a stamp layout: it decides where each code goes on '
                  'the page.')
            )},
            status=400,
        )

    try:
        document, outcome = certify_summary(
            summary,
            source_file=source_file,
            layout=layout,
            request=request,
        )
    except CertificationError as error:
        return JsonResponse({'detail': str(error)}, status=400)
    except Exception as error:  # noqa: BLE001
        # Estampar lee y reescribe un PDF que sube el usuario: un archivo roto
        # o protegido revienta abajo, y con ATOMIC_REQUESTS eso seria un 500
        # que ademas desharia lo que hubiera guardado. Se cuenta la causa.
        logger.exception('Could not issue the summary document %s', summary.pk)

        return JsonResponse(
            {'detail': str(
                _('The summary document could not be issued: %(error)s')
                % {'error': f'{type(error).__name__}: {error}'}
            )},
            status=400,
        )

    summary.refresh_from_db()

    detail = str(
        _('Summary document issued. Its QR points at the anchor page, which '
          'updates itself: there is nothing to reissue when the Bitcoin block '
          'arrives.')
    )

    return JsonResponse({
        'detail': detail,
        'skipped': outcome.skipped,
        **_summary_payload(summary),
    })


def _requested_layout(request, existing):
    """
    La disposicion elegida en el formulario, o la que ya tuviera el documento.

    Devuelve ``None`` cuando no se pidio ninguna, que el llamante distingue de
    «no hay ninguna» mirando tambien el documento anterior.
    """
    from .models import StampLayoutModel

    raw = (request.POST.get('layout') or '').strip()

    if not raw:
        return None

    return StampLayoutModel.objects.filter(pk=raw, is_active=True).first()


@require_http_methods(['GET'])
def preview_symbols(request):
    """
    Simbolos de ejemplo para la vista previa de disposicion.

    La vista previa necesita el simbolo *de verdad* para poder avisar de que el
    ancho declarado no es el que se ocupa: al estampar se conserva la
    proporcion, asi que un resumen demasiado baja deja ancho sin usar. Con la
    imagen y su tamano natural, el JS calcula exactamente lo mismo que
    ``pdf_stamp`` va a dibujar.

    Parametros de consulta:
        ``length``  longitud de la carga de ejemplo del codigo de barras.
        ``payload`` codigo real, si se quiere ver el caso concreto.
    """
    if not _is_internal(request.user):
        return _forbidden()

    from .services.samples import (BARCODE_SAMPLE_DEFAULT_LENGTH,
                                   BARCODE_SAMPLE_MAX_LENGTH,
                                   BARCODE_SAMPLE_MIN_LENGTH, clamp_length,
                                   sample_symbols)

    length = clamp_length(
        request.GET.get('length'), default=BARCODE_SAMPLE_DEFAULT_LENGTH
    )

    return JsonResponse({
        'symbols': sample_symbols(
            barcode_length=length,
            barcode_payload=(request.GET.get('payload') or '').strip(),
        ),
        'length': length,
        'min_length': BARCODE_SAMPLE_MIN_LENGTH,
        'max_length': BARCODE_SAMPLE_MAX_LENGTH,
    })
