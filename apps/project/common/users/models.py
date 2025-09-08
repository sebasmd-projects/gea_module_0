import uuid
from datetime import date, timedelta

from auditlog.registry import auditlog
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from encrypted_model_fields.fields import (EncryptedCharField,
                                           EncryptedDateField,
                                           EncryptedEmailField)
from functools import lru_cache

from apps.common.utils.functions import generate_md5_or_sha256_hash
from apps.common.utils.models import TimeStampedModel


class UserModel(TimeStampedModel, AbstractUser):
    class UserTypeChoices(models.TextChoices):
        BUYER = 'B', _('Buyer')
        HOLDER = 'H', _('Holder')
        REPRESENTATIVE = 'R', _('Representative')
        INTERMEDIARY = 'I', _('Intermediary')

    NOT_INCLUDE_USER_TYPE_CHOICES = {UserTypeChoices.BUYER}

    USERNAME_FIELD = 'email'

    REQUIRED_FIELDS = [
        'username',
        'first_name',
        'last_name'
    ]

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        unique=True,
        primary_key=True,
        serialize=False,
        editable=False
    )

    first_name = models.CharField(
        _("names"),
        max_length=150,
    )

    last_name = models.CharField(
        _("surnames"),
        max_length=150,
    )

    email = EncryptedEmailField(
        _("email address"),
        unique=True,
    )

    email_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False
    )

    user_type = models.CharField(
        _('User'),
        max_length=2,
        choices=UserTypeChoices.choices,
        default=UserTypeChoices.BUYER
    )

    citizenship_number = models.CharField(
        _('Citizenship Number'),
        max_length=20,
        blank=True,
        null=True
    )

    is_verified_holder = models.BooleanField(
        _('Verified Holder'),
        default=False
    )

    @classmethod
    @lru_cache(maxsize=1)
    def asset_holder_values(cls):
        return frozenset(
            code for code, _ in cls.UserTypeChoices.choices
            if code not in cls.NOT_INCLUDE_USER_TYPE_CHOICES
        )

    @property
    def is_asset_holder(self):
        return self.user_type in type(self).asset_holder_values()

    @property
    def is_buyer(self):
        return self.user_type == type(self).UserTypeChoices.BUYER

    def __str__(self) -> str:
        return f"{self.get_full_name()} ({self.username})"

    def save(self, *args, **kwargs):
        email = self.email.lower().strip()
        self.first_name = self.first_name.title().strip()
        self.last_name = self.last_name.title().strip()
        self.username = self.username.lower().strip()
        self.email = email
        self.email_hash = generate_md5_or_sha256_hash(email)
        if self.user_type == self.UserTypeChoices.BUYER:
            self.is_verified_holder = True
        super().save(*args, **kwargs)

    def clean(self):
        if '@' in self.username:
            raise ValidationError(
                _('The username cannot contain the "@" character.'))
        super().clean()

    class Meta:
        db_table = 'apps_users_user'
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        unique_together = [['username', 'email']]


class CountryModel(TimeStampedModel):
    country_name = models.CharField(
        _('Country Name'),
        max_length=100,
        unique=True
    )

    country_code = models.CharField(
        _('Country Code'),
        max_length=5,
        unique=True
    )

    def __str__(self) -> str:
        return f"{self.country_name} ({self.country_code})"

    def save(self, *args, **kwargs):
        self.country_name = self.country_name.title()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_users_country'
        verbose_name = _('Country')
        verbose_name_plural = _('Countries')


class StateModel(TimeStampedModel):
    state_name = models.CharField(
        _('State Name'),
        max_length=100,
    )

    country = models.ForeignKey(
        CountryModel,
        on_delete=models.CASCADE,
        related_name='users_state_country'
    )

    def __str__(self) -> str:
        return f"{self.state_name}"

    def save(self, *args, **kwargs):
        self.state_name = self.state_name.title()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_users_state'
        unique_together = [['state_name', 'country']]
        verbose_name = _('State')
        verbose_name_plural = _('States')


class CityModel(TimeStampedModel):
    city_name = models.CharField(
        _('City Name'),
        max_length=100,
    )

    state = models.ForeignKey(
        StateModel,
        on_delete=models.CASCADE,
        related_name='users_city_state'
    )

    def __str__(self) -> str:
        return f"{self.city_name} {self.state.state_name}"

    def save(self, *args, **kwargs):
        self.city_name = self.city_name.title()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_users_city'
        unique_together = [['city_name', 'state']]
        verbose_name = _('City')
        verbose_name_plural = _('Cities')


class AddressModel(TimeStampedModel):
    country = models.ForeignKey(
        CountryModel,
        on_delete=models.SET_NULL,
        null=True,
        related_name='users_address_country'
    )

    state = models.ForeignKey(
        StateModel,
        on_delete=models.SET_NULL,
        null=True,
        related_name='users_address_state'
    )

    city = models.ForeignKey(
        CityModel,
        on_delete=models.SET_NULL,
        null=True,
        related_name='users_address_city'
    )

    address_line_1 = EncryptedCharField(
        _('Address Line 1'),
        max_length=255
    )

    address_line_2 = EncryptedCharField(
        _('Address Line 2 (Optional)'),
        max_length=255,
        blank=True,
        null=True
    )

    postal_code = models.CharField(
        _('Postal/Zip Code'),
        max_length=10
    )

    def __str__(self) -> str:
        if self.address_line_2:
            return f"{self.country.country_name} {self.state.state_name} {self.city.city_name} {self.address_line_1} {self.address_line_2}"
        return f"{self.country.country_name} {self.state.state_name} {self.city.city_name} {self.address_line_1}"

    class Meta:
        db_table = 'apps_users_address'
        verbose_name = _('Address')
        verbose_name_plural = _('Addresses')


class UserPersonalInformationModel(TimeStampedModel):
    class GenderChoices(models.TextChoices):
        MALE = 'M', _('Male')
        FEMALE = 'F', _('Female')

    def passport_directory_path(instance, filename):
        return f"passport_images/{instance.id} - {instance.get_full_name()}/{date.today().year}-{date.today().month}-{date.today().day}/{filename}"

    def signature_directory_path(instance, filename):
        return f"signature_images/{instance.id} - {instance.get_full_name()}/{date.today().year}-{date.today().month}-{date.today().day}/{filename}"

    def validate_birth_date(value):
        today = timezone.now().date()
        min_date = today - timedelta(days=18*365)

        if value > today:
            raise ValidationError(
                _('The date of birth cannot be a future date.')
            )

        if value < min_date:
            raise ValidationError(
                _('User must be at least 18 years of age.')
            )

    def default_birth_date():
        return timezone.now() - timedelta(days=18 * 365)

    def default_date_of_expiry():
        return timezone.now() + timedelta(days=365)

    id = models.UUIDField(
        'ID',
        default=uuid.uuid4,
        unique=True,
        primary_key=True,
        serialize=False,
        editable=False
    )

    user = models.OneToOneField(
        UserModel,
        on_delete=models.CASCADE,
        related_name='personal_information'
    )

    birth_date = EncryptedDateField(
        _('Birth Date'),
        validators=[validate_birth_date],
        default=default_birth_date,
    )

    gender = models.CharField(
        _('Gender'),
        max_length=1,
        choices=GenderChoices.choices,
        default=GenderChoices.MALE
    )

    citizenship_country = EncryptedCharField(
        _('Citizenship'),
        max_length=100,
    )

    passport_id = EncryptedCharField(
        _('Passport Identification'),
        max_length=20,
    )

    date_of_issue = models.DateField(
        _('Date of Issue'),
        default=timezone.now
    )

    issuing_authority = models.CharField(
        _('Issuing Authority'),
        max_length=100,
    )

    date_of_expiry = models.DateField(
        _('Date of Expiry'),
        default=default_date_of_expiry
    )

    addresses = models.ManyToManyField(
        AddressModel,
        related_name='personal_information',
        blank=True,
    )

    phone_number_code = models.CharField(
        _('Phone Number Code'),
        max_length=5,
    )

    phone_number = EncryptedCharField(
        _('Phone Number'),
        max_length=25,
    )

    passport_image = models.ImageField(
        _('Passport Image'),
        upload_to=passport_directory_path,
    )

    signature = models.ImageField(
        _('Beneficiary signature'),
        upload_to=signature_directory_path,
    )

    def __str__(self) -> str:
        return f"{self.user.get_full_name()}"

    def save(self, *args, **kwargs):
        self.issuing_authority = self.issuing_authority.title()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_users_userpersonalpnformation'
        verbose_name = _('User Personal Information')
        verbose_name_plural = _('User Personal Information')


auditlog.register(
    UserModel,
    serialize_data=True
)

auditlog.register(
    CountryModel,
    serialize_data=True
)

auditlog.register(
    StateModel,
    serialize_data=True
)

auditlog.register(
    CityModel,
    serialize_data=True
)

auditlog.register(
    AddressModel,
    serialize_data=True
)

auditlog.register(
    UserPersonalInformationModel,
    serialize_data=True
)
