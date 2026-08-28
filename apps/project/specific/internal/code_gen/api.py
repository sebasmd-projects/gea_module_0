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

        cleaned.append({
            'kind': kind,
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
