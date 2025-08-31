import re

from django.http import HttpResponse
from django.urls import include, path, re_path

from .api import urls as api_urls
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
    lines = [
        "User-agent: *",
        "Disallow: /",
        "User-agent: GPTBot",
        "Disallow: /",
        "User-agent: Google-Extended",
        "Disallow: /",
        "User-agent: ClaudeBot",
        "Disallow: /",
        "User-agent: Claude-User",
        "Disallow: /",
        "User-agent: Claude-SearchBot",
        "Disallow: /",
        "User-agent: PerplexityBot",
        "Disallow: /",
        "User-agent: Perplexity-User",
        "Disallow: /",
        "User-agent: Meta-ExternalAgent",
        "Disallow: /",
        "User-agent: Applebot",
        "Disallow: /",
        "User-agent: Applebot-Extended",
        "Disallow: /"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


utils_path = [
    path('robots.txt', robots_txt),
    path('set_language/', set_language, name='set_language'),
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

urlpatterns = utils_path + drf_urls
