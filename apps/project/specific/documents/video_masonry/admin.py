# apps/project/specific/documents/video_masonry/admin.py
from django.contrib import admin
from .models import MediaAsset

@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "media_type", "file", "remove_audio", "size_bytes", "created")
    list_filter = ("media_type", "remove_audio", "created")
    search_fields = ("file", "caption")
    readonly_fields = ("media_type", "size_bytes", "created")

    fieldsets = (
        ("Archivo", {"fields": ("file", "caption")}),
        ("Política de video", {"fields": ("remove_audio",)}),
        ("Sistema", {"fields": ("media_type", "size_bytes", "created")}),
    )
