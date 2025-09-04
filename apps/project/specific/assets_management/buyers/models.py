import logging
import os
import uuid
from datetime import date

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import CheckConstraint, F, Q
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions import generate_md5_or_sha256_hash
from apps.common.utils.models import TimeStampedModel
from apps.project.specific.assets_management.assets.models import AssetModel
from apps.project.specific.assets_management.assets_location.models import \
    AssetCountryModel

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

    is_approved = models.BooleanField(
        _("Approved"),
        default=False
    )

    reviewed = models.BooleanField(
        _("Reviewed"),
        default=False
    )

    display = models.BooleanField(
        _("Display"),
        default=True
    )

    approved_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="buyers_offer_approved_by_user",
        verbose_name=_("Approved By"),
        null=True,
        blank=True
    )

    reviewed_by = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="buyers_offer_reviewed_by_user",
        verbose_name=_("Reviewed By"),
        null=True,
        blank=True
    )

    approved_by_timestamp = models.DateTimeField(
        verbose_name=_("Approved By Timestamp"),
        null=True,
        blank=True
    )

    reviewed_by_timestamp = models.DateTimeField(
        verbose_name=_("Reviewed By Timestamp"),
        null=True,
        blank=True
    )

    @property
    def asset_display_name(self):
        lang = get_language()
        if lang == "es" and self.asset.asset_name.es_name:
            return self.asset.asset_name.es_name
        return self.asset.asset_name.en_name or self.asset.asset_name.es_name

    @transaction.atomic
    def mark_reviewed(self, user):
        self.reviewed_by = user
        self.reviewed = True
        self.save(
            update_fields=[
                "reviewed_by",
                "reviewed",
                "reviewed_by_timestamp"
            ]
        )

    @transaction.atomic
    def mark_approved(self, user):
        if not self.reviewed or not self.reviewed_by:
            raise ValidationError(_("Offer must be reviewed before approval."))
        self.approved_by = user
        self.is_approved = True
        self.save(
            update_fields=[
                "approved_by",
                "is_approved",
                "approved_by_timestamp"
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
                "is_approved", "approved_by", "reviewed", "reviewed_by").first()

        # approved_at
        if self.is_approved and self.approved_by:
            should_set = False
            if is_new or not self.approved_by_timestamp:
                should_set = True
            elif old and (old.approved_by_id != self.approved_by_id):
                should_set = True
            if should_set:
                self.approved_by_timestamp = timezone.now()
        else:
            self.approved_by_timestamp = None

        # reviewed_at
        if self.reviewed and self.reviewed_by:
            should_set = False
            if is_new or not self.reviewed_by_timestamp:
                should_set = True
            elif old and (old.reviewed_by_id != self.reviewed_by_id):
                should_set = True
            if should_set:
                self.reviewed_by_timestamp = timezone.now()
        else:
            self.reviewed_by_timestamp = None

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
        ]


auditlog.register(
    OfferModel,
    serialize_data=True
)
