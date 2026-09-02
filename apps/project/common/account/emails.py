# apps/project/common/account/emails.py
"""
El correo con el código de acceso.

La maqueta, los logos y el pie viven en `apps.common.utils.otp_email`, que es
el mismo correo que manda la verificación pública de certificados. Aquí sólo
está lo que distingue a este de aquel: el asunto y la frase que dice para qué
sirve el código.
"""

from django.utils.translation import gettext as _

from apps.common.utils.otp_email import send_otp_email


def send_login_otp_email(*, user, code: str, minutes: int) -> None:
    """
    Manda el código de acceso a la dirección del usuario.

    Sale con ``fail_silently=False`` a propósito: si el correo no llega a
    salir, quien lo espera se quedaría mirando una pantalla que promete un
    código que no va a llegar, y es mejor que la pantalla lo diga.
    """
    send_otp_email(
        to=user.email,
        subject=_(
            'Sign in to Propensiones (GEA): here is the 6-digit verification '
            'code you requested'
        ),
        instruction=_('Use the following code to sign in to your account.'),
        code=code,
        minutes=minutes,
        greeting_name=user.get_short_name() or user.get_username(),
    )
