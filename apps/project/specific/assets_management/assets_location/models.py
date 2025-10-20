import secrets

import string
import uuid

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel
from apps.project.specific.assets_management.assets.models import AssetModel

UserModel = get_user_model()


def generate_random_code(length=10):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class AssetCountryModel(TimeStampedModel):
    class ContinentChoices(models.TextChoices):
        AFRICA = "AF", _("Africa")
        ANTARCTICA = "AN", _("Antarctica")
        ASIA = "AS", _("Asia")
        CENTRAL_AMERICA = "CA", _("Central America")
        EUROPE = "EU", _("Europe")
        NORTH_AMERICA = "NA", _("North America")
        OCEANIA = "OC", _("Oceania")
        SOUTH_AMERICA = "SA", _("South America")

    continent = models.CharField(
        _("continent"),
        max_length=3,
        choices=ContinentChoices.choices,
        default=ContinentChoices.SOUTH_AMERICA
    )

    es_country_name = models.CharField(
        _('Country Name (ES)'),
        max_length=100,
    )

    en_country_name = models.CharField(
        _('Country Name (EN)'),
        max_length=100,
        blank=True, null=True
    )
    
    def country_name(self):
        return self.es_country_name if self.es_country_name else self.en_country_name

    def __str__(self) -> str:
        return f"{self.get_continent_display()} - {self.es_country_name} - {self.en_country_name}"

    def save(self, *args, **kwargs):
        if self.es_country_name:
            self.es_country_name = self.es_country_name.title().strip()
        if self.en_country_name:
            self.en_country_name = self.en_country_name.title().strip()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_assets_location_country'
        unique_together = ['continent', 'es_country_name', 'en_country_name']
        verbose_name = _('Country')
        verbose_name_plural = _('Countries')
        ordering = ["default_order", "-created", 'continent']


class LocationModel(TimeStampedModel):
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
        related_name="assetslocation_location_user",
        verbose_name=_("Created By"),
        null=True
    )

    reference = models.CharField(
        _("location reference"),
        max_length=150,
        blank=True,
        null=True
    )

    description_es = models.TextField(
        _("description (ES)"),
        blank=True,
        null=True
    )

    description_en = models.TextField(
        _("description (EN)"),
        blank=True,
        null=True
    )

    country = models.ForeignKey(
        AssetCountryModel,
        on_delete=models.CASCADE,
        related_name="assetlocation_location_country",
        verbose_name=_("Country")
    )

    def __str__(self):
        return "{} ({})".format(self.reference, self.country.es_country_name)

    def save(self, *args, **kwargs):
        if self.reference:
            self.reference = self.reference.upper().strip()

        if not self.reference:
            self.reference = "{} - {}".format(
                self.country.country_name(),
                generate_random_code()
            ).upper()

        super(LocationModel, self).save(*args, **kwargs)

    class Meta:
        db_table = "apps_assets_location_location"
        unique_together = ['reference', 'country', 'created_by',
                           'is_active', 'description_es', 'description_en']
        verbose_name = _("Location")
        verbose_name_plural = _("Locations")
        ordering = ["default_order", "-created"]


class AssetLocationModel(TimeStampedModel):
    class QuantityTypeChoices(models.TextChoices):
        UNITS = "U", _("Units")
        BOXES = "B", _("Boxes")

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
        related_name="assetslocation_assetslocation_user",
        verbose_name=_("Created By"),
        null=True
    )

    asset = models.ForeignKey(
        AssetModel,
        on_delete=models.CASCADE,
        related_name="assetlocation_assetlocation_asset",
        verbose_name=_("Asset")
    )

    location = models.ForeignKey(
        LocationModel,
        on_delete=models.CASCADE,
        related_name="assetlocation_assetlocation_location",
        verbose_name=_("location"),
        blank=True,
        null=True
    )

    quantity_type = models.CharField(
        _("quantity type"),
        max_length=255,
        choices=QuantityTypeChoices.choices,
        default=QuantityTypeChoices.BOXES
    )

    amount = models.PositiveBigIntegerField(
        _("amount")
    )

    observations_es = models.TextField(
        _("observations (ES)"),
        blank=True,
        null=True
    )

    observations_en = models.TextField(
        _("observations (EN)"),
        blank=True,
        null=True
    )

    def asset_name(self):
        return self.asset.asset_name.es_name if self.asset and self.asset.asset_name else _("No Asset")
    
    def __str__(self) -> str:
        location_ref = self.location.reference if self.location else _(
            "No Location")
        return "{} - {} - {} - {} - {}".format(
            self.asset.asset_name.en_name,
            self.get_quantity_type_display(),
            self.amount,
            location_ref,
            self.created_by,
        )

    class Meta:
        db_table = "apps_assets_location_assetlocation"
        verbose_name = _("Location Registration")
        verbose_name_plural = _("Locations Registration")
        ordering = ["default_order", "-created"]
        unique_together = [
            'asset',
            'location',
            'quantity_type',
            'amount',
            'created_by',
            'observations_es',
            'observations_en',
        ]


auditlog.register(
    AssetCountryModel,
    serialize_data=True
)

auditlog.register(
    LocationModel,
    serialize_data=True
)

auditlog.register(
    AssetLocationModel,
    serialize_data=True
)
