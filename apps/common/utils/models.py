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


class RequestLogModel(TimeStampedModel):
    """A model to log requests."""
    requests = models.JSONField(
        _("requests"),
        blank=True,
        null=True,
        default=dict
    )

    @classmethod
    def get_instance(cls):
        """Get the singleton instance of RequestLogModel."""
        instance, _ = cls.objects.get_or_create(id=1)
        return instance

    def add_request_entry(self, entry):
        """Add a request entry to the log.

        :param entry: The request entry to add.
        :type entry: dict
        """
        requests = self.requests or []
        requests.insert(0, entry)
        self.requests = requests
        self.save()

    def __str__(self) -> str:
        return f'{self.id}'

    class Meta:
        db_table = f'apps_utils_requestlog'
        verbose_name = _('Request')
        verbose_name_plural = _('Requests')


auditlog.register(
    IPBlockedModel,
    serialize_data=True
)

auditlog.register(
    WhiteListedIPModel,
    serialize_data=True
)
