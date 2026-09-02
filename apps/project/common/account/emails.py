# apps/project/common/account/emails.py
"""
El correo con el código de acceso.

Los logos van **incrustados en el propio mensaje** (`cid:`), no enlazados. Un
`<img src="https://…">` en un correo lo bloquea Gmail y lo bloquea Outlook
hasta que el destinatario pulsa «mostrar imágenes»: el mensaje llega con dos
huecos rotos justo encima del código, que es lo que menos conviene en el
correo que autoriza una entrada. Con `cid:` la imagen viaja dentro y se ve
siempre, sin pedir permiso ni delatar cuándo se abrió el mensaje.

Y en PNG, no en WebP. Los logos del proyecto están en WebP porque es lo que
conviene en la web; en correo, Outlook de escritorio no lo pinta. La
conversión se hace una vez y se queda en memoria.
"""

import logging
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)

#: Los logos que van en la cabecera del mensaje, con el identificador con el
#: que la plantilla los referencia.
LOGOS = (
    ('propensiones', 'assets/imgs/logos/propensiones_h.webp'),
    ('gea', 'assets/imgs/logos/gea_logo_gold.webp'),
)

#: Ancho al que se reducen antes de mandarlos. Un logo de 2000 px en un correo
#: son cientos de kilobytes por mensaje sin ninguna ganancia.
LOGO_WIDTH = 320

_cache = {}


def _logo_png(path: str):
    """
    El logo en PNG, listo para adjuntar. ``None`` si no se puede leer.

    Nunca lanza: un correo sin logo se lee igual, y un fallo aquí no puede
    impedir que alguien entre en su cuenta.
    """
    if path in _cache:
        return _cache[path]

    _cache[path] = None

    try:
        import io

        from PIL import Image

        source = Path(settings.STATIC_ROOT or '') / path
        if not source.exists():
            for base in getattr(settings, 'STATICFILES_DIRS', []):
                candidate = Path(base) / path
                if candidate.exists():
                    source = candidate
                    break

        if not source.exists():
            logger.warning('Login OTP email: no se encontró el logo %s', path)
            return None

        image = Image.open(source)
        if image.width > LOGO_WIDTH:
            height = round(image.height * LOGO_WIDTH / image.width)
            image = image.resize((LOGO_WIDTH, height), Image.LANCZOS)

        buffer = io.BytesIO()
        image.convert('RGBA').save(buffer, 'PNG', optimize=True)
        _cache[path] = buffer.getvalue()

    except Exception:
        logger.exception('Login OTP email: no se pudo preparar el logo %s', path)

    return _cache[path]


def send_login_otp_email(*, user, code: str, minutes: int) -> None:
    """
    Manda el código a la dirección del usuario.

    Se llama con ``fail_silently=False`` a propósito: si el correo no sale, el
    usuario se quedaría esperando un código que no va a llegar, y es mejor que
    la pantalla lo diga a que se quede mirando.
    """
    from .otp_login import contact_email

    context = {
        'usuario': user.get_short_name() or user.get_username(),
        'codigo': code,
        'tiempo': minutes,
        'correo_contacto': contact_email(),
        'logos': [cid for cid, _path in LOGOS],
    }

    subject = _(
        'Sign in to Propensiones (GEA): here is the 6-digit verification '
        'code you requested'
    )

    html = render_to_string('email/login_otp_email.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(html.replace('</p>', '</p>\n')),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    # `related` y no `mixed`: los logos son parte del cuerpo, no adjuntos que
    # el destinatario deba ver colgando del mensaje.
    message.mixed_subtype = 'related'
    message.attach_alternative(html, 'text/html')

    for cid, path in LOGOS:
        blob = _logo_png(path)
        if not blob:
            continue
        image = MIMEImage(blob, _subtype='png')
        image.add_header('Content-ID', f'<{cid}>')
        image.add_header('Content-Disposition', 'inline', filename=f'{cid}.png')
        message.attach(image)

    message.send(fail_silently=False)
