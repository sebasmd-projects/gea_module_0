import logging
import os
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from apps.common.utils.models import GeaDailyUniqueCode


logger = logging.getLogger(__name__)


def generate_and_send_gea_code():
    """
    Se ejecuta diariamente vía django-crontab.
    Genera (si no existe) el código y lo envía por correo.
    """
    GeaDailyUniqueCode.send_today(kind=GeaDailyUniqueCode.KindChoices.GENERAL)
    GeaDailyUniqueCode.send_today(kind=GeaDailyUniqueCode.KindChoices.BUYER)


def warm_gea_app():
    url = os.getenv("GEA_WARMUP_URL", "https://geausa.propensionesabogados.com/health/")

    try:
        with urlopen(url, timeout=20) as response:
            response.getcode()
    except HTTPError as e:
        logger.warning("WARMUP HTTPError %s (status=%s)", url, e.code)
    except URLError as e:
        logger.warning("WARMUP URLError %s (reason=%s)", url, e.reason)
    except Exception as e:
        logger.exception("WARMUP Exception %s (%s)", url, e)
