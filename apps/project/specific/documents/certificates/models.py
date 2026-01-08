import hashlib
import secrets
import uuid

from apps.common.utils.models import TimeStampedModel
from apps.project.common.users.models import UserModel
from auditlog.registry import auditlog
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import EncryptedCharField


class CertificateTypesModel(TimeStampedModel):
    class CertificateTypeChoices(models.TextChoices):
        AEGIS = 'ASSET_AEGIS', _('Asset Certificate (AEGIS)')
        IDONEITY = 'IDONEITY', _('Idoneity')
        EMPLOYEE_VERIFICATION_IPCON = 'EMPLOYEE_VERIFICATION_IPCON',
        _('Employee ID Verification (IPCON)')
        EMPLOYEE_VERIFICATION_PROPENSIONES = 'EMPLOYEE_VERIFICATION_PROPENSIONES',
        _('Employee ID Verification (Propensiones)')

    name = models.CharField(
        _('Name'),
        max_length=100,
        choices=CertificateTypeChoices.choices,
    )

    def __str__(self):
        return self.name

    class Meta:
        db_table = "apps_certificates_certificate_types"
        verbose_name = _("Certificate Type")
        verbose_name_plural = _("Certificate Types")
        ordering = ["default_order", "-created"]


class CertificateUserModel(TimeStampedModel):
    class DocumentTypeChoices(models.TextChoices):
        CC = 'CC', _('Citizen ID (CC)')
        PA = 'PA', _('Passport (PA)')
        UNIQUE_CODE = 'UNIQUE_CODE', _('Unique Code')

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        unique=True,
        primary_key=True,
        serialize=False,
        editable=False
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

    document_type = models.CharField(
        _('Document type'),
        max_length=15,
        choices=DocumentTypeChoices.choices,
        default=DocumentTypeChoices.CC
    )

    document_number = EncryptedCharField(
        _('Document number'),
        max_length=20,
    )

    document_number_hash = models.CharField(
        max_length=64,
        editable=False,
        default='',
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

    certificate_type = models.ForeignKey(
        CertificateTypesModel,
        on_delete=models.SET_NULL,
        verbose_name=_('Certificate type'),
        related_name='certificates_certificate_certificate_type',
        blank=True,
        null=True,
        default=CertificateTypesModel.CertificateTypeChoices.AEGIS
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

    is_revoked = models.BooleanField(
        _('Is revoked'),
        default=False
    )

    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now().date()

    def masked_document_number(self):
        """Returns the ID number with all but the last four digits masked."""
        document_number_str = str(self.document_number)
        last_four = document_number_str[-4:]
        masked = '*' * (len(document_number_str) - 4) + last_four
        return masked

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.upper()

        if self.last_name:
            self.last_name = self.last_name.upper()

        if self.user and not self.name:
            self.name = self.user.first_name.upper()

        if self.user and not self.last_name:
            self.last_name = self.user.last_name.upper()

        self.document_number_hash = hashlib.sha256(
            self.document_number.encode()
        ).hexdigest()

        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} {self.masked_document_number()}'

    class Meta:
        db_table = "apps_certificates_user_verification"
        verbose_name = _("User Verification")
        verbose_name_plural = _("User Verification")
        ordering = ["default_order", "-created"]
        unique_together = [
            'document_number',
            'document_type',
            'certificate_type'
        ]


class DocumentVerificationModel(TimeStampedModel):
    class DeliveryMethod(models.TextChoices):
        DIGITAL = 'DIGITAL', _('Digital')
        PHYSICAL = 'PHYSICAL', _('Physical')
        NONE = 'NONE', _('Not delivered')

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    public_code = models.CharField(
        _('Public verification code'),
        max_length=16,
        unique=True
    )

    uuid_prefix = models.CharField(
        max_length=8,
        editable=False,
        unique=True
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

    daily_validation_enabled = models.BooleanField(
        default=False
    )

    daily_validation_token = models.CharField(
        max_length=64,
        blank=True,
        null=True
    )

    daily_validation_date = models.DateField(
        blank=True,
        null=True
    )

    def generate_daily_token(self):
        self.daily_validation_token = secrets.token_urlsafe(32)
        self.daily_validation_date = timezone.now().date()

    def is_daily_token_valid(self):
        return (
            self.daily_validation_enabled and
            self.daily_validation_date == timezone.now().date()
        )

    def is_expired(self):
        return self.expires_at and self.expires_at < timezone.now().date()

    def save(self, *args, **kwargs):
        if not self.public_code:
            self.public_code = secrets.token_hex(6).upper()

        self.uuid_prefix = str(self.id).partition('-')[0]

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


auditlog.register(
    CertificateUserModel,
    serialize_data=True
)

auditlog.register(
    DocumentVerificationModel,
    serialize_data=True
)
