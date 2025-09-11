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
        self.api_key = settings.CHAT_GPT_API_KEY
        if not self.api_key:
            raise ValueError(_("CHAT_GPT_API_KEY not configured"))

        self.model = model

        self.timeout = timeout or 20

        self.client = OpenAI(api_key=self.api_key)

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
        if max_chars:
            text = text[:max_chars]

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
