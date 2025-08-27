
import logging
import os

from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


def auto_delete_asset_img_on_delete(sender, instance, *args, **kwargs):
    """
    Delete image file from filesystem when the corresponding AssetModel instance is deleted.
    """
    if instance.asset_img:
        try:
            if os.path.isfile(instance.asset_img.path):
                os.remove(instance.asset_img.path)
        except Exception as e:
            logger.error(
                f"Error deleting image {instance.asset_img.path}: {e}"
            )


def auto_delete_asset_img_on_change(sender, instance, *args, **kwargs):
    """
    Delete old image file from filesystem when the corresponding AssetModel instance is updated with a new file.
    """
    if not instance.pk:
        return

    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    if old_instance.asset_img and old_instance.asset_img != instance.asset_img:
        try:
            if os.path.isfile(old_instance.asset_img.path):
                os.remove(old_instance.asset_img.path)
        except Exception as e:
            logger.error(
                f"Error deleting old image {old_instance.asset_img.path}: {e}"
            )
