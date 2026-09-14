"""
Los documentos legales, sus versiones y la constancia de quien los acepto.

Por que dejan de ser plantillas
-------------------------------
Los cuatro textos --terminos, tratamiento de datos, aviso de privacidad y
cookies-- vivian en plantillas HTML con su texto dentro de `{% trans %}`. Eso
tenia tres problemas, y los tres son de cumplimiento y no de comodidad:

1. **Un abogado no podia cambiar una coma sin un despliegue.** Quien redacta el
   documento no es quien tiene acceso al repositorio, asi que el texto vigente
   dependia de que alguien encontrara hueco para desplegarlo.
2. **El estado «borrador» estaba escrito en dos sitios a la vez**: un recuadro
   a mano dentro de cada plantilla y un sufijo `-borrador` en un ajuste de
   `settings.py`. Nada impedia publicar como aprobado un texto que seguia
   enseñando el aviso de borrador, ni al reves.
3. **No habia forma de demostrar que texto acepto nadie.** El articulo 9 de la
   Ley 1581 de 2012 obliga a conservar prueba de la autorizacion, y una
   plantilla no deja rastro de lo que decia el dia del alta: se despliega
   encima y el texto anterior desaparece del sitio publicado.

El estado vive en un solo sitio
-------------------------------
`LegalDocumentVersionModel.status` es **la unica** marca. El recuadro de
borrador que ve el visitante sale de ahi, y la cabecera con la version tambien.
No hay un segundo interruptor que pueda quedarse desincronizado.

La prueba es el hash, no el texto
---------------------------------
Una version aprobada **no se edita**: se aprueba otra. En el momento de
aprobar se calcula el `content_hash` sobre los bytes exactos del texto en los
dos idiomas, y es ese hash --no una copia del texto-- el que se guarda junto a
cada aceptacion. Asi la constancia sigue en pie aunque la fila de la version
se borre, y cambiar una letra del documento aprobado se nota, porque el hash
deja de cuadrar.

Es la misma idea que sostiene la certificacion de documentos (invariante 8):
lo que acredita no es el archivo, es su huella.
"""

import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from django_ckeditor_5.fields import CKEditor5Field

from apps.common.utils.functions.generate_hash import sha256_hex
from apps.common.utils.models import TimeStampedModel


class LegalDocumentKind(models.TextChoices):
    """
    Los cuatro documentos, con la clave que usa su URL.

    La clave es parte del contrato con el exterior: sale en `core:terms` y
    compañia, y una aceptacion guardada apunta a ella. No se renombran.
    """

    TERMS = 'terms', _('Terms and conditions')
    DATA_POLICY = 'data_policy', _('Personal data processing policy')
    PRIVACY = 'privacy', _('Privacy notice')
    COOKIES = 'cookies', _('Cookie policy')


class LegalVersionStatus(models.TextChoices):
    DRAFT = 'DRAFT', _('Draft')
    APPROVED = 'APPROVED', _('Approved')
    RETIRED = 'RETIRED', _('Retired')


class AcceptanceMethod(models.TextChoices):
    """
    Como se dio la autorizacion.

    Se guarda porque no valen lo mismo: una casilla marcada en el alta es
    consentimiento expreso, y seguir usando la plataforma despues de un aviso
    es consentimiento por conducta. Si algun dia hay que acreditar una, lo
    primero que se pregunta es cual de las dos fue.
    """

    REGISTRATION = 'REGISTRATION', _('On registration')
    CONTINUED_USE = 'CONTINUED_USE', _('Continued use after logging in')
    EXPLICIT = 'EXPLICIT', _('Accepted explicitly')


class LegalDocumentModel(TimeStampedModel):
    """
    Un documento legal. El texto no esta aqui: esta en sus versiones.

    Esta fila es la identidad estable --lo que la URL nombra y lo que una
    aceptacion referencia-- y dura mas que cualquier redaccion suya.
    """

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    key = models.CharField(
        _('Key'),
        max_length=30,
        choices=LegalDocumentKind.choices,
        unique=True,
        db_index=True,
        help_text=_('Identifies the document in its URL. Never renamed.')
    )

    es_name = models.CharField(_('Name (Spanish)'), max_length=200)
    en_name = models.CharField(_('Name (English)'), max_length=200)

    def name_for(self, language: str) -> str:
        return self.es_name if (language or 'es').startswith('es') else self.en_name

    def current_version(self):
        """
        La version vigente: la aprobada mas reciente que ya entro en vigor.

        Devuelve `None` si no hay ninguna aprobada — y entonces la pagina
        enseña el ultimo borrador con su aviso, que es mejor que un 404: el
        documento existe, lo que falta es la firma.
        """
        return (
            self.versions
            .filter(
                status=LegalVersionStatus.APPROVED,
                effective_from__lte=timezone.localdate(),
            )
            .order_by('-effective_from', '-approved_at')
            .first()
        )

    def latest_version(self):
        """La mas reciente sea cual sea su estado, para poder enseñar algo."""
        return self.versions.order_by('-created').first()

    def displayed_version(self):
        """Lo que ve un visitante: la vigente si la hay, si no el borrador."""
        return self.current_version() or self.latest_version()

    def __str__(self) -> str:
        return self.es_name or self.get_key_display()

    class Meta:
        db_table = 'apps_core_legal_document'
        verbose_name = _('Legal document')
        verbose_name_plural = _('Legal documents')
        ordering = ['default_order', 'key']


class LegalDocumentVersionModel(TimeStampedModel):
    """
    Una redaccion concreta de un documento, con su estado y su huella.

    **Una version aprobada no se edita.** Se aprueba otra. Lo impide `clean()`
    y lo comprueba una prueba: editar el texto que alguien ya acepto dejaria la
    constancia apuntando a algo que no existe, que es exactamente lo que esta
    tabla viene a evitar.
    """

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    document = models.ForeignKey(
        LegalDocumentModel,
        on_delete=models.CASCADE,
        related_name='versions',
        verbose_name=_('Document')
    )

    version = models.CharField(
        _('Version'),
        max_length=30,
        help_text=_('For example 1.0.0. Unique within the document.')
    )

    es_body = CKEditor5Field(
        _('Text (Spanish)'),
        config_name='legal',
        blank=True,
        default='',
        help_text=_('The wording that governs: these documents are Colombian.')
    )

    en_body = CKEditor5Field(
        _('Text (English)'),
        config_name='legal',
        blank=True,
        default='',
        help_text=_('Courtesy translation. Where they differ, Spanish rules.')
    )

    status = models.CharField(
        _('Status'),
        max_length=10,
        choices=LegalVersionStatus.choices,
        default=LegalVersionStatus.DRAFT,
        db_index=True
    )

    effective_from = models.DateField(
        _('In force since'),
        blank=True,
        null=True,
        help_text=_('Set when it is approved. Article 18 of the policy '
                    'requires publishing it.')
    )

    change_note_es = models.TextField(
        _('What changed (Spanish)'),
        blank=True,
        default='',
        help_text=_('Goes into the notice sent to every user. Say what '
                    'changed, not that something changed.')
    )

    change_note_en = models.TextField(
        _('What changed (English)'),
        blank=True,
        default=''
    )

    content_hash = models.CharField(
        _('Content hash (SHA-256)'),
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        editable=False,
        help_text=_('Computed on approval, over the exact text of both '
                    'languages. It is what an acceptance points to.')
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_legal_versions',
        verbose_name=_('Approved by'),
        blank=True,
        null=True,
        editable=False
    )

    approved_at = models.DateTimeField(
        _('Approved at'),
        blank=True,
        null=True,
        editable=False
    )

    notify_users = models.BooleanField(
        _('Notify every user'),
        default=True,
        help_text=_('Turn it off only for a correction that changes no '
                    'obligation — a typo, a broken link.')
    )

    notified_at = models.DateTimeField(
        _('Users notified at'),
        blank=True,
        null=True,
        editable=False
    )

    notified_count = models.PositiveIntegerField(
        _('People notified'),
        default=0,
        editable=False
    )

    @property
    def is_approved(self) -> bool:
        return self.status == LegalVersionStatus.APPROVED

    def body_for(self, language: str) -> str:
        return self.es_body if (language or 'es').startswith('es') else self.en_body

    def change_note_for(self, language: str) -> str:
        if (language or 'es').startswith('es'):
            return self.change_note_es
        return self.change_note_en or self.change_note_es

    def compute_hash(self) -> str:
        """
        La huella del texto, sobre los dos idiomas y la version.

        Se separan los campos con un caracter que no puede aparecer dentro
        (`\\x1f`, el separador de unidades) para que dos redacciones distintas
        no puedan producir la misma cadena concatenada. Es la misma precaucion
        que toma `services/jcs.py` con el payload maestro, por la misma razon:
        un hash que se puede provocar no prueba nada.
        """
        payload = '\x1f'.join([
            self.document.key if self.document_id else '',
            self.version or '',
            self.es_body or '',
            self.en_body or '',
        ])
        return sha256_hex(payload)

    def approve(self, *, user, effective_from=None):
        """
        Aprueba la version: fija quien, cuando, desde cuando y con que huella.

        Es el unico camino: el hash se calcula aqui y no en `save()`, porque
        recalcularlo en cada guardado convertiria una correccion de un
        borrador en un cambio de huella de algo ya aceptado.
        """
        if self.is_approved:
            return self

        self.status = LegalVersionStatus.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.effective_from = effective_from or timezone.localdate()
        self.content_hash = self.compute_hash()

        self.save(update_fields=[
            'status', 'approved_by', 'approved_at', 'effective_from',
            'content_hash', 'updated',
        ])

        return self

    def save(self, *args, **kwargs):
        """
        Un borrador lleva siempre la huella de lo que dice ahora mismo.

        Hace falta porque se puede aceptar un borrador: mientras no haya nada
        aprobado, es lo que el alta enseña, y una aceptacion sin huella no
        acredita **que** se acepto. Al aprobar, `approve()` la congela y este
        bloque deja de tocarla — si siguiera recalculandola, editar el texto
        despues cambiaria la huella de algo que alguien ya habia aceptado, que
        es justo lo que no puede pasar.
        """
        if self.status != LegalVersionStatus.APPROVED:
            self.content_hash = self.compute_hash()

        super().save(*args, **kwargs)

    def clean(self):
        errors = {}

        if self.is_approved and not self.effective_from:
            errors['effective_from'] = _(
                'An approved version has to say since when it is in force.'
            )

        if self.pk and self.is_approved:
            previous = (
                type(self).objects
                .filter(pk=self.pk)
                .values('es_body', 'en_body', 'version', 'status')
                .first()
            )

            # Solo muerde sobre una version que YA estaba aprobada: aprobar es
            # justamente pasar de borrador a aprobada cambiando el estado.
            if previous and previous['status'] == LegalVersionStatus.APPROVED:
                cambiado = (
                    previous['es_body'] != self.es_body
                    or previous['en_body'] != self.en_body
                    or previous['version'] != self.version
                )

                if cambiado:
                    errors['es_body'] = _(
                        'An approved version cannot be edited: somebody has '
                        'already accepted this exact text. Create a new '
                        'version instead.'
                    )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f'{self.document.key} {self.version} [{self.get_status_display()}]'

    class Meta:
        db_table = 'apps_core_legal_document_version'
        verbose_name = _('Legal document version')
        verbose_name_plural = _('Legal document versions')
        ordering = ['-effective_from', '-created']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'version'],
                name='uniq_version_per_legal_document'
            ),
            # Aprobada sin fecha de vigencia no se puede publicar, y aprobada
            # sin huella no se puede acreditar. La base lo impide tambien,
            # porque `approve()` no es el unico camino hasta una fila.
            models.CheckConstraint(
                condition=(
                    ~models.Q(status=LegalVersionStatus.APPROVED)
                    | (
                        models.Q(effective_from__isnull=False)
                        & ~models.Q(content_hash='')
                    )
                ),
                name='approved_legal_version_needs_date_and_hash'
            ),
        ]


class LegalAcceptanceModel(TimeStampedModel):
    """
    Constancia de que alguien acepto un texto concreto.

    Lo que exige la ley no es saber que el titular acepto, sino poder
    demostrar **que** acepto y **cuando**. De ahi que se guarde el hash junto a
    la referencia: la referencia dice cual, el hash prueba que ese cual no ha
    cambiado desde entonces.

    IP y agente son la prueba de la circunstancia, igual que en PQRS
    (`pqrs/models.py`): «marco una casilla» no es constancia si no se guarda
    desde donde y con que.
    """

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='legal_acceptances',
        verbose_name=_('Data owner')
    )

    version = models.ForeignKey(
        LegalDocumentVersionModel,
        on_delete=models.PROTECT,
        related_name='acceptances',
        verbose_name=_('Accepted version')
    )

    content_hash = models.CharField(
        _('Hash of what was accepted'),
        max_length=64,
        db_index=True,
        editable=False,
        help_text=_('Copied on acceptance. The proof survives even if the '
                    'version row does not.')
    )

    method = models.CharField(
        _('How it was given'),
        max_length=20,
        choices=AcceptanceMethod.choices,
        db_index=True
    )

    accepted_at = models.DateTimeField(
        _('Accepted at'),
        default=timezone.now,
        editable=False
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        blank=True,
        null=True,
        editable=False
    )

    user_agent = models.CharField(
        _('Browser'),
        max_length=400,
        blank=True,
        default='',
        editable=False
    )

    def save(self, *args, **kwargs):
        # La huella se copia de la version, no se recalcula: si el texto
        # cambiara, recalcularla haria que la constancia siguiera cuadrando
        # con un documento distinto del que se acepto.
        if not self.content_hash and self.version_id:
            self.content_hash = self.version.content_hash

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f'{self.user} · {self.version}'

    class Meta:
        db_table = 'apps_core_legal_acceptance'
        verbose_name = _('Legal acceptance')
        verbose_name_plural = _('Legal acceptances')
        ordering = ['-accepted_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'version'],
                name='uniq_acceptance_per_user_and_version'
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'accepted_at']),
        ]


# La auditoria de quien toco que, sobre la que se apoya la certificacion
# (docs/NORMATIVA.md). En estos tres es donde mas falta hace: un texto legal
# que cambia sin dejar rastro de quien lo cambio no se puede defender, y una
# constancia de aceptacion que se pueda editar en silencio no acredita nada.
auditlog.register(LegalDocumentModel, serialize_data=True)
auditlog.register(LegalDocumentVersionModel, serialize_data=True)
auditlog.register(LegalAcceptanceModel, serialize_data=True)
