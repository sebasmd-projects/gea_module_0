# apps/common/utils/management/commands/db_backup.py
"""
Respaldos de la base de datos, sin deshacer el cifrado de campo.

Lo que hacía y por qué era un problema
--------------------------------------
``dumpdata`` serializa el **valor de Python** de cada campo, y en los campos de
``django-encrypted-model-fields`` ese valor es el ya descifrado. Así que los
respaldos de usuarios salían con el correo, el teléfono, la fecha de nacimiento
y el pasaporte **en claro** -- comprobado, no deducido.

Es decir: el respaldo deshacía el cifrado de campo. `FIELD_ENCRYPTION_KEY`
protege la base de datos contra un volcado robado, y el volcado de al lado, sin
llave y con permisos de lectura para todo el mundo, era ese volcado robado ya
servido. Y un respaldo no se queda quieto: acaba en un portátil, en un adjunto
o en una carpeta compartida.

Tres cosas cambian
------------------
1. **El fichero se cifra** con una contraseña (``backup_crypto.py``), así que
   descargarlo no basta para leerlo. Se abre con ``manage.py db_restore_open``.
2. **Permisos 600** en todo lo que se escribe, cifrado o no. Es una línea y
   cubre el caso más tonto y más frecuente: el respaldo en un directorio que
   comparte la cuenta de hosting.
3. **Sin contraseña no se escribe PII en claro.** El volcado de usuarios se
   salta, con un aviso que dice cómo arreglarlo. Escribirlo igualmente exige
   pedirlo a mano con ``--allow-plaintext``, que es justo la fricción que hace
   falta para que sea una decisión y no un descuido.

El volcado general no lleva PII, y hay una comprobación que lo sostiene: las
apps con campos cifrados están declaradas abajo, y si alguna acabara en la
lista del volcado general el comando se niega en vez de escribirla.
"""

import os
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.common.utils.backup_crypto import (PASSPHRASE_ENV,
                                             BackupCryptoError, encrypt,
                                             passphrase_from)

#: Apps cuyos modelos llevan campos cifrados. Un volcado suyo es PII en claro.
#: La lista es explícita a propósito: una comprobación automática que recorriera
#: los modelos sería más lista y también más fácil de romper en silencio el día
#: que cambie el nombre de la clase del campo.
APPS_WITH_PII = {'users', 'certificates', 'pqrs'}

#: El volcado general: lo que se puede guardar sin PII dentro.
GENERAL_APPS = [
    'core', 'utils', 'assets', 'assets_location', 'buyers', 'account',
    'notifications',
]

#: El volcado de usuarios, que **sí** la lleva.
USER_APPS = ['users']

#: Sistema y terceros que no interesa arrastrar.
EXCLUDE = [
    'contenttypes',
    'auth.Permission',
    'admin.LogEntry',
    'sessions.Session',
    'axes.AccessAttempt',
    'axes.AccessLog',
    'auditlog.LogEntry',
]


class Command(BaseCommand):
    help = (
        'Genera respaldos JSON. Los que llevan datos personales se cifran con '
        'una contraseña; sin ella no se escriben.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '-o', '--output-dir',
            default='.',
            help='Directorio de salida (por defecto: el actual).',
        )
        parser.add_argument(
            '--passphrase-file',
            help=(
                'Fichero con la contraseña de cifrado. Si no se indica se usa '
                f'la variable de entorno {PASSPHRASE_ENV}. No hay opción para '
                'pasarla como argumento: acabaría en el historial y en «ps».'
            ),
        )
        parser.add_argument(
            '--allow-plaintext',
            action='store_true',
            help=(
                'Escribe el volcado de usuarios SIN cifrar. Es PII en claro en '
                'un fichero; hay que pedirlo a mano y a sabiendas.'
            ),
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)

        self._refuse_pii_in_the_general_dump()

        passphrase = passphrase_from(options.get('passphrase_file'))

        files = [
            ('h_backup.json', GENERAL_APPS, 4, False),
            ('backup.json', GENERAL_APPS, None, False),
            ('h_users_backup.json', USER_APPS, 4, True),
            ('users_backup.json', USER_APPS, None, True),
        ]

        for filename, apps, indent, carries_pii in files:
            self._write(
                output_dir, filename, apps, indent, carries_pii,
                passphrase, options['allow_plaintext'],
            )

        if not passphrase:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                'Los volcados de usuarios NO se han escrito: llevan datos '
                'personales en claro y no había contraseña con la que '
                'cifrarlos.'
            ))
            self.stdout.write(
                f'   Pon {PASSPHRASE_ENV} en el entorno, o pasa '
                '--passphrase-file, y vuelve a lanzarlo.'
            )

    # ------------------------------------------------------------------
    def _refuse_pii_in_the_general_dump(self):
        """
        Que el volcado «sin datos personales» siga sin llevarlos.

        Hoy se cumple, y sin esta comprobación se cumpliría hasta que alguien
        añadiera una app a la lista de arriba sin caer en que sus modelos
        llevan campos cifrados. El fallo saldría en un fichero, meses después.
        """
        offenders = APPS_WITH_PII.intersection(GENERAL_APPS)

        if offenders:
            raise CommandError(
                'GENERAL_APPS incluye apps con datos personales: '
                f'{", ".join(sorted(offenders))}. Ese volcado se escribe sin '
                'cifrar, así que o sale de la lista o pasa a los de usuarios.'
            )

    def _write(self, output_dir, filename, apps, indent, carries_pii,
               passphrase, allow_plaintext):
        """Escribe un volcado, cifrado si lleva PII y hay con qué."""
        if carries_pii and not passphrase and not allow_plaintext:
            return

        encrypting = bool(carries_pii and passphrase)
        target = output_dir / (filename + '.enc' if encrypting else filename)

        from io import StringIO

        buffer = StringIO()

        call_command(
            'dumpdata',
            *apps,
            use_natural_foreign_keys=False,
            use_natural_primary_keys=False,
            exclude=EXCLUDE,
            indent=indent,
            stdout=buffer,
        )

        payload = buffer.getvalue().encode('utf-8')

        if encrypting:
            try:
                payload = encrypt(payload, passphrase)
            except BackupCryptoError as error:
                raise CommandError(str(error))

        # Se abre con los permisos ya puestos, no se corrigen después: entre
        # crear el fichero y hacerle chmod hay una ventana en la que cualquiera
        # de la máquina puede abrirlo, y en un hosting compartido esa ventana
        # es el problema entero.
        descriptor = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)

        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(payload)

        note = ''

        if encrypting:
            note = ' (cifrado)'
        elif carries_pii:
            note = ' (SIN CIFRAR: lleva datos personales en claro)'

        style = self.style.WARNING if (
            carries_pii and not encrypting) else self.style.SUCCESS

        self.stdout.write(style(f'✔ {target.resolve()}{note}'))
