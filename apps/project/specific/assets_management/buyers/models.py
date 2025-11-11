# apps.project.specific.assets_management.buyers.models.py
import logging
import os
import uuid
from datetime import date

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import pre_save, post_delete
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions import sha256_hex
from apps.common.utils.models import TimeStampedModel
from apps.project.specific.assets_management.assets.models import AssetModel
from apps.project.specific.assets_management.assets_location.models import \
    AssetCountryModel

from .signals import (auto_delete_and_optimize_offer_img_on_change,
                      auto_delete_offer_img_on_delete,
                      auto_fill_offer_translation)

logger = logging.getLogger(__name__)

UserModel = get_user_model()


class OfferModel(TimeStampedModel):
    def offer_image_upload_path(instance, filename) -> str:
        """
        Generate a file path for an asset image.
        Path format: offer/{slugified_name}/img/YYYY/MM/DD/{hashed_filename}.{extension}
        """
        try:
            name_src = (
                getattr(instance.asset.asset_name, "es_name", None)
                or getattr(instance.asset.asset_name, "en_name", "")
                or "asset"
            )
            slug = slugify(name_src)[:40] or "asset"
            base, ext = os.path.splitext(filename)
            hashed = sha256_hex(base)[:10]
            return os.path.join(
                "offer", slug, "img",
                str(date.today().year),
                str(date.today().month),
                str(date.today().day),
                f"{hashed}{ext.lower()}"
            )
        except Exception as e:
            logger.error(f"Error generating file path for {filename}: {e}")
            raise e

    class QuantityTypeChoices(models.TextChoices):
        UNITS = "U", _("Units")
        BOXES = "B", _("Boxes")

    class StatusChoices(models.TextChoices):
        # Pre-approval
        UNDER_REVIEW = "UNDER_REVIEW",          _("Under review")
        PENDING_APPROVAL = "PENDING_APPROVAL",      _("Pending for Approval")
        NOT_APPROVED = "NOT_APPROVED",          _("NOT Approved")
        APPROVED = "APPROVED",              _("Approved")
        # Secuencia posterior
        SO_CREATED = "SO_CREATED",            _("Service Order Created")
        SO_SENT = "SO_SENT",               _("Service Order Sent")
        PAY_CREATED = "PAY_CREATED",           _("Payment Order Created")
        PAY_SENT = "PAY_SENT",              _("Payment Order Sent")
        POSSESSION = "POSSESSION",            _("Asset In Possession")
        ASSET_SENT = "ASSET_SENT",            _("Asset Sent")
        PROFIT_CREATED = "PROFIT_CREATED",        _("Profitability Created")
        PROFIT_PAID = "PROFIT_PAID",           _("Profitability Paid")
        COMPLETED = "COMPLETED",             _("Completed")

    class OfferTypeChoices(models.TextChoices):
        OFFICIAL_PURCHASE_USA = "O", _(
            "Official purchase of the United States")

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        unique=True,
        primary_key=True,
        serialize=False,
        editable=False
    )

    created_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="buyers_offer_user",
        verbose_name=_("Created By"),
        null=True
    )

    asset = models.ForeignKey(
        AssetModel,
        on_delete=models.CASCADE,
        related_name="buyers_offer_asset",
        verbose_name=_("Asset")
    )

    offer_type = models.CharField(
        _("Purchase order Type"),
        max_length=255,
        choices=OfferTypeChoices.choices,
        default=OfferTypeChoices.OFFICIAL_PURCHASE_USA
    )

    quantity_type = models.CharField(
        _("quantity type"),
        max_length=255,
        choices=QuantityTypeChoices.choices,
        default=QuantityTypeChoices.BOXES
    )

    offer_quantity = models.PositiveIntegerField(
        _("Quantity needed"),
        default=0
    )

    en_observation = models.TextField(
        _("Observation (EN)"),
        blank=True, null=True
    )

    es_observation = models.TextField(
        _("Observation (ES)"),
        blank=True, null=True
    )

    en_description = models.TextField(
        _("Description (EN)"),
        blank=True, null=True
    )

    es_description = models.TextField(
        _("Description (ES)"),
        blank=True, null=True
    )

    buyer_country = models.ForeignKey(
        AssetCountryModel,
        on_delete=models.CASCADE,
        related_name="buyers_offer_country",
        verbose_name=_("Country"),
        null=True
    )

    display = models.BooleanField(
        _("Display"),
        default=True
    )

    # Image
    offer_img = models.ImageField(
        "img",
        max_length=255,
        upload_to=offer_image_upload_path,
        blank=True,
        null=True
    )

    # Purchase order approval

    is_approved = models.BooleanField(
        _("Approved"),
        default=False
    )

    approved_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="buyers_offer_approved_by_user",
        verbose_name=_("Approved By"),
        null=True,
        blank=True
    )

    approved_by_timestamp = models.DateTimeField(
        verbose_name=_("Approved By Timestamp"),
        null=True,
        blank=True
    )

    # Purchase order review

    reviewed = models.BooleanField(
        _("Reviewed"),
        default=False
    )

    reviewed_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="buyers_offer_reviewed_by_user",
        verbose_name=_("Reviewed By"),
        null=True,
        blank=True
    )

    reviewed_by_timestamp = models.DateTimeField(
        verbose_name=_("Reviewed By Timestamp"),
        null=True,
        blank=True
    )

    # Service Order
    service_order_created_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_service_order_created_by",
        verbose_name=_("Service Order Created By"),
        null=True, blank=True
    )

    service_order_created_at = models.DateTimeField(
        _("Service Order Created At"), null=True, blank=True
    )

    service_order_sent_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_service_order_sent_by",
        verbose_name=_("Service Order Sent By"),
        null=True, blank=True
    )

    service_order_sent_at = models.DateTimeField(
        _("Service Order Sent At"), null=True, blank=True
    )

    # Payment Order
    payment_order_created_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_payment_order_created_by",
        verbose_name=_("Payment Order Created By"),
        null=True, blank=True
    )

    payment_order_created_at = models.DateTimeField(
        _("Payment Order Created At"), null=True, blank=True
    )

    payment_order_sent_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_payment_order_sent_by",
        verbose_name=_("Payment Order Sent By"),
        null=True, blank=True
    )

    payment_order_sent_at = models.DateTimeField(
        _("Payment Order Sent At"), null=True, blank=True
    )

    # Asset movement
    asset_in_possession_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_asset_in_possession_by",
        verbose_name=_("Asset In Possession By"),
        null=True, blank=True
    )

    asset_in_possession_at = models.DateTimeField(
        _("Asset In Possession At"), null=True, blank=True
    )

    asset_sent_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_asset_sent_by",
        verbose_name=_("Asset Sent By"),
        null=True, blank=True
    )

    asset_sent_at = models.DateTimeField(
        _("Asset Sent At"), null=True, blank=True
    )

    # Profitability
    profitability_created_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_profitability_created_by",
        verbose_name=_("Profitability Created By"),
        null=True, blank=True
    )

    profitability_created_at = models.DateTimeField(
        _("Profitability Created At"), null=True, blank=True
    )

    profitability_paid_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        related_name="buyers_offer_profitability_paid_by",
        verbose_name=_("Profitability Paid By"),
        null=True, blank=True
    )

    profitability_paid_at = models.DateTimeField(
        _("Profitability Paid At"), null=True, blank=True
    )

    # ===== Profitability: subpagos =====
    recovery_repatriation_foundation_paid = models.BooleanField(
        default=False
    )

    recovery_repatriation_foundation_mark_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buyers_offer_rrf_paid_by"
    )

    recovery_repatriation_foundation_mark_at = models.DateTimeField(
        null=True,
        blank=True
    )

    am_pro_service_paid = models.BooleanField(
        default=False
    )

    am_pro_service_mark_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buyers_offer_ampro_paid_by"
    )

    am_pro_service_mark_at = models.DateTimeField(
        null=True,
        blank=True
    )

    propensiones_paid = models.BooleanField(
        default=False
    )

    propensiones_mark_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="buyers_offer_prop_paid_by"
    )

    propensiones_mark_at = models.DateTimeField(
        null=True,
        blank=True
    )

    @property
    def asset_display_name(self):
        lang = get_language()
        if lang == "es" and self.asset.asset_name.es_name:
            return self.asset.asset_name.es_name
        return self.asset.asset_name.en_name or self.asset.asset_name.es_name

    @property
    def profitability_all_paid(self) -> bool:
        return (
            self.recovery_repatriation_foundation_paid and
            self.am_pro_service_paid and
            self.propensiones_paid
        )

    @property
    def status_code(self) -> str:
        # Del más avanzado al más básico
        if self.profitability_paid_at and self.profitability_all_paid:
            return self.StatusChoices.PROFIT_PAID

        if self.profitability_created_at:
            return self.StatusChoices.PROFIT_CREATED

        if self.asset_sent_at:
            return self.StatusChoices.ASSET_SENT

        if self.asset_in_possession_at:
            return self.StatusChoices.POSSESSION

        if self.payment_order_sent_at:
            return self.StatusChoices.PAY_SENT

        if self.payment_order_created_at:
            return self.StatusChoices.PAY_CREATED

        if self.service_order_sent_at:
            return self.StatusChoices.SO_SENT

        if self.service_order_created_at:
            return self.StatusChoices.SO_CREATED

        if self.is_approved and self.reviewed:
            return self.StatusChoices.APPROVED

        if (not self.is_approved) and self.reviewed:
            return self.StatusChoices.NOT_APPROVED

        if (not self.is_approved) and (not self.reviewed) and self.is_active:
            return self.StatusChoices.PENDING_APPROVAL

        return self.StatusChoices.UNDER_REVIEW

    @property
    def status_label(self) -> str:
        return self.StatusChoices(self.status_code).label

    @property
    def status_icon(self) -> str:
        mapping = {
            # Pre-approval (tus íconos/colores originales)
            self.StatusChoices.PENDING_APPROVAL: "fa-regular fa-circle-xmark",
            self.StatusChoices.APPROVED:         "fa-solid fa-check-double",
            self.StatusChoices.NOT_APPROVED:     "fa-regular fa-circle-xmark",
            self.StatusChoices.UNDER_REVIEW:     "fa-regular fa-circle-xmark",
            # Post-approval (elige los que prefieras)
            self.StatusChoices.SO_CREATED:       "fa-solid fa-paperclip",
            self.StatusChoices.SO_SENT:          "fa-solid fa-paper-plane",
            self.StatusChoices.PAY_CREATED:      "fa-solid fa-file-invoice-dollar",
            self.StatusChoices.PAY_SENT:         "fa-solid fa-paper-plane",
            self.StatusChoices.POSSESSION:       "fa-solid fa-box-open",
            self.StatusChoices.ASSET_SENT:       "fa-solid fa-truck-fast",
            self.StatusChoices.PROFIT_CREATED:   "fa-solid fa-chart-line",
            # o "fa-solid fa-circle-check"
            self.StatusChoices.PROFIT_PAID:      "fa-solid fa-receipt",
            self.StatusChoices.COMPLETED:        "fa-solid fa-lock",
        }
        return mapping[self.status_code]

    @property
    def status_color(self) -> str:
        mapping = {
            # Pre-approval
            self.StatusChoices.PENDING_APPROVAL: "orange",
            self.StatusChoices.APPROVED:         "green",
            self.StatusChoices.NOT_APPROVED:     "red",
            self.StatusChoices.UNDER_REVIEW:     "grey",
            # Post-approval
            self.StatusChoices.SO_CREATED:       "#0d6efd",
            self.StatusChoices.SO_SENT:          "green",
            self.StatusChoices.PAY_CREATED:      "#0d6efd",
            self.StatusChoices.PAY_SENT:         "green",
            self.StatusChoices.POSSESSION:       "#0d6efd",
            self.StatusChoices.ASSET_SENT:       "green",
            self.StatusChoices.PROFIT_CREATED:   "#0d6efd",
            self.StatusChoices.PROFIT_PAID:      "green",
            self.StatusChoices.COMPLETED:        "green",
        }
        return mapping[self.status_code]

    @transaction.atomic
    def mark_service_order_sent(self, user):
        if not self.service_order_created_at:
            raise ValidationError(
                _("You cannot send a service order before it is created."))
        self.service_order_sent_by = user
        if not self.service_order_sent_at:
            self.service_order_sent_at = timezone.now()
        self.save(update_fields=[
                  "service_order_sent_by", "service_order_sent_at"])

    @transaction.atomic
    def mark_payment_order_created(self, user):
        if not self.service_order_sent_at:
            raise ValidationError(
                _("You cannot create a payment order before service order is sent."))
        self.payment_order_created_by = user
        if not self.payment_order_created_at:
            self.payment_order_created_at = timezone.now()
        self.save(update_fields=[
                  "payment_order_created_by", "payment_order_created_at"])

    @transaction.atomic
    def mark_payment_order_sent(self, user):
        if not self.payment_order_created_at:
            raise ValidationError(
                _("You cannot send a payment order before it is created."))
        self.payment_order_sent_by = user
        if not self.payment_order_sent_at:
            self.payment_order_sent_at = timezone.now()
        self.save(update_fields=[
                  "payment_order_sent_by", "payment_order_sent_at"])

    @transaction.atomic
    def mark_asset_in_possession(self, user):
        if not self.payment_order_sent_at:
            raise ValidationError(
                _("You cannot mark asset in possession before payment order is sent."))
        self.asset_in_possession_by = user
        if not self.asset_in_possession_at:
            self.asset_in_possession_at = timezone.now()
        self.save(update_fields=[
                  "asset_in_possession_by", "asset_in_possession_at"])

    @transaction.atomic
    def mark_asset_sent(self, user):
        if not self.asset_in_possession_at:
            raise ValidationError(
                _("You cannot mark asset as sent before it is in possession."))
        self.asset_sent_by = user
        if not self.asset_sent_at:
            self.asset_sent_at = timezone.now()
        self.save(update_fields=["asset_sent_by", "asset_sent_at"])

    @transaction.atomic
    def mark_profitability_created(self, user):
        if not self.asset_sent_at:
            raise ValidationError(
                _("You cannot create profitability before asset is sent."))
        self.profitability_created_by = user
        if not self.profitability_created_at:
            self.profitability_created_at = timezone.now()
        self.save(update_fields=[
                  "profitability_created_by", "profitability_created_at"])

    @transaction.atomic
    def mark_rrf_paid(self, user, *, paid: bool = True):
        if not self.profitability_created_at:
            raise ValidationError(
                _("You cannot mark sub-payments before profitability is created."))
        self.recovery_repatriation_foundation_paid = bool(paid)
        self.recovery_repatriation_foundation_mark_by = user if paid else None
        self.recovery_repatriation_foundation_mark_at = timezone.now() if paid else None
        self.save(update_fields=[
            "recovery_repatriation_foundation_paid",
            "recovery_repatriation_foundation_mark_by",
            "recovery_repatriation_foundation_mark_at",
        ])

    @transaction.atomic
    def mark_ampro_paid(self, user, *, paid: bool = True):
        if not self.profitability_created_at:
            raise ValidationError(
                _("You cannot mark sub-payments before profitability is created."))
        self.am_pro_service_paid = bool(paid)
        self.am_pro_service_mark_by = user if paid else None
        self.am_pro_service_mark_at = timezone.now() if paid else None
        self.save(update_fields=[
            "am_pro_service_paid",
            "am_pro_service_mark_by",
            "am_pro_service_mark_at",
        ])

    @transaction.atomic
    def mark_prop_paid(self, user, *, paid: bool = True):
        if not self.profitability_created_at:
            raise ValidationError(
                _("You cannot mark sub-payments before profitability is created."))
        self.propensiones_paid = bool(paid)
        self.propensiones_mark_by = user if paid else None
        self.propensiones_mark_at = timezone.now() if paid else None
        self.save(update_fields=[
            "propensiones_paid",
            "propensiones_mark_by",
            "propensiones_mark_at",
        ])

    @transaction.atomic
    def mark_profitability_paid(self, user):
        if not self.profitability_created_at:
            raise ValidationError(
                _("You cannot pay profitability before it is created."))
        if not self.profitability_all_paid:
            raise ValidationError(
                _("All profitability sub-payments must be marked as paid first."))
        self.profitability_paid_by = user
        if not self.profitability_paid_at:
            self.profitability_paid_at = timezone.now()
        self.save(update_fields=[
                  "profitability_paid_by", "profitability_paid_at"])

    def offers_directory_path(instance, filename) -> str:
        """
        Generate a file path for an offer image.
        Path format: offer/{slugified_name}/img/YYYY/MM/DD/{hashed_filename}.{extension}
        """
        try:
            name_src = (
                getattr(instance.asset.asset_name, "es_name", None)
                or getattr(instance.asset.asset_name, "en_name", "")
                or "asset"
            )
            es_name = slugify(name_src)[:40]
            base_filename, file_extension = os.path.splitext(filename)
            filename_hash = sha256_hex(base_filename)
            path = os.path.join(
                "offer", es_name, "img",
                str(date.today().year),
                str(date.today().month),
                str(date.today().day),
                f"{filename_hash[:10]}{file_extension}"
            )
            return path
        except Exception as e:
            logger.error(
                f"Error generating file path for {filename}: {e}"
            )
            raise e

    def _ensure_can_progress(self):
        # Solo permitir progreso si está aprobado (nota: ya exigiste reviewed cuando is_approved=True)
        if not self.is_approved:
            raise ValidationError(
                _("You cannot progress stages unless the offer is approved."))

    def clean(self):
        errors = []
        if self.is_approved and not self.approved_by:
            errors.append(
                _("An approver is required when marking as approved."))
        if self.reviewed and not self.reviewed_by:
            errors.append(
                _("A reviewer is required when marking as reviewed."))
        if self.is_approved and not self.reviewed:
            errors.append(_("An approved offer must also be reviewed."))
        if self.approved_by and not self.is_approved:
            errors.append(
                _("If there is an approver, the offer must be marked as approved."))
        if self.approved_by and not self.reviewed:
            errors.append(
                _("If there is an approver, the offer must be marked as reviewed."))

        # --- Cadena secuencial ---
        # (1) PO Reviewed requiere PO Created
        if (self.reviewed or self.reviewed_by or self.reviewed_by_timestamp) and not self.created:
            errors.append(
                _("You cannot review before the purchase order is created."))

        # (2) PO Approved requiere PO Reviewed
        if (self.is_approved or self.approved_by or self.approved_by_timestamp) and not self.reviewed:
            errors.append(
                _("You cannot approve before the purchase order is reviewed."))

        # (3) SO Created requiere PO Approved (aunque lo haremos automático)
        if (self.service_order_created_at or self.service_order_created_by) and not self.is_approved:
            errors.append(
                _("Service order cannot be created before approval."))

        # (4) SO Sent requiere SO Created
        if (self.service_order_sent_at or self.service_order_sent_by) and not self.service_order_created_at:
            errors.append(
                _("You cannot send a service order before it is created."))

        # (5) Payment Order Created requiere SO Sent
        if (self.payment_order_created_at or self.payment_order_created_by) and not self.service_order_sent_at:
            errors.append(
                _("You cannot create a payment order before service order is sent."))

        # (6) Payment Order Sent requiere Payment Order Created
        if (self.payment_order_sent_at or self.payment_order_sent_by) and not self.payment_order_created_at:
            errors.append(
                _("You cannot send a payment order before it is created."))

        # (7) Asset In Possession requiere Payment Order Sent
        if (self.asset_in_possession_at or self.asset_in_possession_by) and not self.payment_order_sent_at:
            errors.append(
                _("You cannot mark asset in possession before payment order is sent."))

        # (8) Asset Sent requiere Asset In Possession
        if (self.asset_sent_at or self.asset_sent_by) and not self.asset_in_possession_at:
            errors.append(
                _("You cannot mark asset as sent before it is in possession."))

        # (9) Profitability Created requiere Asset Sent
        if (self.profitability_created_at or self.profitability_created_by) and not self.asset_sent_at:
            errors.append(
                _("You cannot create profitability before asset is sent."))

        # (10) Profitability Paid requiere Profitability Created
        if (self.profitability_paid_at or self.profitability_paid_by) and not self.profitability_created_at:
            errors.append(
                _("You cannot pay profitability before it is created."))

        if (self.profitability_paid_at or self.profitability_paid_by) and not self.profitability_all_paid:
            errors.append(
                _("Profitability cannot be closed until the three sub-payments are paid."))

        # Si algún mark_by está seteado, su boolean debe ser True
        tuple_checks = [
            ("recovery_repatriation_foundation_paid",
             "recovery_repatriation_foundation_mark_by"),
            ("am_pro_service_paid", "am_pro_service_mark_by"),
            ("propensiones_paid", "propensiones_mark_by"),
        ]

        for paid_field, by_field in tuple_checks:
            if getattr(self, by_field) and not getattr(self, paid_field):
                errors.append(
                    _("Marked-by user requires the corresponding paid flag to be true."))

        if self.reviewed and not self.is_approved:
            blocked_fields = [
                ("service_order_sent_by", _(
                    "Cannot send service order before approval.")),
                ("payment_order_created_by", _(
                    "Cannot create payment order before approval.")),
                ("payment_order_sent_by", _(
                    "Cannot send payment order before approval.")),
                ("asset_in_possession_by", _(
                    "Cannot mark asset in possession before approval.")),
                ("asset_sent_by", _("Cannot mark asset as sent before approval.")),
                ("profitability_created_by", _(
                    "Cannot create profitability before approval.")),
                ("profitability_paid_by", _(
                    "Cannot pay profitability before approval.")),
            ]
            for fname, msg in blocked_fields:
                if getattr(self, fname):
                    errors.append(msg)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        old = None
        if not is_new and self.pk:
            old = OfferModel.objects.filter(pk=self.pk).only(
                "is_approved", "approved_by", "approved_by_timestamp",
                "reviewed", "reviewed_by", "reviewed_by_timestamp",
                "service_order_created_at", "service_order_created_by",
                "service_order_sent_by", "service_order_sent_at",
                "payment_order_created_by", "payment_order_created_at",
                "payment_order_sent_by", "payment_order_sent_at",
                "asset_in_possession_by", "asset_in_possession_at",
                "asset_sent_by", "asset_sent_at",
                "profitability_created_by", "profitability_created_at",
                "profitability_paid_by", "profitability_paid_at",
                "recovery_repatriation_foundation_paid", "recovery_repatriation_foundation_mark_by",
                "am_pro_service_paid", "am_pro_service_mark_by",
                "propensiones_paid", "propensiones_mark_by",
            ).first()

        # -------- Normalización previa (auto y cascadas) --------
        def clear(*names):
            for n in names:
                setattr(self, n, None)

        # Si no está revisada, no puede estar aprobada
        if not self.reviewed:
            self.is_approved = False
            self.approved_by = None
            self.approved_by_timestamp = None

        # (A) Si NO aprobado => NADA de lo posterior
        if not self.is_approved:
            clear(
                "service_order_created_by", "service_order_created_at",
                "service_order_sent_by", "service_order_sent_at",
                "payment_order_created_by", "payment_order_created_at",
                "payment_order_sent_by", "payment_order_sent_at",
                "asset_in_possession_by", "asset_in_possession_at",
                "asset_sent_by", "asset_sent_at",
                "profitability_created_by", "profitability_created_at",
                "profitability_paid_by", "profitability_paid_at",
                "profitability_created_by", "profitability_created_at",
                "profitability_paid_by", "profitability_paid_at",
            )
            self.recovery_repatriation_foundation_paid = False
            self.am_pro_service_paid = False
            self.propensiones_paid = False
            clear(
                "recovery_repatriation_foundation_mark_by", "recovery_repatriation_foundation_mark_at",
                "am_pro_service_mark_by", "am_pro_service_mark_at",
                "propensiones_mark_by", "propensiones_mark_at",
            )
        else:
            if not self.profitability_created_at:
                self.recovery_repatriation_foundation_paid = False
                self.am_pro_service_paid = False
                self.propensiones_paid = False
                clear(
                    "recovery_repatriation_foundation_mark_by", "recovery_repatriation_foundation_mark_at",
                    "am_pro_service_mark_by", "am_pro_service_mark_at",
                    "propensiones_mark_by", "propensiones_mark_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            else:
                # Si algún subpago fue puesto en False de nuevo, borra suo marca/fecha
                if not self.recovery_repatriation_foundation_paid:
                    clear("recovery_repatriation_foundation_mark_by",
                          "recovery_repatriation_foundation_mark_at")
                if not self.am_pro_service_paid:
                    clear("am_pro_service_mark_by", "am_pro_service_mark_at")
                if not self.propensiones_paid:
                    clear("propensiones_mark_by", "propensiones_mark_at")
                # Si no están TODOS en True, no puede existir profitability_paid
                if not self.profitability_all_paid:
                    clear("profitability_paid_by", "profitability_paid_at")

            # (B) Aprobado => asegurar SO Created (auto)
            if not self.service_order_created_at:
                # Si ya hay timestamp de aprobación úsalo; si no, ahora
                ts = self.approved_by_timestamp or timezone.now()
                self.service_order_created_at = ts
                self.service_order_created_by = self.approved_by

            # (C) Cascadas posteriores según el primer faltante
            if not self.service_order_sent_at:
                clear(
                    "payment_order_created_by", "payment_order_created_at",
                    "payment_order_sent_by", "payment_order_sent_at",
                    "asset_in_possession_by", "asset_in_possession_at",
                    "asset_sent_by", "asset_sent_at",
                    "profitability_created_by", "profitability_created_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            elif not self.payment_order_created_at:
                clear(
                    "payment_order_sent_by", "payment_order_sent_at",
                    "asset_in_possession_by", "asset_in_possession_at",
                    "asset_sent_by", "asset_sent_at",
                    "profitability_created_by", "profitability_created_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            elif not self.payment_order_sent_at:
                clear(
                    "asset_in_possession_by", "asset_in_possession_at",
                    "asset_sent_by", "asset_sent_at",
                    "profitability_created_by", "profitability_created_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            elif not self.asset_in_possession_at:
                clear(
                    "asset_sent_by", "asset_sent_at",
                    "profitability_created_by", "profitability_created_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            elif not self.asset_sent_at:
                clear(
                    "profitability_created_by", "profitability_created_at",
                    "profitability_paid_by", "profitability_paid_at",
                )
            elif not self.profitability_created_at:
                clear("profitability_paid_by", "profitability_paid_at")

        # Ahora sí validaciones
        self.full_clean()

        # -------- Timestamps “by/timestamp” coherentes --------
        # Aprobación
        if self.is_approved and self.approved_by:
            if is_new or not self.approved_by_timestamp or (old and old.approved_by_id != self.approved_by_id):
                self.approved_by_timestamp = timezone.now()
        else:
            self.approved_by_timestamp = None

        # Revisión
        if self.reviewed and self.reviewed_by:
            if is_new or not self.reviewed_by_timestamp or (old and old.reviewed_by_id != self.reviewed_by_id):
                self.reviewed_by_timestamp = timezone.now()
        else:
            self.reviewed_by_timestamp = None

        # Auto-set genérico para *_by -> *_at (cuando cambie la persona)
        def auto_ts(field_by, field_at):
            by_val = getattr(self, field_by)
            at_val = getattr(self, field_at)
            old_by_val = getattr(old, field_by) if old else None
            if by_val:
                if is_new or not at_val or (old and old_by_val != by_val):
                    setattr(self, field_at, timezone.now())
            else:
                setattr(self, field_at, None)

        # Nota: service_order_created_* ya está tratado arriba, pero mantenemos por consistencia
        auto_ts("service_order_created_by", "service_order_created_at")
        auto_ts("service_order_sent_by", "service_order_sent_at")
        auto_ts("payment_order_created_by", "payment_order_created_at")
        auto_ts("payment_order_sent_by", "payment_order_sent_at")
        auto_ts("asset_in_possession_by", "asset_in_possession_at")
        auto_ts("asset_sent_by", "asset_sent_at")
        auto_ts("profitability_created_by", "profitability_created_at")
        auto_ts("profitability_paid_by", "profitability_paid_at")
        auto_ts("recovery_repatriation_foundation_mark_by",
                "recovery_repatriation_foundation_mark_at")
        auto_ts("am_pro_service_mark_by", "am_pro_service_mark_at")
        auto_ts("propensiones_mark_by", "propensiones_mark_at")

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.asset.asset_name.en_name} - {self.buyer_country} - {self.offer_quantity}"

    class Meta:
        db_table = "apps_buyers_offer"
        verbose_name = _("Purchase order")
        verbose_name_plural = _("Purchase orders")
        ordering = ["default_order", "-created"]
        permissions = [
            ("can_approve_offer",             _("Can approve purchase orders")),
            ("can_review_offer",              _("Can review purchase orders")),
            ("can_send_service_order",        _("Can send service orders")),
            ("can_create_payment_order",      _("Can create payment orders")),
            ("can_send_payment_order",        _("Can send payment orders")),
            ("can_set_asset_possession",      _("Can set asset in possession")),
            ("can_send_asset",                _("Can send asset")),
            ("can_set_profitability",         _("Can set profitability")),
            ("can_pay_profitability",         _("Can pay profitability")),
            ("can_approve_pay_profitability", _("Can approve pay profitability")),
            ("can_see_profitability_page",    _("Can see profitability page")),
            ("can_see_wizard_page",           _("Can see the offer workflow wizard page")),
            
            ("recovery_repatriation_foundation_paid",    _("Mark Recovery Repatriation Foundation as paid")),
            ("recovery_repatriation_foundation_mark_by", _("Set user who marked Recovery Repatriation Foundation as paid")),
            ("recovery_repatriation_foundation_mark_at", _("Set timestamp when Recovery Repatriation Foundation was marked as paid")),

            ("am_pro_service_paid",    _("Mark AM PRO service as paid")),
            ("am_pro_service_mark_by", _("Set user who marked AM PRO as paid")),
            ("am_pro_service_mark_at", _("Set timestamp when AM PRO was marked as paid")),

            ("propensiones_paid",    _("Mark Propensiones as paid")),
            ("propensiones_mark_by", _("Set user who marked Propensiones as paid")),
            ("propensiones_mark_at", _("Set timestamp when Propensiones was marked as paid")),
        ]
        
        constraints = [
            # Aprobado => Debe estar revisado
            models.CheckConstraint(
                name="approved_requires_reviewed",
                check=Q(is_approved=False) | Q(reviewed=True),
            ),
            # SO Created => Approved
            models.CheckConstraint(
                name="so_created_requires_approved",
                check=Q(service_order_created_at__isnull=True) | Q(
                    is_approved=True),
            ),
            # SO Sent => SO Created
            models.CheckConstraint(
                name="so_sent_requires_so_created",
                check=Q(service_order_sent_at__isnull=True) | Q(
                    service_order_created_at__isnull=False),
            ),
            # Payment Created => SO Sent
            models.CheckConstraint(
                name="pay_created_requires_so_sent",
                check=Q(payment_order_created_at__isnull=True) | Q(
                    service_order_sent_at__isnull=False),
            ),
            # Payment Sent => Payment Created
            models.CheckConstraint(
                name="pay_sent_requires_pay_created",
                check=Q(payment_order_sent_at__isnull=True) | Q(
                    payment_order_created_at__isnull=False),
            ),
            # In Possession => Payment Sent
            models.CheckConstraint(
                name="possession_requires_pay_sent",
                check=Q(asset_in_possession_at__isnull=True) | Q(
                    payment_order_sent_at__isnull=False),
            ),
            # Asset Sent => In Possession
            models.CheckConstraint(
                name="asset_sent_requires_possession",
                check=Q(asset_sent_at__isnull=True) | Q(
                    asset_in_possession_at__isnull=False),
            ),
            # Profit Created => Asset Sent
            models.CheckConstraint(
                name="profit_created_requires_asset_sent",
                check=Q(profitability_created_at__isnull=True) | Q(
                    asset_sent_at__isnull=False),
            ),
            # Profit Paid => Profit Created
            models.CheckConstraint(
                name="profit_paid_requires_profit_created",
                check=Q(profitability_paid_at__isnull=True) | Q(
                    profitability_created_at__isnull=False),
            ),
            # Profit Paid => 3 subpagos
            models.CheckConstraint(
                name="profit_paid_requires_3_subpaids",
                check=Q(profitability_paid_at__isnull=True) |
                (Q(recovery_repatriation_foundation_paid=True) &
                 Q(am_pro_service_paid=True) &
                 Q(propensiones_paid=True))
            ),
        ]


class ServiceOrderRecipient(TimeStampedModel):
    offer = models.ForeignKey(
        OfferModel, on_delete=models.CASCADE, related_name="so_recipients")
    user = models.ForeignKey(
        UserModel, null=True,
                             blank=True, on_delete=models.CASCADE)
    user_type = models.CharField(
        max_length=2,
        choices=UserModel.UserTypeChoices.choices,
        null=True, blank=True
    )
    added_by = models.ForeignKey(
        UserModel, on_delete=models.SET_NULL, null=True, related_name="so_recipient_added_by")

    class Meta:
        db_table = "apps_buyers_service_order_recipient"
        verbose_name = _("Service Order Recipient")
        verbose_name_plural = _("Service Order Recipients")
        ordering = ["default_order", "-created"]
        constraints = [
            models.CheckConstraint(
                name="so_recipient_user_or_type",
                check=~(Q(user__isnull=True) & Q(user_type__isnull=True)),
            ),
            models.UniqueConstraint(
                fields=["offer", "user"],
                name="uniq_so_recipient_user",
                condition=Q(user__isnull=False),
            ),
            models.UniqueConstraint(
                fields=["offer", "user_type"],
                name="uniq_so_recipient_type",
                condition=Q(user_type__isnull=False),
            ),
        ]


pre_save.connect(
    auto_fill_offer_translation,
    sender=OfferModel
)

post_delete.connect(
    auto_delete_offer_img_on_delete,
    sender=OfferModel
)

pre_save.connect(
    auto_delete_and_optimize_offer_img_on_change,
    sender=OfferModel
)

auditlog.register(
    OfferModel,
    serialize_data=True
)

auditlog.register(
    ServiceOrderRecipient,
    serialize_data=True
)
