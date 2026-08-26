# apps/project/specific/internal/code_gen/models.py

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel

from .constants import (DEFAULT_MARGIN_PT, DEFAULT_QR_SIZE_PT,
                        SEQUENCE_DEFAULT_NAME, SEQUENCE_MODULUS,
                        SEQUENCE_MULTIPLIER, SEQUENCE_PAD)


class CodeKindChoices(models.TextChoices):
    BARCODE = 'BARCODE', _('Barcode (Code128)')
    QR = 'QR', _('QR code')


class PageSelectorChoices(models.TextChoices):
    FIRST = 'FIRST', _('First page')
    LAST = 'LAST', _('Last page')
    ALL = 'ALL', _('Every page')
    NUMBERS = 'NUMBERS', _('Specific pages')


class AnchorChoices(models.TextChoices):
    BOTTOM_LEFT = 'BL', _('Bottom left')
    BOTTOM_CENTER = 'BC', _('Bottom center')
    BOTTOM_RIGHT = 'BR', _('Bottom right')
    TOP_LEFT = 'TL', _('Top left')
    TOP_CENTER = 'TC', _('Top center')
    TOP_RIGHT = 'TR', _('Top right')


class CodeSequenceModel(TimeStampedModel):
    """
    Contador interno de la secuencia autonoma.

    El valor publicado nunca es el contador: se aplica una permutacion
    multiplicativa modular sobre el, de modo que la serie emitida no es
    consecutiva y no se repite dentro del ciclo.
    """

    name = models.CharField(
        _('Sequence name'),
        max_length=50,
        unique=True,
        default=SEQUENCE_DEFAULT_NAME
    )

    counter = models.PositiveBigIntegerField(
        _('Internal counter'),
        default=0
    )

    def __str__(self) -> str:
        return f'{self.name} ({self.counter})'

    @classmethod
    def next_value(cls, name: str = SEQUENCE_DEFAULT_NAME) -> str:
        """
        Reserva y devuelve el siguiente valor de la secuencia.

        Returns:
            str: valor de SEQUENCE_PAD digitos.
        """
        with transaction.atomic():
            row, _created = (
                cls.objects
                .select_for_update()
                .get_or_create(name=name)
            )
            row.counter = (row.counter + 1) % SEQUENCE_MODULUS
            row.save(update_fields=['counter', 'updated'])
            counter = row.counter

        value = (counter * SEQUENCE_MULTIPLIER) % SEQUENCE_MODULUS
        return str(value).zfill(SEQUENCE_PAD)

    class Meta:
        db_table = 'apps_code_gen_sequence'
        verbose_name = _('Code Sequence')
        verbose_name_plural = _('Code Sequences')


class StampLayoutModel(TimeStampedModel):
    """
    Plantilla reutilizable con las posiciones donde se incrustan los codigos
    dentro del PDF (los espacios reservados del certificado).
    """

    name = models.CharField(
        _('Layout name'),
        max_length=100,
        unique=True
    )

    description = models.TextField(
        _('Description'),
        blank=True,
        null=True
    )

    is_default = models.BooleanField(
        _('Use as default layout'),
        default=False
    )

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            (
                type(self).objects
                .exclude(pk=self.pk)
                .filter(is_default=True)
                .update(is_default=False)
            )

    @classmethod
    def get_default(cls):
        return cls.objects.filter(is_default=True, is_active=True).first()

    class Meta:
        db_table = 'apps_code_gen_stamp_layout'
        verbose_name = _('Stamp Layout')
        verbose_name_plural = _('Stamp Layouts')


class StampPlacementModel(TimeStampedModel):
    """
    Una posicion concreta dentro de un layout.

    Las coordenadas van en puntos PostScript (72 pt = 1 pulgada) y se miden
    desde la esquina indicada en anchor, hacia el interior de la pagina.
    """

    layout = models.ForeignKey(
        StampLayoutModel,
        on_delete=models.CASCADE,
        related_name='placements',
        verbose_name=_('Layout')
    )

    kind = models.CharField(
        _('Code kind'),
        max_length=10,
        choices=CodeKindChoices.choices,
        default=CodeKindChoices.QR
    )

    page_selector = models.CharField(
        _('Pages'),
        max_length=10,
        choices=PageSelectorChoices.choices,
        default=PageSelectorChoices.LAST
    )

    page_numbers = models.CharField(
        _('Page numbers'),
        max_length=100,
        blank=True,
        null=True,
        help_text=_(
            'Comma separated, 1-based. Only used with the specific pages selector.'
        )
    )

    anchor = models.CharField(
        _('Anchor'),
        max_length=2,
        choices=AnchorChoices.choices,
        default=AnchorChoices.BOTTOM_RIGHT
    )

    offset_x = models.FloatField(
        _('Horizontal offset (pt)'),
        default=DEFAULT_MARGIN_PT
    )

    offset_y = models.FloatField(
        _('Vertical offset (pt)'),
        default=DEFAULT_MARGIN_PT
    )

    width = models.FloatField(
        _('Width (pt)'),
        default=DEFAULT_QR_SIZE_PT,
        validators=[MinValueValidator(1.0)]
    )

    height = models.FloatField(
        _('Height (pt)'),
        default=DEFAULT_QR_SIZE_PT,
        validators=[MinValueValidator(1.0)]
    )

    opacity = models.FloatField(
        _('Opacity'),
        default=1.0
    )

    def clean(self):
        errors = {}

        if self.page_selector == PageSelectorChoices.NUMBERS and not self.page_numbers:
            errors['page_numbers'] = _(
                'Provide at least one page number for this selector.'
            )

        if self.page_numbers:
            for token in str(self.page_numbers).split(','):
                token = token.strip()
                if not token:
                    continue
                if not token.isdigit() or int(token) < 1:
                    errors['page_numbers'] = _(
                        'Page numbers must be positive integers separated by commas.'
                    )
                    break

        if not 0.0 < float(self.opacity or 0) <= 1.0:
            errors['opacity'] = _('Opacity must be greater than 0 and up to 1.')

        if errors:
            raise ValidationError(errors)

    def resolved_pages(self, page_count: int) -> list:
        """Devuelve los indices de pagina (base 0) a los que aplica."""
        if self.page_selector == PageSelectorChoices.FIRST:
            return [0] if page_count else []

        if self.page_selector == PageSelectorChoices.LAST:
            return [page_count - 1] if page_count else []

        if self.page_selector == PageSelectorChoices.ALL:
            return list(range(page_count))

        pages = []
        for token in str(self.page_numbers or '').split(','):
            token = token.strip()
            if token.isdigit():
                index = int(token) - 1
                if 0 <= index < page_count:
                    pages.append(index)
        return pages

    def __str__(self) -> str:
        return f'{self.layout} - {self.get_kind_display()}'

    class Meta:
        db_table = 'apps_code_gen_stamp_placement'
        verbose_name = _('Stamp Placement')
        verbose_name_plural = _('Stamp Placements')
        ordering = ['default_order', 'id']


class CodeRegistrationModel(TimeStampedModel):
    """
    Registro historico de cada codigo emitido por el generador.
    """

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

    initials = models.CharField(
        _('Certificate initials'),
        max_length=20,
        blank=True,
        null=True
    )

    sequence = models.CharField(
        _('Autonomous sequence'),
        max_length=20,
        blank=True,
        null=True,
        db_index=True
    )

    random_code = models.CharField(
        _('Unique random code'),
        max_length=32,
        blank=True,
        null=True,
        db_index=True
    )

    source_file_hash = models.CharField(
        _('Source file hash (SHA-256)'),
        max_length=64,
        blank=True,
        null=True,
        db_index=True
    )

    hash_fragment = models.CharField(
        _('Hash fragment (base64)'),
        max_length=64,
        blank=True,
        null=True
    )

    generated_barcode = models.BooleanField(
        _('Barcode generated'),
        default=False
    )

    generated_qr = models.BooleanField(
        _('QR generated'),
        default=False
    )

    qr_payload = models.TextField(
        _('QR payload'),
        blank=True,
        null=True
    )

    def __str__(self) -> str:
        return self.reference

    def save(self, *args, **kwargs):
        self.reference = (self.reference or '').upper()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_code_gen_coderegistration'
        verbose_name = _('Code Registration')
        verbose_name_plural = _('Code Registrations')
