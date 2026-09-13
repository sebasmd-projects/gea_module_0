"""
Que el grupo de desarrollo no acabe instalado en el servidor.

`requirements.txt` se exporta a mano desde `uv`, y `uv export` **incluye el
grupo de desarrollo salvo que se le diga que no**. Durante un tiempo se exporto
sin `--no-dev`, y el resultado era que produccion instalaba 48 paquetes de mas:
`bandit`, `pip-audit` y --lo peor-- `safety`, que es exactamente la herramienta
que este proyecto decidio no ejecutar en el servidor porque se queda esperando
una credencial. Con ella entraba ademas `nltk`, que era el unico paquete del
entorno con un aviso de seguridad sin version que lo corrija: estaba en
produccion sin que nada de produccion lo usara.

Aqui se comprueba que el comando lo detecta, porque la alternativa --acordarse
del `--no-dev`-- ya se demostro que no funciona.
"""

import tomllib
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)


def declared_dev_tools() -> set:
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    names = set()

    for group in (data.get('dependency-groups') or {}).values():
        names.update(line.split('>')[0].split('=')[0].split('[')[0].strip()
                     for line in group if isinstance(line, str))

    return names


def exported_names() -> set:
    lines = (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()

    return {
        line.split('==')[0].split('[')[0].strip().lower()
        for line in lines
        if line.strip() and not line.strip().startswith(('#', '-'))
    }


class RequirementsExportTests(SimpleTestCase):

    def test_el_grupo_de_desarrollo_no_esta_exportado(self):
        """El fichero que hay en el repositorio, tal cual esta."""
        leaked = sorted(
            name for name in declared_dev_tools()
            if name.lower() in exported_names()
        )

        self.assertEqual(
            leaked, [],
            'requirements.txt lleva herramientas de desarrollo: '
            f'{leaked}. Reexporta con '
            '`uv export --no-dev --format=requirements-txt > requirements.txt`'
        )

    def test_el_comando_lo_dice_cuando_pasa(self):
        """
        Con un requirements.txt contaminado, `check_requirements` lo canta.

        Se le da un fichero de mentira en vez de tocar el de verdad: una prueba
        que reescribe un fichero del repositorio y falla a mitad lo deja roto.
        """
        with self.settings(BASE_DIR=self._fake_project()):
            salida = StringIO()
            call_command('check_requirements', stdout=salida)

        texto = salida.getvalue()

        self.assertIn('Herramientas de desarrollo', texto)
        self.assertIn('bandit', texto)
        self.assertIn('--no-dev', texto)

    def test_no_lo_dice_cuando_esta_bien(self):
        with self.settings(BASE_DIR=self._fake_project(clean=True)):
            salida = StringIO()
            call_command('check_requirements', stdout=salida)

        self.assertNotIn('Herramientas de desarrollo', salida.getvalue())

    # ------------------------------------------------------------------
    def _fake_project(self, clean: bool = False) -> Path:
        import tempfile

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(self._remove, directory)

        (directory / 'pyproject.toml').write_text(
            '[project]\n'
            'dependencies = ["django>=5.2"]\n'
            '\n'
            '[dependency-groups]\n'
            'dev = ["bandit>=1.9.4", "safety>=3.8.1"]\n',
            encoding='utf-8',
        )

        exported = 'django==5.2.17\n'

        if not clean:
            exported += 'bandit==1.9.4\nsafety==3.8.1\nnltk==3.10.3\n'

        (directory / 'requirements.txt').write_text(exported, encoding='utf-8')

        return directory

    def _remove(self, directory: Path) -> None:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)
