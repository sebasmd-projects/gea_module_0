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

from apps.common.utils.functions import sha256_hex
from apps.common.utils.models import TimeStampedModel


class UserModel(TimeStampedModel, AbstractUser):
    class UserTypeChoices(models.TextChoices):
        INTERMEDIARY = 'I', _('Intermediary')
        REPRESENTATIVE = 'R', _('Representative')
        HOLDER = 'H', _('Holder')
        BUYER = 'B', _('Buyer')
    
    class PhoneCodeChoices(models.TextChoices):
        COLOMBIA = "57-CO", _("+57 Colombia")
        UNITED_STATES = "1-US", _("+1 United States")
        AMERICAN_SAMOA = "1-AS", _("+1 American Samoa")
        ANGUILLA = "1-AI", _("+1 Anguilla")
        ANTIGUA_AND_BARBUDA = "1-AG", _("+1 Antigua and Barbuda")
        ARGENTINA = "54-AR", _("+54 Argentina")
        BAHAMAS = "1-BS", _("+1 Bahamas")
        BARBADOS = "1-BB", _("+1 Barbados")
        BELIZE = "501-BZ", _("+501 Belize")
        BERMUDA = "1-BM", _("+1 Bermuda")
        BOLIVIA = "591-BO", _("+591 Bolivia")
        BRAZIL = "55-BR", _("+55 Brazil")
        BRITISH_VIRGIN_ISLANDS = "1-VG", _("+1 British Virgin Islands")
        CANADA = "1-CA", _("+1 Canada")
        CAYMAN_ISLANDS = "1-KY", _("+1 Cayman Islands")
        CHILE = "56-CL", _("+56 Chile")
        COSTA_RICA = "506-CR", _("+506 Costa Rica")
        DOMINICA = "1-DM", _("+1 Dominica")
        DOMINICAN_REPUBLIC = "1-DO", _("+1 Dominican Republic")
        ECUADOR = "593-EC", _("+593 Ecuador")
        EL_SALVADOR = "503-SV", _("+503 El Salvador")
        FALKLAND_ISLANDS = "500-FK", _("+500 Falkland Islands")
        FRENCH_GUIANA = "594-GF", _("+594 French Guiana")
        GREENLAND = "299-GL", _("+299 Greenland")  # Dinamarca
        GRENADA = "1-GD", _("+1 Grenada")
        GUAM = "1-GU", _("+1 Guam")
        GUATEMALA = "502-GT", _("+502 Guatemala")
        GUYANA = "592-GY", _("+592 Guyana")
        HONDURAS = "504-HN", _("+504 Honduras")
        JAMAICA = "1-JM", _("+1 Jamaica")
        MEXICO = "52-MX", _("+52 Mexico")
        MONTSERRAT = "1-MS", _("+1 Montserrat")
        NICARAGUA = "505-NI", _("+505 Nicaragua")
        NORTHERN_MARIANA_ISLANDS = "1-MP", _("+1 Northern Mariana Islands")
        PANAMA = "507-PA", _("+507 Panama")
        PARAGUAY = "595-PY", _("+595 Paraguay")
        PERU = "51-PE", _("+51 Peru")
        PUERTO_RICO = "1-PR", _("+1 Puerto Rico")
        SAINT_KITTS_AND_NEVIS = "1-KN", _("+1 Saint Kitts and Nevis")
        SAINT_LUCIA = "1-LC", _("+1 Saint Lucia")
        SAINT_VINCENT_AND_THE_GRENADINES = "1-VC", _("+1 Saint Vincent and the Grenadines")
        SINT_MAARTEN = "1-SX", _("+1 Sint Maarten (Dutch part)")
        SURINAME = "597-SR", _("+597 Suriname")
        TRINIDAD_AND_TOBAGO = "1-TT", _("+1 Trinidad and Tobago")
        TURKS_AND_CAICOS_ISLANDS = "1-TC", _("+1 Turks and Caicos Islands")
        URUGUAY = "598-UY", _("+598 Uruguay")
        US_VIRGIN_ISLANDS = "1-VI", _("+1 United States Virgin Islands")
        VENEZUELA = "58-VE", _("+58 Venezuela")
        
        # --- Europa ---
        ALBANIA = "355-AL", _("+355 Albania")
        ANDORRA = "376-AD", _("+376 Andorra")
        AUSTRIA = "43-AT", _("+43 Austria")
        BELARUS = "375-BY", _("+375 Belarus")
        BELGIUM = "32-BE", _("+32 Belgium")
        BOSNIA_AND_HERZEGOVINA = "387-BA", _("+387 Bosnia and Herzegovina")
        BULGARIA = "359-BG", _("+359 Bulgaria")
        CROATIA = "385-HR", _("+385 Croatia")
        CZECHIA = "420-CZ", _("+420 Czechia")
        DENMARK = "45-DK", _("+45 Denmark")
        ESTONIA = "372-EE", _("+372 Estonia")
        FINLAND = "358-FI", _("+358 Finland")
        FRANCE = "33-FR", _("+33 France")
        GERMANY = "49-DE", _("+49 Germany")
        GREECE = "30-GR", _("+30 Greece")
        GUERNSEY = "44-GG", _("+44 Guernsey")
        HUNGARY = "36-HU", _("+36 Hungary")
        ICELAND = "354-IS", _("+354 Iceland")
        IRELAND = "353-IE", _("+353 Ireland")
        ISLE_OF_MAN = "44-IM", _("+44 Isle of Man")
        ITALY = "39-IT", _("+39 Italy")
        JERSEY = "44-JE", _("+44 Jersey")
        KOSOVO = "383-XK", _("+383 Kosovo")
        LATVIA = "371-LV", _("+371 Latvia")
        LIECHTENSTEIN = "423-LI", _("+423 Liechtenstein")
        LITHUANIA = "370-LT", _("+370 Lithuania")
        LUXEMBOURG = "352-LU", _("+352 Luxembourg")
        MOLDOVA = "373-MD", _("+373 Moldova")
        MONACO = "377-MC", _("+377 Monaco")
        MONTENEGRO = "382-ME", _("+382 Montenegro")
        NETHERLANDS = "31-NL", _("+31 Netherlands")
        NORTH_MACEDONIA = "389-MK", _("+389 North Macedonia")
        NORWAY = "47-NO", _("+47 Norway")
        POLAND = "48-PL", _("+48 Poland")
        PORTUGAL = "351-PT", _("+351 Portugal")
        ROMANIA = "40-RO", _("+40 Romania")
        SAN_MARINO = "378-SM", _("+378 San Marino")
        SERBIA = "381-RS", _("+381 Serbia")
        SLOVAKIA = "421-SK", _("+421 Slovakia")
        SLOVENIA = "386-SI", _("+386 Slovenia")
        SPAIN = "34-ES", _("+34 Spain")
        SWEDEN = "46-SE", _("+46 Sweden")
        SWITZERLAND = "41-CH", _("+41 Switzerland")
        UKRAINE = "380-UA", _("+380 Ukraine")
        UNITED_KINGDOM = "44-GB", _("+44 United Kingdom")
        VATICAN_CITY = "39-VA", _("+39 Vatican City")
        # Rusia y Kazajistán comparten +7
        RUSSIA = "7-RU", _("+7 Russia")
        KAZAKHSTAN = "7-KZ", _("+7 Kazakhstan")
        
            # --- África ---
        ALGERIA = "213-DZ", _("+213 Algeria")
        ANGOLA = "244-AO", _("+244 Angola")
        BENIN = "229-BJ", _("+229 Benin")
        BOTSWANA = "267-BW", _("+267 Botswana")
        BURKINA_FASO = "226-BF", _("+226 Burkina Faso")
        BURUNDI = "257-BI", _("+257 Burundi")
        CAMEROON = "237-CM", _("+237 Cameroon")
        CENTRAL_AFRICAN_REPUBLIC = "236-CF", _("+236 Central African Republic")
        CHAD = "235-TD", _("+235 Chad")
        COMOROS = "269-KM", _("+269 Comoros")
        CONGO = "242-CG", _("+242 Republic of the Congo")
        DJIBOUTI = "253-DJ", _("+253 Djibouti")
        DRC = "243-CD", _("+243 Democratic Republic of the Congo")
        EGYPT = "20-EG", _("+20 Egypt")
        EQUATORIAL_GUINEA = "240-GQ", _("+240 Equatorial Guinea")
        ERITREA = "291-ER", _("+291 Eritrea")
        ESWATINI = "268-SZ", _("+268 Eswatini")
        ETHIOPIA = "251-ET", _("+251 Ethiopia")
        GABON = "241-GA", _("+241 Gabon")
        GAMBIA = "220-GM", _("+220 Gambia")
        GHANA = "233-GH", _("+233 Ghana")
        GUINEA = "224-GN", _("+224 Guinea")
        GUINEA_BISSAU = "245-GW", _("+245 Guinea-Bissau")
        IVORY_COAST = "225-CI", _("+225 Ivory Coast")
        KENYA = "254-KE", _("+254 Kenya")
        LESOTHO = "266-LS", _("+266 Lesotho")
        LIBERIA = "231-LR", _("+231 Liberia")
        LIBYA = "218-LY", _("+218 Libya")
        MADAGASCAR = "261-MG", _("+261 Madagascar")
        MALAWI = "265-MW", _("+265 Malawi")
        MALI = "223-ML", _("+223 Mali")
        MAURITANIA = "222-MR", _("+222 Mauritania")
        MAURITIUS = "230-MU", _("+230 Mauritius")
        MAYOTTE = "262-YT", _("+262 Mayotte")
        MOROCCO = "212-MA", _("+212 Morocco")
        MOZAMBIQUE = "258-MZ", _("+258 Mozambique")
        NAMIBIA = "264-NA", _("+264 Namibia")
        NIGER = "227-NE", _("+227 Niger")
        NIGERIA = "234-NG", _("+234 Nigeria")
        REUNION = "262-RE", _("+262 Réunion")
        RWANDA = "250-RW", _("+250 Rwanda")
        SENEGAL = "221-SN", _("+221 Senegal")
        SEYCHELLES = "248-SC", _("+248 Seychelles")
        SIERRA_LEONE = "232-SL", _("+232 Sierra Leone")
        SOMALIA = "252-SO", _("+252 Somalia")
        SOUTH_AFRICA = "27-ZA", _("+27 South Africa")
        SOUTH_SUDAN = "211-SS", _("+211 South Sudan")
        SUDAN = "249-SD", _("+249 Sudan")
        TANZANIA = "255-TZ", _("+255 Tanzania")
        TOGO = "228-TG", _("+228 Togo")
        TUNISIA = "216-TN", _("+216 Tunisia")
        UGANDA = "256-UG", _("+256 Uganda")
        WESTERN_SAHARA = "212-EH", _("+212 Western Sahara")
        ZAMBIA = "260-ZM", _("+260 Zambia")
        ZIMBABWE = "263-ZW", _("+263 Zimbabwe")
        
        # --- Asia ---
        AFGHANISTAN = "93-AF", _("+93 Afghanistan")
        BANGLADESH = "880-BD", _("+880 Bangladesh")
        BHUTAN = "975-BT", _("+975 Bhutan")
        BRUNEI = "673-BN", _("+673 Brunei")
        CAMBODIA = "855-KH", _("+855 Cambodia")
        CHINA = "86-CN", _("+86 China")
        CYPRUS = "357-CY", _("+357 Cyprus")
        EAST_TIMOR = "670-TL", _("+670 East Timor")
        INDIA = "91-IN", _("+91 India")
        INDONESIA = "62-ID", _("+62 Indonesia")
        IRAN = "98-IR", _("+98 Iran")
        IRAQ = "964-IQ", _("+964 Iraq")
        ISRAEL = "972-IL", _("+972 Israel")
        JAPAN = "81-JP", _("+81 Japan")
        JORDAN = "962-JO", _("+962 Jordan")
        LAOS = "856-LA", _("+856 Laos")
        LEBANON = "961-LB", _("+961 Lebanon")
        MALAYSIA = "60-MY", _("+60 Malaysia")
        MALDIVES = "960-MV", _("+960 Maldives")
        MONGOLIA = "976-MN", _("+976 Mongolia")
        MYANMAR = "95-MM", _("+95 Myanmar")
        NEPAL = "977-NP", _("+977 Nepal")
        NORTH_KOREA = "850-KP", _("+850 North Korea")
        PAKISTAN = "92-PK", _("+92 Pakistan")
        PALESTINE = "970-PS", _("+970 Palestine")
        PHILIPPINES = "63-PH", _("+63 Philippines")
        SINGAPORE = "65-SG", _("+65 Singapore")
        SOUTH_KOREA = "82-KR", _("+82 South Korea")
        SRI_LANKA = "94-LK", _("+94 Sri Lanka")
        SYRIA = "963-SY", _("+963 Syria")
        THAILAND = "66-TH", _("+66 Thailand")
        TURKEY = "90-TR", _("+90 Turkey")
        VIETNAM = "84-VN", _("+84 Vietnam")
        
        # --- Oceanía ---
        AUSTRALIA = "61-AU", _("+61 Australia")
        CHRISTMAS_ISLAND = "61-CX", _("+61 Christmas Island")
        COCOS_KEELING_ISLANDS = "61-CC", _("+61 Cocos (Keeling) Islands")
        FIJI = "679-FJ", _("+679 Fiji")
        FRENCH_POLYNESIA = "689-PF", _("+689 French Polynesia")
        KIRIBATI = "686-KI", _("+686 Kiribati")
        MARSHALL_ISLANDS = "692-MH", _("+692 Marshall Islands")
        MICRONESIA = "691-FM", _("+691 Micronesia (Federated States)")
        NAURU = "674-NR", _("+674 Nauru")
        NEW_CALEDONIA = "687-NC", _("+687 New Caledonia")
        NEW_ZEALAND = "64-NZ", _("+64 New Zealand")
        PALAU = "680-PW", _("+680 Palau")
        PAPUA_NEW_GUINEA = "675-PG", _("+675 Papua New Guinea")
        SAMOA = "685-WS", _("+685 Samoa")
        SOLOMON_ISLANDS = "677-SB", _("+677 Solomon Islands")
        TONGA = "676-TO", _("+676 Tonga")
        TUVALU = "688-TV", _("+688 Tuvalu")
        VANUATU = "678-VU", _("+678 Vanuatu")
        WALLIS_AND_FUTUNA = "681-WF", _("+681 Wallis and Futuna")

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
    
    phone_number_code = models.CharField(
        _('Phone Number Code'),
        max_length=7,
        choices=PhoneCodeChoices.choices,
        default=PhoneCodeChoices.COLOMBIA,
    )

    phone_number = EncryptedCharField(
        _('Phone Number'),
        max_length=25,
        default='',
    )
    
    referred = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='referrals'
    )
    
    is_referred = models.BooleanField(
        _('Is Referred'),
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
        return f"({self.user_type}) {self.get_full_name()} ({self.username})"

    def save(self, *args, **kwargs):
        email = self.email.lower().strip()
        self.first_name = self.first_name.title().strip()
        self.last_name = self.last_name.title().strip()
        self.username = self.username.lower().strip()
        self.email = email
        self.email_hash = sha256_hex(email.strip().lower())
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
        permissions = [
            ('can_view_buyer', _('Can view Buyer dashboard')),
            ('can_view_holder', _('Can view Suppliers Area dashboard')),
            ('can_view_all_users', _('Can view all users')),
            ('can_view_buyers', _('Can view only buyers users')),
            ('can_view_holders', _('Can view only holders users')),
            ('can_change_password', _('Can change user password')),
            ('can_change_all_passwords', _('Can change all users passwords')),
            ('can_change_users_personal_info', _('Can change users personal information')),
            ('can_change_users_contact_info', _('Can change users contact information')),
            ('can_change_users_referred', _('Can change users referred by field')),
            ('can_verify_holders', _('Can verify holders')),
            ('can_deactivate_users', _('Can deactivate users')),
        ]


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
        primary_key=True,
        editable=False,
        max_length=36,
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
