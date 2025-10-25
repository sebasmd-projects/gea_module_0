from django.conf import settings
from django.http import HttpResponse
from django.urls import path

from .attack_patterns import common_attack_paths
from .views import handler400 as error400
from .views import handler401 as error401
from .views import handler403 as error403
from .views import handler404 as error404
from .views import handler500 as error500
from .views import handler503 as error503
from .views import handler504 as error504
from .views import set_language

app_name = 'utils'


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
    path(
        'robots.txt',
        robots_txt
    ),
    path(
        'set_language/',
        set_language,
        name='set_language'
    )
]


urlpatterns = common_attack_paths + utils_path

if settings.DEBUG:
    urlpatterns += [
        path(
            "__test__/400/",
            lambda r: error400(r, Exception("Bad request test"))
        ),
        path(
            "__test__/401/",
            lambda r: error401(r, Exception("Unauthorized test"))
        ),
        path(
            "__test__/403/",
            lambda r: error403(r, Exception("Forbidden test"))
        ),
        path(
            "__test__/404/",
            lambda r: error404(r, Exception("Not found test"))
        ),
        path(
            "__test__/500/",
            lambda r: error500(r)
        ),
        path(
            "__test__/503/",
            lambda r: error503(r)
        ),
        path(
            "__test__/504/",
            lambda r: error504(r)
        ),
    ]
