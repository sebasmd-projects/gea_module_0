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
    # Solo para el documento resumen: el codigo de barras de uno de sus
    # miembros. El miembro concreto se indica en `member_code` (AEGIS-1...).
    MEMBER_BARCODE = 'MEMBER', _('Member barcode (summary only)')
    # QR de la pagina de anclaje: URL estable, se actualiza sola.
    ANCHOR_QR = 'ANCHOR', _('Anchor QR (summary only)')


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

    def placement_data(self) -> list:
        """Posiciones activas, en la forma que consume la vista previa."""
        return [
            {
                'kind': placement.kind,
                'anchor': placement.anchor,
                'offset_x': placement.offset_x,
                'offset_y': placement.offset_y,
                'width': placement.width,
                'height': placement.height,
                'kind_label': str(placement.get_kind_display()),
                'member_code': placement.member_code or '',
                # El valor crudo lo usa el JS para saber a que paginas aplica;
                # la etiqueta es solo para pintarla.
                'page_selector': placement.page_selector,
                'page_selector_label': str(
                    placement.get_page_selector_display()
                ),
                'page_numbers': placement.page_numbers or '',
            }
            for placement in self.placements.all()
            if placement.is_active
        ]

    @property
    def preview_data(self) -> str:
        """JSON listo para el atributo ``data-placements`` de una plantilla."""
        import json

        return json.dumps(self.placement_data())

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

    member_code = models.CharField(
        _('Member code'),
        max_length=30,
        blank=True,
        default='',
        help_text=_(
            'Only for the member barcode: which document of the summary this '
            'position carries (AEGIS-1, AEGIS-2…).'
        )
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

        if self.kind == CodeKindChoices.MEMBER_BARCODE and not self.member_code:
            errors['member_code'] = _(
                'A member barcode needs to say which document of the summary it '
                'carries.'
            )

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

    document = models.ForeignKey(
        'certificates.DocumentVerificationModel',
        on_delete=models.SET_NULL,
        verbose_name=_('Certified document'),
        related_name='code_registrations',
        blank=True,
        null=True,
        help_text=_(
            'Set when the code was issued as part of certifying a document.'
        )
    )

    @property
    def has_barcode(self) -> bool:
        """El payload es representable como Code128."""
        from .services.codes import validate_barcode_payload

        if not self.generated_barcode or not self.code_information:
            return False

        try:
            validate_barcode_payload(self.code_information)
        except Exception:
            return False

        return True

    def __str__(self) -> str:
        return self.reference

    def save(self, *args, **kwargs):
        self.reference = (self.reference or '').upper()
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'apps_code_gen_coderegistration'
        verbose_name = _('Code Registration')
        verbose_name_plural = _('Code Registrations')


class AnchorTypeChoices(models.TextChoices):
    RFC3161 = 'RFC3161', _('Timestamp authority (RFC 3161)')
    OPENTIMESTAMPS = 'OTS', _('OpenTimestamps (Bitcoin)')


class AnchorStatusChoices(models.TextChoices):
    PENDING = 'PENDING', _('Pending confirmation')
    CONFIRMED = 'CONFIRMED', _('Confirmed')
    FAILED = 'FAILED', _('Failed')


class CertificationAnchorModel(TimeStampedModel):
    """
    Prueba de que un hash existia en una fecha.

    Se ancla el **master hash** de un resumen, nunca un documento ni el
    payload: lo que sale de la plataforma es una sola cifra de 64 caracteres,
    y esa cifra compromete transitivamente a todos los miembros del resumen.

    Un mismo hash puede tener varios anclajes a la vez —una TSA cualificada y
    OpenTimestamps, por ejemplo— porque cubren fallos distintos: la TSA es el
    instrumento que un tribunal reconoce hoy, y Bitcoin la prueba que sigue en
    pie cuando el certificado de esa TSA haya caducado.
    """

    summary = models.ForeignKey(
        'certificates.AegisSummaryModel',
        on_delete=models.CASCADE,
        related_name='anchors',
        verbose_name=_('Summary')
    )

    anchor_type = models.CharField(
        _('Anchor type'),
        max_length=20,
        choices=AnchorTypeChoices.choices
    )

    payload_hash = models.CharField(
        _('Anchored hash'),
        max_length=64,
        db_index=True,
        help_text=_('The master hash at the moment it was anchored.')
    )

    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=AnchorStatusChoices.choices,
        default=AnchorStatusChoices.PENDING,
        db_index=True
    )

    proof = models.BinaryField(
        _('Proof'),
        blank=True,
        null=True,
        help_text=_('DER timestamp token, or the .ots proof file.')
    )

    provider = models.CharField(
        _('Provider'),
        max_length=255,
        blank=True,
        default=''
    )

    stamped_at = models.DateTimeField(
        _('Attested time'),
        blank=True,
        null=True,
        help_text=_('The time the anchor itself attests, not our clock.')
    )

    serial = models.CharField(
        _('Serial'),
        max_length=80,
        blank=True,
        default=''
    )

    detail = models.TextField(
        _('Detail'),
        blank=True,
        default=''
    )

    @property
    def is_confirmed(self) -> bool:
        return self.status == AnchorStatusChoices.CONFIRMED

    def __str__(self) -> str:
        return f'{self.get_anchor_type_display()} · {self.payload_hash[:16]}…'

    class Meta:
        db_table = 'apps_code_gen_certification_anchor'
        verbose_name = _('Certification anchor')
        verbose_name_plural = _('Certification anchors')
        ordering = ['-created']
        indexes = [
            models.Index(fields=['payload_hash']),
            models.Index(fields=['anchor_type', 'status']),
        ]
