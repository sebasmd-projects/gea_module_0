from django.urls import path

from .api import layout_create, layout_placements
from .views import (CodeDetailView, CodeGeneratorView, CodeHistoryListView,
                    StampLayoutEditView, StampLayoutListView)

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
        "generate/layouts/save/",
        layout_create,
        name="layout_create_api"
    ),
]
