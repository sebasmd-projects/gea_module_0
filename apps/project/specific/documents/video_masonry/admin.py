# apps/project/specific/documents/video_masonry/admin.py
from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, Q

from .models import MediaAsset, MediaAssetInteraction, MediaAssetUserStats


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "media_type",
        "file_name",
        "size_bytes",
        "views_total",
        "downloads_total",
    )
    list_filter = ("media_type",)
    search_fields = ("file", "caption")
    readonly_fields = ("media_type", "size_bytes")
    ordering = ("-id",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            _views=Count("interactions", filter=Q(interactions__action=MediaAssetInteraction.Action.VIEW)),
            _downloads=Count("interactions", filter=Q(interactions__action=MediaAssetInteraction.Action.DOWNLOAD)),
        )

    @admin.display(description="File")
    def file_name(self, obj: MediaAsset) -> str:
        return (obj.file.name or "").rsplit("/", 1)[-1]

    @admin.display(description="Views", ordering="_views")
    def views_total(self, obj: MediaAsset) -> int:
        return int(getattr(obj, "_views", 0) or 0)

    @admin.display(description="Downloads", ordering="_downloads")
    def downloads_total(self, obj: MediaAsset) -> int:
        return int(getattr(obj, "_downloads", 0) or 0)


@admin.register(MediaAssetInteraction)
class MediaAssetInteractionAdmin(admin.ModelAdmin):
    list_display = ("id", "asset", "action", "user")
    list_filter = ("action",)
    search_fields = (
        "asset__file",
        "asset__caption",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    readonly_fields = ("user", "asset", "action")
    ordering = ("-id",)

    autocomplete_fields = ("user", "asset")


@admin.register(MediaAssetUserStats)
class MediaAssetUserStatsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "asset",
        "user",
        "views_count",
        "downloads_count",
        "last_viewed_at",
        "last_downloaded_at",
    )
    list_filter = ("last_viewed_at", "last_downloaded_at")
    search_fields = (
        "asset__file",
        "asset__caption",
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    readonly_fields = ()
    ordering = ("-id",)

    autocomplete_fields = ("user", "asset")
