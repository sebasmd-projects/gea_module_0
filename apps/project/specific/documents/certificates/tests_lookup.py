# apps/project/specific/documents/certificates/tests_lookup.py
"""
El formulario publico de verificacion: que encuentre, y que no sea un oraculo.

Dos cosas que fallaban.

**Un resumen con su codigo publico no se encontraba.** El resumen tambien es
una cosa certificada con un codigo impreso, pero vive en su propia tabla, y la
busqueda solo miraba la de documentos. Quien tecleaba el codigo de un resumen
--correcto, y en el papel que tenia delante-- recibia "Document not found".
Quien lee un codigo no sabe en que tabla se guarda, ni tiene por que saberlo.

**Y no habia ningun limite al numero de codigos que se podian probar.** El OTP
estaba limitado por todos lados, pero una vez superado se podian teclear
identificadores sin tope durante los 30 minutos que dura el acceso, y el
formulario responde si el codigo existe o no. Los codigos de persona son de
cuatro caracteres.

    manage.py test apps.project.specific.documents.certificates.tests_lookup \\
        --settings=app_core.settings_test
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .mixins import OTPSessionMixin
from .models import (AegisSummaryModel, DocumentCertificateTypeChoices,
                     DocumentVerificationModel)
from .verification import (find_summary_by_identifier, resolve_identifier)


class SummaryLookupTests(TestCase):
    """La busqueda, sin pasar por la vista."""

    def setUp(self):
        self.summary = AegisSummaryModel.objects.create(
            title='Resumen de prueba'
        )

    def test_a_summary_is_found_by_its_public_code(self):
        found = find_summary_by_identifier(self.summary.public_code)

        self.assertEqual(found, self.summary)

    def test_the_code_is_not_case_sensitive(self):
        """Nadie copia un codigo de un papel respetando las mayusculas."""
        found = find_summary_by_identifier(self.summary.public_code.lower())

        self.assertEqual(found, self.summary)

    def test_surrounding_blanks_do_not_break_it(self):
        found = find_summary_by_identifier(f'  {self.summary.public_code} ')

        self.assertEqual(found, self.summary)

    def test_a_summary_is_found_by_its_uuid_prefix(self):
        found = find_summary_by_identifier(self.summary.uuid_prefix)

        self.assertEqual(found, self.summary)

    def test_a_summary_is_found_by_its_full_uuid(self):
        found = find_summary_by_identifier(str(self.summary.pk))

        self.assertEqual(found, self.summary)

    def test_an_unknown_code_finds_nothing(self):
        self.assertIsNone(find_summary_by_identifier('NOEXISTE1234'))

    def test_an_empty_identifier_finds_nothing(self):
        """Sin esto, un campo vacio devolveria el primer resumen de la tabla."""
        self.assertIsNone(find_summary_by_identifier(''))
        self.assertIsNone(find_summary_by_identifier('   '))


class ResolveIdentifierTests(TestCase):
    """Un identificador es un identificador, venga de donde venga."""

    def setUp(self):
        self.summary = AegisSummaryModel.objects.create(title='Resumen')
        self.document = DocumentVerificationModel.objects.create(
            document_title='Documento',
            certificate_type=DocumentCertificateTypeChoices.AEGIS,
            issued_at=timezone.localdate(),
        )

    def test_it_resolves_a_document(self):
        kind, found = resolve_identifier(self.document.public_code)

        self.assertEqual(kind, 'document')
        self.assertEqual(found, self.document)

    def test_it_resolves_a_summary(self):
        """La regresion: esto respondia "no encontrado"."""
        kind, found = resolve_identifier(self.summary.public_code)

        self.assertEqual(kind, 'summary')
        self.assertEqual(found, self.summary)

    def test_nothing_resolves_to_nothing(self):
        self.assertEqual(resolve_identifier('NOEXISTE1234'), (None, None))


class IdentifierThrottleTests(TestCase):
    """
    El limite del formulario de identificador.

    Se cuenta por IP y no por sesion a proposito: la sesion la controla quien
    busca, y tirar la cookie para empezar de cero es una linea de script.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def make_view(self, ip='203.0.113.7'):
        from django.test import RequestFactory

        view = OTPSessionMixin()
        view.request = RequestFactory().get('/', REMOTE_ADDR=ip)
        view.request.session = self.client.session

        return view

    def test_the_first_attempts_are_allowed(self):
        view = self.make_view()

        for _ in range(OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW):
            self.assertTrue(view.can_try_identifier())
            view.record_identifier_attempt()

    def test_it_stops_after_the_limit(self):
        view = self.make_view()

        for _ in range(OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW):
            view.record_identifier_attempt()

        self.assertFalse(view.can_try_identifier())

    def test_a_new_session_does_not_reset_the_counter(self):
        """
        Lo que hace inutil un contador por sesion: borrar la cookie.
        """
        view = self.make_view()

        for _ in range(OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW):
            view.record_identifier_attempt()

        fresh = self.make_view()

        self.assertFalse(fresh.can_try_identifier())

    def test_another_ip_is_not_punished(self):
        view = self.make_view()

        for _ in range(OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW):
            view.record_identifier_attempt()

        self.assertTrue(self.make_view(ip='198.51.100.9').can_try_identifier())


class VerificationFormTests(TestCase):
    """De punta a punta, con un usuario autenticado (que se salta el OTP)."""

    def setUp(self):
        from apps.project.common.users.models import UserModel

        cache.clear()
        self.addCleanup(cache.clear)

        self.user = UserModel.objects.create_user(
            username='verificador',
            email='verificador@example.com',
            password='una-clave-larga-de-prueba',
        )
        self.client.force_login(self.user)

        self.url = reverse('certificates:input_document_verification_aegis')
        self.summary = AegisSummaryModel.objects.create(title='Resumen')

    def post_identifier(self, identifier):
        return self.client.post(self.url, {
            'identifier': identifier,
            'certificate_type': '',
        })

    def test_a_summary_code_lands_on_the_summary_page(self):
        response = self.post_identifier(self.summary.public_code)

        self.assertRedirects(
            response,
            reverse(
                'certificates:summary_detail', kwargs={'pk': self.summary.pk}
            ),
        )

    def test_the_certificate_type_is_optional(self):
        """
        Era obligatorio, y elegir mal daba "no encontrado" con un codigo
        valido. Quien tiene el papel delante no sabe de que tipo es.
        """
        document = DocumentVerificationModel.objects.create(
            document_title='Documento',
            certificate_type=DocumentCertificateTypeChoices.AEGIS,
            issued_at=timezone.localdate(),
        )

        response = self.post_identifier(document.public_code)

        self.assertRedirects(
            response,
            reverse(
                'certificates:detail_document_verification_aegis',
                kwargs={'pk': document.pk},
            ),
        )

    def test_the_form_stops_answering_after_too_many_tries(self):
        limit = OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW

        for _ in range(limit):
            self.post_identifier('NOEXISTE1234')

        response = self.post_identifier(self.summary.public_code)

        # Ni siquiera acertando: pasado el limite, no se busca.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many verification attempts')

    def test_a_valid_code_also_counts_against_the_limit(self):
        """
        Si solo contaran los fallos, enumerar saldria gratis en cuanto se
        acierta una vez.
        """
        limit = OTPSessionMixin.IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW

        for _ in range(limit):
            self.post_identifier(self.summary.public_code)

        response = self.post_identifier(self.summary.public_code)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many verification attempts')
