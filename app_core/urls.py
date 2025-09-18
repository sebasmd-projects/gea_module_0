from __future__ import annotations

from importlib import import_module
from typing import Final, Iterable, List

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path
from django.utils.translation import gettext_lazy as _

from drf_yasg import openapi
from drf_yasg.views import get_schema_view

from two_factor.urls import urlpatterns as tf_urls

from apps.common.utils.views import (
    handler400 as h400,
    handler401 as h401,
    handler403 as h403,
    handler404 as h404,
    handler500 as h500,
    handler503 as h503,
    handler504 as h504,
)

# ==== Tipos útiles ====
UrlItem = URLPattern | URLResolver

# ==== Constantes (tipadas) ====
ADMIN_URL: Final[str] = settings.ADMIN_URL
CUSTOM_APPS: Final[Iterable[str]] = tuple(
    getattr(settings, "ALL_CUSTOM_APPS", ())
)
UTILS_PATH: Final[str] = getattr(settings, "UTILS_PATH", "")

# ==== Handlers de error (exportados por Django) ====
handler400 = h400
handler401 = h401
handler403 = h403
handler404 = h404
handler500 = h500
handler503 = h503
handler504 = h504


def include_if_present(dotted_path: str) -> list[URLResolver]:
    # ==== Helper: incluye app solo si su módulo urls existe ====
    """
    Devuelve [include(dotted_path)] si el módulo existe, en caso contrario [].
    Evita fallos en despliegues parciales o entornos de CI.
    """
    try:
        # Validación rápida de import
        import_module(dotted_path)
    except Exception:
        return []
    return [path("", include(dotted_path))]


# ==== URLs de apps propias (seguras ante módulos faltantes) ====
apps_urls: List[UrlItem] = []
for app_label in CUSTOM_APPS:
    apps_urls += include_if_present(f"{app_label}.urls")


# ==== Terceros ====
third_party_urls: List[UrlItem] = [
    path("rosetta/", include("rosetta.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    path("select2/", include("django_select2.urls")),
]

# ==== Admin ====
admin_urls: List[UrlItem] = [
    path(ADMIN_URL, admin.site.urls),
]

# ==== Two-Factor ====
two_factor_urls: List[UrlItem] = [path("", include(tf_urls))]


# ==== URL patterns finales (orden explícito) ====
urlpatterns: List[UrlItem] = [
    *two_factor_urls,
    *admin_urls,
    *apps_urls,
    *third_party_urls,
]

# ==== Static/Media en DEBUG ====
if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT
    )
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
