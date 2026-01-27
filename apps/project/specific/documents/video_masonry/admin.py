# apps/project/specific/documents/video_masonry/admin.py
from django.contrib import admin
from .models import MediaAsset

@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "media_type", "file", "remove_audio", "categories", "size_bytes", "created_at")
    list_filter = ("media_type", "remove_audio", "created_at")
    search_fields = ("file", "caption", "categories")
    readonly_fields = ("media_type", "size_bytes", "created_at")

    fieldsets = (
        ("Archivo", {"fields": ("file", "caption", "categories")}),
        ("Política de video", {"fields": ("remove_audio",)}),
        ("Sistema", {"fields": ("media_type", "size_bytes", "created_at")}),
    )
