import logging
import os
import uuid
from datetime import date

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import pre_save
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions import generate_md5_or_sha256_hash
from apps.common.utils.models import TimeStampedModel
from apps.project.specific.assets_management.assets.models import AssetModel
from apps.project.specific.assets_management.assets_location.models import \
    AssetCountryModel

from .signals import auto_fill_offer_translation

logger = logging.getLogger(__name__)
UserModel = get_user_model()


class OfferModel(TimeStampedModel):
    class QuantityTypeChoices(models.TextChoices):
        UNITS = "U", _("Units")
        BOXES = "B", _("Boxes")

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
            filename_hash = generate_md5_or_sha256_hash(base_filename)
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

    offer_amount = models.DecimalField(
        _("Total value of the offer ($ USD)"),
        max_digits=20,
        decimal_places=2,
        default=0
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

    @property
    def asset_display_name(self):
        lang = get_language()
        if lang == "es" and self.asset.asset_name.es_name:
            return self.asset.asset_name.es_name
        return self.asset.asset_name.en_name or self.asset.asset_name.es_name

    @transaction.atomic
    def mark_service_order_sent(self, user):
        self.service_order_sent_by = user
        if not self.service_order_sent_at:
            self.service_order_sent_at = timezone.now()
        self.save(update_fields=[
                  "service_order_sent_by", "service_order_sent_at"])

    @transaction.atomic
    def mark_payment_order_created(self, user):
        self.payment_order_created_by = user
        if not self.payment_order_created_at:
            self.payment_order_created_at = timezone.now()
        self.save(update_fields=[
                  "payment_order_created_by", "payment_order_created_at"])

    @transaction.atomic
    def mark_payment_order_sent(self, user):
        self.payment_order_sent_by = user
        if not self.payment_order_sent_at:
            self.payment_order_sent_at = timezone.now()
        self.save(
            update_fields=[
                "payment_order_sent_by",
                "payment_order_sent_at"
            ]
        )

    @transaction.atomic
    def mark_asset_in_possession(self, user):
        self.asset_in_possession_by = user
        if not self.asset_in_possession_at:
            self.asset_in_possession_at = timezone.now()
        self.save(
            update_fields=[
                "asset_in_possession_by",
                "asset_in_possession_at"
            ]
        )

    @transaction.atomic
    def mark_asset_sent(self, user):
        self.asset_sent_by = user
        if not self.asset_sent_at:
            self.asset_sent_at = timezone.now()
        self.save(
            update_fields=[
                "asset_sent_by",
                "asset_sent_at"
            ]
        )

    @transaction.atomic
    def mark_profitability_created(self, user):
        self.profitability_created_by = user
        if not self.profitability_created_at:
            self.profitability_created_at = timezone.now()
        self.save(
            update_fields=[
                "profitability_created_by",
                "profitability_created_at"
            ]
        )

    @transaction.atomic
    def mark_profitability_paid(self, user):
        self.profitability_paid_by = user
        if not self.profitability_paid_at:
            self.profitability_paid_at = timezone.now()
        self.save(
            update_fields=[
                "profitability_paid_by",
                "profitability_paid_at"
            ]
        )

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
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        is_new = self._state.adding
        old = None
        if not is_new and self.pk:
            old = OfferModel.objects.filter(pk=self.pk).only(
                "is_approved",
                "approved_by",
                "reviewed",
                "reviewed_by",
                "service_order_sent_by",
                "payment_order_created_by",
                "payment_order_sent_by",
                "asset_in_possession_by",
                "asset_sent_by",
                "profitability_created_by",
                "profitability_paid_by",
            ).first()

        # --- approved ---
        if self.is_approved and self.approved_by:
            if is_new or not self.approved_by_timestamp or (old and old.approved_by_id != self.approved_by_id):
                self.approved_by_timestamp = timezone.now()
        else:
            self.approved_by_timestamp = None

        # --- reviewed ---
        if self.reviewed and self.reviewed_by:
            if is_new or not self.reviewed_by_timestamp or (old and old.reviewed_by_id != self.reviewed_by_id):
                self.reviewed_by_timestamp = timezone.now()
        else:
            self.reviewed_by_timestamp = None

        # --- auto timestamps para etapas faltantes cuando cambia el *_by ---
        def auto_ts(field_by, field_at):
            by_val = getattr(self, field_by)
            at_val = getattr(self, field_at)
            old_by_val = getattr(old, field_by) if old else None
            if by_val:
                if is_new or not at_val or (old and old_by_val != by_val):
                    setattr(self, field_at, timezone.now())
            else:
                setattr(self, field_at, None)

        auto_ts("service_order_sent_by", "service_order_sent_at")
        auto_ts("payment_order_created_by", "payment_order_created_at")
        auto_ts("payment_order_sent_by", "payment_order_sent_at")
        auto_ts("asset_in_possession_by", "asset_in_possession_at")
        auto_ts("asset_sent_by", "asset_sent_at")
        auto_ts("profitability_created_by", "profitability_created_at")
        auto_ts("profitability_paid_by", "profitability_paid_at")

        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.asset.asset_name.en_name} - {self.buyer_country} - {self.offer_quantity}"

    class Meta:
        db_table = "apps_buyers_offer"
        verbose_name = _("1. Purchase order")
        verbose_name_plural = _("1. Purchase orders")
        ordering = ["default_order", "-created"]
        permissions = [
            ("can_approve_offer", _("Can approve purchase orders")),
            ("can_review_offer", _("Can review purchase orders")),
            ("can_send_service_order", _("Can send service orders")),
            ("can_create_payment_order", _("Can create payment orders")),
            ("can_send_payment_order", _("Can send payment orders")),
            ("can_set_asset_possession", _("Can set asset in possession")),
            ("can_send_asset", _("Can send asset")),
            ("can_set_profitability", _("Can set profitability")),
            ("can_pay_profitability", _("Can pay profitability")),
        ]


pre_save.connect(
    auto_fill_offer_translation,
    sender=OfferModel
)

auditlog.register(
    OfferModel,
    serialize_data=True
)
