from django.apps import AppConfig


class VideoMasonryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.documents.video_masonry'

    def ready(self):
        from . import signals
