from django.apps import AppConfig
from django.conf import settings

class UtilsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = f'{settings.UTILS_PATH}'
