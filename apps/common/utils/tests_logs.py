# apps/common/utils/tests_logs.py
"""
Rotacion del log: que rote, que no pierda nada, y que no llene el disco.

El log no tenia rotacion: `stderr.log` crecia sin fin y se renombraba a mano
cuando alguien se acordaba -- produccion iba por `stderr_old_5.log`.

La prueba que de verdad importa es `TestARunningWorkerFollowsTheRotation`.
Rotar es renombrar, y en Linux renombrar no afecta a quien tiene el fichero
abierto: el descriptor sigue apuntando al mismo inodo. Con el `FileHandler` de
siempre, tras rotar **todos los workers seguirian escribiendo en el fichero
renombrado**, el `stderr.log` nuevo no llegaria a crearse, y el "viejo" seria
el que crece. Sin error y sin aviso. Por eso el handler es
`WatchedFileHandler`, y por eso hay una prueba que lo fija: es el tipo de
detalle que alguien "simplifica" sin saber lo que sostiene.

    manage.py test apps.common.utils.tests_logs \\
        --settings=app_core.settings_test
"""

import logging
import logging.handlers
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from .logs import (human_size, next_number, prune, rotate, rotated_files,
                   rotated_name, should_rotate)


class LogDirectoryMixin:
    """Un directorio de trabajo propio: nadie toca el log de verdad."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        self.directory = Path(self.tmp.name)
        self.current = self.directory / 'stderr.log'

        settings = override_settings(LOG_FILE=self.current)
        settings.enable()
        self.addCleanup(settings.disable)

    def write(self, text='linea\n'):
        self.current.write_text(text)

    def make_rotated(self, *numbers):
        for number in numbers:
            rotated_name(self.current, number).write_text(f'viejo {number}\n')


class TestTheNumbering(LogDirectoryMixin, SimpleTestCase):

    def test_the_first_rotation_is_number_one(self):
        self.write()

        self.assertEqual(next_number(self.current), 1)

    def test_it_continues_from_what_is_already_there(self):
        """
        Produccion va por el 5. Renumerar lo existente cambiaria el nombre de
        ficheros a los que alguien quiza ya se refirio en una incidencia.
        """
        self.make_rotated(1, 2, 3, 4, 5)

        self.assertEqual(next_number(self.current), 6)

    def test_a_gap_does_not_reuse_a_number(self):
        """
        Si falta el 3 porque alguien lo borro, el siguiente sigue siendo el 6:
        reutilizar el 3 pisaria el orden y dos ficheros distintos acabarian
        pareciendo consecutivos.
        """
        self.make_rotated(1, 2, 4, 5)

        self.assertEqual(next_number(self.current), 6)

    def test_a_file_that_only_looks_rotated_is_ignored(self):
        (self.directory / 'stderr_old_x.log').write_text('x')
        (self.directory / 'otro_old_9.log').write_text('x')

        self.assertEqual(rotated_files(self.current), [])
        self.assertEqual(next_number(self.current), 1)


class TestWhenItRotates(LogDirectoryMixin, SimpleTestCase):

    def test_a_small_file_is_left_alone(self):
        self.write('corto\n')

        self.assertFalse(should_rotate(self.current, max_bytes=1024))

    def test_a_file_at_the_limit_rotates(self):
        self.write('x' * 1024)

        self.assertTrue(should_rotate(self.current, max_bytes=1024))

    def test_a_missing_file_is_not_an_error(self):
        """Puede que aun no se haya escrito nada. No hay nada que rotar."""
        self.assertFalse(should_rotate(self.current))

    def test_the_command_does_nothing_below_the_limit(self):
        self.write('corto\n')

        call_command('rotate_logs', max_mb=100, stdout=StringIO())

        self.assertTrue(self.current.exists())
        self.assertEqual(rotated_files(self.current), [])

    def test_the_command_rotates_above_the_limit(self):
        self.write('x' * 2048)

        call_command('rotate_logs', max_mb=0.001, stdout=StringIO())

        self.assertFalse(self.current.exists())
        self.assertEqual(len(rotated_files(self.current)), 1)

    def test_force_rotates_a_small_file(self):
        self.write('corto\n')

        call_command('rotate_logs', force=True, stdout=StringIO())

        self.assertEqual(len(rotated_files(self.current)), 1)


class TestNothingIsLost(LogDirectoryMixin, SimpleTestCase):

    def test_the_content_travels_to_the_rotated_file(self):
        self.write('lo que habia\n')

        target = rotate(self.current)

        self.assertEqual(target.read_text(), 'lo que habia\n')

    def test_the_new_file_is_not_created_here(self):
        """
        Lo crea el handler en la primera escritura. Crearlo desde el cron lo
        dejaria con el dueno y los permisos de ese proceso, que no tienen por
        que ser los del worker que luego intenta escribirlo.
        """
        self.write()

        rotate(self.current)

        self.assertFalse(self.current.exists())


class TestARunningWorkerFollowsTheRotation(LogDirectoryMixin, SimpleTestCase):
    """
    La prueba que sostiene todo lo demas.

    Renombrar no afecta a un descriptor ya abierto. Si el handler no reabre,
    rotar deja el log roto en silencio.
    """

    def make_logger(self, handler_class):
        handler = handler_class(str(self.current), encoding='utf-8')
        logger = logging.getLogger(f'prueba.{handler_class.__name__}')
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)
        logger.propagate = False

        self.addCleanup(handler.close)

        return logger, handler

    def test_the_configured_handler_reopens_the_new_file(self):
        logger, handler = self.make_logger(
            logging.handlers.WatchedFileHandler
        )

        logger.info('antes de rotar')
        target = rotate(self.current)
        logger.info('despues de rotar')
        handler.flush()

        self.assertIn('antes de rotar', target.read_text())

        # Lo que decide: la escritura posterior va al fichero NUEVO.
        self.assertTrue(self.current.exists())
        self.assertIn('despues de rotar', self.current.read_text())
        self.assertNotIn('despues de rotar', target.read_text())

    def test_a_plain_file_handler_would_lose_everything(self):
        """
        El fallo del que protege el cambio de handler, fijado aqui para que se
        vea que no es una precaucion teorica: con `FileHandler`, tras rotar el
        `stderr.log` nuevo ni siquiera llega a existir.
        """
        logger, handler = self.make_logger(logging.FileHandler)

        logger.info('antes de rotar')
        target = rotate(self.current)
        logger.info('despues de rotar')
        handler.flush()

        self.assertFalse(self.current.exists())
        self.assertIn('despues de rotar', target.read_text())

    def test_the_project_is_configured_with_the_handler_that_survives(self):
        """
        Se lee el fichero de ajustes, no ``settings.LOGGING``.

        Estas pruebas corren con ``settings_test``, que manda el log a un
        ``NullHandler`` a proposito -- ninguna prueba deberia escribir en el
        log de verdad. Asi que preguntarle a los ajustes activos no diria nada
        de lo que hace produccion, que es lo unico que importa aqui.
        """
        from django.conf import settings as active

        source = (Path(active.BASE_DIR) / 'app_core' / 'settings.py').read_text(
            encoding='utf-8'
        )

        self.assertIn("'logging.handlers.WatchedFileHandler'", source)
        self.assertNotIn("'class': 'logging.FileHandler'", source)


class TestTheDiskDoesNotFillUp(LogDirectoryMixin, SimpleTestCase):
    """
    El disco de cPanel es una cuota fija. Un log sin tope la llena, y cuando
    eso pasa fallan las escrituras de todo lo demas, no solo las del log.
    """

    def test_the_oldest_ones_are_deleted(self):
        self.make_rotated(1, 2, 3, 4, 5)

        removed = prune(self.current, keep=2)

        self.assertEqual(
            sorted(path.name for path in removed),
            ['stderr_old_1.log', 'stderr_old_2.log', 'stderr_old_3.log'],
        )

    def test_the_newest_ones_survive(self):
        self.make_rotated(1, 2, 3, 4, 5)

        prune(self.current, keep=2)

        self.assertEqual(
            [path.name for _n, path in rotated_files(self.current)],
            ['stderr_old_5.log', 'stderr_old_4.log'],
        )

    def test_keeping_zero_means_keeping_everything(self):
        """Es la salida de emergencia, no el valor por defecto."""
        self.make_rotated(1, 2, 3)

        self.assertEqual(prune(self.current, keep=0), [])
        self.assertEqual(len(rotated_files(self.current)), 3)

    def test_rotating_repeatedly_does_not_pile_up(self):
        for _ in range(8):
            self.write('x' * 64)
            call_command('rotate_logs', force=True, keep=3, stdout=StringIO())

        self.assertEqual(len(rotated_files(self.current)), 3)


class TestReadingTheLog(LogDirectoryMixin, SimpleTestCase):

    def test_it_shows_the_last_lines(self):
        self.write(''.join(f'linea {n}\n' for n in range(1, 51)))

        out = StringIO()
        call_command('show_log', lines=3, stdout=out)
        body = out.getvalue()

        self.assertIn('linea 50', body)
        self.assertNotIn('linea 1\n', body)

    def test_it_can_filter_by_text(self):
        self.write('todo bien\nOperationalError: se cayo\notra cosa\n')

        out = StringIO()
        call_command('show_log', contains='OperationalError', stdout=out)
        body = out.getvalue()

        self.assertIn('se cayo', body)
        self.assertNotIn('otra cosa', body)

    def test_a_missing_file_says_so_instead_of_crashing(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command('show_log')

    def test_the_number_of_lines_has_a_ceiling(self):
        """
        La salida se guarda en `CommandRunModel`. Sin tope, `--lines 999999`
        vuelca el fichero entero a una tabla de la base de datos.
        """
        from .management.commands.show_log import MAX_LINES

        self.write(''.join(f'linea {n}\n' for n in range(MAX_LINES + 500)))

        out = StringIO()
        call_command('show_log', lines=999999, stdout=out)

        # El encabezado ocupa tres lineas mas.
        self.assertLessEqual(len(out.getvalue().splitlines()), MAX_LINES + 5)


class TestHumanSize(SimpleTestCase):

    def test_it_reads_at_a_glance(self):
        self.assertEqual(human_size(512), '512 B')
        self.assertEqual(human_size(3 * 1024 * 1024), '3.0 MB')
