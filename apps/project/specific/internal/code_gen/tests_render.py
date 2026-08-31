# apps/project/specific/internal/code_gen/tests_render.py
"""
Que los simbolos salgan con el fondo transparente, tambien en el papel.

La transparencia habia que pedirla, y solo la pedia la vista previa. Todo lo
que se estampaba de verdad --el codigo del certificado, el del resumen, el de
cada miembro, los dos QR-- salia con un rectangulo blanco debajo que tapaba el
diseño del documento. Y como la vista previa si los dibujaba transparentes,
enseñaba una cosa y el papel traia otra.

Ahora es lo de por defecto. Se comprueba en los tres sitios donde se puede
perder: al dibujar el PNG, al llegar al PDF --ReportLab tiene que llevarse el
canal alfa como ``/SMask``, y sin eso el PDF lo pinta opaco-- y en el valor por
defecto de las funciones, que es lo que fallo la primera vez.

    manage.py test apps.project.specific.internal.code_gen.tests_render \\
        --settings=app_core.settings_test
"""

import inspect
import io

from django.test import SimpleTestCase
from PIL import Image

from .services.pdf_stamp import StampSpec, stamp_pdf
from .services.render import render_barcode_png, render_qr_png


def a_pdf_with_colour() -> bytes:
    """Un PDF con color justo donde va a caer el codigo."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer)
    sheet.setFillColorRGB(0.85, 0.9, 0.65)
    sheet.rect(20, 20, 300, 120, fill=1, stroke=0)
    sheet.showPage()
    sheet.save()

    return buffer.getvalue()


def transparency_of(png: bytes) -> float:
    """Que proporcion de la imagen es transparente del todo."""
    image = Image.open(io.BytesIO(png)).convert('RGBA')
    pixels = list(image.getdata())

    return sum(1 for pixel in pixels if pixel[3] == 0) / len(pixels)


def opaque_white_in(png: bytes) -> int:
    """Cuantos pixeles quedan blancos y opacos."""
    image = Image.open(io.BytesIO(png)).convert('RGBA')

    return sum(
        1 for pixel in image.getdata()
        if pixel[3] == 255 and pixel[:3] == (255, 255, 255)
    )


class TestTheSymbolsComeOutTransparent(SimpleTestCase):

    def test_the_barcode_has_no_white_background(self):
        png = render_barcode_png('GEA-1-20260115-ABCD')

        self.assertEqual(opaque_white_in(png), 0)
        self.assertGreater(transparency_of(png), 0.5)

    def test_the_qr_has_no_white_background(self):
        png = render_qr_png('https://ejemplo.test/verify/')

        self.assertEqual(opaque_white_in(png), 0)
        self.assertGreater(transparency_of(png), 0.5)

    def test_white_can_still_be_asked_for(self):
        """
        Se deja la puerta abierta: sobre un fondo oscuro un codigo transparente
        no lo lee ningun escaner, y entonces el rectangulo blanco es lo que
        salva la lectura.
        """
        png = render_barcode_png('GEA-1-20260115-ABCD', transparent=False)

        self.assertGreater(opaque_white_in(png), 0)


class TestTransparentIsTheDefault(SimpleTestCase):
    """
    Lo que fallo la primera vez no fue que no se pudiera: fue que habia que
    pedirlo y ocho de los diez sitios no lo pedian. El valor por defecto es lo
    que evita que vuelva a pasar en el proximo sitio que se escriba.
    """

    def test_the_barcode_defaults_to_transparent(self):
        default = inspect.signature(
            render_barcode_png).parameters['transparent'].default

        self.assertIs(default, True)

    def test_the_qr_defaults_to_transparent(self):
        default = inspect.signature(
            render_qr_png).parameters['transparent'].default

        self.assertIs(default, True)


class TestTheAlphaSurvivesTheStamping(SimpleTestCase):
    """
    Que el PNG sea transparente no basta: si ReportLab no se lleva el canal
    alfa al PDF, el papel sale opaco igual y no hay forma de verlo hasta
    abrirlo. En el PDF ese canal es una `/SMask` colgando de la imagen.
    """

    def stamped(self) -> bytes:
        spec = StampSpec(
            image_png=render_barcode_png('GEA-TRANSPARENTE-2026'),
            pages=[0],
            anchor='BL',
            offset_x=30,
            offset_y=30,
            width=200,
            height=60,
            opacity=1.0,
            label='prueba',
        )

        output, _report = stamp_pdf(a_pdf_with_colour(), [spec])

        return output

    def images_in(self, pdf: bytes) -> list:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf))
        found = []

        def walk(obj, depth=0):
            if depth > 6 or obj is None:
                return

            try:
                obj = obj.get_object()
            except Exception:  # noqa: BLE001
                return

            if not isinstance(obj, dict):
                return

            for value in obj.values():
                try:
                    resolved = value.get_object()
                except Exception:  # noqa: BLE001
                    continue

                if (isinstance(resolved, dict)
                        and resolved.get('/Subtype') == '/Image'):
                    found.append(resolved)

                walk(value, depth + 1)

        walk(reader.pages[0].get('/Resources'))

        return found

    def test_the_stamped_image_carries_its_alpha_channel(self):
        images = self.images_in(self.stamped())

        self.assertTrue(images, 'no se incrusto ninguna imagen')
        self.assertTrue(
            any('/SMask' in image for image in images),
            'la imagen llego al PDF sin canal alfa: saldria opaca',
        )
