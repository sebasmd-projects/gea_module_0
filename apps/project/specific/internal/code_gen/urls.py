from django.urls import path

from .api import (layout_create, layout_placements, summary_members,
                  summary_seal)
from .views import (CodeDetailView, CodeGeneratorView, CodeHistoryListView,
                    StampLayoutEditView, StampLayoutListView,
                    SummaryComposerView, SummaryListView)

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

    path(
        "generate/layouts/save/",
        layout_create,
        name="layout_create_api"
    ),
]
