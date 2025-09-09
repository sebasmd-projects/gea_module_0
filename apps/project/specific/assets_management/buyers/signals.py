import logging

from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions.chatgpt_api import ChatGPTAPI

logger = logging.getLogger(__name__)
translator = ChatGPTAPI()


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
