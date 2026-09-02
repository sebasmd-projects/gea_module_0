# apps/project/specific/documents/certificates/utils.py

from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.utils.otp_email import send_otp_email as send_otp_email_template
from apps.project.common.users.models import UserModel

from .functions import get_client_ip
from .models import CertificateViewLogModel


def track_certificate_view(
    *,
    request: HttpRequest,
    certificate_user=None,
    document_verification=None,
    min_interval_seconds: int = 60,
) -> None:
    """
    Registra una visualización de certificado o documento
    evitando duplicados por IP en un intervalo corto.

    Parameters:
        request: HttpRequest actual
        certificate_user: UserVerificationModel
        document_verification: DocumentVerificationModel
        min_interval_seconds: intervalo antifraude en segundos

    Output:
        None
    """

    user: UserModel | None = (
        request.user if request.user.is_authenticated else None
    )

    ip_address = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT")

    recent_exists = CertificateViewLogModel.objects.filter(
        certificate_user=certificate_user,
        document_verification=document_verification,
        ip_address=ip_address,
        viewed_at__gte=timezone.now() - timedelta(seconds=min_interval_seconds),
    ).exists()

    if recent_exists:
        return

    CertificateViewLogModel.objects.create(
        certificate_user=certificate_user,
        document_verification=document_verification,
        user=user,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def track_document_view(
    *,
    request,
    document_verification,
    user=None,
    anonymous_email=None,
    deduplicate_minutes: int = 1
):
    """
    Track document visualization with deduplication.

    Rules:
    - Authenticated user OR anonymous email required
    - Prevent duplicate logs in short time window
    """

    if not user and not anonymous_email:
        return

    ip = get_client_ip(request)
    ua = request.META.get('HTTP_USER_AGENT', '')

    since = timezone.now() - timedelta(minutes=deduplicate_minutes)

    recent = CertificateViewLogModel.objects.filter(
        document_verification=document_verification,
        user=user,
        anonymous_email=anonymous_email,
        ip_address=ip,
        viewed_at__gte=since,
    ).exists()

    if recent:
        return

    CertificateViewLogModel.objects.create(
        document_verification=document_verification,
        user=user,
        anonymous_email=anonymous_email,
        ip_address=ip,
        user_agent=ua[:500],
    )


def send_otp_email(email: str, otp: str, minutes: int = 15) -> None:
    """
    Manda el código de verificación documental.

    Es el mismo correo que el del acceso --misma maqueta, mismos logos, mismo
    pie--, y esa es la gracia: llega a quien acaba de escanear el QR de un
    papel, no es usuario de la plataforma y no tiene por qué reconocer el
    remitente. Antes era un ``send_mail`` de tres líneas en texto plano, sin
    logos y sin el aviso de que nadie del despacho pide el código; justo al
    revés de lo que necesita quien menos contexto tiene.

    Parameters:
        email: a quién.
        otp: el código.
        minutes: cuánto dura, para decirlo en el mensaje. Lo pasa quien llama
            para que el correo no pueda prometer una duración distinta de la
            que de verdad se aplica.
    """
    send_otp_email_template(
        to=email,
        subject=_(
            'Verification at Propensiones (GEA): here is the 6-digit '
            'verification code you requested'
        ),
        instruction=_('Use the following code to validate the certifications.'),
        code=otp,
        minutes=minutes,
    )
