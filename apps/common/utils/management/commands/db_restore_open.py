# apps/common/utils/management/commands/db_restore_open.py
"""
Abre un respaldo cifrado por ``db_backup``.

Existe porque un fichero cifrado que nadie sabe abrir no es un respaldo, es un
fichero perdido. La cabecera del propio fichero dice el formato y los
parámetros --se puede leer con ``head``-- y este comando hace el resto.

**No carga nada en la base de datos.** Descifra y deja el JSON, que es lo que
después se pasa a ``loaddata`` si de verdad se quiere restaurar. Separarlo es
deliberado: descifrar para mirar un dato es una operación de todos los días, y
sobrescribir la base con un volcado de hace tres semanas no debería estar a un
argumento de distancia.
"""

import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.common.utils.backup_crypto import (PASSPHRASE_ENV,
                                             BackupCryptoError, decrypt,
                                             passphrase_from)


class Command(BaseCommand):
    help = 'Descifra un respaldo generado por db_backup. No carga nada.'

    def add_arguments(self, parser):
        parser.add_argument('source', help='El fichero .json.enc')
        parser.add_argument(
            '-o', '--output',
            help=(
                'Dónde dejar el JSON. Por defecto, el mismo nombre sin «.enc» '
                'y en el mismo directorio.'
            ),
        )
        parser.add_argument(
            '--passphrase-file',
            help=(
                'Fichero con la contraseña. Si no se indica se usa la variable '
                f'de entorno {PASSPHRASE_ENV}.'
            ),
        )

    def handle(self, *args, **options):
        source = Path(options['source'])

        if not source.exists():
            raise CommandError(f'no existe: {source}')

        passphrase = passphrase_from(options.get('passphrase_file'))

        if not passphrase:
            raise CommandError(
                f'no hay contraseña: pon {PASSPHRASE_ENV} en el entorno o pasa '
                '--passphrase-file'
            )

        try:
            payload = decrypt(source.read_bytes(), passphrase)
        except BackupCryptoError as error:
            raise CommandError(str(error))

        target = Path(
            options['output']
            or (source.with_suffix('') if source.suffix == '.enc' else
                source.with_name(source.name + '.json'))
        )

        # 600, igual que al escribirlo: el JSON descifrado es exactamente lo
        # que el cifrado existe para que no ande suelto.
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)

        self.stdout.write(self.style.SUCCESS(f'✔ {target.resolve()}'))
        self.stdout.write(
            '   Lleva datos personales en claro. Bórralo en cuanto acabes; '
            'para restaurar de verdad: manage.py loaddata <fichero>'
        )
