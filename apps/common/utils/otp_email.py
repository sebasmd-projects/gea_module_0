# apps/common/utils/otp_email.py
"""
El correo que lleva un código de seis cifras, escrito una vez.

Hay dos sitios que mandan uno --entrar en la plataforma y consultar un
certificado-- y hasta ahora eran dos correos distintos: el del acceso llevaba
logos, aviso de caducidad y el recordatorio de que nadie del despacho pide el
código; el de la verificación era ``send_mail`` con tres líneas de texto
plano. El segundo llega a gente que no es usuaria de la plataforma y que acaba
de escanear un QR de un papel, o sea justo a quien más falta le hace reconocer
de quién viene el mensaje.

Aquí vive la parte que no cambia --la maqueta, los logos, la caja del código,
el pie-- y cada sitio pone lo suyo: el asunto y la frase que dice para qué es
el código.

Tres decisiones de maquetado que parecen anticuadas y no lo son
--------------------------------------------------------------

**Tablas y estilos en línea.** Los clientes de correo no traen hoja de estilos
externa, Outlook ignora la mayor parte del CSS moderno y Gmail recorta lo que
hay dentro de una etiqueta ``<style>``. Lo que aquí parece de hace veinte años
es lo único que se ve igual en todos.

**Los logos van dentro del mensaje** (``cid:``), no enlazados. Un
``<img src="https://…">`` lo bloquean Gmail y Outlook hasta que el destinatario
da permiso: el mensaje llegaría con dos huecos rotos justo encima del código,
que es lo que menos conviene en el correo que autoriza una entrada. Y de paso
un logo remoto delata cuándo se abrió el mensaje.

**Y en PNG, no en WebP.** Los logos del proyecto están en WebP porque es lo que
conviene en la web; en correo, Outlook de escritorio no lo pinta. La conversión
se hace una vez y se queda en memoria.
"""

import io
import logging
from html import unescape
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

#: Los logos de la cabecera, con el identificador con el que la plantilla los
#: referencia.
LOGOS = (
    ('propensiones', 'assets/imgs/logos/propensiones_h.webp'),
    ('gea', 'assets/imgs/logos/gea_logo_gold.webp'),
)

#: Ancho al que se reducen antes de mandarlos. Un logo de 2000 px en un correo
#: son cientos de kilobytes por mensaje sin ninguna ganancia.
LOGO_WIDTH = 320

#: A quién escribir si a alguien le llega un código que no ha pedido, que es la
#: señal de que otro está intentando entrar en su cuenta.
DEFAULT_CONTACT_EMAIL = 'info@propensionesabogados.com'

_cache = {}


def contact_email() -> str:
    return getattr(settings, 'OTP_CONTACT_EMAIL', DEFAULT_CONTACT_EMAIL)


def _logo_png(path: str):
    """
    El logo en PNG, listo para adjuntar. ``None`` si no se puede leer.

    Nunca lanza: un correo sin logo se lee igual, y un fallo aquí no puede
    impedir que alguien entre en su cuenta ni que consulte su certificado.
    """
    if path in _cache:
        return _cache[path]

    _cache[path] = None

    try:
        from PIL import Image

        source = Path(settings.STATIC_ROOT or '') / path

        if not source.exists():
            for base in getattr(settings, 'STATICFILES_DIRS', []):
                candidate = Path(base) / path

                if candidate.exists():
                    source = candidate
                    break

        if not source.exists():
            logger.warning('OTP email: no se encontró el logo %s', path)
            return None

        image = Image.open(source)

        if image.width > LOGO_WIDTH:
            height = round(image.height * LOGO_WIDTH / image.width)
            image = image.resize((LOGO_WIDTH, height), Image.LANCZOS)

        buffer = io.BytesIO()
        image.convert('RGBA').save(buffer, 'PNG', optimize=True)
        _cache[path] = buffer.getvalue()

    except Exception:  # noqa: BLE001
        logger.exception('OTP email: no se pudo preparar el logo %s', path)

    return _cache[path]


def send_otp_email(
    *,
    to: str,
    subject: str,
    instruction: str,
    code: str,
    minutes: int,
    greeting_name: str = '',
    fail_silently: bool = False,
) -> None:
    """
    Manda un código de seis cifras.

    Args:
        to: la dirección de destino.
        subject: el asunto, ya traducido.
        instruction: para qué es el código («…para iniciar sesión en tu
            cuenta», «…para validar las certificaciones»). Es lo único que
            distingue un correo del otro dentro del cuerpo.
        code: el código.
        minutes: cuánto dura, para decirlo en el mensaje.
        greeting_name: a quién se saluda. Vacío cuando no se sabe --la
            verificación pública no pide el nombre de nadie-- y entonces el
            saludo va a secas.
        fail_silently: por defecto **no**. Si el correo no sale, quien lo
            espera se quedaría mirando una pantalla que promete un código que
            no va a llegar; es mejor que la pantalla lo diga.
    """
    context = {
        'usuario': greeting_name or '',
        'instruccion': instruction,
        'codigo': code,
        'tiempo': minutes,
        'correo_contacto': contact_email(),
    }

    html = render_to_string('email/otp_email.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        # Dos cuidados en la versión en texto plano, que es la que ven los
        # clientes que no pintan HTML y la que acaban leyendo los lectores de
        # pantalla mal configurados. El salto tras cada párrafo evita que salga
        # como un solo renglón con el código pegado a la frase anterior; y
        # `unescape` deshace las entidades, porque `strip_tags` quita las
        # etiquetas pero deja el `&middot;` escrito tal cual.
        body=unescape(strip_tags(html.replace('</p>', '</p>\n'))),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
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

    message.send(fail_silently=fail_silently)
