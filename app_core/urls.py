from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.utils.translation import gettext_lazy as _
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from two_factor.urls import urlpatterns as tf_urls

from apps.common.utils.views import handler400 as h400
from apps.common.utils.views import handler403 as h403
from apps.common.utils.views import handler404 as h404
from apps.common.utils.views import handler500 as h500

admin_url = settings.ADMIN_URL
custom_apps = settings.ALL_CUSTOM_APPS
utils_path = settings.UTILS_PATH

apps_urls = [path('', include(f'{app}.urls')) for app in custom_apps]

handler400 = h400

handler403 = h403

handler404 = h404

handler500 = h500

third_party_urls = [
    re_path(
        r'^rosetta/',
        include('rosetta.urls')
    ),
]

admin_urls = [
    path(admin_url, admin.site.urls),
]

two_factor_urls = [
    path('', include(tf_urls)),
]

rest_urls = [
    path(
        'api-auth/',
        include('rest_framework.urls')
    )
]

schema_view = get_schema_view(
    openapi.Info(
        title='Backend Endpoints',
        default_version='v1.0.0',
        description=_('API documentation and endpoint representation'),
        terms_of_service='',
        contact=openapi.Contact(email=settings.YASG_DEFAULT_EMAIL),
        license=openapi.License(name=settings.YASG_TERMS_OF_SERVICE),
    ),
    public=False,
)

swagger_urls = [
    re_path(
        r'^api/docs/',
        schema_view.with_ui(
            'swagger',
            cache_timeout=0
        ),
        name='schema-swagger-ui'
    ),
    re_path(
        r'^api/redocs/',
        schema_view.with_ui(
            'redoc',
            cache_timeout=0
        ),
        name='schema-redoc'
    ),
    re_path(
        r'^api/docs/<format>/',
        schema_view.without_ui(
            cache_timeout=0
        ),
        name='schema-json-yaml'
    ),
]

ckeditor_urls = [
    path(
        "ckeditor5/",
        include('django_ckeditor_5.urls')
    ),
]

django_select2_urls = [
    path(
        'select2/',
        include('django_select2.urls')
    )
]

urlpatterns = admin_urls + two_factor_urls + \
    apps_urls + third_party_urls + swagger_urls + ckeditor_urls + django_select2_urls

if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT
    )
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
