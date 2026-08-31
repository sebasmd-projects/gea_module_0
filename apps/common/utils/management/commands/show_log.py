# apps/common/utils/management/commands/show_log.py
"""
Ensena el final del log sin entrar por SSH.

Mirar el log era lo unico que seguia obligando a abrir una terminal, y es
justo lo primero que hace falta cuando algo falla. Ahora se lee desde la
consola de operaciones, como todo lo demas.

Se lee **por el final** y sin cargar el fichero entero en memoria: son varios
megas y la parte util son las ultimas lineas. Un ``read()`` de tres megas
dentro de una peticion es una forma tonta de tumbar un worker.

Cuidado con lo que sale
-----------------------
Un log lleva trazas, rutas, direcciones IP y a veces correos. La salida de la
consola **se guarda en ``CommandRunModel``**, asi que lo que se mire aqui
queda ademas escrito en una tabla del propio panel. Es una razon de peso para
pedir pocas lineas y filtrar, en vez de volcar el fichero entero por si acaso.

    manage.py show_log
    manage.py show_log --lines 200 --contains OperationalError
    manage.py show_log --list
"""

import os
import re

from django.core.management.base import BaseCommand, CommandError

from apps.common.utils.logs import (human_size, log_file, rotated_files,
                                    rotated_name)

#: Tope duro de lineas. Sin el, `--lines 999999` vuelca el fichero entero a
#: una tabla de la base de datos.
MAX_LINES = 2000

#: Cuanto se lee del final del fichero como mucho. Es el limite real: con
#: lineas muy largas, mil lineas pueden ser muchisimo texto.
MAX_TAIL_BYTES = 2 * 1024 * 1024

#: Lo que se lee de disco en cada paso al ir hacia atras.
CHUNK = 64 * 1024


def tail(path, lines: int, max_bytes: int = MAX_TAIL_BYTES) -> list:
    """
    Las ultimas ``lines`` lineas del fichero.

    Va hacia atras a trozos y para en cuanto tiene bastantes saltos de linea,
    para no leer megas de fichero que nadie va a mirar.
    """
    with open(path, 'rb') as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()

        data = b''
        position = end

        while position > 0 and data.count(b'\n') <= lines:
            step = min(CHUNK, position)
            position -= step

            handle.seek(position)
            data = handle.read(step) + data

            if len(data) >= max_bytes:
                break

    text = data.decode('utf-8', errors='replace')

    return text.splitlines()[-lines:]


class Command(BaseCommand):
    help = 'Muestra las ultimas lineas del log de la aplicacion.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--lines',
            type=int,
            default=100,
            help=f'Cuantas lineas del final. Maximo {MAX_LINES}.',
        )
        parser.add_argument(
            '--contains',
            default='',
            help='Solo las lineas que contengan este texto.',
        )
        parser.add_argument(
            '--rotated',
            type=int,
            default=0,
            help='Leer un rotado en vez del actual: 5 para stderr_old_5.log.',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='Solo listar los ficheros de log y su tamano.',
        )

    def handle(self, *args, **options):
        current = log_file()

        if options['list']:
            return self._list(current)

        target = current

        if options['rotated']:
            target = rotated_name(current, options['rotated'])

        if not target.exists():
            raise CommandError(f'No existe: {target}')

        lines = max(1, min(options['lines'], MAX_LINES))
        needle = (options['contains'] or '').strip()

        try:
            rows = tail(target, lines)
        except OSError as error:
            raise CommandError(f'No se pudo leer {target}: {error}')

        if needle:
            # Busqueda literal, no expresion regular: un patron mal escrito
            # desde una pagina web puede colgar el proceso, y aqui nadie
            # necesita expresiones regulares.
            lowered = needle.lower()
            rows = [row for row in rows if lowered in row.lower()]

        size = target.stat().st_size

        self.stdout.write(f'{target.name} — {human_size(size)}')

        if needle:
            self.stdout.write(
                f'Ultimas {lines} lineas, filtrando por "{needle}": '
                f'{len(rows)} coinciden.'
            )
        else:
            self.stdout.write(f'Ultimas {len(rows)} lineas.')

        self.stdout.write('')

        if not rows:
            self.stdout.write('(nada que mostrar)')
            return

        for row in rows:
            self.stdout.write(row)

    def _list(self, current):
        self.stdout.write(f'Carpeta: {current.parent}')
        self.stdout.write('')

        total = 0

        for path in [current] + [p for _n, p in rotated_files(current)]:
            if not path.exists():
                self.stdout.write(f'  {path.name:<28} (no existe todavia)')
                continue

            size = path.stat().st_size
            total += size

            self.stdout.write(f'  {path.name:<28} {human_size(size)}')

        self.stdout.write('')
        self.stdout.write(f'  {"total":<28} {human_size(total)}')
