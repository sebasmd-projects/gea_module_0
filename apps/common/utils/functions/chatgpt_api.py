import logging
import re
from typing import Literal, Optional

from django.conf import settings
from django.utils.translation import gettext_lazy as _
from openai import APIConnectionError, OpenAI, OpenAIError, RateLimitError

logger = logging.getLogger(__name__)

Language = Literal["es", "en"]


class ChatGPTAPI:
    """
    Encapsula el cliente de OpenAI y provee un método translate()
    que rellena el campo vacío con traducción.
    """

    def __init__(self, model: Optional[str] = "gpt-4o-mini", timeout: Optional[int] = None):
        """
        Sin clave **no revienta**: se queda sin traductor y ya.

        Antes lanzaba ``ValueError`` aqui, y eso tumbaba el proyecto entero.
        Los dos sitios que usan esta clase la instancian a nivel de modulo
        --``assets/signals.py`` y ``buyers/signals.py``--, y ``models.py``
        importa sus senales, asi que sin ``CHAT_GPT_API_KEY`` la aplicacion no
        llegaba ni a arrancar: una integracion opcional sin configurar se
        llevaba por delante el catalogo de activos, las ordenes de compra y
        todo lo demas.

        Traducir es una comodidad. Que falte no puede ser peor que un campo
        sin traducir.
        """
        self.api_key = getattr(settings, 'CHAT_GPT_API_KEY', None)
        self.model = model
        self.timeout = timeout or 20

        if not self.api_key:
            logger.warning(
                'CHAT_GPT_API_KEY is not configured: automatic translation '
                'is off, and the bilingual fields keep the original text.'
            )
            self.client = None
            return

        self.client = OpenAI(api_key=self.api_key)

    @property
    def is_available(self) -> bool:
        return self.client is not None

    def _sanitize(self, s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip())

    def translate(
        self,
        text: str,
        src: Language,
        dst: Language,
        *,
        max_chars: Optional[int] = None,
        system_hint: str = (
            "You are a professional, concise translator. Keep meaning and tone. "
            "Return ONLY the translated text, without quotes or labels."
            "Remember that the context is about historical assets, such as German bonds, gold objects, high-denomination banknotes, among others."
        ),
    ) -> str:
        """
        Traduce un texto de src → dst usando el Responses API.
        Solo devuelve el texto traducido (sin extras).
        """
        if not text:
            return ""

        text = self._sanitize(text)

        # El recorte va **antes** de la salida corta, no despues: el campo de
        # destino tiene el mismo `max_length` se traduzca o no, y devolver el
        # original entero haria fallar el guardado justo en el caso en que se
        # queria simplificar.
        if max_chars:
            text = text[:max_chars]

        # En desarrollo no se sale a la red, y sin clave no se puede: en los
        # dos casos se devuelve **el texto original**.
        #
        # Aqui ponia `return src`, o sea que traducir "Bono aleman" de es a en
        # devolvia la cadena `"es"`. Todo activo creado en desarrollo se
        # quedaba con `en_name = "es"`, `en_description = "es"`... Era un
        # `text` mal escrito: la intencion --no llamar a OpenAI-- era buena, y
        # lo que hacia era llenar la base de basura.
        #
        # Una copia sin traducir es el "todavia no" natural de este proyecto:
        # las plantillas ya hacen `en_name or es_name`, asi que se lee bien y
        # el hueco no queda vacio.
        if settings.DEBUG or not self.is_available:
            return text

        try:
            resp = self.client.responses.create(
                model=self.model,
                instructions=system_hint,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    f"Translate the following text.\n"
                                    f"Source language: {src}\n"
                                    f"Target language: {dst}\n"
                                    f"Text: {text}"
                                ),
                            }
                        ],
                    }
                ],
                timeout=self.timeout,
            )
            out = (resp.output_text or "").strip()
            # limpieza por si el modelo añade prefijos
            out = re.sub(r"^\s*(translated\s*[:\-–]\s*)", "", out, flags=re.I)
            return out
        except (APIConnectionError, RateLimitError) as e:
            logger.warning("OpenAI temporary error: %s", e)
            return ""
        except OpenAIError as e:
            logger.error("OpenAI error: %s", e)
            return ""
        except Exception as e:
            logger.exception("Unexpected error in translation")
            return ""
