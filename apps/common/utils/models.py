from auditlog.models import AuditlogHistoryField
from auditlog.registry import auditlog
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import models, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _


class TimeStampedModel(models.Model):
    """Abstract model providing timestamp fields (created and updated) and additional metadata.

    Args:
        models.Model (class): Base Django model class.
    """
    history = AuditlogHistoryField()

    language_choices = [
        ('es', _('Spanish')),
        ('en', _('English')),
    ]

    language = models.CharField(
        _("language"),
        max_length=4,
        choices=language_choices,
        default='es',
        blank=True,
        null=True
    )

    created = models.DateTimeField(
        _('created'),
        default=timezone.now,
        editable=False
    )

    updated = models.DateTimeField(
        _('updated'),
        auto_now=True,
        editable=False
    )

    is_active = models.BooleanField(
        _("is active"),
        default=True
    )

    default_order = models.PositiveIntegerField(
        _('priority'),
        default=1,
        blank=True,
        null=True
    )

    class Meta:
        abstract = True
        ordering = ['default_order']

class GeaDailyUniqueCodeManager(models.Manager):
    def today(self):
        """Devuelve el código de hoy si existe, o None."""
        today = timezone.localdate()
        return self.filter(valid_on=today, is_active=True).first()

    @transaction.atomic
    def get_or_create_for_today(self):
        """Obtiene o crea el código de hoy. Garantiza unicidad por fecha."""
        today = timezone.localdate()
        obj = self.select_for_update().filter(valid_on=today).first()
        if obj and obj.is_active:
            return obj, False

        if not obj:
            obj = GeaDailyUniqueCode(valid_on=today)

        # Genera un código de 10 caracteres (A-Z, 2-7, sin caracteres ambiguos)
        # Puedes ajustar el length si quieres más/menos entropía.
        code = get_random_string(
            length=10, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        obj.code = code
        obj.is_active = True
        obj.save()
        return obj, True

    def verify_code(self, candidate: str) -> bool:
        """Valida un código contra el código activo de HOY."""
        if not candidate:
            return False
        rec = self.today()
        return bool(rec and candidate.strip() == rec.code)

class GeaDailyUniqueCode(TimeStampedModel):
    """
    Código único diario para registro GEA.
    - 'valid_on' es la fecha (zona horaria del servidor) para la cual el código es válido.
    - 'code' es el token que se envía por correo y se usa en el formulario.
    """
    valid_on = models.DateField(_("valid on"), unique=True)
    code = models.CharField(_("code"), max_length=64, db_index=True)

    sent_to = models.JSONField(_("sent to emails"), default=list, blank=True)
    sent_at = models.DateTimeField(_("sent at"), blank=True, null=True)
    last_email_message_id = models.CharField(_("last email message id"), max_length=255, blank=True, null=True)

    objects = GeaDailyUniqueCodeManager()

    class Meta:
        db_table = "utils_gea_daily_unique_code"
        verbose_name = _("GEA daily unique code")
        verbose_name_plural = _("GEA daily unique codes")
        indexes = [
            models.Index(fields=["valid_on"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return f"{self.valid_on} -> {self.code}"

    def mark_sent(self, to_list, message_id=None):
        self.sent_to = list(to_list or [])
        self.sent_at = timezone.now()
        self.last_email_message_id = message_id
        self.save(update_fields=["sent_to", "sent_at", "last_email_message_id", "updated"])

    @classmethod
    def send_today(cls):
        """
        Crea (si no existe) y envía el código de hoy a los destinatarios configurados.
        """
        obj, _created = cls.objects.get_or_create_for_today()
        recipients = [
            "support@propensionesabogados.com",
            "notificaciones@propensionesabogados.com",
            "info@propensionesabogados.com"
        ]
        subject = "Código de registro GEA (válido por hoy)"
        from_email = settings.DEFAULT_FROM_EMAIL

        text_body = (
            f"Código de registro GEA para {obj.valid_on}:\n\n"
            f"    {obj.code}\n\n"
            "Este código es válido únicamente para el día indicado.\n"
        )
        html_body = (
            f"<p><strong>Código de registro GEA</strong> para <strong>{obj.valid_on}</strong>:</p>"
            f"<p style='font-size:20px; letter-spacing:2px;'><code>{obj.code}</code></p>"
            "<p>Este código es válido únicamente para el día indicado.</p>"
        )

        msg = EmailMultiAlternatives(subject, text_body, from_email, recipients)
        msg.attach_alternative(html_body, "text/html")
        message_id = msg.send()  # En backends comunes devuelve num de enviados; algunos backends no devuelven id

        obj.mark_sent(recipients, message_id=str(message_id))
        return obj

