# apps/project/specific/documents/video_masonry/models.py
from __future__ import annotations

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_VIDEO_EXTS = {".mp4", ".webm"}
DEFAULT_MAX_MB = 160
DEFAULT_MAX_BYTES = DEFAULT_MAX_MB * 1024 * 1024


def upload_to(instance: "MediaAsset", filename: str) -> str:
    base = os.path.basename(filename)
    return f"video_masonry/{base}"


class MediaAsset(TimeStampedModel):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    file = models.FileField(upload_to=upload_to)
    media_type = models.CharField(max_length=10, choices=MediaType.choices, editable=False)
    caption = models.TextField(blank=True, null=True)
    remove_audio = models.BooleanField(default=True)
    size_bytes = models.BigIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["-created", "-id"]
        indexes = [
            models.Index(fields=["media_type", "created"]),
        ]

    def __str__(self) -> str:
        return f"{self.media_type}: {self.file.name}"

    def infer_media_type(self) -> str:
        ext = os.path.splitext(self.file.name or "")[1].lower()
        if ext in ALLOWED_IMAGE_EXTS:
            return self.MediaType.IMAGE
        if ext in ALLOWED_VIDEO_EXTS:
            return self.MediaType.VIDEO
        return ""

    def clean(self):
        super().clean()

        if not self.file:
            raise ValidationError({"file": _("File is required.")})

        ext = os.path.splitext(self.file.name or "")[1].lower()
        if ext not in (ALLOWED_IMAGE_EXTS | ALLOWED_VIDEO_EXTS):
            raise ValidationError({"file": _("File extension not allowed: ") + ext})

        size = getattr(self.file, "size", None)
        if size is not None and size > DEFAULT_MAX_BYTES:
            raise ValidationError({"file": _("File exceeds ") + str(DEFAULT_MAX_MB) + _("MB.")})

    def save(self, *args, **kwargs):
        # Derivar tipo y tamaño de forma consistente (sin signals)
        if self.file:
            inferred = self.infer_media_type()
            if not inferred:
                raise ValidationError(_("File type not allowed."))
            self.media_type = inferred

            size = getattr(self.file, "size", None)
            self.size_bytes = int(size) if size is not None else 0

        super().save(*args, **kwargs)


class MediaAssetInteraction(TimeStampedModel):
    """
    Registro auditable de cada acción:
    - qué usuario
    - qué asset
    - qué acción (view/download)
    - cuándo
    """
    class Action(models.TextChoices):
        VIEW = "view", "View"
        DOWNLOAD = "download", "Download"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_asset_interactions",
    )
    asset = models.ForeignKey(
        MediaAsset,
        on_delete=models.CASCADE,
        related_name="interactions",
    )
    action = models.CharField(max_length=20, choices=Action.choices)

    class Meta:
        indexes = [
            models.Index(fields=["asset", "action", "created"]),
            models.Index(fields=["user", "action", "created"]),
        ]


class MediaAssetUserStats(TimeStampedModel):
    """
    Contadores agregados por (usuario, asset).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="media_asset_stats",
    )
    asset = models.ForeignKey(
        MediaAsset,
        on_delete=models.CASCADE,
        related_name="user_stats",
    )
    views_count = models.PositiveIntegerField(default=0)
    downloads_count = models.PositiveIntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "asset"], name="uniq_mediaasset_stats_user_asset")
        ]

    @classmethod
    def inc_view(cls, *, user, asset):
        obj, _ = cls.objects.get_or_create(user=user, asset=asset)
        cls.objects.filter(pk=obj.pk).update(
            views_count=F("views_count") + 1,
            last_viewed_at=models.functions.Now(),
        )

    @classmethod
    def inc_download(cls, *, user, asset):
        obj, _ = cls.objects.get_or_create(user=user, asset=asset)
        cls.objects.filter(pk=obj.pk).update(
            downloads_count=F("downloads_count") + 1,
            last_downloaded_at=models.functions.Now(),
        )
