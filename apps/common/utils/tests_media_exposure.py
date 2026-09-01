# apps/common/utils/tests_media_exposure.py
"""
Que ninguna carpeta de subidas la reparta el servidor web por su cuenta.

`pqrs/` se cayo de la lista de `deploy/media.htaccess` cuando se creo la app, y
es el peor sitio donde olvidarlo: el formulario es **publico y sin sesion**, o
sea que cualquiera puede depositar ahi una cedula o un pasaporte, y la carpeta
se servia por URL directa sin pasar por Django.

La ruta lleva el radicado, pero un radicado **no es un secreto**. Va impreso en
el acuse, viaja por correo y por captura de pantalla; el propio comprobante es
publico a proposito. Apoyar la confidencialidad de un documento de identidad en
eso es apoyarla en nada.

El invariante 13 dice que los ficheros sensibles no se enlazan por `MEDIA_URL`,
pero el invariante no lo aplica Django: lo aplica el `.htaccess`. Un fichero que
Apache sirve antes de que Django lo vea no pasa por ningun control, por muchas
comprobaciones que tenga la vista.

Aqui se comprueban las dos mitades: que el `.htaccess` cubre lo que hay hoy, y
que un campo nuevo no se puede colar sin decidirlo.

    manage.py test apps.common.utils.tests_media_exposure \\
        --settings=app_core.settings_test
"""

from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from .management.commands.check_security import (MEDIA_HTACCESS,
                                                 PUBLICLY_SERVABLE_MEDIA,
                                                 Command)

#: Lo que guarda datos personales y por tanto no puede servirse directo.
MUST_BE_BLOCKED = ('pqrs', 'passport_images', 'signature_images', 'certificates')


def htaccess_text():
    from pathlib import Path

    return (Path(settings.BASE_DIR) / MEDIA_HTACCESS).read_text(encoding='utf-8')


class TheRulesCoverWhatExistsTests(TestCase):

    def test_the_sensitive_folders_are_blocked(self):
        rules = htaccess_text()

        for folder in MUST_BE_BLOCKED:
            with self.subTest(folder=folder):
                self.assertIn(folder, rules)

    def test_pqrs_is_blocked_by_both_mechanisms(self):
        """
        Hay dos bloqueos --`mod_rewrite` y `RedirectMatch`-- porque el
        segundo es el respaldo del primero: en un hosting compartido nadie
        garantiza que `mod_rewrite` este activo, y un bloqueo que depende de
        un modulo opcional no es un bloqueo.
        """
        rules = htaccess_text()

        self.assertIn('|pqrs)', rules)
        self.assertIn('RedirectMatch 404 ^/public/media/pqrs/', rules)

    def test_nothing_sensitive_is_declared_publicly_servable(self):
        for folder in MUST_BE_BLOCKED:
            with self.subTest(folder=folder):
                self.assertNotIn(folder, PUBLICLY_SERVABLE_MEDIA)


class TheCheckReadsTheRealPathsTests(TestCase):
    """
    Que el comando lea bien a donde escribe cada campo.

    Esta parte ya fallo dos veces mientras se escribia, y las dos en silencio,
    que es lo que la hace peligrosa: una comprobacion que no sabe leer un
    campo lo da por bueno.

    Primero una expresion regular leia tambien el docstring, y de un
    "Path format: offer/..." sacaba `er`. Luego un `ast.walk` --que recorre en
    anchura, no en orden de codigo-- devolvia `asset`, que era el valor por
    defecto de un nombre y no una carpeta. Hoy se mira lo que se **devuelve**.
    """

    def test_every_upload_field_resolves_to_a_folder(self):
        prefixes = Command()._upload_prefixes()

        self.assertNotIn(
            '?', prefixes,
            'hay un campo de fichero cuyo destino el comando no sabe leer: '
            f'{prefixes.get("?")}',
        )

    def test_it_finds_the_pqrs_folder(self):
        """El que origino todo esto. Su `upload_to` es una f-string."""
        prefixes = Command()._upload_prefixes()

        self.assertIn('pqrs', prefixes)

    def test_it_reads_the_returned_path_and_not_a_default_value(self):
        """
        `offer_image_upload_path` hace `... or "asset"` antes de componer la
        ruta, y devuelve `os.path.join("offer", ...)`. Lo que vale es lo
        segundo.
        """
        prefixes = Command()._upload_prefixes()

        self.assertIn('offer', prefixes)
        self.assertIn(
            'buyers.OfferModel.offer_img', prefixes['offer'])

    def test_it_resolves_a_path_returned_by_name(self):
        """
        `assets_directory_path` hace `path = os.path.join(...)` y luego
        `return path`. Sin resolver el nombre, ese campo se quedaba **sin
        mirar** y nadie se enteraba.
        """
        prefixes = Command()._upload_prefixes()

        self.assertIn('asset', prefixes)


class TheCheckRunsCleanTests(TestCase):
    """Que la seccion no deje hallazgos con el codigo tal y como esta."""

    def test_the_upload_section_is_clean(self):
        out = StringIO()
        call_command('check_security', stdout=out)

        report = out.getvalue()
        section = report.split('5. Carpetas')[1].split('6. Ajustes')[0]

        self.assertNotIn('AVISO', section)
