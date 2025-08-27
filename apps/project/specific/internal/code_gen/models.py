from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel


class CodeRegistrationModel(TimeStampedModel):
    reference = models.CharField(
        _('Reference'),
        max_length=100,
    )

    description = models.TextField(
        _('Description'),
        blank=True,
        null=True,
    )

    custom_text_input = models.CharField(
        _('Custom Text Input'),
        max_length=100,
        blank=True,
        null=True,
    )

    code_information = models.TextField(
        _('Code Information'),
        blank=True,
        null=True,
    )

    def __str__(self) -> str:
        return self.reference

    def save(self, *args, **kwargs):
        self.reference = self.reference.upper()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_code_gen_coderegistration'
        verbose_name = _('Code Registration')
        verbose_name_plural = _('Code Registrations')
