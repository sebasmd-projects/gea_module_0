# apps/project/specific/internal/code_gen/tests/test_generator_custom_symbols.py
"""
Las tres piezas del generador de codigos que no dependian de "Code segments":

1. Generar solo un barcode o un QR con contenido propio ya no exige
   configurar segmentos que no se van a usar para nada
   (`CodeGeneratorView._issue_code`).
2. La vista previa puede pedir los simbolos con la carga real, no solo con
   una muestra de relleno (`api.preview_symbols`).
3. El logo del QR sigue siendo el favicon de GEA por defecto, pero se puede
   apagar o cambiar por una imagen propia (`services.render.resolve_qr_logo`,
   `CodeRegistrationModel.qr_logo_mode`).

    manage.py test apps.project.specific.internal.code_gen.tests.test_generator_custom_symbols \\
        --settings=app_core.settings_test
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.project.common.users.models import UserModel

from ..forms import CodeGeneratorForm
from ..models import CodeRegistrationModel, QRLogoModeChoices
from ..services.render import resolve_qr_logo

PASSWORD = 'pw-for-tests-123'


def png_bytes(color=(10, 20, 30, 255)) -> bytes:
    buffer = BytesIO()
    Image.new('RGBA', (16, 16), color).save(buffer, format='PNG')
    return buffer.getvalue()


class GeneratorPostTestCase(TestCase):

    def setUp(self):
        self.operator = UserModel.objects.create_user(
            username='ops-symbols', email='ops-symbols@example.com',
            password=PASSWORD, is_staff=True,
        )
        self.client.force_login(self.operator)
        self.url = reverse('code_gen:code_generate')

    def base_data(self, **overrides) -> dict:
        """
        Un envio minimo: sin ningun segmento marcado, sin certificar. Cada
        prueba solo añade lo que le interesa comprobar.
        """
        data = {
            'reference': 'Prueba de simbolo suelto',
            'description': '',
            'custom_text_input': '',
            # Los cuatro segmentos, deliberadamente sin marcar.
            'include_nit': '',
            'include_initials_sequence': '',
            'initials': '',
            'include_document_hash': '',
            'hash_fragment_length': 16,
            'include_date': '',
            'include_random_code': '',
            'random_code_length': 12,
            'generate_barcode': '',
            'barcode_content': 'COMPOSED',
            'barcode_custom_value': '',
            'generate_qr': '',
            'qr_content': 'CODE',
            'qr_custom_value': '',
            'qr_logo_mode': QRLogoModeChoices.DEFAULT,
            'certify_document': '',
            'document_title': '',
            'certificate_type': '',
            'holders': [],
        }
        data.update(overrides)
        return data


class TestABareSymbolDoesNotNeedSegments(GeneratorPostTestCase):

    def test_a_custom_barcode_does_not_require_any_segment(self):
        response = self.client.post(self.url, self.base_data(
            generate_barcode='on',
            barcode_content='CUSTOM',
            barcode_custom_value='HELLO-WORLD-123',
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(registration.code_information, 'HELLO-WORLD-123')

    def test_a_custom_qr_does_not_require_any_segment(self):
        response = self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/lo-que-sea',
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(
            registration.qr_payload, 'https://ejemplo.test/lo-que-sea'
        )

    def test_a_composed_barcode_without_any_segment_still_fails(self):
        """
        Lo que se relajo es la obligacion cuando no hace falta un codigo
        compuesto. Si se pide expresamente ("The code composed below") y no
        hay ningun segmento, el error sigue estando: no hay nada que
        componer.
        """
        response = self.client.post(self.url, self.base_data(
            generate_barcode='on',
            barcode_content='COMPOSED',
        ))

        self.assertEqual(response.status_code, 200)  # form_invalid: se repinta
        self.assertFalse(CodeRegistrationModel.objects.exists())

    def test_qr_content_code_still_needs_a_composed_code(self):
        response = self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CODE',
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CodeRegistrationModel.objects.exists())

    def test_qr_content_code_uses_the_composed_code_not_a_custom_barcode(self):
        """
        "The generated code itself" se refiere al codigo compuesto de
        segmentos, no al texto libre de un barcode en modo CUSTOM: son dos
        contenidos distintos aunque los dos se llamen "el codigo".
        """
        response = self.client.post(self.url, self.base_data(
            include_random_code='on',
            random_code_length=12,
            generate_barcode='on',
            barcode_content='CUSTOM',
            barcode_custom_value='TEXTO-LIBRE',
            generate_qr='on',
            qr_content='CODE',
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(registration.code_information, 'TEXTO-LIBRE')
        self.assertNotEqual(registration.qr_payload, 'TEXTO-LIBRE')
        self.assertTrue(registration.qr_payload)

    def test_certifying_rejects_a_custom_barcode(self):
        """
        Certificar siempre estampa el codigo institucional compuesto: un
        texto libre en el barcode dejaria el codigo impreso sin relacion con
        lo que el registro de certificacion guarda.
        """
        pdf_bytes = b'%PDF-1.4\n%mock pdf content\n'

        form = CodeGeneratorForm(data=self.base_data(
            certify_document='on',
            generate_barcode='on',
            barcode_content='CUSTOM',
            barcode_custom_value='TEXTO-LIBRE',
            document_title='Un documento',
        ), files={
            'source_file': SimpleUploadedFile(
                'doc.pdf', pdf_bytes, content_type='application/pdf'
            ),
        })

        self.assertFalse(form.is_valid())
        self.assertIn('barcode_content', form.errors)


class TestPreviewSymbolsReflectsTheRealPayload(TestCase):

    def setUp(self):
        self.operator = UserModel.objects.create_user(
            username='ops-preview', email='ops-preview@example.com',
            password=PASSWORD, is_staff=True,
        )
        self.client.force_login(self.operator)
        self.url = reverse('code_gen:preview_symbols')

    def test_the_barcode_sample_carries_the_given_payload(self):
        response = self.client.get(self.url, {'payload': 'ABC-123'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['symbols']['BARCODE']['payload'], 'ABC-123')

    def test_the_qr_sample_carries_the_given_payload(self):
        response = self.client.get(
            self.url, {'qr_payload': 'https://ejemplo.test/vivo'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['symbols']['QR']['payload'],
            'https://ejemplo.test/vivo',
        )

    def test_without_qr_payload_it_falls_back_to_the_public_base(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        # No es una cadena vacia: sigue apuntando a algun sitio por defecto.
        self.assertTrue(response.json()['symbols']['QR']['payload'])

    def test_an_outsider_cannot_reach_it(self):
        outsider = UserModel.objects.create_user(
            username='holder-preview', email='holder-preview@example.com',
            password=PASSWORD,
        )
        self.client.force_login(outsider)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)


class TestTheQRLogoIsOptionalAndChangeable(GeneratorPostTestCase):

    def test_the_default_mode_keeps_the_institutional_logo(self):
        response = self.client.post(self.url, self.base_data(
            generate_barcode='on',
            barcode_content='CUSTOM',
            barcode_custom_value='ABC',
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/',
            qr_logo_mode=QRLogoModeChoices.DEFAULT,
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(registration.qr_logo_mode, QRLogoModeChoices.DEFAULT)
        # Sin override: el favicon institucional sigue siendo el por defecto
        # de render_qr_png(), asi que no hace falta pasar ningun kwarg.
        self.assertEqual(registration.qr_render_kwargs(), {})

    def test_the_logo_can_be_turned_off(self):
        response = self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/',
            qr_logo_mode=QRLogoModeChoices.NONE,
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(registration.qr_logo_mode, QRLogoModeChoices.NONE)
        self.assertEqual(
            registration.qr_render_kwargs(), {'logo_static_path': None}
        )

    def test_the_logo_can_be_swapped_for_a_custom_image(self):
        upload = SimpleUploadedFile(
            'logo.png', png_bytes(), content_type='image/png'
        )

        response = self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/',
            qr_logo_mode=QRLogoModeChoices.CUSTOM,
            qr_logo_image=upload,
        ))

        self.assertEqual(response.status_code, 302)

        registration = CodeRegistrationModel.objects.get()
        self.assertEqual(registration.qr_logo_mode, QRLogoModeChoices.CUSTOM)
        self.assertTrue(registration.qr_logo_image)

        kwargs = registration.qr_render_kwargs()
        self.assertIsNone(kwargs.get('logo_static_path'))
        self.assertTrue(kwargs.get('logo_bytes'))

    def test_custom_mode_without_an_image_is_rejected(self):
        response = self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/',
            qr_logo_mode=QRLogoModeChoices.CUSTOM,
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(CodeRegistrationModel.objects.exists())

    def test_the_generated_code_detail_page_still_renders(self):
        """
        `CodeDetailView` vuelve a dibujar el QR desde el payload guardado; si
        `qr_render_kwargs()` no encajara con `render_qr_png()` la pagina
        caeria con un 500 en vez de mostrar el codigo.
        """
        upload = SimpleUploadedFile(
            'logo.png', png_bytes(), content_type='image/png'
        )

        self.client.post(self.url, self.base_data(
            generate_qr='on',
            qr_content='CUSTOM',
            qr_custom_value='https://ejemplo.test/',
            qr_logo_mode=QRLogoModeChoices.CUSTOM,
            qr_logo_image=upload,
        ))

        registration = CodeRegistrationModel.objects.get()

        response = self.client.get(
            reverse('code_gen:code_detail', args=[registration.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('qr_image', response.context)


class TestResolveQRLogo(TestCase):
    """Unidad pura, sin base de datos: la traduccion de modo a kwargs."""

    def test_default_changes_nothing(self):
        self.assertEqual(resolve_qr_logo('DEFAULT'), {})

    def test_none_turns_off_the_logo(self):
        self.assertEqual(resolve_qr_logo('NONE'), {'logo_static_path': None})

    def test_custom_without_bytes_falls_back_to_default(self):
        self.assertEqual(resolve_qr_logo('CUSTOM', None), {})

    def test_custom_with_bytes_uses_them(self):
        result = resolve_qr_logo('CUSTOM', b'fake-image-bytes')

        self.assertIsNone(result['logo_static_path'])
        self.assertEqual(result['logo_bytes'], b'fake-image-bytes')
