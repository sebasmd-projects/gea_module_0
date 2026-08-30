from django.urls import path

from .api import (layout_create, layout_placements, preview_symbols,
                  summary_anchor, summary_members, summary_seal)
from .views import (CodeDetailView, CodeGeneratorView, CodeHistoryListView,
                    StampLayoutEditView, StampLayoutListView,
                    SummaryComposerView, SummaryCreateView, SummaryListView)

app_name = "code_gen"

urlpatterns = [
    path(
        "generate/code/",
        CodeGeneratorView.as_view(),
        name="code_generate"
    ),

    # Historial: el resultado de cada generacion en una URL permanente.
    path(
        "generate/code/history/",
        CodeHistoryListView.as_view(),
        name="code_history"
    ),
    path(
        "generate/code/<int:pk>/",
        CodeDetailView.as_view(),
        name="code_detail"
    ),

    # Disposiciones de estampado.
    path(
        "generate/layouts/",
        StampLayoutListView.as_view(),
        name="layout_list"
    ),
    path(
        "generate/layouts/new/",
        StampLayoutEditView.as_view(),
        name="layout_create"
    ),
    path(
        "generate/layouts/<int:pk>/",
        StampLayoutEditView.as_view(),
        name="layout_edit"
    ),
    # JSON: GET lee las posiciones, PATCH las reemplaza.
    path(
        "generate/layouts/<int:pk>/placements/",
        layout_placements,
        name="layout_placements"
    ),
    path(
        "generate/summary/",
        SummaryListView.as_view(),
        name="summary_list"
    ),
    path(
        "generate/summary/new/",
        SummaryCreateView.as_view(),
        name="summary_create"
    ),
    path(
        "generate/summary/<uuid:pk>/compose/",
        SummaryComposerView.as_view(),
        name="summary_compose"
    ),

    # Resumen AEGIS: miembros y sellado.
    path(
        "generate/summary/<uuid:pk>/members/",
        summary_members,
        name="summary_members"
    ),
    path(
        "generate/summary/<uuid:pk>/seal/",
        summary_seal,
        name="summary_seal"
    ),

    # Segundo tiempo de «solo sellar»: mandar a Bitcoin un hash ya sellado.
    path(
        "generate/summary/<uuid:pk>/anchor/",
        summary_anchor,
        name="summary_anchor"
    ),

    path(
        "generate/layouts/save/",
        layout_create,
        name="layout_create_api"
    ),

    # JSON: simbolos de ejemplo para la vista previa (QR real y Code128 de la
    # longitud que se pida), con su tamano natural.
    path(
        "generate/preview/symbols/",
        preview_symbols,
        name="preview_symbols"
    ),
]
