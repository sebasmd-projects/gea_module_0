# apps/project/specific/documents/video_masonry/models.py
from __future__ import annotations

import os
from django.core.exceptions import ValidationError
from django.db import models
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
    media_type = models.CharField(
        max_length=10,
        choices=MediaType.choices,
        editable=False
    )
    caption = models.TextField(blank=True, null=True)

    categories = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=_("Categories separated by commas. E.g: historical, exotic, scrolls"),
    )

    # ✅ NUEVO: clave derivada para filtrar exacto por token: |civil|laboral|
    categories_key = models.CharField(
        max_length=650,
        blank=True,
        null=True,
        editable=False,
        db_index=True,
        help_text=_("Derived field for filtering. Do not edit."),
    )

    remove_audio = models.BooleanField(default=True)

    size_bytes = models.BigIntegerField(default=0, editable=False)

    # Si TimeStampedModel ya trae created_at, elimina este campo.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["media_type", "created_at"]),
            models.Index(fields=["categories_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.media_type}: {self.file.name}"

    def clean(self):
        super().clean()

        if not self.file:
            raise ValidationError({"file": _("File is required.")})

        ext = os.path.splitext(self.file.name or "")[1].lower()
        is_img = ext in ALLOWED_IMAGE_EXTS
        is_vid = ext in ALLOWED_VIDEO_EXTS

        if not (is_img or is_vid):
            raise ValidationError({"file": _("File extension not allowed: ") + ext})

        size = getattr(self.file, "size", None)
        if size is not None and size > DEFAULT_MAX_BYTES:
            raise ValidationError({"file": _("File exceeds ") + str(DEFAULT_MAX_MB) + _("MB.")})

        if self.categories and len(self.categories) > 500:
            raise ValidationError({"categories": _("Categories too long.")})

    def infer_media_type(self) -> str:
        ext = os.path.splitext(self.file.name)[1].lower()
        if ext in ALLOWED_IMAGE_EXTS:
            return self.MediaType.IMAGE
        if ext in ALLOWED_VIDEO_EXTS:
            return self.MediaType.VIDEO
        return ""

    @property
    def categories_list(self) -> list[str]:
        if not self.categories:
            return []
        parts = [p.strip() for p in self.categories.split(",")]
        return [p for p in parts if p]
