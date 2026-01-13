import secrets
import uuid

from auditlog.registry import auditlog
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import EncryptedCharField

from apps.common.utils.models import TimeStampedModel
from apps.project.common.users.models import UserModel

from .functions import (generate_public_code, get_hmac, masked_document_number,
                        normalize_text)


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
    NONE = 'NONE', _('Not delivered')


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
        max_length=4,
        unique=True,
        db_index=True,
        blank=True,
        null=True
    )

    uuid_prefix = models.CharField(
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

    document_file = models.FileField(
        _('Document file'),
        upload_to='certificates/documents/',
        blank=True,
        null=True
    )

    document_hash = models.CharField(
        max_length=64,
        blank=True,
        editable=False
    )

    delivery_method = models.CharField(
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
        
    def __str__(self):
        return f"{self.document_title} [{self.public_code}]"

    def save(self, *args, **kwargs):
        if not self.public_code:
            self.public_code = generate_public_code(4)

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
