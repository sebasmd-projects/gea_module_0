# apps/project/specific/documents/video_masonry/signals.py
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from .models import MediaAsset, DEFAULT_MAX_BYTES, DEFAULT_MAX_MB


def _normalize_categories(raw: str | None) -> list[str]:
    """
    Devuelve lista limpia, deduplicada (case-insensitive), preservando orden.
    """
    if not raw:
        return []
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
    return cleaned


def _build_categories_key(categories: list[str]) -> str | None:
    """
    Formato: |exotic|historical|scrolls|religious|
    en lower para comparación consistente.
    """
    if not categories:
        return None
    return "|" + "|".join([c.strip().lower() for c in categories if c.strip()]) + "|"


@receiver(pre_save, sender=MediaAsset)
def mediaasset_pre_save(sender, instance: MediaAsset, **kwargs):
    if not instance.file:
        return

    inferred = instance.infer_media_type()
    if not inferred:
        raise ValidationError(_("File type not allowed."))
    instance.media_type = inferred

    cats = _normalize_categories(instance.categories)
    instance.categories = ", ".join(cats) if cats else None
    instance.categories_key = _build_categories_key(cats)

    size = getattr(instance.file, "size", None)
    if size is None:
        instance.size_bytes = 0
        return

    instance.size_bytes = int(size)

    if size > DEFAULT_MAX_BYTES:
        raise ValidationError(_("The file exceeds %(max_mb)dMB.") % {"max_mb": DEFAULT_MAX_MB})
