# apps/project/specific/internal/code_gen/forms.py

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .constants import (CERTIFIABLE_EXTENSIONS, HASH_B64_DEFAULT_LENGTH,
                        HASH_B64_MAX_LENGTH, HASH_B64_MIN_LENGTH,
                        MAX_UPLOAD_BYTES, RANDOM_CODE_DEFAULT_LENGTH,
                        RANDOM_CODE_MAX_LENGTH, RANDOM_CODE_MIN_LENGTH)
from .models import StampLayoutModel, StampPlacementModel


QR_CONTENT_VERIFICATION = 'VERIFICATION'
QR_CONTENT_CODE = 'CODE'
QR_CONTENT_CUSTOM = 'CUSTOM'

QR_CONTENT_CHOICES = (
    (
        QR_CONTENT_VERIFICATION,
        _('Public verification URL (requires certifying a document)')
    ),
    (QR_CONTENT_CODE, _('The generated code itself')),
    (QR_CONTENT_CUSTOM, _('A custom URL or text')),
)


class CodeGeneratorForm(forms.Form):
    """
    Generador de codigos y, opcionalmente, certificacion de un documento.

    Los checkboxes componen el codigo en el orden canonico:

        NIT · texto libre · INICIALES_SECUENCIA · HASH · FECHA · ALEATORIO
    """

    # ------------------------------------------------------------------
    # Identificacion
    # ------------------------------------------------------------------
    reference = forms.CharField(
        label=_('Reference'),
        max_length=100,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('e.g. AEGIS Special Edition'),
            }
        )
    )

    description = forms.CharField(
        label=_('Description'),
        required=False,
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': _('Internal notes about this code'),
            }
        )
    )

    custom_text_input = forms.CharField(
        label=_('Custom text'),
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('Free text added to the code'),
            }
        )
    )

    # ------------------------------------------------------------------
    # Segmentos del codigo
    # ------------------------------------------------------------------
    include_nit = forms.BooleanField(
        label=_('NIT'),
        required=False,
        initial=True,
        help_text=_('Adds the tax ID of the firm at the beginning.')
    )

    include_initials_sequence = forms.BooleanField(
        label=_('Certificate initials + autonomous sequence'),
        required=False,
        initial=True,
        help_text=_(
            'Non-consecutive and non-repeating sequence, reserved by the '
            'platform.'
        )
    )

    initials = forms.CharField(
        label=_('Initials'),
        max_length=20,
        required=False,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': _('Derived from the reference if left empty'),
            }
        )
    )

    include_document_hash = forms.BooleanField(
        label=_('Document hash'),
        required=False,
        help_text=_(
            'Requires uploading the document. The code carries the base64 '
            'fingerprint of the original file.'
        )
    )

    hash_fragment_length = forms.IntegerField(
        label=_('Hash characters'),
        required=False,
        initial=HASH_B64_DEFAULT_LENGTH,
        min_value=HASH_B64_MIN_LENGTH,
        max_value=HASH_B64_MAX_LENGTH,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    include_date = forms.BooleanField(
        label=_('Date (DDMMYYYY)'),
        required=False,
        initial=True
    )

    include_random_code = forms.BooleanField(
        label=_('Unique random code'),
        required=False,
        initial=True
    )

    random_code_length = forms.IntegerField(
        label=_('Random code length'),
        required=False,
        initial=RANDOM_CODE_DEFAULT_LENGTH,
        min_value=RANDOM_CODE_MIN_LENGTH,
        max_value=RANDOM_CODE_MAX_LENGTH,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

    # ------------------------------------------------------------------
    # Simbolos
    # ------------------------------------------------------------------
    generate_barcode = forms.BooleanField(
        label=_('Generate barcode (Code128)'),
        required=False,
        initial=True,
        help_text=_(
            'Only letters, digits, spaces and . _ - are allowed. URLs cannot '
            'be encoded in a barcode.'
        )
    )

    generate_qr = forms.BooleanField(
        label=_('Generate QR code'),
        required=False,
        initial=True
    )

    qr_content = forms.ChoiceField(
        label=_('QR content'),
        required=False,
        choices=QR_CONTENT_CHOICES,
        initial=QR_CONTENT_VERIFICATION,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    qr_custom_value = forms.CharField(
        label=_('Custom QR content'),
        required=False,
        max_length=900,
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'https://...',
            }
        )
    )

    # ------------------------------------------------------------------
    # Certificacion del documento
    # ------------------------------------------------------------------
    source_file = forms.FileField(
        label=_('Original document (without codes)'),
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                'class': 'form-control',
                'accept': ','.join(CERTIFIABLE_EXTENSIONS),
            }
        ),
        # El texto de ayuda se interpola en __init__: hacerlo aqui evaluaria
        # la cadena perezosa en el idioma activo al importar el modulo, que
        # no es el del usuario.
    )

    certify_document = forms.BooleanField(
        label=_('Certify this document'),
        required=False,
        help_text=_(
            'Embeds the codes in the PDF, computes its fingerprints and issues '
            'the distributable digital copy.'
        )
    )

    document_title = forms.CharField(
        label=_('Document title'),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    certificate_type = forms.ChoiceField(
        label=_('Certificate type'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    stamp_layout = forms.ModelChoiceField(
        label=_('Stamp layout'),
        required=False,
        queryset=StampLayoutModel.objects.filter(is_active=True),
        empty_label=_('Default layout'),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    issued_at = forms.DateField(
        label=_('Issued at'),
        required=False,
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'}
        )
    )

    expires_at = forms.DateField(
        label=_('Expires at'),
        required=False,
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'}
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from apps.project.specific.documents.certificates.models import \
            DocumentCertificateTypeChoices

        self.fields['certificate_type'].choices = (
            DocumentCertificateTypeChoices.choices
        )
        self.fields['certificate_type'].initial = (
            DocumentCertificateTypeChoices.AEGIS
        )

        self.fields['source_file'].help_text = (
            _('Accepted formats: %(formats)s.')
            % {'formats': ', '.join(CERTIFIABLE_EXTENSIONS)}
        )

        # Que es y donde se ve: sale impreso en la pagina publica de
        # verificacion, asi que no es una etiqueta interna.
        self.fields['certificate_type'].help_text = _(
            'What kind of document this is. It is shown on the public '
            'verification page, under the document title. Use "Asset '
            'Certificate (AEGIS)" for the certificates of a box of assets, '
            'and "Generic Document" for anything else.'
        )

    # ------------------------------------------------------------------
    # Validacion
    # ------------------------------------------------------------------
    def clean_source_file(self):
        uploaded = self.cleaned_data.get('source_file')

        if not uploaded:
            return uploaded

        name = (uploaded.name or '').lower()

        if not name.endswith(CERTIFIABLE_EXTENSIONS):
            raise ValidationError(
                _('Only these formats can be certified: %(formats)s.')
                % {'formats': ', '.join(CERTIFIABLE_EXTENSIONS)}
            )

        if uploaded.size > MAX_UPLOAD_BYTES:
            raise ValidationError(
                _('The file is too large. The maximum is %(size)s MB.')
                % {'size': MAX_UPLOAD_BYTES // (1024 * 1024)}
            )

        return uploaded

    def clean(self):
        cleaned = super().clean()

        source_file = cleaned.get('source_file')

        if cleaned.get('include_document_hash') and not source_file:
            self.add_error(
                'source_file',
                _('Upload the document to include its hash in the code.')
            )

        if cleaned.get('certify_document'):
            if not source_file:
                self.add_error(
                    'source_file',
                    _('Upload the document you want to certify.')
                )

            if not cleaned.get('document_title'):
                cleaned['document_title'] = cleaned.get('reference', '')[:200]

            if not cleaned.get('issued_at'):
                cleaned['issued_at'] = timezone.localdate()

        if not cleaned.get('generate_barcode') and not cleaned.get('generate_qr'):
            raise ValidationError(
                _('Select at least one symbol to generate: barcode or QR.')
            )

        if cleaned.get('generate_qr'):
            qr_content = cleaned.get('qr_content') or QR_CONTENT_VERIFICATION

            if qr_content == QR_CONTENT_CUSTOM and not cleaned.get('qr_custom_value'):
                self.add_error(
                    'qr_custom_value',
                    _('Enter the content for the QR code.')
                )

            if qr_content == QR_CONTENT_VERIFICATION and not cleaned.get('certify_document'):
                self.add_error(
                    'qr_content',
                    _(
                        'The public verification URL only exists once the '
                        'document is certified. Certify the document or choose '
                        'another QR content.'
                    )
                )

        return cleaned


class StampLayoutForm(forms.ModelForm):
    """Edicion de una disposicion de estampado desde el dashboard."""

    class Meta:
        model = StampLayoutModel
        fields = ('name', 'description', 'is_default', 'is_active')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 2}
            ),
            'is_default': forms.CheckboxInput(
                attrs={'class': 'form-check-input'}
            ),
            'is_active': forms.CheckboxInput(
                attrs={'class': 'form-check-input'}
            ),
        }


class StampPlacementForm(forms.ModelForm):
    """Una posicion dentro de la disposicion."""

    class Meta:
        model = StampPlacementModel
        fields = (
            'kind',
            'page_selector',
            'page_numbers',
            'anchor',
            'offset_x',
            'offset_y',
            'width',
            'height',
            'opacity',
            'is_active',
        )
        widgets = {
            'kind': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'page_selector': forms.Select(
                attrs={'class': 'form-select form-select-sm'}
            ),
            'page_numbers': forms.TextInput(
                attrs={'class': 'form-control form-control-sm',
                       'placeholder': '1, 3'}
            ),
            'anchor': forms.Select(
                attrs={'class': 'form-select form-select-sm'}
            ),
            'offset_x': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'step': '0.5'}
            ),
            'offset_y': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'step': '0.5'}
            ),
            'width': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'step': '0.5'}
            ),
            'height': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm', 'step': '0.5'}
            ),
            'opacity': forms.NumberInput(
                attrs={'class': 'form-control form-control-sm',
                       'step': '0.05', 'min': '0.05', 'max': '1'}
            ),
            'is_active': forms.CheckboxInput(
                attrs={'class': 'form-check-input'}
            ),
        }


StampPlacementFormSet = inlineformset_factory(
    StampLayoutModel,
    StampPlacementModel,
    form=StampPlacementForm,
    fk_name='layout',
    extra=1,
    can_delete=True,
)


class AegisSummaryForm(forms.ModelForm):
    """
    Alta de una caja AEGIS fuera del admin.

    Solo pide lo que hace falta para empezar a componerla: el resto -- codigo
    publico, secuencia, sello, documento resumen -- lo pone la plataforma, y
    los miembros se eligen ya en el compositor.
    """

    class Meta:
        from apps.project.specific.documents.certificates.models import \
            AegisSummaryModel

        model = AegisSummaryModel
        fields = ('title', 'asset', 'asset_label', 'issued_at')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'asset_label': forms.TextInput(attrs={'class': 'form-control'}),
            'issued_at': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from apps.project.specific.assets_management.assets.models import \
            AssetModel

        self.fields['asset'].queryset = (
            AssetModel.objects
            .filter(is_active=True)
            .select_related('asset_name', 'category')
            .order_by('asset_name__es_name')
        )
        self.fields['asset'].required = False
        self.fields['asset'].empty_label = _('— none —')

        # El catalogo es largo: sin buscador no se encuentra nada.
        self.fields['asset'].widget.attrs.update({
            'class': 'form-select',
            'data-searchable': '1',
            'data-search-placeholder': _('Search asset…'),
            'data-search-empty': _('No asset matches.'),
        })

        self.fields['title'].help_text = _(
            'How this box is identified internally, e.g. "AEGIS box - '
            'Zimbabwe gold micro-ingots".'
        )
        self.fields['asset_label'].help_text = _(
            'Optional. Readable name printed on the summary. The binding is '
            'made through the asset UUID, never through this text.'
        )
        self.fields['issued_at'].help_text = _(
            'Issue date printed on the summary document.'
        )

    def clean(self):
        cleaned = super().clean()

        # Si se eligio un activo y no se escribio etiqueta, se rellena sola:
        # es solo un texto legible, el vinculo real va por el UUID.
        asset = cleaned.get('asset')

        if asset and not (cleaned.get('asset_label') or '').strip():
            cleaned['asset_label'] = str(asset)[:200]

        return cleaned
