# apps/common/utils/management/commands/check_cron.py
"""
Si las tareas programadas estan instaladas de verdad, y si son las de ahora.

Declarar `CRONJOBS` en `settings.py` no programa nada. `django-crontab` escribe
esas lineas en el crontab del usuario cuando se ejecuta:

    manage.py crontab add

Hasta entonces la lista existe en el codigo y no corre nadie. Y el sintoma es
mudo: no hay error, no hay log, simplemente las cosas no pasan. El anclaje en
Bitcoin se queda pendiente para siempre aunque el envio saliera bien, porque
quien lo madura es un cron.

Hay un segundo modo de fallo, mas traicionero, y es el que este comando existe
para ver. La linea que `django-crontab` escribe **no** lleva el comando: lleva
``crontab run <hash>``, y ese hash se calcula sobre la definicion entera del
trabajo, horario incluido. Cambiar `('15 * * * *', ...)` por
`('*/15 * * * *', ...)` cambia el hash, y la linea instalada pasa a apuntar a
un trabajo que ya no existe. El cron sigue disparando, la aplicacion no
encuentra nada que ejecutar, y todo sigue igual de callado.

Por eso, tras **cualquier** cambio en `CRONJOBS`:

    manage.py crontab remove
    manage.py crontab add

En cPanel tambien se pueden programar desde «Cron Jobs» del panel, y entonces
lo que hay que comprobar es que la linea siga apuntando al hash correcto.

    manage.py check_cron
"""

import hashlib
import json
import os
import subprocess
import re
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand

# La misma expresion que usa django-crontab para leer una linea del crontab.
CRON_LINE = re.compile(r'^\s*(([^#\s]+\s+){5})([^#\n]*)\s*(#\s*([^\n]*)|$)')

RUN_HASH = re.compile(r'crontab\s+run\s+([0-9a-f]{32})')


class Command(BaseCommand):
    help = (
        'Comprueba si las tareas de CRONJOBS estan instaladas en el crontab '
        'y si corresponden a la definicion actual.'
    )

    def handle(self, *args, **options):
        jobs = getattr(settings, 'CRONJOBS', [])

        if not jobs:
            self.stdout.write('No hay tareas declaradas en CRONJOBS.')
            return

        self._section('1. Tareas declaradas en el codigo')

        declared = {}

        for job in jobs:
            digest = self._hash(job)
            declared[digest] = job
            self.stdout.write(f'   {job[0]:<16} {self._describe(job)}')

        installed, error = self._read_crontab()

        self._section('2. Lo que hay instalado en el crontab')

        if error:
            self.stdout.write(self.style.ERROR(f'   No se pudo leer: {error}'))
            self.stdout.write(
                '   Sin acceso al crontab no se puede saber si las tareas '
                'corren. En cPanel se ven en «Cron Jobs» del panel.'
            )
            return

        marker = self._comment()
        ours = []

        for line in installed:
            match = CRON_LINE.findall(line)

            if match and match[0][4].strip() == marker:
                ours.append(line.strip())

        if not ours:
            self.stdout.write(self.style.ERROR(
                '   Ninguna. Las tareas estan declaradas pero no instaladas: '
                'no las ejecuta nadie.'
            ))
            self._how_to_install()
            return

        found = set()

        for line in ours:
            digest = RUN_HASH.search(line)
            digest = digest.group(1) if digest else ''

            if digest in declared:
                found.add(digest)
                job = declared[digest]
                self.stdout.write(self.style.SUCCESS(
                    f'   {job[0]:<16} {self._describe(job)}'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'   {line[:70]}…'
                ))
                self.stdout.write(
                    '      Instalada, pero apunta a un trabajo que ya no '
                    'existe con esa definicion. El cron dispara y no ejecuta '
                    'nada.'
                )

        missing = [declared[d] for d in declared if d not in found]

        self._section('3. Conclusion')

        if not missing and len(found) == len(declared):
            self.stdout.write(self.style.SUCCESS(
                '   Todas las tareas estan instaladas y corresponden a la '
                'definicion actual.'
            ))
            self.stdout.write(
                '   Que esten instaladas no prueba que se hayan ejecutado. '
                'Para el anclaje, «manage.py check_anchoring» dice si hay '
                'pruebas esperando de mas.'
            )
            return

        self.stdout.write(self.style.ERROR(
            f'   Faltan {len(missing)} de {len(declared)} tareas.'
        ))

        for job in missing:
            self.stdout.write(f'      {job[0]:<16} {self._describe(job)}')

        self.stdout.write('')
        self.stdout.write(
            '   Esto pasa sobre todo despues de cambiar un horario: la linea '
            'instalada lleva un hash de la definicion entera, asi que al '
            'cambiarla deja de corresponder y hay que reinstalarla.'
        )

        self._how_to_install()

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _how_to_install(self):
        self.stdout.write('')
        self.stdout.write('   Se instalan con, en este orden:')
        self.stdout.write('      manage.py crontab remove')
        self.stdout.write('      manage.py crontab add')
        self.stdout.write(
            '   Y mientras tanto, para ponerse al dia sin esperar al cron, '
            'los comandos se pueden ejecutar a mano desde esta misma consola.'
        )

    def _hash(self, job) -> str:
        """
        El mismo hash que escribe django-crontab en la linea del crontab.

        Se replica en lugar de importarlo porque el metodo es privado en la
        libreria. Si algun dia cambia, esto lo dira: se veran todas las tareas
        como no instaladas, que es un fallo ruidoso y no uno silencioso.
        """
        encoded = json.JSONEncoder(sort_keys=True).encode(job)

        return hashlib.md5(encoded.encode('utf-8')).hexdigest()

    def _comment(self) -> str:
        """La marca con la que django-crontab reconoce sus propias lineas."""
        default = os.environ.get(
            'DJANGO_SETTINGS_MODULE', 'app_core.settings'
        ).split('.')[0]

        project = getattr(settings, 'CRONTAB_DJANGO_PROJECT_NAME', default)

        return getattr(
            settings, 'CRONTAB_COMMENT', f'django-cronjobs for {project}'
        )

    def _describe(self, job) -> str:
        """Como se llama el trabajo, sin el envoltorio de call_command."""
        target = job[1]

        if len(job) > 2 and isinstance(job[2], (list, tuple)) and job[2]:
            return str(job[2][0])

        return str(target).split('.')[-1]

    def _read_crontab(self):
        """
        Leer el crontab del usuario. Devuelve (lineas, error).

        Se usa el mismo ejecutable que configuraria django-crontab, para que
        lo que se lee aqui sea lo que esa libreria escribe.
        """
        executable = getattr(settings, 'CRONTAB_EXECUTABLE', '/usr/bin/crontab')

        if not os.path.exists(executable):
            found = shutil.which('crontab')

            if not found:
                return [], (
                    f'no se encontro el ejecutable «crontab» (se busco en '
                    f'{executable})'
                )

            executable = found

        # `subprocess.run` con lista, no `os.popen` con una f-string.
        #
        # `os.popen` lanza una shell, y ahi la ruta del ejecutable se
        # interpola dentro de una linea de comandos. Hoy esa ruta sale de
        # `settings` y no del usuario, asi que no es explotable -- pero es
        # ejecucion por shell sin ninguna necesidad, en un comando que ademas
        # se puede lanzar desde la consola de operaciones. Sin shell no hay
        # nada que escapar, y de paso el 2>&1 deja de ser sintaxis de shell y
        # pasa a ser un argumento del propio subproceso.
        try:
            completed = subprocess.run(
                [executable, '-l'],
                capture_output=True,
                text=True,
                timeout=15,
                stdin=subprocess.DEVNULL,
            )
            output = (completed.stdout or '') + (completed.stderr or '')
        except (OSError, subprocess.SubprocessError) as error:
            return [], str(error)

        # «no crontab for <usuario>» no es un error: es un crontab vacio.
        if 'no crontab for' in output:
            return [], None

        if 'not allowed' in output or 'Permission denied' in output:
            return [], output.strip()

        return output.splitlines(), None
