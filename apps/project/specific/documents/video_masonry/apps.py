from django.apps import AppConfig


class VideoMasonryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.project.specific.documents.video_masonry'

    # Sin `ready()`. Habia uno que importaba `signals.py` solo para conectar
    # un `pre_save` que duplicaba lo que ya hace `MediaAsset.save()` -- y que
    # escribia dos campos que la migracion 0003 habia borrado, con lo que
    # guardar cualquier media reventaba. La derivacion vive ahora en un solo
    # sitio, el modelo.
