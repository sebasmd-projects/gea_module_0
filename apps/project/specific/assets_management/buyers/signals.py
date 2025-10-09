import io
import logging
import os

from django.core.files.base import ContentFile
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from apps.common.utils.functions.chatgpt_api import ChatGPTAPI

logger = logging.getLogger(__name__)
translator = ChatGPTAPI()

# =============== OPTIMIZACIÓN ===============


def _optimize_image(file, *, max_w=1600, max_h=1600, quality=85, to_webp=True):
    """
    Optimiza una imagen:
    - Aplica orientación por EXIF
    - Limita tamaño a max_w x max_h manteniendo proporciones
    - Convierte a RGB si hace falta
    - Comprime y (opcional) convierte a WebP
    Devuelve: (bytes, new_ext)  -> bytes de la imagen optimizada y extensión sugerida ('.webp' o original).
    """
    try:
        file.seek(0)
        img = Image.open(file)

        # 1) Corrige orientación por EXIF
        img = ImageOps.exif_transpose(img)

        # 2) Asegura modo compatible
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")

        # 3) Resize si excede límites
        img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

        # 4) Salida
        out = io.BytesIO()
        if to_webp:
            # Si tiene alpha, guarda con lossless para preservar transparencia
            save_kwargs = {"format": "WEBP",
                           "quality": quality, "optimize": True}
            if img.mode == "RGBA":
                save_kwargs["lossless"] = True
            img.save(out, **save_kwargs)
            new_ext = ".webp"
        else:
            # Mantén formato original si no convertimos a WebP
            fmt = (img.format or "JPEG").upper()
            if fmt == "PNG" and img.mode == "RGBA":
                # PNG con alpha, sin pérdida
                img.save(out, format="PNG", optimize=True)
                new_ext = ".png"
            else:
                img.save(out, format="JPEG", quality=quality,
                         optimize=True, progressive=True)
                new_ext = ".jpg"

        out.seek(0)
        return out.read(), new_ext
    except Exception as e:
        logger.error(f"Image optimization error: {e}")
        # Si falla, devuelve None para no bloquear el guardado
        return None, None


def _is_new_file_uploaded(instance, sender, field_name: str) -> tuple[bool, str | None]:
    """
    Determina si hay un archivo NUEVO cargado para el campo de imagen.
    Retorna (is_new, old_name)
    """
    if not instance.pk:
        # Creación: si trae archivo, es nuevo; no hay "viejo"
        return bool(getattr(instance, field_name, None)), None

    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return bool(getattr(instance, field_name, None)), None

    old_f = getattr(old_instance, field_name, None)
    new_f = getattr(instance, field_name, None)
    old_name = getattr(old_f, "name", None) if old_f else None
    new_name = getattr(new_f, "name", None) if new_f else None

    # Si no hay nuevo, no es reemplazo
    if not new_f:
        return False, old_name

    # Si hay nuevo y cambia el nombre o era None antes -> es reemplazo
    return (old_name != new_name), old_name


# =============== DELETE EN REEMPLAZO + OPTIMIZACIÓN PRE-SAVE ===============
def auto_delete_and_optimize_offer_img_on_change(sender, instance, **kwargs):
    """
    1) Si suben una nueva imagen (reemplazo), borra el archivo anterior del storage.
    2) Optimiza la imagen NUEVA (EXIF, resize, compresión, opcional WebP).
    """
    field_name = "offer_img"

    is_new, old_name = _is_new_file_uploaded(instance, sender, field_name)

    # 1) Si hay reemplazo, elimina el archivo anterior del storage
    if is_new and old_name:
        try:
            storage = getattr(getattr(sender.objects.get(
                pk=instance.pk), field_name), "storage", None)
            if storage and storage.exists(old_name):
                storage.delete(old_name)
        except Exception as e:
            logger.error(f"Error deleting old offer image '{old_name}': {e}")

    # 2) Optimiza la imagen nueva (si es que viene)
    f = getattr(instance, field_name, None)
    if not f:
        return

    try:
        # Evita re-optimizar si el archivo ya es pequeño y .webp con tu pipeline;
        # aún así es seguro optimizar siempre.
        optimized_bytes, new_ext = _optimize_image(
            f.file, max_w=1600, max_h=1600, quality=85, to_webp=True)
        if optimized_bytes and new_ext:
            base_name, _ext = os.path.splitext(f.name or "image")
            # Renombra al mismo nombre base + nueva extensión
            new_name = f"{base_name}{new_ext}"
            content = ContentFile(optimized_bytes)
            # Reasigna el archivo optimizado al field
            getattr(instance, field_name).save(new_name, content, save=False)
    except Exception as e:
        logger.error(
            f"Error optimizing image for OfferModel(pk={getattr(instance, 'pk', None)}): {e}")


# =============== DELETE EN BORRADO DEL OBJETO POST DELETE ===============
def auto_delete_offer_img_on_delete(sender, instance, **kwargs):
    """
    Elimina el archivo del storage cuando se borra la instancia.
    """
    f = getattr(instance, "offer_img", None)
    if not f:
        return
    try:
        if f.name and f.storage.exists(f.name):
            f.storage.delete(f.name)
    except Exception as e:
        logger.error(
            f"Error deleting offer image on delete '{getattr(f, 'name', None)}': {e}")


def auto_fill_offer_translation(sender, instance, **kwargs):
    """
    Autocompleta traducciones de description/observation EN<->ES si falta el par.
    """
    try:
        # --- Observation ---
        if instance.es_observation and not instance.en_observation:
            instance.en_observation = translator.translate(
                instance.es_observation, src="es", dst="en", max_chars=10000
            )
        elif instance.en_observation and not instance.es_observation:
            instance.es_observation = translator.translate(
                instance.en_observation, src="en", dst="es", max_chars=10000
            )

        # --- Description ---
        if instance.es_description and not instance.en_description:
            instance.en_description = translator.translate(
                instance.es_description, src="es", dst="en", max_chars=10000
            )
        elif instance.en_description and not instance.es_description:
            instance.es_description = translator.translate(
                instance.en_description, src="en", dst="es", max_chars=10000
            )

    except Exception as e:
        logger.exception(_(f"Error filling offer translation fields: {e}"))
