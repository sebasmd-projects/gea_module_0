import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel


class ContactModel(TimeStampedModel):
    unique_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True
    )

    name = models.CharField(
        _('name'),
        max_length=255
    )

    last_name = models.CharField(
        _('last name'),
        max_length=255
    )

    email = models.EmailField(
        _('email'),
        max_length=255,
    )

    subject = models.CharField(
        _('subject'),
        max_length=255
    )

    message = models.TextField(
        _('message'),
    )

    class Meta:
        db_table = 'apps_core_contact'
        verbose_name = _('Contact')
        verbose_name_plural = _('Contacts')

    def __str__(self):
        return self.name

class ModalBannerModel(TimeStampedModel):
    title = models.CharField(
        _('title'),
        max_length=255
    )
    
    title_en = models.CharField(
        _('title (English)'),
        max_length=255,
        blank=True,
        null=True
    )

    description = models.TextField(
        _('description'),
        blank=True, null=True
    )

    image_file = models.ImageField(
        _('image file'),
        upload_to='modal_banners/'
    )
    
    image_file_en = models.ImageField(
        _('image file (English)'),
        upload_to='modal_banners/',
        blank=True,
        null=True
    )
    
    link = models.URLField(
        _('link'),
        max_length=255,
        blank=True,
        null=True
    )
    
    link_en = models.URLField(
        _('link (English)'),
        max_length=255,
        blank=True,
        null=True
    )

    def save(self, *args, **kwargs):
        if self.is_active:
            ModalBannerModel.objects.filter(
                is_active=True
            ).update(
                is_active=False
            )
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_common_core_modal_banner'
        verbose_name = _('Modal Banner')
        verbose_name_plural = _('Modal Banners')
        ordering = ['-created']

    def __str__(self):
        return self.title
