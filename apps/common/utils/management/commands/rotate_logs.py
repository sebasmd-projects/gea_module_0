# apps/common/utils/management/commands/rotate_logs.py
"""
Rota el log cuando se pasa de tamano, y tira los mas viejos.

El log crecia sin fin. Rotarlo a mano dejaba ``stderr_old_1.log``,
``stderr_old_2.log``... hasta el cinco, que es donde se quedo: se hacia cuando
alguien se acordaba, y acordarse no es una politica.

Por defecto **no hace nada si el fichero no ha llegado al tamano**, asi que
sale barato ejecutarlo a menudo -- es un ``stat``. Eso es lo que permite
programarlo cada hora en vez de una vez por semana: con una revision semanal,
un dia con muchos errores deja el fichero en decenas de megas antes de que a
nadie le toque mirarlo, y el tope de 3 MB no significa nada.

Lo importante de esto no esta aqui, sino en ``settings.LOGGING``: el handler
es ``WatchedFileHandler``, que reabre el fichero cuando detecta que lo han
renombrado. Con el ``FileHandler`` de siempre, rotar en un servidor con varios
workers hace que todos sigan escribiendo en el fichero ya renombrado y que el
nuevo se quede vacio para siempre. Ver ``apps/common/utils/logs.py``.

    manage.py rotate_logs
    manage.py rotate_logs --force
    manage.py rotate_logs --max-mb 10 --keep 20
"""

from django.core.management.base import BaseCommand

from apps.common.utils.logs import (DEFAULT_KEEP, DEFAULT_MAX_BYTES,
                                    human_size, log_file, prune, rotate,
                                    rotated_files, should_rotate)


class Command(BaseCommand):
    help = (
        'Rota el fichero de log si ha superado el tamano maximo, y conserva '
        'solo los ultimos rotados.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-mb',
            type=float,
            default=DEFAULT_MAX_BYTES / (1024 * 1024),
            help='Tamano a partir del cual se rota, en MB.',
        )
        parser.add_argument(
            '--keep',
            type=int,
            default=DEFAULT_KEEP,
            help='Cuantos rotados se conservan. 0 los conserva todos.',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Rota aunque no haya llegado al tamano.',
        )

    def handle(self, *args, **options):
        current = log_file()
        max_bytes = int(options['max_mb'] * 1024 * 1024)
        keep = options['keep']

        self.stdout.write(f'Fichero: {current}')

        if not current.exists():
            self.stdout.write(self.style.WARNING(
                'No existe todavia: no hay nada que rotar.'
            ))
            return

        size = current.stat().st_size
        self.stdout.write(
            f'Tamano:  {human_size(size)} '
            f'(se rota a partir de {human_size(max_bytes)})'
        )

        if not options['force'] and not should_rotate(current, max_bytes):
            self.stdout.write(self.style.SUCCESS(
                'Por debajo del tope: no se rota.'
            ))
            self._report_rotated(current)
            return

        try:
            target = rotate(current)
        except OSError as error:
            # Sin permisos o con el disco lleno. Se dice en voz alta y se sale
            # con codigo distinto de cero: una rotacion que falla en silencio
            # es como no tenerla.
            self.stderr.write(self.style.ERROR(
                f'No se pudo rotar: {error}'
            ))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(f'Rotado a {target.name}.'))
        self.stdout.write(
            'El fichero nuevo lo crea la aplicacion en la primera escritura.'
        )

        for path in prune(current, keep):
            self.stdout.write(f'Borrado por antiguedad: {path.name}')

        self._report_rotated(current)

    def _report_rotated(self, current):
        existing = rotated_files(current)

        if not existing:
            self.stdout.write('Sin rotados previos.')
            return

        total = 0

        self.stdout.write('')
        self.stdout.write('Rotados (del mas nuevo al mas viejo):')

        for _number, path in existing:
            try:
                size = path.stat().st_size
            except OSError:
                continue

            total += size
            self.stdout.write(f'  {path.name:<28} {human_size(size)}')

        self.stdout.write(f'  {"total":<28} {human_size(total)}')
