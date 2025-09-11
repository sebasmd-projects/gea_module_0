from auditlog.models import AuditlogHistoryField
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import models, transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _
from auditlog.registry import auditlog


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
    def today(self, *, kind: str):
        """Devuelve el código activo de hoy para un kind dado, o None."""
        today = timezone.localdate()
        return self.filter(valid_on=today, kind=kind, is_active=True).first()

    @transaction.atomic
    def get_or_create_for_today(self, *, kind: str):
        """
        Obtiene o crea el código de hoy para un kind dado. Garantiza unicidad por (fecha, kind).
        """
        today = timezone.localdate()
        obj = self.select_for_update().filter(valid_on=today, kind=kind).first()
        if obj and obj.is_active:
            return obj, False

        if not obj:
            obj = GeaDailyUniqueCode(valid_on=today, kind=kind)

        code = get_random_string(
            length=10, allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        obj.code = code
        obj.is_active = True
        obj.save()
        return obj, True

    def verify_code(self, candidate: str, *, kind: str) -> bool:
        """Valida un código contra el código activo de HOY para el kind proporcionado."""
        if not candidate:
            return False
        rec = self.today(kind=kind)
        return bool(rec and candidate.strip() == rec.code)


class GeaDailyUniqueCode(TimeStampedModel):
    class KindChoices(models.TextChoices):
        GENERAL = "G", _("General")
        BUYER = "B", _("Buyer")

    valid_on = models.DateField(
        _("valid on")
    )

    kind = models.CharField(
        _("kind"),
        max_length=1,
        choices=KindChoices.choices,
        default=KindChoices.GENERAL
    )

    code = models.CharField(
        _("code"),
        max_length=64,
        db_index=True
    )

    sent_to = models.JSONField(
        _("sent to emails"),
        default=list,
        blank=True
    )

    sent_at = models.DateTimeField(
        _("sent at"),
        blank=True,
        null=True
    )

    last_email_message_id = models.CharField(
        _("last email message id"),
        max_length=255,
        blank=True,
        null=True
    )

    objects = GeaDailyUniqueCodeManager()

    class Meta:
        db_table = "utils_gea_daily_unique_code"
        verbose_name = _("GEA daily unique code")
        verbose_name_plural = _("GEA daily unique codes")
        indexes = [
            models.Index(fields=["valid_on"]),
            models.Index(fields=["code"]),
            models.Index(fields=["kind", "valid_on"]),
        ]

    def __str__(self):
        return f"{self.valid_on} [{self.get_kind_display()}] -> {self.code}"

    def mark_sent(self, to_list, message_id=None):
        self.sent_to = list(to_list or [])
        self.sent_at = timezone.now()
        self.last_email_message_id = message_id
        self.save(
            update_fields=[
                "sent_to",
                "sent_at",
                "last_email_message_id"
            ]
        )

    @classmethod
    def send_today(cls, *, kind: str):
        """
        Crea (si no existe) y envía el código de hoy al grupo definido según el kind.
        """
        obj, _created = cls.objects.get_or_create_for_today(kind=kind)

        if kind == cls.KindChoices.BUYER:
            recipients = settings.GEA_DAILY_CODE_BUYER_RECIPIENTS
            subject = f"Código de registro GEA (Compra) {obj.valid_on}"
        else:
            recipients = settings.GEA_DAILY_CODE_GENERAL_RECIPIENTS
            subject = f"Código de registro GEA (Facilitador, Representante, Tenedor) {obj.valid_on}"
        
        from_email = settings.DEFAULT_FROM_EMAIL

        text_body = (
            f"Código de registro GEA ({obj.get_kind_display()}) para {obj.valid_on}:\n\n"
            f"    {obj.code}\n\n"
            "Este código es válido únicamente para el día indicado.\n"
        )
        html_body = (
            f"<p><strong>Código de registro GEA</strong> (<em>{obj.get_kind_display()}</em>) "
            f"para <strong>{obj.valid_on}</strong>:</p>"
            f"<p style='font-size:20px; letter-spacing:2px;'><code>{obj.code}</code></p>"
            "<p>Este código es válido únicamente para el día indicado.</p>"
        )

        msg = EmailMultiAlternatives(
            subject,
            text_body,
            from_email,
            recipients
        )

        msg.attach_alternative(html_body, "text/html")

        message_id = msg.send()

        obj.mark_sent(recipients, message_id=str(message_id))
        return obj



class IPBlockedModel(TimeStampedModel):
    class ReasonsChoices(models.TextChoices):
        SERVER_HTTP_REQUEST = 'RA', _('Attempts to obtain forbidden urls')
        SECURITY_KEY_ATTEMPTS = 'SK', _(
            'Multiple failed security key entry attempts'
        )

    is_active = models.BooleanField(_("is blocked"), default=True)
    current_ip = models.CharField(_('current user IP'), max_length=150)
    reason = models.CharField(
        _("reason"), max_length=4, choices=ReasonsChoices.choices, default=ReasonsChoices.SERVER_HTTP_REQUEST)
    blocked_until = models.DateTimeField(
        _("blocked until"), null=True, blank=True)
    session_info = models.JSONField(
        _("session information"), default=dict, blank=True)

    def __str__(self):
        return f"{self.current_ip} - Blocked until {self.blocked_until}"

    class Meta:
        db_table = 'apps_common_utils_ipblocked'
        verbose_name = 'Blocked IP'
        verbose_name_plural = 'Blocked IPs'


class WhiteListedIPModel(TimeStampedModel):
    current_ip = models.CharField(
        _('current user IP'),
        max_length=150
    )

    reason = models.CharField(
        _("reason"),
        max_length=150,
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.current_ip}"

    class Meta:
        db_table = 'apps_utils_whitelistedip'
        verbose_name = 'WhiteListed IP'
        verbose_name_plural = 'WhiteListed IPs'


auditlog.register(
    IPBlockedModel,
    serialize_data=True
)

auditlog.register(
    WhiteListedIPModel,
    serialize_data=True
)
