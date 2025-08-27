import re

from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path, re_path

from .api import urls as api_urls
from .api.views import RequestLogDestroyAPIView, RequestLogListView
from .attack_patterns import common_attack_paths
from .views import (DecoratedTokenObtainPairView, DecoratedTokenRefreshView,
                    DecoratedTokenVerifyView, set_language)


def simplify_regex(pattern):
    pattern = re.sub(
        r'\[\^*\]\.\*\?*',
        '',
        pattern
    )
    pattern = re.sub(
        r'\[([A-Za-z])([A-Za-z])\]',
        lambda m: m.group(1).upper(),
        pattern
    )
    pattern = re.sub(
        r'[^a-zA-Z0-9]',
        '',
        pattern
    )
    return pattern


def robots_txt(request):
    lines = ["User-agent: *"]

    attack_terms = sorted(set(settings.COMMON_ATTACK_TERMS))
    for term in attack_terms:
        if term:
            lines.append(f"Disallow: /{term.strip('/')}")

    return HttpResponse("\n".join(lines), content_type="text/plain")


utils_path = [
    path('robots.txt', robots_txt),
    path('set_language/', set_language, name='set_language'),
    re_path(r'^api/logs/v1/', include(api_urls.log_urlpattern)),
    re_path(r'^api/auth/v1/', include(api_urls.urlpatterns)),
]

drf_urls = [
    path(
        'login/',
        DecoratedTokenObtainPairView.as_view(),
        name='token_obtain_pair'
    ),
    path(
        'refresh/',
        DecoratedTokenRefreshView.as_view(),
        name='token_refresh'
    ),
    path(
        'verify/',
        DecoratedTokenVerifyView.as_view(),
        name='token_verify'
    )
]

log_urlpattern = [
    path(
        'log/',
        RequestLogListView.as_view(),
        name='utils_log'
    ),
    path(
        'log/remove/<pk>/',
        RequestLogDestroyAPIView.as_view(),
        name='utils_log_delete'
    )
]

urlpatterns = common_attack_paths + utils_path
