import logging
import os
import uuid
from datetime import date

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django_ckeditor_5.fields import CKEditor5Field

from apps.common.core.functions import generate_md5_or_sha256_hash
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
        CONTAINERS = "C", _("Containers")

    def offers_directory_path(instance, filename) -> str:
        """
        Generate a file path for an offer image.
        Path format: offer/{slugified_name}/img/YYYY/MM/DD/{hashed_filename}.{extension}
        """
        try:
            es_name = slugify(instance.asset.asset_name.es_name)[:40]
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
        SOVEREIGN = "S", _("Sovereign Purchase")
        PRIVATE = "P", _("Private Purchase (Sovereign)")
        BUSINESS = "B", _("Business Purchase")
        GOVERNMENT = "G", _("Government Purchase")

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
        _("Offer Type"),
        max_length=255,
        choices=OfferTypeChoices.choices,
        default=OfferTypeChoices.PRIVATE
    )

    quantity_type = models.CharField(
        _("quantity type"),
        max_length=255,
        choices=QuantityTypeChoices.choices,
        default=QuantityTypeChoices.BOXES
    )

    offer_amount = models.DecimalField(
        _("Offer Amount per quantity type in USD"),
        max_digits=20,
        decimal_places=1,
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

    es_procedure = CKEditor5Field(
        _('Procedure (ES)'),
        config_name='default'
    )

    en_procedure = CKEditor5Field(
        _('Procedure (EN)'),
        config_name='default',
    )

    es_banner = models.ImageField(
        _("Banner (ES)"),
        upload_to=offers_directory_path,
        null=True,
        blank=True
    )

    en_banner = models.ImageField(
        _("Banner (EN)"),
        upload_to=offers_directory_path,
        null=True,
        blank=True
    )

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

    @property
    def asset_display_name(self):
        lang = get_language()
        if lang == "es" and self.asset.asset_name.es_name:
            return self.asset.asset_name.es_name
        return self.asset.asset_name.en_name or self.asset.asset_name.es_name

    def save(self, *args, **kwargs):
        if self.approved_by and not self.is_approved:
            self.is_approved = True

        if not self.approved_by:
            self.is_approved = False
            self.is_active = False

        super(OfferModel, self).save(*args, **kwargs)

    def total_value(self):
        return self.offer_amount * self.offer_quantity

    def __str__(self) -> str:
        return f"{self.asset.asset_name.en_name} - {self.buyer_country} - {self.offer_quantity}"

    class Meta:
        db_table = "apps_buyers_offer"
        verbose_name = _("1. Offer")
        verbose_name_plural = _("1. Offers")
        ordering = ["default_order", "-created"]


auditlog.register(OfferModel, serialize_data=True)
