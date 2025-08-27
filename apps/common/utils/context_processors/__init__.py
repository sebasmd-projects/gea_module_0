from datetime import datetime

from django.conf import settings


def custom_processors(request):
    ctx = {}
    ctx['honeypot_field'] = settings.HONEYPOT_FIELD_NAME
    return ctx
