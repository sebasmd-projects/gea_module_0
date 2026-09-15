# apps/project/specific/documents/certificates/tests/test_entry_point.py
"""
Como se llega a verificar un documento, y que dice la pantalla al llegar.

Dos cosas que estaban mal por separado y se refuerzan la una a la otra.

**Al enlace no llegaba quien mas lo necesita.** La vista siempre fue publica
--figura en `INTENTIONALLY_PUBLIC` y a un anonimo le pide OTP-- pero el enlace
del menu vivia dentro del bloque de `is_staff`. Un comprador o un tenedor, que
son justo los que reciben un certificado, tenian que conocerse la URL de
memoria para usar una pagina que es suya. Una pagina publica a la que solo se
llega sabiendosela no es una pagina publica: es una pagina escondida.

**Y al llegar, la pantalla no distinguia sus dos caminos.** Teclear el codigo
publico y subir el archivo se parecen, estan uno encima del otro y no prueban
lo mismo: el codigo busca una ficha, y solo la comparacion byte a byte dice si
el PDF que alguien tiene en la mano es el que se certifico. Quien usa el codigo
se lleva una pantalla que dice «certificado» y de ahi a creer que su copia
acaba de quedar comprobada hay un paso que nadie le habia dicho que no diera.
Un documento alterado da exactamente la misma pagina.

    manage.py test apps.project.specific.documents.certificates.tests.test_entry_point \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'


class TheLinkIsForEveryoneWhoIsLoggedIn(TestCase):
    """
    El menu lateral, mirado desde cada rol.

    Se pinta la plantilla del menu directamente y no una pagina que la incluya,
    porque lo que se prueba es el menu: por una pagina concreta habria que
    elegir una a la que lleguen los tres roles, y entonces lo que fallaria el
    dia que algo se rompa seria el permiso de esa pagina, no la visibilidad del
    enlace.
    """

    PLANTILLA = 'dashboard/partials/sidenav/dashboard_sidenav.html'

    def setUp(self):
        self.verify_url = reverse(
            'certificates:input_document_verification_aegis')

    def sidenav(self, **extra) -> str:
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        usuario = UserModel.objects.create_user(
            username=extra.pop('username', 'alguien'),
            email=extra.pop('email', 'alguien@example.com'),
            password=PASSWORD,
            **extra,
        )

        request = RequestFactory().get('/')
        request.user = usuario

        return render_to_string(self.PLANTILLA, request=request)

    def test_a_buyer_finds_it_in_the_menu(self):
        html = self.sidenav(username='comprador',
                            email='comprador@example.com', user_type='B')

        self.assertIn(self.verify_url, html)

    def test_a_holder_finds_it_in_the_menu(self):
        html = self.sidenav(username='tenedor', email='tenedor@example.com',
                            user_type='H')

        self.assertIn(self.verify_url, html)

    def test_staff_still_finds_it(self):
        """
        Lo que se hizo fue sacarlo del bloque de personal, no moverlo a otro
        bloque cerrado: quien lo tenia lo sigue teniendo.
        """
        html = self.sidenav(username='ops', email='ops@example.com',
                            is_staff=True)

        self.assertIn(self.verify_url, html)

    def test_the_staff_only_pages_are_still_staff_only(self):
        """
        Lo que se abrio fue un enlace, no el bloque entero: el generador de
        codigos y las disposiciones siguen donde estaban.
        """
        html = self.sidenav(username='comprador2',
                            email='comprador2@example.com', user_type='B')

        # Con `href="…"`: `/generate/code/` es **prefijo** de
        # `/generate/code/history/`, que un titular si tiene en su menu desde
        # que el historial se abrio a los dos papeles. Sin las comillas esta
        # prueba fallaba por el prefijo, no por el permiso -- el mismo error
        # que hizo que el termino `env` bloqueara `/envio/` (invariante 14).
        self.assertNotIn(
            'href="%s"' % reverse('code_gen:code_generate'), html)
        self.assertNotIn(
            'href="%s"' % reverse('code_gen:layout_list'), html)


class TheScreenSaysWhichOfTheTwoChecksIntegrity(TestCase):
    """
    El aviso solo tiene sentido cuando los dos formularios estan en pantalla.

    Antes de superar el OTP lo que hay es el correo o el codigo de acceso, y
    explicar ahi la diferencia entre dos formularios que todavia no se ven solo
    estorba. Por eso se pinta con la misma condicion que el cotejo por archivo.
    """

    def setUp(self):
        self.url = reverse('certificates:input_document_verification_aegis')

    def page(self) -> str:
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        return response.content.decode('utf-8')

    def test_a_logged_in_user_is_told_both_halves(self):
        usuario = UserModel.objects.create_user(
            username='titular', email='titular@example.com', password=PASSWORD,
        )
        self.client.force_login(usuario)

        html = self.page()

        self.assertIn('Uploading the document does verify its', html)
        self.assertIn('Entering the public code does not', html)

    def test_it_also_says_that_neither_attests_the_truth(self):
        """
        Invariante 11: la plataforma prueba que el archivo no ha cambiado, no
        que sea cierto lo que dice.
        """
        usuario = UserModel.objects.create_user(
            username='titular2', email='titular2@example.com',
            password=PASSWORD,
        )
        self.client.force_login(usuario)

        self.assertIn('is true', self.page())

    def test_an_anonymous_visitor_is_not_told_it_before_the_otp(self):
        """
        En esa pantalla no hay ningun formulario de los dos: solo el correo al
        que mandar el codigo de acceso.
        """
        self.assertNotIn('Entering the public code does not', self.page())
