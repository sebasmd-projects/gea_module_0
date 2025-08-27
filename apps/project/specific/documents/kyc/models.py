from django.db import models
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import (EncryptedCharField,
                                           EncryptedEmailField)

from apps.common.utils.models import TimeStampedModel


class LegalAdvisorModel(TimeStampedModel):
    legal_advisor_first_name = models.CharField(
        _('Legal Advisor Name'),
        max_length=100
    )

    legal_advisor_last_name = models.CharField(
        _('Legal Advisor Last Name'),
        max_length=100
    )

    legal_advisor_card_id = EncryptedCharField(
        _('Legal Advisor Card ID'),
        max_length=100
    )

    legal_advisor_country = models.CharField(
        _('Legal Advisor Country'),
        max_length=100
    )

    legal_advisor_phonenumber = EncryptedCharField(
        _('Legal Advisor Phone Number'),
        max_length=100
    )

    legal_advisor_email = EncryptedEmailField(
        _('Legal Advisor Email')
    )

    def get_full_name(self) -> str:
        full_name = f"{self.legal_advisor_first_name} {self.legal_advisor_last_name}"
        return full_name.strip()

    def __str__(self) -> str:
        return self.get_full_name()

    def save(self, *args, **kwargs):
        self.legal_advisor_first_name = self.legal_advisor_first_name.title()
        self.legal_advisor_last_name = self.legal_advisor_last_name.title()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_kyc_legaladvisor'
        verbose_name = _('Legal Advisor')
        verbose_name_plural = _('Legal Advisors')
