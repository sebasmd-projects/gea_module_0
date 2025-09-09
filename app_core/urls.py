from __future__ import annotations

from importlib import import_module
from typing import Final, Iterable, List

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import URLPattern, URLResolver, include, path, re_path
from django.utils.translation import gettext_lazy as _

from drf_yasg import openapi
from drf_yasg.views import get_schema_view

from two_factor.urls import urlpatterns as tf_urls

from apps.common.utils.views import (
    handler400 as h400,
    handler403 as h403,
    handler404 as h404,
    handler500 as h500,
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
handler400 = h400  # type: ignore[assignment]
handler403 = h403  # type: ignore[assignment]
handler404 = h404  # type: ignore[assignment]
handler500 = h500  # type: ignore[assignment]


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

# ==== DRF auth ====
rest_urls: List[UrlItem] = [
    path("api-auth/", include("rest_framework.urls")),
]


# ==== OpenAPI / Swagger (drf_yasg) ====
schema_view = get_schema_view(
    openapi.Info(
        title="Backend Endpoints",
        default_version="v1.0.0",
        description=_("API documentation and endpoint representation"),
        terms_of_service="",
        contact=openapi.Contact(email=settings.YASG_DEFAULT_EMAIL),
        license=openapi.License(name=settings.YASG_TERMS_OF_SERVICE),
    ),
    public=False,
)

swagger_urls: List[UrlItem] = [
    # UI Swagger
    path(
        "api/docs/",
        schema_view.with_ui("swagger", cache_timeout=0),
        name="schema-swagger-ui",
    ),
    # UI Redoc
    path(
        "api/redoc/",
        schema_view.with_ui("redoc", cache_timeout=0),
        name="schema-redoc",
    ),
    # Esquema sin UI (json o yaml): /api/schema.json o /api/schema.yaml
    path(
        "api/schema.<str:format>/",
        schema_view.without_ui(cache_timeout=0),
        name="schema-json-yaml",
    ),
]

# ==== URL patterns finales (orden explícito) ====
urlpatterns: List[UrlItem] = [
    *two_factor_urls,
    *admin_urls,
    *apps_urls,
    *rest_urls,
    *third_party_urls,
    *swagger_urls,
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
