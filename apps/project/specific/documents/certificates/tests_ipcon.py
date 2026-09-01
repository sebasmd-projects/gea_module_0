# apps/project/specific/documents/certificates/tests_ipcon.py
"""
Consulta publica de certificados de persona: el formulario mas expuesto.

Era el que menos protegido estaba, y por una asimetria que no se sostiene: el
portal de **documentos** exige OTP para un anonimo y limita los intentos; el
de **personas** no tenia ni una cosa ni la otra, y devuelve nombre, apellidos
y fotografia.

El codigo publico son cuatro caracteres sobre A-Z0-9: 1.679.616
combinaciones. Sin freno, eso no es un secreto, es un rato de barrido -- y lo
que sale del otro lado no son codigos, es la plantilla del despacho con sus
fotos. El mismo formulario acepta numeros de documento, asi que tambien sirve
para comprobar si una persona concreta tiene credencial.

Habia ademas un segundo fallo, distinto y mas tonto: un codigo de longitud
distinta de 4, 8 o 36 dejaba el filtro con solo el tipo de certificado, y el
``.get()`` devolvia **un certificado cualquiera** si solo habia uno, o
reventaba con ``MultipleObjectsReturned`` si habia varios.

    manage.py test apps.project.specific.documents.certificates.tests_ipcon \\
        --settings=app_core.settings_test
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import UserCertificateTypeChoices, UserVerificationModel
from .views import InputEmployeeIPCONFormView

LIMIT = InputEmployeeIPCONFormView.throttle.limit


class IPCONMixin:

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.url = reverse('certificates:input_employee_verification_ipcon')

        self.certificate = UserVerificationModel.objects.create(
            name='Ana', last_name='Lopez',
            certificate_type=UserCertificateTypeChoices.EM_IPCON,
            document_number_cc='1234567890',
            issued_at=timezone.localdate(),
        )

    def lookup(self, value, kind='UNIQUE_CODE', ip='203.0.113.7'):
        return self.client.post(
            self.url,
            {'document_type': kind, 'document_number': value},
            REMOTE_ADDR=ip,
        )


class TestItStillWorksForSomeoneHoldingACard(IPCONMixin, TestCase):
    """
    La otra mitad. Un limite que impide verificar una credencial de verdad se
    acaba quitando, y entonces no protege nada.
    """

    def test_the_public_code_finds_the_certificate(self):
        response = self.lookup(self.certificate.public_code)

        self.assertRedirects(
            response,
            reverse('certificates:detail_employee_verification_ipcon',
                    kwargs={'pk': self.certificate.pk}),
        )

    def test_the_uuid_prefix_works_too(self):
        response = self.lookup(self.certificate.uuid_prefix)

        self.assertEqual(response.status_code, 302)

    def test_a_few_typos_do_not_lock_anyone_out(self):
        """Equivocarse tres veces seguidas es normal y tiene que seguir yendo."""
        for _ in range(3):
            self.lookup('ZZZZ')

        response = self.lookup(self.certificate.public_code)

        self.assertEqual(response.status_code, 302)


class TestSweepingIsNotPossible(IPCONMixin, TestCase):
    """El limite, que es lo que convierte el barrido en inviable."""

    def test_it_stops_after_the_limit(self):
        for _ in range(LIMIT):
            self.lookup('ZZZZ')

        response = self.lookup('YYYY')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many verification attempts')

    def test_a_correct_code_also_spends_quota(self):
        """
        Si solo contaran los fallos, enumerar saldria gratis en cuanto se
        acierta el primero: bastaria con intercalar un codigo valido conocido
        para resetear el ritmo.
        """
        for _ in range(LIMIT):
            self.lookup(self.certificate.public_code)

        response = self.lookup(self.certificate.public_code)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Too many verification attempts')

    def test_the_limit_is_by_address_not_by_session(self):
        """
        Un contador por sesion no limita nada: tirar la cookie y volver a
        empezar es una linea de script.
        """
        for _ in range(LIMIT):
            self.lookup('ZZZZ')

        self.client.cookies.clear()
        response = self.lookup('YYYY')

        self.assertContains(response, 'Too many verification attempts')

    def test_another_address_keeps_its_own_quota(self):
        for _ in range(LIMIT):
            self.lookup('ZZZZ', ip='203.0.113.7')

        response = self.lookup(
            self.certificate.public_code, ip='198.51.100.9')

        self.assertEqual(response.status_code, 302)

    def test_the_document_number_lookup_is_limited_too(self):
        """
        Es el otro vector: comprobar si una persona concreta tiene credencial
        probando su numero de cedula.
        """
        for _ in range(LIMIT):
            self.lookup('9999999999', kind='CC')

        response = self.lookup('1234567890', kind='CC')

        self.assertContains(response, 'Too many verification attempts')


class TestAQueryThatIdentifiesNobodyFindsNobody(IPCONMixin, TestCase):
    """
    El segundo fallo: con una sola credencial en la base, **cualquier** cadena
    de longitud rara devolvia esa credencial. El filtro se quedaba con solo el
    tipo de certificado.
    """

    def test_a_five_character_code_finds_nothing(self):
        response = self.lookup('ABCDE')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not found')

    def test_it_does_not_leak_the_only_certificate_there_is(self):
        self.assertEqual(UserVerificationModel.objects.count(), 1)

        response = self.lookup('X')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Location', response)

    def test_several_certificates_do_not_crash_it(self):
        """Antes esto era un `MultipleObjectsReturned`, o sea un 500."""
        for index in range(3):
            UserVerificationModel.objects.create(
                name=f'Otro{index}', last_name='Persona',
                certificate_type=UserCertificateTypeChoices.EM_IPCON,
                document_number_cc=f'99999999{index}',
                issued_at=timezone.localdate(),
            )

        response = self.lookup('ABCDEFG')

        self.assertEqual(response.status_code, 200)

    def test_the_message_is_the_same_either_way(self):
        """
        Un mensaje distinto para "no existe" y para "eso no es un
        identificador" le diria al que barre que formato tiene que probar.
        """
        unknown = self.lookup('ZZZZ')
        malformed = self.lookup('ABCDE')

        self.assertContains(unknown, 'not found')
        self.assertContains(malformed, 'not found')
