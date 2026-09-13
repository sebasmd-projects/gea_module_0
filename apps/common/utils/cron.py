import logging
import os
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
from apps.common.utils.models import GeaDailyUniqueCode
from apps.common.utils.outbound import InsecureUrlScheme, require_http_url


logger = logging.getLogger(__name__)


def generate_and_send_gea_code():
    """
    Se ejecuta diariamente vía django-crontab.
    Genera (si no existe) el código y lo envía por correo.
    """
    GeaDailyUniqueCode.send_today(kind=GeaDailyUniqueCode.KindChoices.GENERAL)


def warm_gea_app():
    url = os.getenv("GEA_WARMUP_URL", "https://geausa.propensionesabogados.com/health/")

    # `urlopen` abre tambien `file://`, y esta URL sale de una variable de
    # entorno. Una variable mal puesta --o cambiada por quien pueda tocar el
    # entorno del cron-- convertiria el calentamiento en una lectura de
    # ficheros locales cada tres minutos. Se comprueba el esquema antes.
    try:
        require_http_url(url)
    except InsecureUrlScheme as error:
        logger.error("WARMUP %s", error)
        return

    try:
        with urlopen(url, timeout=20) as response:
            response.getcode()
    except HTTPError as e:
        logger.warning("WARMUP HTTPError %s (status=%s)", url, e.code)
    except URLError as e:
        logger.warning("WARMUP URLError %s (reason=%s)", url, e.reason)
    except Exception as e:
        logger.exception("WARMUP Exception %s (%s)", url, e)
