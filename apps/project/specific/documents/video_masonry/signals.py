# apps/project/specific/documents/video_masonry/signals.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from .models import MediaAsset, DEFAULT_MAX_BYTES, DEFAULT_MAX_MB


def _normalize_categories(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(",")]
    cleaned: list[str] = []
    seen = set()
    for p in parts:
        if not p:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(p)
    return ", ".join(cleaned) if cleaned else None


@receiver(pre_save, sender=MediaAsset)
def mediaasset_pre_save(sender, instance: MediaAsset, **kwargs):
    if not instance.file:
        return

    # Infer media_type
    inferred = instance.infer_media_type()
    if not inferred:
        raise ValidationError("File type not allowed.")
    instance.media_type = inferred

    # Normalizar categories
    instance.categories = _normalize_categories(instance.categories)

    # Verificar peso
    size = getattr(instance.file, "size", None)
    if size is None:
        instance.size_bytes = 0
        return

    instance.size_bytes = int(size)

    if size > DEFAULT_MAX_BYTES:
        raise ValidationError(f"The file exceeds {DEFAULT_MAX_MB}MB.")
