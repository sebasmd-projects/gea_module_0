import logging
import os
import uuid
from datetime import date

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models.signals import post_delete, pre_save
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.common.utils.functions import generate_md5_or_sha256_hash
from apps.common.utils.models import TimeStampedModel

from .signals import (auto_delete_asset_img_on_change,
                      auto_delete_asset_img_on_delete,
                      auto_fill_asset_category_translation,
                      auto_fill_asset_name_translation,
                      auto_fill_asset_translation_fields)

logger = logging.getLogger(__name__)
UserModel = get_user_model()


class AssetCategoryModel(TimeStampedModel):
    es_name = models.CharField(
        _("category (ES)"),
        max_length=50,
        blank=True,
        null=True
    )

    en_name = models.CharField(
        _("category (EN)"),
        max_length=50,
        blank=True,
        null=True
    )

    es_description = models.TextField(
        _("description"),
        blank=True,
        null=True
    )

    en_description = models.TextField(
        _("description"),
        blank=True,
        null=True
    )

    created_by = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name="assets_asset_assetcategory",
        verbose_name=_("created by"),
        blank=True,
        null=True
    )

    def __str__(self) -> str:
        return self.es_name or self.en_name or str(self.pk)

    def save(self, *args, **kwargs):
        if self.es_name:
            self.es_name = self.es_name.title().strip()
        if self.en_name:
            self.en_name = self.en_name.title().strip()
        super(AssetCategoryModel, self).save(*args, **kwargs)

    class Meta:
        db_table = "apps_assets_assetcategory"
        verbose_name = _("Category")
        verbose_name_plural = _("Categories")
        ordering = ["default_order", "-created"]


class AssetsNamesModel(TimeStampedModel):
    es_name = models.CharField(
        _("asset (es)"),
        max_length=255,
        blank=True,
        null=True
    )

    en_name = models.CharField(
        _("asset (en)"),
        max_length=255,
        blank=True,
        null=True
    )

    def __str__(self) -> str:
        return self.en_name or self.es_name or str(self.pk)

    def save(self, *args, **kwargs):
        if self.es_name:
            self.es_name = self.es_name.title().strip()
        if self.en_name:
            self.en_name = self.en_name.title().strip()

        super(AssetsNamesModel, self).save(*args, **kwargs)

    class Meta:
        db_table = "apps_assets_assetsnames"
        verbose_name = _("Asset Name")
        verbose_name_plural = _("Asset Names")
        ordering = ["default_order", "-created"]


class AssetModel(TimeStampedModel):
    def assets_directory_path(instance, filename) -> str:
        """
        Generate a file path for an asset image.
        Path format: asset/{slugified_name}/img/YYYY/MM/DD/{hashed_filename}.{extension}
        """
        try:
            es_name = slugify(instance.asset_name.es_name)[:40]
            base_filename, file_extension = os.path.splitext(filename)
            filename_hash = generate_md5_or_sha256_hash(base_filename)
            path = os.path.join(
                "asset", es_name, "img",
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

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        unique=True,
        primary_key=True,
        serialize=False,
        editable=False
    )

    asset_img = models.ImageField(
        _("img"),
        max_length=255,
        upload_to=assets_directory_path,
        blank=True,
        null=True
    )

    asset_name = models.OneToOneField(
        AssetsNamesModel,
        on_delete=models.CASCADE,
        related_name="assets_asset_assetsnames",
        verbose_name=_("asset")
    )

    category = models.ForeignKey(
        AssetCategoryModel,
        on_delete=models.CASCADE,
        related_name="assets_asset_assetcategory",
        verbose_name=_("category")
    )

    es_description = models.TextField(
        _("description (ES)"),
        blank=True,
        null=True
    )

    en_description = models.TextField(
        _("description (EN)"),
        blank=True,
        null=True
    )

    es_observations = models.TextField(
        _("observations (ES)"),
        default="",
        blank=True,
        null=True
    )

    en_observations = models.TextField(
        _("observations (EN)"),
        default="",
        blank=True,
        null=True
    )

    def asset_total_quantity_by_type(self):
        """
        Calculate the total quantity grouped by quantity_type with readable labels.
        """
        from collections import defaultdict

        related_model = self.assetlocation_assetlocation_asset.model
        quantity_type_display = dict(related_model.QuantityTypeChoices.choices)

        totals_by_type = self.assetlocation_assetlocation_asset.filter(is_active=True).values('quantity_type').annotate(
            total=models.Sum('amount')
        )

        totals = defaultdict(int)

        for entry in totals_by_type:
            readable_label = quantity_type_display.get(
                entry['quantity_type'], entry['quantity_type'])
            totals[readable_label] = entry['total']

        return totals

    def __str__(self) -> str:
        return self.asset_name.__str__() or str(self.pk)

    class Meta:
        db_table = "apps_assets_asset"
        verbose_name = _("Asset")
        verbose_name_plural = _("Assets")
        ordering = ["default_order", "-created"]
        unique_together = ['asset_name', 'category']


post_delete.connect(
    auto_delete_asset_img_on_delete,
    sender=AssetModel
)

pre_save.connect(
    auto_delete_asset_img_on_change,
    sender=AssetModel
)

pre_save.connect(
    auto_fill_asset_category_translation,
    sender=AssetCategoryModel
)

pre_save.connect(
    auto_fill_asset_name_translation,
    sender=AssetsNamesModel
)

pre_save.connect(
    auto_fill_asset_translation_fields,
    sender=AssetModel
)

auditlog.register(
    AssetCategoryModel,
    serialize_data=True
)

auditlog.register(
    AssetsNamesModel,
    serialize_data=True
)

auditlog.register(
    AssetModel,
    serialize_data=True
)
