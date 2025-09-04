
import logging
import os

from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions.chatgpt_api import ChatGPTAPI

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


translator = ChatGPTAPI()


def auto_fill_asset_category_translation(sender, instance, *args, **kwargs):
    """
    Automatically fill the asset category translation fields when a new AssetModel instance is created.
    """

    try:
        # Name
        if instance.es_name and not instance.en_name:
            instance.en_name = translator.translate(
                instance.es_name,
                src="es",
                dst="en",
                max_chars=50
            )

        elif instance.en_name and not instance.es_name:
            instance.es_name = translator.translate(
                instance.en_name,
                src="en",
                dst="es",
                max_chars=50
            )

        # Description
        if instance.es_description and not instance.en_description:
            instance.en_description = translator.translate(
                instance.es_description,
                src="es",
                dst="en",
                max_chars=100
            )

        elif instance.en_description and not instance.es_description:
            instance.es_description = translator.translate(
                instance.en_description,
                src="en",
                dst="es",
                max_chars=100
            )

    except Exception as e:
        logger.exception(
            _(f"Error filling asset category translation fields: {e}"))


def auto_fill_asset_name_translation(sender, instance, *args, **kwargs):
    """
    Automatically fill the asset name translation fields when a new AssetModel instance is created.
    """
    print("Filling asset name translation fields...")
    try:
        # Name
        if instance.es_name and not instance.en_name:
            instance.en_name = translator.translate(
                instance.es_name,
                src="es",
                dst="en",
                max_chars=50
            )

        elif instance.en_name and not instance.es_name:
            instance.es_name = translator.translate(
                instance.en_name,
                src="en",
                dst="es",
                max_chars=50
            )

    except Exception as e:
        logger.exception(
            _(f"Error filling asset name translation fields: {e}"))


def auto_fill_asset_translation_fields(sender, instance, *args, **kwargs):
    """
    Automatically fill the asset translation fields when a new AssetModel instance is created.
    """

    try:
        # Description
        if instance.es_description and not instance.en_description:
            instance.en_description = translator.translate(
                instance.es_description,
                src="es",
                dst="en",
                max_chars=200
            )

        elif instance.en_description and not instance.es_description:
            instance.es_description = translator.translate(
                instance.en_description,
                src="en",
                dst="es",
                max_chars=200
            )

        # Observations
        if instance.es_observations and not instance.en_observations:
            instance.en_observations = translator.translate(
                instance.es_observations,
                src="es",
                dst="en",
                max_chars=200
            )

        elif instance.en_observations and not instance.es_observations:
            instance.es_observations = translator.translate(
                instance.en_observations,
                src="en",
                dst="es",
                max_chars=200
            )
            
    except Exception as e:
        logger.exception(_(f"Error filling asset translation fields: {e}"))
