from django.urls import path

from .views import CodeGeneratorView, dynamic_qr_view

app_name = "code_gen"

urlpatterns = [
    path(
        "generate/code/",
        CodeGeneratorView.as_view(),
        name="code_generate"
    ),
    path(
        "qr/generate/<path:text>/",
        dynamic_qr_view,
        name="dynamic_qr"
    ),
]
