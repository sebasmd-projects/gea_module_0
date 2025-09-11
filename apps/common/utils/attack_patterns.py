from django.conf import settings
from django.urls import re_path

from .views import HttpRequestAttakView

pattern = r'^.*(?:' + '|'.join(settings.COMMON_ATTACK_TERMS) + r').*$'

common_attack_paths = [
    re_path(
        pattern,
        HttpRequestAttakView.as_view(),
        name='attack_path',
    ),
]
