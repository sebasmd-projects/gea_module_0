# apps/common/utils/tests_attack_patterns.py
"""
Que la trampa anti-escaneo atrape lo que dice atrapar, y solo eso.

Dejo de registrar nada el 9 de febrero. No porque se apagara: porque el patron
exigia barra o fin de cadena **justo despues** del termino, y lo que llega de
un escaner de WordPress no es ``/xmlrpc/`` sino ``/xmlrpc.php``. Los terminos
se escriben sin extension y lo que se pide siempre la lleva, asi que la trampa
descartaba precisamente los objetivos mas escaneados que hay.

Al ampliarla hay que vigilar el lado contrario con el mismo cuidado, porque ya
paso: el patron original buscaba el termino como subcadena suelta, ``env``
convertia ``/envio/`` en trampa y bloqueaba al usuario. Un falso positivo aqui
deja fuera a alguien legitimo, que es mucho peor que dejar pasar a un bot.

    manage.py test apps.common.utils.tests_attack_patterns \\
        --settings=app_core.settings_test
"""

import re

from django.test import TestCase

from .attack_patterns import build_pattern, normalize_terms

TERMS = ['wp-admin', 'wp-login', 'xmlrpc', 'wlwmanifest', 'env', 'config']


class TrapMatchingTests(TestCase):

    def setUp(self):
        self.compiled = re.compile(build_pattern(TERMS))

    def falls(self, path) -> bool:
        return bool(self.compiled.match(path))


class TheTrapCatchesRealScans(TrapMatchingTests):
    """
    Las rutas de esta lista son las que aparecian en `session_info` de los
    bloqueos reales, tal cual llegaron.
    """

    def test_a_plain_segment_falls(self):
        self.assertTrue(self.falls('/wp-admin/'))

    def test_a_php_file_falls(self):
        """La regresion: los terminos van sin extension, las rutas la traen."""
        self.assertTrue(self.falls('/xmlrpc.php'))
        self.assertTrue(self.falls('/wp-login.php'))

    def test_an_xml_file_falls(self):
        self.assertTrue(self.falls('/wlwmanifest.xml'))

    def test_a_nested_file_falls(self):
        self.assertTrue(
            self.falls('/ge//blog/wp-includes/wlwmanifest.xml')
        )

    def test_a_double_extension_falls(self):
        """``config.php.bak`` es un clasico de los escaneres de backups."""
        self.assertTrue(self.falls('/config.php.bak'))

    def test_a_dotfile_falls(self):
        self.assertTrue(self.falls('/.env'))


class TheTrapLetsLegitimateRoutesThrough(TrapMatchingTests):
    """
    El lado que ya se rompio una vez. Cada una de estas contiene un termino
    como subcadena y ninguna puede caer.
    """

    def test_a_word_that_merely_starts_with_a_term_passes(self):
        self.assertFalse(self.falls('/envio/'))
        self.assertFalse(self.falls('/envios/nuevo/'))
        self.assertFalse(self.falls('/configuracion/'))

    def test_a_hyphenated_word_passes(self):
        self.assertFalse(self.falls('/environment-report/'))

    def test_the_projects_own_routes_pass(self):
        for path in (
            '/generate/summary/new/',
            '/verify/aegis/summary/abc/',
            '/verify/aegis/asset/certification/',
        ):
            self.assertFalse(self.falls(path), path)

    def test_the_extension_cannot_swallow_the_rest_of_the_path(self):
        """
        La extension se acota a letras y digitos a proposito. Con ``.*`` el
        termino volveria a valer como subcadena suelta -- y con el, el
        autobloqueo de usuarios legitimos.
        """
        self.assertFalse(self.falls('/env.iar-formulario/paso-2/'))


class NormalizationTests(TestCase):

    def test_it_drops_blanks_slashes_and_duplicates(self):
        self.assertEqual(
            normalize_terms(['/wp-admin/', ' env ', '', 'env', None]),
            ['wp-admin', 'env'],
        )

    def test_no_terms_means_no_trap(self):
        """Un patron vacio matchearia todo: mejor sin trampa que sin sitio."""
        self.assertEqual(build_pattern([]), '')
