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
                  'document of the box it carries.')
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

def _summary_payload(summary):
    from .services.anchoring import anchor_url, summary_anchor_state

    state = summary_anchor_state(summary)

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
    GET: miembros de la caja. PATCH: reemplaza el conjunto.

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
                    _('The code %(code)s is repeated in the box.')
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
        'detail': str(_('Members updated. The box needs sealing again.')),
        **_summary_payload(summary),
    })


@require_http_methods(['POST'])
def summary_seal(request, pk):
    """Calcula el master hash de la caja."""
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

    summary.refresh_from_db()

    return JsonResponse({
        'detail': str(_('Box sealed.')),
        'master_hash': digest,
        **_summary_payload(summary),
    })
