import hashlib
import hmac
import re
import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import EncryptedCharField

from apps.common.utils.models import TimeStampedModel
from apps.project.common.users.models import UserModel

from .checks import MIN_ISSUER_KEY_LENGTH
from .constants import DOCUMENT_PUBLIC_CODE_LENGTH
from .functions import (generate_public_code, generate_unique_public_code,
                        get_hmac, masked_document_number, normalize_text)


class DocumentTypeChoices(models.TextChoices):
    CC = 'CC', _('Citizen ID (CC)')
    PA = 'PA', _('Passport (PA)')
    UNIQUE_CODE = 'UNIQUE_CODE', _('Unique Code')


class UserCertificateTypeChoices(models.TextChoices):
    IDONEITY = 'IDONEITY', _('Idoneity')
    EM_IPCON = 'EM_IPCON', _('Employee Badge (IPCON)')
    EM_PROPENSIONES = 'EM_PROPENSIONES', _('Employee Badge (Propensiones)')


class DocumentCertificateTypeChoices(models.TextChoices):
    AEGIS = 'ASSET_AEGIS', _('Asset Certificate (AEGIS)')
    GENERIC = 'GENERIC', _('Generic Document')


class DeliveryMethod(models.TextChoices):
    DIGITAL = 'DIGITAL', _('Digital')
    PHYSICAL = 'PHYSICAL', _('Physical')
    BOTH = 'BOTH', _('Digital and Physical')
    NONE = 'NONE', _('Not delivered')


class CertificationStatusChoices(models.TextChoices):
    DRAFT = 'DRAFT', _('Draft (original uploaded, not certified)')
    CERTIFIED = 'CERTIFIED', _('Certified')
    REVOKED = 'REVOKED', _('Revoked')


class DocumentCopyKind(models.TextChoices):
    """Que archivo de los tres reconocio la verificacion por huella."""
    SOURCE = 'SOURCE', _('Original document without codes')
    CERTIFIED = 'CERTIFIED', _('Certified document with codes')
    PUBLIC_COPY = 'PUBLIC_COPY', _('Certified distributable digital copy')
    WATERMARK = 'WATERMARK', _('Distributable copy identified by its hidden watermark')


class UserVerificationModel(TimeStampedModel):
    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    public_uuid = models.CharField(
        _('Public UUID'),
        max_length=36,
        unique=True,
        blank=True,
        null=True
    )

    uuid_prefix = models.CharField(
        _('UUID Prefix'),
        max_length=8,
        editable=False,
        unique=True,
        blank=True,
        null=True
    )

    public_code = models.CharField(
        _('Public verification code'),
        max_length=4,
        unique=True,
        db_index=True,
        blank=True,
        null=True
    )

    user = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        verbose_name=_('User'),
        related_name='certificates_certificate_user',
        blank=True,
        null=True
    )

    employee_photo = models.ImageField(
        _('Employee photo'),
        upload_to='certificates/employee_photos/',
        blank=True,
        null=True
    )

    name = models.CharField(
        _('Names'),
        max_length=100,
        blank=True,
        null=True
    )

    last_name = models.CharField(
        _('Last name'),
        max_length=100,
        blank=True,
        null=True
    )

    document_number_cc = EncryptedCharField(
        _('Document number CC'),
        max_length=20,
        blank=True,
        null=True
    )

    document_number_pa = EncryptedCharField(
        _('Document number PA'),
        max_length=20,
        blank=True,
        null=True
    )

    passport_expiration_date = models.DateField(
        _('Passport expiration date'),
        blank=True,
        null=True
    )

    document_number_cc_hash = models.CharField(
        max_length=64,
        editable=False,
        blank=True,
        null=True
    )

    document_number_pa_hash = models.CharField(
        max_length=64,
        editable=False,
        blank=True,
        null=True
    )

    approved = models.BooleanField(
        _('Approved'),
        default=True,
    )

    approved_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        verbose_name=_('Approved by'),
        related_name='certificates_certificate_user_approvedby',
        blank=True,
        null=True
    )

    approval_date = models.DateField(
        _('Approval date'),
        blank=True,
        null=True
    )

    certificate_type = models.CharField(
        _('Certificate type'),
        max_length=100,
        choices=UserCertificateTypeChoices.choices,
    )

    issued_at = models.DateField(
        _('Issued at'),
        blank=True,
        null=True,
        help_text=_('Legal issuance date of the certificate')
    )

    expires_at = models.DateField(
        _('Expires at'),
        blank=True,
        null=True,
        db_index=True
    )

    revoked_at = models.DateTimeField(
        _('Revoked at'),
        blank=True,
        null=True
    )

    revocation_reason = models.TextField(
        _('Revocation reason'),
        blank=True,
        null=True
    )

    @property
    def is_revoked(self):
        return self.revoked_at is not None

    @property
    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now().date()

    @property
    def is_passport_expired(self):
        return self.passport_expiration_date and self.passport_expiration_date < timezone.now().date()

    @property
    def cc_masked(self):
        if self.document_number_cc:
            return masked_document_number(self.document_number_cc)
        return None

    @property
    def pa_masked(self):
        if self.document_number_pa:
            return masked_document_number(self.document_number_pa)
        return None

    @property
    def total_views(self) -> int:
        return self.view_logs.count()

    @property
    def unique_views(self) -> int:
        return (
            self.view_logs
            .values('user', 'anonymous_email')
            .distinct()
            .count()
        )

    def clean(self):
        errors = {}

        has_cc = bool(self.document_number_cc)
        has_pa = bool(self.document_number_pa)
        has_user = self.user is not None
        has_full_name = bool(self.name) and bool(self.last_name)

        if not has_user and not has_full_name:
            errors["name"] = _(
                "If no user is provided, both name and last name are required."
            )

        if not has_cc and not has_pa:
            errors["document_number_cc"] = _(
                "You must provide at least one document: CC or Passport."
            )

        if has_pa and not self.passport_expiration_date:
            errors["passport_expiration_date"] = _(
                "Passport expiration date is required when Passport is provided."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        if not self.public_code:
            self.public_code = generate_public_code(4)

        if self.user:
            self.name = self.user.first_name.upper().strip()
            self.last_name = self.user.last_name.upper().strip()
        else:
            self.name = self.name.upper().strip()
            self.last_name = self.last_name.upper().strip()

        if (self.user and self.certificate_type and self.certificate_type == UserCertificateTypeChoices.EM_IPCON):
            self.public_uuid = str(self.user.id)
            self.id = self.user.id

        if not self.public_uuid:
            self.public_uuid = str(uuid.uuid4())

        self.uuid_prefix = self.public_uuid[:8]

        if self.document_number_cc:
            normalized_cc = normalize_text(self.document_number_cc)
            self.document_number_cc = normalized_cc
            self.document_number_cc_hash = get_hmac(normalized_cc)
        else:
            self.document_number_cc_hash = None

        if self.document_number_pa:
            normalized_pa = normalize_text(self.document_number_pa)
            self.document_number_pa = normalized_pa
            self.document_number_pa_hash = get_hmac(normalized_pa)
        else:
            self.document_number_pa_hash = None

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} {self.last_name} [{self.public_code}]"

    class Meta:
        db_table = "apps_certificates_user_verification"
        verbose_name = _("User Verification")
        verbose_name_plural = _("User Verification")
        ordering = ["default_order", "-created"]
        constraints = [
            models.UniqueConstraint(
                fields=["document_number_cc_hash", "certificate_type"],
                name="uniq_cc_per_certificate_type"
            ),
            models.UniqueConstraint(
                fields=["document_number_pa_hash", "certificate_type"],
                name="uniq_pa_per_certificate_type"
            ),
        ]
        indexes = [
            models.Index(fields=["expires_at"]),
            models.Index(fields=["certificate_type"]),
            models.Index(fields=["approved"]),
        ]


class DocumentVerificationModel(TimeStampedModel):
    """
    Documento verificable publicamente.

    Un documento certificado existe en tres archivos:

    - ``source_file``      original recibido, sin codigos.
    - ``document_file``    original con el QR y el codigo de barras ya
                           incrustados: es el que hace fe y del que sale el
                           hash certificado.
    - ``public_copy_file`` copia distribuible, identica a la anterior a la
                           vista, con una marca de agua oculta y verificable.

    De cada uno se guardan dos huellas: la del archivo exacto (``*_hash``) y
    la del contenido renderizable (``*_content_hash``), que sobrevive a los
    cambios de metadatos habituales en el transporte por correo.
    """

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    document_title = models.CharField(
        _('Document title'),
        max_length=200
    )

    public_code = models.CharField(
        _('Public verification code'),
        max_length=32,
        unique=True,
        db_index=True,
        blank=True,
        null=True
    )

    uuid_prefix = models.CharField(
        _('UUID Prefix'),
        max_length=8,
        editable=False,
        unique=True,
        blank=True,
        null=True
    )

    certificate_type = models.CharField(
        _('Certificate type'),
        max_length=100,
        choices=DocumentCertificateTypeChoices.choices
    )

    certification_status = models.CharField(
        _('Certification status'),
        max_length=20,
        choices=CertificationStatusChoices.choices,
        default=CertificationStatusChoices.DRAFT,
        db_index=True
    )

    # M2M y no FK: un certificado puede pertenecer a varias personas a la vez
    # -- los integrantes de una organizacion, no solo quien lo tramito --, y
    # un FK unico obligaba a elegir uno y dejar al resto fuera. Quitar a un
    # titular es quitar su fila de la tabla intermedia: el certificado sigue
    # entero para los demas y **nunca ensancha el acceso** a nadie mas, que es
    # la misma razon por la que antes se usaba `SET_NULL` en vez de `CASCADE`
    # o `PROTECT`. Un fallo aqui tiene que dejar a alguien fuera, no dentro.
    holders = models.ManyToManyField(
        UserModel,
        verbose_name=_('Holders'),
        related_name='held_certificates',
        blank=True,
        help_text=_(
            'The users this certificate was issued for. They can see it in '
            'the code history, read-only: never the original file, the '
            'symbols or where they were stamped.'
        )
    )

    # ---------- Emisor externo ----------
    # Documentos que otra plataforma (p. ej. Propensiones Abogados) manda a
    # certificar por servidor (ver `external.py`). Van vacios en los
    # documentos propios de gea. `null` y no cadena vacia en los dos que entran
    # en la restriccion: NULL no choca con NULL en MySQL ni en SQLite, que es
    # lo que deja a los documentos propios fuera de la unicidad sin necesitar
    # una restriccion condicional (MySQL no las soporta).
    external_issuer = models.CharField(
        _('External issuer'),
        max_length=40,
        blank=True,
        null=True,
        db_index=True,
        editable=False,
        help_text=_(
            'Slug of the external platform that sent this document to be '
            'certified. Empty for documents issued by GEA itself.'
        )
    )

    external_reference = models.CharField(
        _('External reference'),
        max_length=200,
        blank=True,
        default='',
        editable=False,
        help_text=_('Identifier of the case or record in the external platform.')
    )

    external_idempotency_key = models.CharField(
        _('External idempotency key'),
        max_length=128,
        blank=True,
        null=True,
        editable=False
    )

    revoked_at = models.DateTimeField(
        _('Revoked at'),
        blank=True,
        null=True,
        editable=False
    )

    revocation_reason = models.TextField(
        _('Revocation reason'),
        blank=True,
        default='',
        editable=False
    )

    stamp_layout = models.ForeignKey(
        'code_gen.StampLayoutModel',
        on_delete=models.SET_NULL,
        verbose_name=_('Stamp layout'),
        related_name='documents',
        blank=True,
        null=True,
        help_text=_(
            'Where the QR and the barcode are placed inside the PDF. '
            'Leave empty to use the default layout.'
        )
    )

    # ---------- 1. Original sin codigos ----------
    source_file = models.FileField(
        _('Original document (without codes)'),
        upload_to='certificates/documents/source/',
        blank=True,
        null=True
    )

    source_hash = models.CharField(
        _('Original file hash'),
        max_length=64,
        blank=True,
        db_index=True,
        default=''
    )

    source_content_hash = models.CharField(
        _('Original content hash'),
        max_length=64,
        blank=True,
        db_index=True,
        default=''
    )

    # ---------- 2. Certificado con codigos ----------
    document_file = models.FileField(
        _('Certified document (with codes)'),
        upload_to='certificates/documents/',
        blank=True,
        null=True
    )

    document_hash = models.CharField(
        _('Certified file hash'),
        max_length=64,
        blank=True,
        db_index=True,
        editable=False
    )

    certified_content_hash = models.CharField(
        _('Certified content hash'),
        max_length=64,
        blank=True,
        db_index=True,
        default=''
    )

    # ---------- 3. Copia publica distribuible ----------
    public_copy_file = models.FileField(
        _('Distributable digital copy'),
        upload_to='certificates/documents/public/',
        blank=True,
        null=True
    )

    public_copy_hash = models.CharField(
        _('Distributable copy hash'),
        max_length=64,
        blank=True,
        db_index=True,
        default=''
    )

    public_copy_content_hash = models.CharField(
        _('Distributable copy content hash'),
        max_length=64,
        blank=True,
        db_index=True,
        default=''
    )

    watermark_token = models.CharField(
        _('Watermark token'),
        max_length=128,
        blank=True,
        default='',
        editable=False
    )

    # ---------- Codigo emitido ----------
    code_payload = models.TextField(
        _('Code payload'),
        blank=True,
        default=''
    )

    code_initials = models.CharField(
        _('Certificate initials'),
        max_length=20,
        blank=True,
        default=''
    )

    code_sequence = models.CharField(
        _('Autonomous sequence'),
        max_length=20,
        blank=True,
        default='',
        db_index=True
    )

    code_hash_fragment = models.CharField(
        _('Hash fragment in the code'),
        max_length=64,
        blank=True,
        default=''
    )

    qr_payload = models.TextField(
        _('QR payload'),
        blank=True,
        default=''
    )

    certified_at = models.DateTimeField(
        _('Certified at'),
        blank=True,
        null=True
    )

    delivery_method = models.CharField(
        _('Delivery method'),
        max_length=10,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.NONE
    )

    sent_at = models.DateTimeField(
        _('Sent at'),
        blank=True,
        null=True
    )

    issued_at = models.DateField(
        _('Issued at')
    )

    expires_at = models.DateField(
        _('Expires at'),
        blank=True,
        null=True
    )

    @property
    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now().date()

    @property
    def is_certified(self) -> bool:
        return self.certification_status == CertificationStatusChoices.CERTIFIED

    @property
    def total_views(self) -> int:
        return self.view_logs.count()

    @property
    def unique_views(self) -> int:
        return (
            self.view_logs
            .values('user', 'anonymous_email')
            .distinct()
            .count()
        )

    def known_hashes(self) -> dict:
        """Mapa huella -> tipo de copia, para la verificacion por archivo."""
        return {
            self.source_hash: DocumentCopyKind.SOURCE,
            self.document_hash: DocumentCopyKind.CERTIFIED,
            self.public_copy_hash: DocumentCopyKind.PUBLIC_COPY,
        }

    def __str__(self):
        return f"{self.document_title} [{self.public_code}]"

    def save(self, *args, **kwargs):
        if not self.public_code:
            self.public_code = generate_unique_public_code(
                type(self),
                length=DOCUMENT_PUBLIC_CODE_LENGTH
            )

        self.uuid_prefix = str(self.id)[:8]

        if self.document_file and not self.document_hash:
            from .functions import get_file_hash
            self.document_hash = get_file_hash(self.document_file)

        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_certificates_document_verification'
        verbose_name = _("Document Verification")
        verbose_name_plural = _("Document Verification")
        ordering = ["default_order", "-created"]
        indexes = [
            models.Index(fields=['public_code']),
            models.Index(fields=['uuid_prefix']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['certification_status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['external_issuer', 'external_idempotency_key'],
                name='uniq_document_external_idempotency',
            ),
        ]


class CertificateViewLogModel(TimeStampedModel):
    """
    Traza cada visualización de un certificado o documento verificable.
    Permite diferenciar entre usuarios autenticados y anónimos.
    """

    certificate_user = models.ForeignKey(
        UserVerificationModel,
        on_delete=models.CASCADE,
        related_name='view_logs',
        verbose_name=_('User Certificate'),
        blank=True,
        null=True
    )

    document_verification = models.ForeignKey(
        DocumentVerificationModel,
        on_delete=models.CASCADE,
        related_name='view_logs',
        verbose_name=_('Document Verification'),
        blank=True,
        null=True
    )

    user = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name='certificate_views',
        verbose_name=_('Authenticated user'),
        blank=True,
        null=True
    )

    anonymous_email = models.EmailField(
        _('Anonymous email'),
        blank=True,
        null=True
    )

    ip_address = models.GenericIPAddressField(
        _('IP address'),
        blank=True,
        null=True
    )

    user_agent = models.TextField(
        _('User agent'),
        blank=True,
        null=True
    )

    viewed_at = models.DateTimeField(
        _('Viewed at'),
        default=timezone.now
    )

    def clean(self):
        errors = {}

        if not self.certificate_user and not self.document_verification:
            errors['certificate_user'] = _(
                'You must relate the view to a certificate or a document.'
            )

        if self.document_verification and not self.user and not self.anonymous_email:
            errors['anonymous_email'] = _(
                'Anonymous view require an email address.'
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        target = self.certificate_user or self.document_verification
        return f"View of {target} at {self.viewed_at} IP {self.ip_address}"

    class Meta:
        db_table = 'apps_certificates_view_log'
        verbose_name = _('Certificate View Log')
        verbose_name_plural = _('Certificate View Logs')
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['certificate_user']),
            models.Index(fields=['document_verification']),
            models.Index(fields=['user']),
            models.Index(fields=['anonymous_email']),
            models.Index(fields=['viewed_at']),
        ]


auditlog.register(
    DocumentVerificationModel,
    serialize_data=True
)

auditlog.register(
    UserVerificationModel,
    serialize_data=True
)


class SummaryStatusChoices(models.TextChoices):
    DRAFT = 'DRAFT', _('Draft (members selected, not sealed)')
    SEALED = 'SEALED', _('Sealed (master hash computed)')
    CERTIFIED = 'CERTIFIED', _('Certified (summary document issued)')


class AegisSummaryModel(TimeStampedModel):
    """
    Documento maestro que integra varios certificados de un mismo resumen.

    El resumen (AEGIS-6) no es un certificado mas: es el que los ata. Lleva
    estampado el codigo de barras de cada uno de sus miembros, su propio par
    QR/barcode, y el QR del anclaje temporal.

    **La circularidad de siempre**: el master hash cubre a los miembros, nunca
    a si mismo. Se sella primero (`seal()`), luego se genera el documento del
    resumen llevando ese hash dentro, y solo despues se registra la huella del
    propio resumen. Igual que el codigo de barras y el hash del original.
    """

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        primary_key=True,
        editable=False
    )

    title = models.CharField(
        _('Summary title'),
        max_length=200
    )

    public_code = models.CharField(
        _('Public verification code'),
        max_length=32,
        unique=True,
        db_index=True,
        blank=True,
        null=True
    )

    uuid_prefix = models.CharField(
        _('UUID Prefix'),
        max_length=8,
        editable=False,
        unique=True,
        blank=True,
        null=True
    )

    # ---------- Activo al que pertenece el resumen ----------
    asset = models.ForeignKey(
        'assets.AssetModel',
        on_delete=models.SET_NULL,
        verbose_name=_('Asset'),
        related_name='aegis_summaries',
        blank=True,
        null=True,
        help_text=_('The asset this summary of certificates belongs to.')
    )

    asset_label = models.CharField(
        _('Asset label'),
        max_length=200,
        blank=True,
        default='',
        help_text=_(
            'Human readable name of the asset. Only a label: the binding is '
            'made through the asset UUID.'
        )
    )

    # ---------- Miembros ----------
    documents = models.ManyToManyField(
        DocumentVerificationModel,
        through='AegisSummaryDocumentModel',
        related_name='aegis_summaries',
        verbose_name=_('Documents')
    )

    # ---------- Sello ----------
    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=SummaryStatusChoices.choices,
        default=SummaryStatusChoices.DRAFT,
        db_index=True
    )

    canonical_payload = models.TextField(
        _('Canonical payload'),
        blank=True,
        default='',
        help_text=_(
            'The exact bytes the master hash was computed over (JCS/RFC8785). '
            'Stored verbatim so anyone can recompute it.'
        )
    )

    master_hash = models.CharField(
        _('Master hash'),
        max_length=64,
        blank=True,
        default='',
        db_index=True
    )

    sealed_at = models.DateTimeField(
        _('Sealed at'),
        blank=True,
        null=True
    )

    # ---------- El documento del resumen (AEGIS-6) ----------
    summary_document = models.OneToOneField(
        DocumentVerificationModel,
        on_delete=models.SET_NULL,
        verbose_name=_('Summary document'),
        related_name='summary_of',
        blank=True,
        null=True,
        help_text=_(
            'The certified PDF that carries the master hash and the barcodes '
            'of every member. Issued after sealing, never part of the hash.'
        )
    )

    issued_at = models.DateField(
        _('Issued at'),
        blank=True,
        null=True
    )

    @property
    def is_sealed(self) -> bool:
        return bool(self.master_hash)

    @property
    def member_count(self) -> int:
        return self.members.count()

    def ordered_members(self):
        return self.members.select_related('document').order_by(
            'default_order', 'code'
        )

    def __str__(self) -> str:
        return f'{self.title} [{self.public_code or self.uuid_prefix}]'

    def save(self, *args, **kwargs):
        if not self.public_code:
            self.public_code = generate_unique_public_code(
                type(self),
                length=DOCUMENT_PUBLIC_CODE_LENGTH
            )

        self.uuid_prefix = str(self.id)[:8]

        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_certificates_aegis_summary'
        verbose_name = _('AEGIS Summary')
        verbose_name_plural = _('AEGIS Summaries')
        ordering = ['default_order', '-created']
        indexes = [
            models.Index(fields=['public_code']),
            models.Index(fields=['uuid_prefix']),
            models.Index(fields=['master_hash']),
        ]


class AegisSummaryDocumentModel(TimeStampedModel):
    """
    Un certificado dentro de un resumen, con el codigo que le toca en el resumen.
    """

    summary = models.ForeignKey(
        AegisSummaryModel,
        on_delete=models.CASCADE,
        related_name='members',
        verbose_name=_('Summary')
    )

    document = models.ForeignKey(
        DocumentVerificationModel,
        on_delete=models.PROTECT,
        related_name='summary_memberships',
        verbose_name=_('Document')
    )

    code = models.CharField(
        _('Code in the summary'),
        max_length=30,
        help_text=_('For example AEGIS-1, AEGIS-2…')
    )

    document_type_label = models.CharField(
        _('Document type'),
        max_length=200,
        blank=True,
        default='',
        help_text=_('As it appears in the master payload.')
    )

    def clean(self):
        errors = {}

        if self.document_id and not self.document.is_certified:
            errors['document'] = _(
                'Only certified documents can be part of a summary: an '
                'uncertified one has no fingerprint to include.'
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f'{self.code} · {self.document}'

    class Meta:
        db_table = 'apps_certificates_aegis_summary_document'
        verbose_name = _('Summary member')
        verbose_name_plural = _('Summary members')
        ordering = ['default_order', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['summary', 'document'],
                name='uniq_document_per_summary'
            ),
            models.UniqueConstraint(
                fields=['summary', 'code'],
                name='uniq_code_per_summary'
            ),
        ]


auditlog.register(AegisSummaryModel, serialize_data=True)


# ==========================================================
# Emisores externos
# ==========================================================

class ExternalIssuerKindChoices(models.TextChoices):
    GROUP = 'GROUP', _('Corporate group company')
    THIRD_PARTY = 'THIRD_PARTY', _('Third party')


#: Un host por linea: nombre de dominio, sin puerto, esquema, ruta ni
#: credenciales; lo que no encaje aqui nunca coincidiria con un
#: ``urlparse(...).hostname``, y aceptarlo en silencio dejaria la lista
#: pareciendo mas amplia (o mas estrecha) de lo que es.
_HOST_LINE = re.compile(r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$')

#: Hash que no corresponde a ninguna clave: con lo que se compara cuando el
#: emisor no tiene clave, para que comparar cueste lo mismo que con una.
NO_KEY_HASH = '0' * 64

MAX_ISSUER_LOGO_BYTES = 1024 * 1024


def hash_issuer_key(raw: str) -> str:
    """
    HMAC-SHA256 de una clave de emisor con ``SECRET_KEY``.

    Es el mismo mecanismo que el de los numeros de documento y los OTP
    (invariante 4): la base de datos nunca guarda la clave, solo algo que no
    sirve para presentarla. El prefijo es de dominio: el mismo texto como
    clave de emisor y como numero de documento no produce el mismo hash.
    """
    return hmac.new(
        key=settings.SECRET_KEY.encode('utf-8'),
        msg=b'external-issuer-key:' + str(raw).encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()


def validate_issuer_logo_size(file):
    if file and file.size > MAX_ISSUER_LOGO_BYTES:
        raise ValidationError(
            _('The logo is too large (1 MB at most).'), code='too_large')


class ExternalIssuerModel(TimeStampedModel):
    """
    Una plataforma que certifica documentos por servidor
    (``/api/certificates/external/``).

    Antes los emisores estaban en ``settings.GEA_EXTERNAL_ISSUERS`` y solo
    existia uno. Ahora son filas, para poder dar de alta a una empresa del
    grupo o a un tercero desde el admin sin tocar el codigo ni desplegar.

    **La clave nunca se guarda.** Se guarda ``key_hash`` (HMAC con
    ``SECRET_KEY``) y ``key_hint``, los cuatro ultimos caracteres, para
    reconocerla en el listado. La unica excepcion de diseno es
    ``uses_server_key``: Propensiones comparte su clave con pag y Vercel
    (``SERVER_KEY``) y esa vive en el entorno, no aqui.

    Los documentos se asocian al emisor por el slug que llevan en
    ``DocumentVerificationModel.external_issuer`` --no hay clave ajena--, de
    ahi que el slug no pueda cambiar si ya hay documentos con el.
    """

    id = models.UUIDField(
        'ID', default=uuid.uuid4, primary_key=True, editable=False)

    slug = models.SlugField(
        _('Slug'),
        max_length=40,
        unique=True,
        help_text=_(
            'What the issuer sends as "issuer" or in the X-Issuer header. It '
            'cannot be changed once documents have been issued with it.'
        ),
    )

    name = models.CharField(_('Name'), max_length=120)

    kind = models.CharField(
        _('Kind'),
        max_length=20,
        choices=ExternalIssuerKindChoices.choices,
        default=ExternalIssuerKindChoices.THIRD_PARTY,
    )

    contact_email = models.EmailField(_('Contact email'), blank=True)

    key_hash = models.CharField(
        _('Key hash'), max_length=64, blank=True, editable=False)

    key_hint = models.CharField(
        _('Key ends in'), max_length=4, blank=True, editable=False)

    key_rotated_at = models.DateTimeField(
        _('Key set at'), null=True, blank=True, editable=False)

    uses_server_key = models.BooleanField(
        _('Uses the environment key (SERVER_KEY)'),
        default=False,
        help_text=_(
            'The key is the SERVER_KEY of the environment, shared with other '
            'platforms, instead of one stored here. It is not generated or '
            'changed from the admin.'
        ),
    )

    issue_limit_per_hour = models.PositiveIntegerField(
        _('Documents it can issue per hour'),
        default=60,
        validators=[MinValueValidator(1)],
    )

    access_limit_per_hour = models.PositiveIntegerField(
        _('Downloads and revocations per hour'),
        default=300,
        validators=[MinValueValidator(1)],
    )

    allowed_qr_hosts = models.TextField(
        _('Allowed hosts for the QR'),
        blank=True,
        help_text=_(
            'One host per line (for example verify.example.com). Empty: any '
            'https URL. Otherwise the QR can only point to these hosts.'
        ),
    )

    qr_logo = models.ImageField(
        _('QR logo'),
        upload_to='code_gen/issuers/',
        blank=True,
        validators=[validate_issuer_logo_size],
        help_text=_(
            'Printed in the centre of the QR. Empty: the GEA logo.'),
    )

    default_certificate_type = models.CharField(
        _('Certificate type'),
        max_length=100,
        choices=DocumentCertificateTypeChoices.choices,
        default=DocumentCertificateTypeChoices.GENERIC,
    )

    notes = models.TextField(_('Notes'), blank=True)

    # ---------- clave ----------

    def set_key(self, raw: str) -> None:
        """Guarda el hash de una clave nueva. No guarda el modelo."""
        raw = str(raw or '')

        if len(raw) < MIN_ISSUER_KEY_LENGTH:
            raise ValidationError(
                _('The key must have at least %(min)s characters.'),
                params={'min': MIN_ISSUER_KEY_LENGTH},
                code='key_too_short',
            )

        self.key_hash = hash_issuer_key(raw)
        self.key_hint = raw[-4:]
        self.key_rotated_at = timezone.now()

    @property
    def has_key(self) -> bool:
        if self.uses_server_key:
            return bool(getattr(settings, 'SERVER_KEY', ''))

        return bool(self.key_hash)

    def check_key(self, given: str) -> bool:
        """
        Si la clave presentada es la de este emisor.

        Calcula siempre el HMAC y compara siempre, tenga clave o no, para que
        el tiempo no diga cual de los casos fue. Se compara hash con hash: asi
        la longitud de la clave del entorno tampoco se filtra por el tiempo.
        """
        presented = hash_issuer_key(given or '')

        if self.uses_server_key:
            server_key = getattr(settings, 'SERVER_KEY', '') or ''
            expected = hash_issuer_key(server_key) if server_key else ''
        else:
            expected = self.key_hash or ''

        matches = hmac.compare_digest(
            presented.encode('ascii'),
            (expected or NO_KEY_HASH).encode('ascii'),
        )

        return bool(self.is_active and expected and matches)

    # ---------- QR ----------

    @property
    def qr_hosts(self) -> list:
        return [
            line.strip().lower()
            for line in (self.allowed_qr_hosts or '').splitlines()
            if line.strip()
        ]

    # ---------- validacion ----------

    def documents_issued(self) -> int:
        return DocumentVerificationModel.objects.filter(
            external_issuer=self.slug).count()

    def _check_slug_can_change(self):
        if not self.pk:
            return

        previous = type(self).objects.filter(pk=self.pk).values_list(
            'slug', flat=True).first()

        if previous and previous != self.slug and (
            DocumentVerificationModel.objects.filter(
                external_issuer=previous).exists()
        ):
            raise ValidationError({
                'slug': _(
                    'There are documents issued with "%(slug)s": the slug '
                    'cannot change or they would be left without an issuer.'
                ) % {'slug': previous}
            })

    def clean(self):
        super().clean()

        self._check_slug_can_change()

        for line in (self.allowed_qr_hosts or '').splitlines():
            host = line.strip().lower()

            if host and not _HOST_LINE.match(host):
                raise ValidationError({
                    'allowed_qr_hosts': _(
                        '"%(host)s" is not a host name. Write only the host, '
                        'without https:// or a path.'
                    ) % {'host': line.strip()}
                })

    def save(self, *args, **kwargs):
        # Fuera de `clean()` tambien: un guardado directo no pasa por los
        # formularios, y cambiar el slug deja documentos huerfanos.
        self._check_slug_can_change()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} [{self.slug}]'

    class Meta:
        db_table = 'apps_certificates_external_issuer'
        verbose_name = _('External issuer')
        verbose_name_plural = _('External issuers')
        ordering = ['name']


# Sin `key_hash` en el historial: es lo unico que permite comprobar una clave,
# y el historial lo lee cualquiera con acceso al admin.
auditlog.register(ExternalIssuerModel, exclude_fields=['key_hash'])
