# apps/common/utils/tests_cron.py
"""
Que se sepa si las tareas programadas corren de verdad.

Declarar `CRONJOBS` no programa nada: `django-crontab` escribe esas lineas en
el crontab del usuario cuando alguien ejecuta `manage.py crontab add`. Hasta
entonces la lista existe en el codigo y no la ejecuta nadie, sin error y sin
log. Un anclaje en Bitcoin puede quedarse pendiente para siempre --aunque el
envio saliera perfecto-- porque quien lo madura es un cron que nunca se
instalo.

Y hay un segundo modo de fallo peor, que es el que llevo a escribir esto. La
linea que se instala **no** lleva el comando: lleva ``crontab run <hash>``, y
ese hash cubre la definicion entera del trabajo, horario incluido. Al cambiar
`('15 * * * *', ...)` por `('*/15 * * * *', ...)` el hash cambia, la linea
instalada pasa a apuntar a un trabajo que ya no existe, y el cron sigue
disparando sin ejecutar nada. Desde fuera se ve exactamente igual que si todo
funcionara.

Aqui se comprueba que los tres desenlaces se distingan, porque cada uno lleva
a hacer algo distinto.

    manage.py test apps.common.utils.tests_cron \\
        --settings=app_core.settings_test
"""

import hashlib
import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

READ = 'apps.common.utils.management.commands.check_cron.Command._read_crontab'

JOBS = [
    ('*/15 * * * *', 'django.core.management.call_command',
     ['upgrade_ots_anchors']),
    ('0 19 * * *', 'apps.common.utils.cron.generate_and_send_gea_code'),
]

COMMENT = 'django-cronjobs for app_core'


def job_hash(job) -> str:
    """El hash que django-crontab escribe en la linea."""
    return hashlib.md5(
        json.JSONEncoder(sort_keys=True).encode(job).encode('utf-8')
    ).hexdigest()


def crontab_line(job, comment=COMMENT) -> str:
    return (
        f'{job[0]} /usr/bin/python manage.py crontab run {job_hash(job)} '
        f'--settings=app_core.settings # {comment}'
    )


class CronCheckTestCase(SimpleTestCase):

    def run_command(self, lines, error=None):
        out = StringIO()

        with override_settings(CRONJOBS=JOBS):
            with mock.patch(READ, return_value=(lines, error)):
                call_command('check_cron', stdout=out, stderr=out,
                             no_color=True)

        return out.getvalue()


class TestNothingInstalled(CronCheckTestCase):

    def test_an_empty_crontab_is_reported_as_nobody_running_them(self):
        """
        Es el caso que mas despista: el codigo declara las tareas, la pagina
        del anclaje dice «pendiente», y no hay ningun error en ninguna parte.
        """
        output = self.run_command([])

        self.assertIn('no instaladas', output)
        self.assertIn('no las ejecuta nadie', output)

    def test_it_says_how_to_install_them(self):
        output = self.run_command([])

        self.assertIn('crontab remove', output)
        self.assertIn('crontab add', output)

    def test_lines_from_other_programs_are_not_counted_as_ours(self):
        """El crontab del usuario puede tener cosas que no son del proyecto."""
        output = self.run_command([
            '0 3 * * * /usr/bin/backup.sh # copia de seguridad nocturna',
        ])

        self.assertIn('no instaladas', output)


class TestEverythingInstalled(CronCheckTestCase):

    def test_matching_lines_are_reported_as_correct(self):
        output = self.run_command([crontab_line(job) for job in JOBS])

        self.assertIn('estan instaladas y corresponden', output)
        self.assertNotIn('Faltan', output)

    def test_it_does_not_claim_they_have_actually_run(self):
        """
        Instalado no es ejecutado. Decir lo contrario mandaria a buscar el
        fallo en otro sitio cuando el cron esta ahi pero el servidor no lo
        dispara.
        """
        output = self.run_command([crontab_line(job) for job in JOBS])

        self.assertIn('no prueba que se hayan ejecutado', output)


class TestInstalledButStale(CronCheckTestCase):
    """
    El fallo silencioso: la linea esta, el cron dispara, y no ejecuta nada.
    """

    def test_a_line_pointing_at_an_old_definition_is_flagged(self):
        vieja = ('15 * * * *', 'django.core.management.call_command',
                 ['upgrade_ots_anchors'])

        output = self.run_command([
            crontab_line(vieja),
            crontab_line(JOBS[1]),
        ])

        self.assertIn('ya no existe con esa definicion', output)
        self.assertIn('El cron dispara y no ejecuta nada', output)

    def test_it_counts_the_job_as_missing_and_says_why(self):
        vieja = ('15 * * * *', 'django.core.management.call_command',
                 ['upgrade_ots_anchors'])

        output = self.run_command([
            crontab_line(vieja),
            crontab_line(JOBS[1]),
        ])

        self.assertIn('Faltan 1 de 2', output)
        self.assertIn('upgrade_ots_anchors', output)
        self.assertIn('despues de cambiar un horario', output)


class TestWhenTheCrontabCannotBeRead(CronCheckTestCase):

    def test_it_says_so_instead_of_claiming_nothing_is_installed(self):
        """
        No poder mirar y no haber nada son cosas distintas, y confundirlas
        mandaria a reinstalar tareas que quiza ya estan puestas.
        """
        output = self.run_command([], error='crontab: not allowed')

        self.assertIn('No se pudo leer', output)
        self.assertNotIn('no las ejecuta nadie', output)
        self.assertIn('Cron Jobs', output)
