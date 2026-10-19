# apps/project/specific/documents/certificates/tests/test_otp_next.py
"""
Volver adonde se estaba tras superar el OTP.

Un anonimo que llegaba por el enlace a un documento concreto
(``detail_document_verification_aegis``) se topaba con el guardia del OTP,
lo pasaba, y se quedaba en la pantalla generica de busqueda por codigo
(``input_document_verification_aegis``): el documento que habia pedido se
perdia por el camino y tenia que volver a teclear su codigo o reabrir el
enlace original. El mismo guardia (``OTPProtectedDocumentMixin``) protege
tambien ``certification_record`` y ``summary_detail``, asi que el arreglo
--recordar el destino y volver a el tras el OTP-- les sirve igual.

    manage.py test apps.project.specific.documents.certificates.tests.test_otp_next \\
        --settings=app_core.settings_test
"""
import re
from urllib.parse import quote

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ..models import DocumentCertificateTypeChoices, DocumentVerificationModel

EMAIL = 'visitante@propensionesabogados.com'


def codes_in(outbox):
    """Los codigos de seis cifras que salieron por correo."""
    found = []
    for message in outbox:
        # Solo el HTML: el mismo codigo sale tambien en el cuerpo de texto, y
        # contarlo dos veces haria creer que se mandaron dos correos.
        html = message.alternatives[0][0] if message.alternatives else message.body
        found += re.findall(r'>(\d{6})<', html) or re.findall(r'\b(\d{6})\b', html)
    return found


class AnonymousOTPReturnsToTheOriginalDocumentTests(TestCase):
    """De punta a punta: enlace a un documento -> OTP -> de vuelta al documento."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        mail.outbox = []

        self.document = DocumentVerificationModel.objects.create(
            document_title='Documento',
            certificate_type=DocumentCertificateTypeChoices.AEGIS,
            issued_at=timezone.localdate(),
        )
        self.detail_url = reverse(
            'certificates:detail_document_verification_aegis',
            kwargs={'pk': self.document.pk},
        )
        self.input_url = reverse(
            'certificates:input_document_verification_aegis')

    def test_the_door_sends_the_anonymous_visitor_with_their_destination_attached(self):
        response = self.client.get(self.detail_url)

        self.assertRedirects(
            response,
            f'{self.input_url}?next={quote(self.detail_url, safe="")}',
            fetch_redirect_response=False,
        )

    def test_completing_the_otp_lands_back_on_the_document_not_on_the_search_form(self):
        # Llega por el enlace del documento y de ahi al formulario, siguiendo
        # el redirect tal y como lo haria un navegador.
        self.client.get(self.detail_url, follow=True)

        self.assertEqual(
            self.client.session.get('document_otp_next'), self.detail_url)

        # Paso 1: correo.
        self.client.post(self.input_url, {'email': EMAIL})
        code = codes_in(mail.outbox)[0]

        # Paso 2: codigo. Antes esto devolvia al formulario generico de
        # busqueda por identificador; con el arreglo, va directo al
        # documento que se habia pedido.
        response = self.client.post(self.input_url, {'otp': code})

        self.assertRedirects(response, self.detail_url)
        self.assertNotIn('document_otp_next', self.client.session)

    def test_a_plain_visit_without_a_prior_document_keeps_the_old_behaviour(self):
        """
        Quien llega sin pedir un documento concreto --el buscador por
        codigo-- no tiene destino que recordar, asi que tras el OTP sigue
        viendo el mismo formulario de identificador de siempre.
        """
        self.client.get(self.input_url)
        self.client.post(self.input_url, {'email': EMAIL})
        code = codes_in(mail.outbox)[0]

        response = self.client.post(self.input_url, {'otp': code})

        self.assertRedirects(response, self.input_url)

    def test_an_external_next_is_not_honoured(self):
        """
        El `next` llega por la query string de un GET, no por algo que el
        propio guardia construyo: sin `safe_next` de por medio, esto seria
        un redirector abierto de manual.
        """
        self.client.get(f'{self.input_url}?next=https://evil.example/phish')

        self.assertNotIn('document_otp_next', self.client.session)

        self.client.post(self.input_url, {'email': EMAIL})
        code = codes_in(mail.outbox)[0]

        response = self.client.post(self.input_url, {'otp': code})

        self.assertRedirects(response, self.input_url)
