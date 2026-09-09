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
    """
    Una IP frenada, y lo que se sabe de ella.

    Los datos vivían **dentro** de ``session_info``, un JSON. Funcionaba para
    guardarlos y no servía para nada más: desde el admin no se podía ordenar
    por número de intentos, ni filtrar las que vienen de un proveedor cloud,
    ni ver de un vistazo cuándo empezó cada una. Para responder «¿esto es un
    escáner o alguien que se equivocó de URL?» había que abrir la fila y leer
    un JSON.

    Así que lo que se consulta está ahora en columnas y el JSON se queda como
    **el rastro crudo**: la lista de rutas, las cabeceras, los parámetros. Las
    columnas se derivan de él al anotar cada intento (``blocking.py``), no se
    escriben a mano por separado -- si se escribieran en dos sitios acabarían
    contando cosas distintas.
    """

    class ReasonsChoices(models.TextChoices):
        SERVER_HTTP_REQUEST = 'RA', _('Attempts to obtain forbidden urls')
        SECURITY_KEY_ATTEMPTS = 'SK', _(
            'Multiple failed security key entry attempts'
        )
        # Las dos de abajo son nuevas. La primera la levanta el detector de
        # ráfagas de 404 --enumerar sin acertar ningún término de la trampa--
        # y la segunda, una herramienta de escaneo que se identifica sola.
        PATH_ENUMERATION = 'PE', _('Enumerating paths that do not exist')
        SCANNER_SIGNATURE = 'SC', _('Known scanning tool')

    is_active = models.BooleanField(_("is blocked"), default=True)
    current_ip = models.CharField(_('current user IP'), max_length=150)
    reason = models.CharField(
        _("reason"), max_length=4, choices=ReasonsChoices.choices, default=ReasonsChoices.SERVER_HTTP_REQUEST)
    blocked_until = models.DateTimeField(
        _("blocked until"), null=True, blank=True)
    session_info = models.JSONField(
        _("session information"), default=dict, blank=True)

    # --- Lo que antes había que leer del JSON --------------------------
    attempt_count = models.PositiveIntegerField(
        _('attempts'), default=0, db_index=True)

    unique_paths = models.PositiveIntegerField(
        _('unique paths'),
        default=0,
        help_text=_(
            'Distinct paths tried. Many attempts on one path is someone '
            'retrying; a few attempts on many paths is a scan.'
        ),
    )

    #: `created` es cuándo se abrió la fila y `updated` cambia con cualquier
    #: guardado, incluido uno hecho a mano desde el admin. Estas dos son de la
    #: actividad de la IP y sólo las mueve un intento suyo.
    first_seen = models.DateTimeField(
        _('first detection'), null=True, blank=True, db_index=True)
    last_seen = models.DateTimeField(
        _('last detection'), null=True, blank=True, db_index=True)

    user_agent = models.CharField(
        _('user agent'), max_length=500, blank=True, default='')

    matched_pattern = models.CharField(
        _('pattern'),
        max_length=150,
        blank=True,
        default='',
        help_text=_('What tripped the block: the trap term, or the signature.'),
    )

    # --- De qué red viene (ver netintel.py) ----------------------------
    country = models.CharField(
        _('country'), max_length=2, blank=True, default='', db_index=True)

    network_owner = models.CharField(
        _('network / ASN'), max_length=100, blank=True, default='')

    is_datacenter = models.BooleanField(
        _('datacenter or cloud'),
        default=False,
        db_index=True,
        help_text=_(
            'The IP belongs to a hosting provider range. A person browses '
            'from a home or office address; a server does not browse.'
        ),
    )

    # ------------------------------------------------------------------
    @property
    def is_currently_blocked(self) -> bool:
        """
        Si el bloqueo está en pie **ahora**, que no es lo mismo que ``is_active``.

        ``is_active`` es el interruptor: dice si alguien lo desactivó a mano.
        Que el bloqueo siga vigente depende además del reloj, y eso no lo puede
        guardar una columna sin que algo la vaya actualizando -- un cron o un
        guardado en cada petición, las dos cosas peores que la pregunta.

        Se calcula al leerla, así que el admin enseña siempre el estado real
        sin que nadie tenga que refrescar nada. Es también la condición exacta
        que aplica el middleware, escrita una sola vez.
        """
        if not self.is_active or not self.blocked_until:
            return False

        return self.blocked_until > timezone.now()

    @property
    def time_remaining(self):
        """Cuánto queda de bloqueo, o ``None`` si ya no hay."""
        if not self.is_currently_blocked:
            return None

        return self.blocked_until - timezone.now()

    def save(self, *args, **kwargs):
        """
        Rellena el origen de la IP la primera vez, venga la fila de donde venga.

        Va en ``save()`` y no sólo en el camino del bloqueo porque las filas se
        crean por cuatro sitios --la trampa, el detector de ráfagas, la firma
        de escáner y a mano desde el admin-- y una fila sin origen es
        justamente la que no se puede leer. Se calcula una sola vez: la tabla
        de prefijos es un recorrido en memoria, pero no cambia entre intentos.

        Respeta ``update_fields``: si quien guarda no pidió estos campos, no se
        escriben. Es lo que evita pisar un cambio hecho a mano desde el admin
        mientras una petición estaba en curso.
        """
        fields = kwargs.get('update_fields')

        if self.current_ip and not self.network_owner and not self.country:
            from apps.common.utils import netintel

            intel = netintel.describe(self.current_ip)

            self.network_owner = (intel['network_owner'] or '')[:100]
            self.is_datacenter = intel['is_datacenter']
            self.country = (intel['country'] or '')[:2]

            if fields is not None:
                kwargs['update_fields'] = set(fields) | {
                    'network_owner', 'is_datacenter', 'country'}

        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.current_ip} - Blocked until {self.blocked_until}"

    class Meta:
        db_table = 'apps_common_utils_ipblocked'
        verbose_name = 'Blocked IP'
        verbose_name_plural = 'Blocked IPs'
        # Por fecha de alta y, a igualdad, por la última vez que se tocó la
        # fila. `TimeStampedModel` ordena por `default_order`, que aquí no
        # significa nada: todas las filas lo tienen a 1, así que el orden
        # acababa siendo el que quisiera la base de datos.
        #
        # Las demás columnas del listado son ordenables desde el admin, así
        # que ver «lo último que se movió» es un clic en `last detection`.
        ordering = ['-created', '-updated']
        indexes = [
            # La consulta del middleware, que corre en **cada** petición que no
            # sea de un estático. Sin índice es un recorrido de la tabla entera
            # por petición, y esta tabla sólo crece.
            models.Index(
                fields=['current_ip', 'is_active', 'blocked_until'],
                name='ipblocked_lookup_idx',
            ),
        ]


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
