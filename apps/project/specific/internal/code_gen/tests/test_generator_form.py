# apps/project/specific/internal/code_gen/tests/test_generator_form.py
"""
La pantalla de `/generate/code/`: vista previa de verdad, y la certificacion
escondida hasta que se pide.

Dos huecos reales, no de estilo
--------------------------------
Uno: el banco de trabajo de "Posiciones sobre el documento" montaba su
contenedor a mano en la plantilla, sin pasar por
`preview.render_preview_container()`. Le faltaban los atributos que
`stamp_preview.js` necesita para dibujar algo -- ni siquiera una muestra --,
asi que esta era la unica pantalla del generador de codigos sin vista previa
de como quedaba el codigo de barras o el QR.

Dos: "Hash del documento" (segmentos), "URL publica de verificacion"
(simbolos) y la tarjeta entera de "Certificacion del documento" -- con las
posiciones sobre el documento -- se veian siempre, aunque nadie fuera a
certificar nada. Las tres dependen de "Certificar documento", que ahora vive
en Identificacion y las revela por JS (`code_generator_certify.js`); aqui solo
se comprueba lo que depende del servidor: que esos marcadores esten en el HTML
para que el JS los pueda encontrar, y que el campo se haya movido de verdad.

    manage.py test apps.project.specific.internal.code_gen.tests.test_generator_form \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

PASSWORD = 'pw-for-tests-123'


class TestTheGeneratorPageRenders(TestCase):

    def setUp(self):
        self.operator = UserModel.objects.create_user(
            username='ops-generator', email='ops-generator@example.com',
            password=PASSWORD, is_staff=True,
        )
        self.client.force_login(self.operator)
        self.url = reverse('code_gen:code_generate')

    def test_it_renders_without_error(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_the_stamp_workspace_carries_real_preview_symbols(self):
        """
        Antes de esto, el contenedor no llevaba `data-symbols-url` ni
        `data-sample-length`: sin ellos `stamp_preview.js` no tiene de donde
        sacar ni una muestra que dibujar.
        """
        html = self.client.get(self.url).content.decode('utf-8')

        self.assertIn('data-gea-preview', html)
        self.assertIn('data-symbols-url', html)
        self.assertIn('data-sample-length', html)

    def test_certify_document_moved_to_identification(self):
        """
        La casilla que decide si se certifica vive ahora en Identificacion,
        no dentro de la propia tarjeta de certificacion que ella revela.
        """
        html = self.client.get(self.url).content.decode('utf-8')

        identification_start = html.index('Identification')
        certification_start = html.index('Document certification')

        certify_checkbox_at = html.index('id="id_certify_document"')

        self.assertTrue(identification_start < certify_checkbox_at)
        self.assertTrue(certify_checkbox_at < certification_start)

    def test_the_certify_only_sections_carry_their_toggle_ids(self):
        """
        `code_generator_certify.js` los busca por estos tres ids exactos. Si
        alguno se pierde en un refactor de la plantilla, el script no rompe
        --se limita a no encontrar nada-- asi que esto es lo que lo detecta.
        """
        html = self.client.get(self.url).content.decode('utf-8')

        self.assertIn('id="certificationCard"', html)
        self.assertIn('id="documentHashField"', html)
        self.assertIn('id="layoutWorkspace"', html)

    def test_the_toggle_script_is_loaded(self):
        html = self.client.get(self.url).content.decode('utf-8')

        self.assertIn('code_generator_certify.js', html)
