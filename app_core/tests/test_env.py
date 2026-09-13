"""
Pruebas de la comprobacion del entorno (`app_core/env.py`).

Lo que de verdad se protege aqui no es el formato del mensaje, sino que la
lista no se quede vieja: `settings.py` sigue creciendo, y una variable nueva
leida sin valor por defecto que nadie declare vuelve al error de antes --el
`int() argument must be a string` que no nombra nada--. Por eso la primera
prueba lee el propio `settings.py` y exige que cada lectura sin defecto este
decidida: obligatoria, obligatoria en produccion, o prescindible con su motivo
escrito.
"""

import re
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from app_core import env

SETTINGS = Path(__file__).resolve().parent.parent / 'settings.py'
ENV_EXAMPLE = Path(__file__).resolve().parent.parent.parent / env.ENV_EXAMPLE

# `os.getenv('NOMBRE')` sin segundo argumento. Con defecto no hace falta
# declarar nada: el defecto ya es la respuesta a que falte.
WITHOUT_DEFAULT = re.compile(r"os\.getenv\(\s*'([A-Z0-9_]+)'\s*\)")


def read_settings() -> str:
    return SETTINGS.read_text(encoding='utf-8')


def declared() -> set:
    return (
        set(env.REQUIRED)
        | set(env.REQUIRED_IN_PRODUCTION)
        | set(env.OPTIONAL_WITHOUT_DEFAULT)
    )


def complete_environment(debug='True') -> dict:
    """Un entorno que pasa la comprobacion, para partir de el y quitar cosas."""
    environ = {name: 'valor' for name in env.REQUIRED}
    environ.update({name: 'valor' for name in env.REQUIRED_IN_PRODUCTION})
    environ['DJANGO_DEBUG'] = debug
    return environ


class SettingsCoverageTests(SimpleTestCase):
    """Que la lista siga cubriendo lo que `settings.py` lee de verdad."""

    def test_toda_lectura_sin_defecto_esta_decidida(self):
        leidas = set(WITHOUT_DEFAULT.findall(read_settings()))
        sin_decidir = sorted(leidas - declared())

        self.assertEqual(
            sin_decidir, [],
            'settings.py lee estas variables sin valor por defecto y no estan '
            'declaradas en app_core/env.py. Decide cada una: a REQUIRED (o a '
            'REQUIRED_IN_PRODUCTION) si su ausencia impide arrancar, o a '
            'OPTIONAL_WITHOUT_DEFAULT con el motivo escrito de por que no. '
            f'Sin decidir: {sin_decidir}'
        )

    def test_no_quedan_entradas_de_variables_que_ya_nadie_lee(self):
        fuente = read_settings()
        huerfanas = sorted(
            name for name in declared()
            if f"'{name}'" not in fuente
        )

        self.assertEqual(
            huerfanas, [],
            'Estas variables estan declaradas en app_core/env.py pero '
            f'settings.py ya no las lee: {huerfanas}'
        )

    def test_allowed_empty_solo_nombra_variables_conocidas(self):
        desconocidas = sorted(env.ALLOWED_EMPTY - declared())

        self.assertEqual(desconocidas, [], f'ALLOWED_EMPTY: {desconocidas}')

    def test_ninguna_variable_esta_en_dos_listas(self):
        self.assertEqual(
            set(env.REQUIRED) & set(env.OPTIONAL_WITHOUT_DEFAULT), set()
        )
        self.assertEqual(
            set(env.REQUIRED) & set(env.REQUIRED_IN_PRODUCTION), set()
        )

    def test_cada_declaracion_lleva_su_motivo_escrito(self):
        for grupo in (
            env.REQUIRED, env.REQUIRED_IN_PRODUCTION,
            env.OPTIONAL_WITHOUT_DEFAULT,
        ):
            for name, reason in grupo.items():
                with self.subTest(name=name):
                    self.assertTrue(
                        reason and len(reason) > 20,
                        f'{name} necesita una explicacion util, no una etiqueta'
                    )


class MissingVariablesTests(SimpleTestCase):

    def test_un_entorno_completo_no_echa_nada_en_falta(self):
        self.assertEqual(
            env.missing_variables(complete_environment(), debug=True), []
        )

    def test_la_que_falta_sale_por_su_nombre(self):
        environ = complete_environment()
        del environ['DB_PORT']

        faltan = dict(env.missing_variables(environ, debug=True))

        self.assertIn('DB_PORT', faltan)
        self.assertEqual(len(faltan), 1)

    def test_salen_todas_las_que_faltan_de_una_vez(self):
        environ = complete_environment()
        for name in ('DB_PORT', 'DB_NAME', 'FIELD_ENCRYPTION_KEY'):
            del environ[name]

        faltan = dict(env.missing_variables(environ, debug=True))

        self.assertEqual(
            sorted(faltan), ['DB_NAME', 'DB_PORT', 'FIELD_ENCRYPTION_KEY']
        )

    def test_vacia_cuenta_como_ausente(self):
        environ = complete_environment()
        environ['DB_PORT'] = '   '

        self.assertIn('DB_PORT', dict(env.missing_variables(environ, debug=True)))

    def test_vacia_es_valida_donde_vacio_significa_algo(self):
        environ = complete_environment()
        for name in env.ALLOWED_EMPTY:
            environ[name] = ''

        self.assertEqual(env.missing_variables(environ, debug=True), [])

    def test_allowed_hosts_solo_se_exige_en_produccion(self):
        environ = complete_environment()
        del environ['DJANGO_ALLOWED_HOSTS']

        self.assertEqual(env.missing_variables(environ, debug=True), [])
        self.assertIn(
            'DJANGO_ALLOWED_HOSTS',
            dict(env.missing_variables(environ, debug=False)),
        )

    def test_el_modo_sale_de_django_debug_si_no_se_dice_otra_cosa(self):
        environ = complete_environment(debug='False')
        del environ['DJANGO_ALLOWED_HOSTS']

        self.assertIn(
            'DJANGO_ALLOWED_HOSTS', dict(env.missing_variables(environ))
        )

    def test_lo_opcional_no_se_echa_en_falta(self):
        environ = complete_environment()

        for name in env.OPTIONAL_WITHOUT_DEFAULT:
            environ.pop(name, None)

        self.assertEqual(env.missing_variables(environ, debug=True), [])


class ErrorMessageTests(SimpleTestCase):

    def test_el_error_nombra_la_variable_y_para_que_sirve(self):
        environ = complete_environment()
        del environ['FIELD_ENCRYPTION_KEY']

        with self.assertRaises(ImproperlyConfigured) as caso:
            env.check_environment(environ, debug=True)

        mensaje = str(caso.exception)

        self.assertIn('FIELD_ENCRYPTION_KEY', mensaje)
        self.assertIn('PII', mensaje)
        self.assertIn(env.ENV_EXAMPLE, mensaje)

    def test_el_error_las_nombra_todas(self):
        environ = complete_environment()
        for name in ('DB_HOST', 'DB_USER', 'DJANGO_SECRET_KEY'):
            del environ[name]

        with self.assertRaises(ImproperlyConfigured) as caso:
            env.check_environment(environ, debug=True)

        mensaje = str(caso.exception)

        for name in ('DB_HOST', 'DB_USER', 'DJANGO_SECRET_KEY'):
            self.assertIn(name, mensaje)

        self.assertIn('Faltan 3', mensaje)

    def test_una_sola_no_se_anuncia_en_plural(self):
        environ = complete_environment()
        del environ['DB_HOST']

        with self.assertRaises(ImproperlyConfigured) as caso:
            env.check_environment(environ, debug=True)

        self.assertIn('Falta 1 variable', str(caso.exception))

    def test_un_entorno_completo_no_levanta_nada(self):
        env.check_environment(complete_environment(), debug=True)


class EnvExampleTests(SimpleTestCase):
    """La plantilla que el error recomienda tiene que servir para arrancar."""

    def test_la_plantilla_existe_donde_dice_el_error(self):
        self.assertTrue(ENV_EXAMPLE.is_file(), env.ENV_EXAMPLE)

    def test_la_plantilla_declara_todas_las_obligatorias(self):
        texto = ENV_EXAMPLE.read_text(encoding='utf-8')
        declaradas = set(re.findall(r'^([A-Z0-9_]+)=', texto, re.MULTILINE))

        obligatorias = set(env.REQUIRED) | set(env.REQUIRED_IN_PRODUCTION)
        faltan = sorted(obligatorias - declaradas)

        self.assertEqual(
            faltan, [],
            f'{env.ENV_EXAMPLE} no declara: {faltan}. Quien copie la '
            'plantilla se llevara el error que esto pretende evitar.'
        )
