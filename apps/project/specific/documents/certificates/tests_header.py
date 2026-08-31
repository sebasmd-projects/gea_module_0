# apps/project/specific/documents/certificates/tests_header.py
"""
Que las paginas de certificacion se pinten, y con su breadcrumb.

El encabezado de estas paginas era una imagen que ademas navegaba: el banner
llevaba de vuelta, y para saberlo habia que pasar el raton por encima y ver
que cambiaba el cursor. No decia a donde llevaba ni en que punto del camino
estabas.

Ahora lleva un breadcrumb de verdad, con el mismo formato que el resto del
panel. Y como ese breadcrumb se arma en cada plantilla con `{% url %}` --uno
de ellos con un argumento, `summary.pk`--, hay que **renderizar**: compilar la
plantilla no ejecuta ningun `{% url %}`, asi que un nombre mal escrito o una
variable que no esta en el contexto pasarian la compilacion y reventarian en
la cara del primero que abriera la pagina.

    manage.py test apps.project.specific.documents.certificates.tests_header \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from .models import AegisSummaryModel


class TestThePublicPagesRender(TestCase):
    """
    Las que no piden OTP: la portada y la del anclaje, que es el destino del
    QR impreso y por eso tiene que abrirse sin nada.
    """

    def test_the_landing_renders_with_its_trail(self):
        response = self.client.get(reverse('certificates:certificates_landing'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="breadcrumb"')

    def test_the_anchor_page_renders_with_its_trail(self):
        summary = AegisSummaryModel.objects.create(title='Resumen de prueba')

        response = self.client.get(
            reverse('certificates:summary_anchor', kwargs={'pk': summary.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="breadcrumb"')

    def test_the_anchor_trail_links_back_to_its_summary(self):
        """
        Es el unico tramo que se construye con un argumento. Si el nombre de
        la ruta estuviera mal, la pagina reventaria en vez de pintarse.
        """
        summary = AegisSummaryModel.objects.create(title='Resumen de prueba')

        response = self.client.get(
            reverse('certificates:summary_anchor', kwargs={'pk': summary.pk})
        )

        self.assertContains(
            response,
            reverse('certificates:summary_detail', kwargs={'pk': summary.pk}),
        )

    def test_the_verification_form_renders_with_its_trail(self):
        response = self.client.get(
            reverse('certificates:input_document_verification_aegis')
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="breadcrumb"')


class TestTheBannerIsStillTheWayBack(TestCase):
    """
    El banner sigue siendo un enlace: quien ya lo usaba no pierde nada. Lo que
    cambia es que ya no es la unica pista.
    """

    def test_the_banner_keeps_its_link(self):
        response = self.client.get(reverse('certificates:certificates_landing'))

        self.assertContains(response, 'aegis-header__banner')

    def test_the_banner_has_an_alternative_text(self):
        """Una imagen que es el encabezado de la pagina no puede ir muda."""
        response = self.client.get(reverse('certificates:certificates_landing'))

        self.assertNotContains(response, 'aegis_header.webp" alt=""')
