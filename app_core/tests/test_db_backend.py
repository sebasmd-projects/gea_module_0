"""
Los UUID se siguen guardando como se guardaron.

Django 5.0 empezo a usar el tipo nativo `uuid` de MariaDB 10.7+, y con el
cambia lo que va en **cada consulta**: el UUID con guiones en vez del hex de
32. Una base creada con Django 4.2 tiene `char(32)` con el hex, asi que al
subir de version las busquedas por clave primaria dejan de encontrar nada.

Y no falla: la fila se lee, `filter(username=...)` la encuentra, y solo
`filter(pk=...)` se queda vacio. En el acceso eso se vio como una contrasena
aceptada y un asistente que, acto seguido, no podia recargar al usuario:

    Motivo: no hay ninguna cuenta con pk=d717d90c-5e8c-45a7-... en
    propensi_geausadb en 127.0.0.1:3307, pero acaba de identificarse con esa
    clave

`app_core/db/mysql` apaga ese interruptor. Esto lo fija, porque es
exactamente el tipo de linea que alguien quita al limpiar --parece un ajuste
de nada-- y el sintoma vuelve en produccion, en silencio, y solo al entrar.

    manage.py test app_core.tests.test_db_backend \\
        --settings=app_core.settings_test
"""

from django.test import SimpleTestCase

from app_core.db.mysql.base import DatabaseFeatures, DatabaseWrapper


class MySQLKeepsUUIDsAsTheyWereTests(SimpleTestCase):

    def test_el_tipo_nativo_de_uuid_esta_apagado(self):
        self.assertIs(DatabaseFeatures.has_native_uuid_field, False)

    def test_el_motor_usa_esas_caracteristicas(self):
        """
        Declarar la clase no sirve de nada si el wrapper no la usa.
        """
        self.assertIs(DatabaseWrapper.features_class, DatabaseFeatures)

    def test_es_el_motor_de_mysql_de_django_con_un_cambio(self):
        """
        No es un motor propio: es el de Django con una caracteristica menos.
        Si algun dia se reescribiera de cero, se perderian las correcciones
        que Django haga al suyo.
        """
        from django.db.backends.mysql import base as django_mysql

        self.assertTrue(issubclass(DatabaseWrapper, django_mysql.DatabaseWrapper))
        self.assertTrue(
            issubclass(DatabaseFeatures, django_mysql.DatabaseWrapper.features_class)
        )

    def test_django_sigue_teniendo_ese_interruptor(self):
        """
        El dia que Django lo quite, esto sobra -- y hay que enterarse, porque
        entonces habra que mirar que hace en su lugar.
        """
        from django.db.backends.base.features import BaseDatabaseFeatures

        self.assertTrue(hasattr(BaseDatabaseFeatures, 'has_native_uuid_field'))


class SettingsPointAtThatBackendTests(SimpleTestCase):
    """
    Que `settings.py` lo instale cuando toca, y no lo instale cuando no.
    """

    def test_mysql_declarado_instala_el_motor_propio(self):
        engine = self._engine_for('django.db.backends.mysql')

        self.assertEqual(engine, 'app_core.db.mysql')

    def test_postgresql_se_queda_como_esta(self):
        """
        Esto es de MySQL: en PostgreSQL el UUID es nativo desde siempre y sus
        columnas se escribieron asi.
        """
        engine = self._engine_for('django.db.backends.postgresql')

        self.assertEqual(engine, 'django.db.backends.postgresql')

    def test_sqlite_se_queda_como_esta(self):
        engine = self._engine_for('django.db.backends.sqlite3')

        self.assertEqual(engine, 'django.db.backends.sqlite3')

    # ------------------------------------------------------------------
    def _engine_for(self, declared: str) -> str:
        """
        La decision de verdad, la misma que llama `settings.py`.

        Se prueba la funcion y no se repite la regla aqui: una prueba que
        reimplementa lo que comprueba pasa igual de bien con `settings.py`
        haciendo otra cosa, que es exactamente lo que hay que detectar.
        """
        from app_core.db import engine_for

        return engine_for(declared)

    def test_settings_usa_esa_funcion(self):
        """
        Que no sea una funcion correcta a la que nadie llama.
        """
        import inspect

        from app_core import settings

        fuente = inspect.getsource(settings)

        self.assertIn('engine_for(DECLARED_DB_ENGINE)', fuente)


class TheMechanismItselfTests(SimpleTestCase):
    """
    Que apagar el interruptor cambie de verdad lo que va en la consulta.

    Es lo unico que importa: con el encendido, Django manda el UUID con
    guiones contra una columna que guarda el hex de 32, y no coincide con
    nada. Se comprueba sobre `UUIDField` directamente, sin base de datos, para
    que valga tambien donde la suite corre sobre SQLite.
    """

    def _prepared(self, native: bool):
        import uuid
        from types import SimpleNamespace

        from django.db.models import UUIDField

        conexion = SimpleNamespace(
            features=SimpleNamespace(has_native_uuid_field=native)
        )
        valor = uuid.UUID('d717d90c-5e8c-45a7-bebd-3fac0944a087')

        return UUIDField().get_db_prep_value(valor, conexion)

    def test_con_el_tipo_nativo_va_con_guiones(self):
        self.assertEqual(
            str(self._prepared(native=True)),
            'd717d90c-5e8c-45a7-bebd-3fac0944a087',
        )

    def test_sin_el_tipo_nativo_va_el_hex_de_32(self):
        """El formato con el que estan escritas las filas de este proyecto."""
        preparado = self._prepared(native=False)

        self.assertEqual(preparado, 'd717d90c5e8c45a7bebd3fac0944a087')
        self.assertEqual(len(preparado), 32)
