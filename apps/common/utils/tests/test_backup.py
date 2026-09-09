# apps/common/utils/tests/test_backup.py
"""
Que un respaldo no sea la PII descifrada esperando a que alguien la copie.

`dumpdata` serializa el **valor de Python** de cada campo, y en los de
``django-encrypted-model-fields`` ese valor es el ya descifrado. Asi que los
respaldos de usuarios salian con el correo, el telefono y el pasaporte en
claro: el respaldo deshacia el cifrado de campo. `FIELD_ENCRYPTION_KEY`
protege la base de datos contra un volcado robado, y el volcado de al lado sin
llave era ese volcado robado ya servido.

La primera prueba de este fichero es la que **reproduce el fallo**: comprueba
que `dumpdata` en crudo saca el correo legible. Si algun dia la biblioteca
cambia y deja de hacerlo, esa prueba falla y avisa de que la razon de ser de
todo esto ya no existe -- que es informacion util, no una molestia.

    manage.py test apps.common.utils.tests.test_backup \\
        --settings=app_core.settings_test
"""

import os
import stat
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from ..backup_crypto import BackupCryptoError, decrypt, encrypt
from ..testing import posix_only
from apps.project.common.users.models import UserModel

PASSPHRASE = 'una-contrasena-de-respaldo-larga'
SECRET_EMAIL = 'secreto@example.com'
SECRET_PHONE = '+573001112233'


class TheProblemThisSolvesTests(TestCase):
    """La razon de ser, escrita como prueba para que no se olvide."""

    def test_dumpdata_writes_the_pii_in_the_clear(self):
        UserModel.objects.create_user(
            username='ana', email=SECRET_EMAIL, password='pw-for-tests-123',
            phone_number=SECRET_PHONE,
        )

        out = StringIO()
        call_command('dumpdata', 'users.UserModel', stdout=out)

        self.assertIn(
            SECRET_EMAIL, out.getvalue(),
            'si esto deja de cumplirse, el cifrado del respaldo sobra',
        )


class TheEnvelopeTests(SimpleTestCase):

    def test_it_comes_back_the_same(self):
        blob = encrypt(b'{"hola": "mundo"}', PASSPHRASE)

        self.assertEqual(decrypt(blob, PASSPHRASE), b'{"hola": "mundo"}')

    def test_the_content_is_not_readable(self):
        blob = encrypt(b'{"email": "secreto@example.com"}', PASSPHRASE)

        self.assertNotIn(b'secreto@example.com', blob)

    def test_the_wrong_passphrase_does_not_open_it(self):
        blob = encrypt(b'x', PASSPHRASE)

        with self.assertRaises(BackupCryptoError):
            decrypt(blob, 'otra-cosa')

    def test_a_tampered_file_is_refused_instead_of_returning_garbage(self):
        """
        Fernet esta autenticado, y eso importa: descifrar mal no puede
        devolver algo que parezca un JSON valido.
        """
        blob = bytearray(encrypt(b'{"a": 1}', PASSPHRASE))
        blob[-5] = blob[-5] ^ 0xFF

        with self.assertRaises(BackupCryptoError):
            decrypt(bytes(blob), PASSPHRASE)

    def test_two_backups_of_the_same_thing_look_different(self):
        """Sal distinta cada vez: si no, se ve que dos respaldos son iguales."""
        first = encrypt(b'{"a": 1}', PASSPHRASE)
        second = encrypt(b'{"a": 1}', PASSPHRASE)

        self.assertNotEqual(first, second)

    def test_something_that_is_not_a_backup_says_so(self):
        with self.assertRaises(BackupCryptoError):
            decrypt(b'esto no es un respaldo', PASSPHRASE)

    def test_the_header_says_what_it_is(self):
        """
        Quien se encuentre el fichero dentro de tres anos tiene que poder
        saber que es con un `head`, sin leer el codigo.
        """
        blob = encrypt(b'x', PASSPHRASE)

        self.assertTrue(blob.startswith(b'GEABACKUP1\n'))
        self.assertIn(b'scrypt n=', blob)


class TheBackupCommandTests(TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)

        UserModel.objects.create_user(
            username='ana', email=SECRET_EMAIL, password='pw-for-tests-123',
            phone_number=SECRET_PHONE,
        )

    def run_backup(self, **options):
        out = StringIO()
        call_command('db_backup', '-o', str(self.path), stdout=out,
                     stderr=out, **options)
        return out.getvalue()

    def written(self):
        return sorted(item.name for item in self.path.iterdir())

    # -- con contraseña -------------------------------------------------
    def test_with_a_passphrase_the_user_dump_is_encrypted(self):
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()

        self.assertIn('users_backup.json.enc', self.written())
        self.assertNotIn('users_backup.json', self.written())

    def test_the_encrypted_dump_does_not_leak_the_email(self):
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()

        blob = (self.path / 'users_backup.json.enc').read_bytes()

        self.assertNotIn(SECRET_EMAIL.encode(), blob)
        self.assertNotIn(SECRET_PHONE.encode(), blob)

    def test_it_can_be_opened_again(self):
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()
        call_command(
            'db_restore_open', str(self.path / 'users_backup.json.enc'),
            stdout=StringIO(),
        )

        recovered = (self.path / 'users_backup.json').read_text(encoding='utf-8')

        self.assertIn(SECRET_EMAIL, recovered)

    # -- sin contraseña -------------------------------------------------
    def test_without_a_passphrase_the_pii_is_simply_not_written(self):
        """
        El defecto seguro. Antes se escribia igual, en claro y legible por
        cualquiera de la maquina.
        """
        os.environ.pop('GEA_BACKUP_PASSPHRASE', None)

        output = self.run_backup()

        self.assertNotIn('users_backup.json', self.written())
        self.assertIn('backup.json', self.written())
        self.assertIn('GEA_BACKUP_PASSPHRASE', output)

    def test_writing_it_in_the_clear_has_to_be_asked_for(self):
        os.environ.pop('GEA_BACKUP_PASSPHRASE', None)

        self.run_backup(allow_plaintext=True)

        self.assertIn('users_backup.json', self.written())

    # -- permisos -------------------------------------------------------
    @posix_only
    def test_everything_is_written_readable_only_by_its_owner(self):
        """
        El caso mas tonto y mas frecuente: el respaldo en un directorio que
        comparte la cuenta de hosting.

        Solo en POSIX. Windows no tiene el modo `rw-------` de Unix --`os.open`
        con 0o600 alli solo controla el bit de solo lectura-- asi que esta
        asercion fallaria en un portatil sin que nada estuviera roto. La
        propiedad importa en el servidor, que es Linux; por eso se salta en vez
        de borrarse.
        """
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()

        for item in self.path.iterdir():
            mode = stat.S_IMODE(item.stat().st_mode)

            self.assertEqual(
                mode, 0o600, f'{item.name} salio con permisos {oct(mode)}')

    def test_the_files_are_written_on_any_system(self):
        """
        Lo que la de arriba no puede comprobar en Windows: que el respaldo se
        escriba. Los permisos son una propiedad de POSIX; existir, no.
        """
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()

        for name in ('backup.json', 'h_backup.json', 'users_backup.json.enc'):
            self.assertIn(name, self.written())
            self.assertGreater((self.path / name).stat().st_size, 0)

    # -- el volcado general ---------------------------------------------
    def test_the_general_dump_carries_no_pii(self):
        os.environ['GEA_BACKUP_PASSPHRASE'] = PASSPHRASE
        self.addCleanup(os.environ.pop, 'GEA_BACKUP_PASSPHRASE', None)

        self.run_backup()

        general = (self.path / 'backup.json').read_text(encoding='utf-8')

        self.assertNotIn(SECRET_EMAIL, general)
        self.assertNotIn(SECRET_PHONE, general)

    def test_adding_a_pii_app_to_the_general_dump_is_refused(self):
        """
        Hoy se cumple, y sin esta comprobacion se cumpliria hasta que alguien
        anadiera una app sin caer en que sus modelos llevan campos cifrados.
        El fallo saldria en un fichero, meses despues.
        """
        from apps.common.utils.management.commands import db_backup

        original = db_backup.GENERAL_APPS
        db_backup.GENERAL_APPS = original + ['users']
        self.addCleanup(setattr, db_backup, 'GENERAL_APPS', original)

        with self.assertRaises(CommandError):
            self.run_backup()
