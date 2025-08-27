from apps.common.utils.models import GeaDailyUniqueCode


def generate_and_send_gea_code():
    """
    Se ejecuta diariamente vía django-crontab.
    Genera (si no existe) el código y lo envía por correo.
    """
    GeaDailyUniqueCode.send_today()