# apps/common/utils/management/commands/check_requirements.py
"""
Que lo declarado en el proyecto sea lo que produccion instala.

El proyecto usa dos ficheros de dependencias y cada uno manda en un sitio:

* ``pyproject.toml`` + ``uv.lock`` es lo que se usa **en local**, con ``uv``.
* ``requirements.txt`` es lo que instala **produccion**, con ``pip``, porque
  en cPanel no hay uv.

El puente entre los dos es un paso manual: ``uv export --format=requirements-txt
> requirements.txt``. Y un paso manual es un paso que se olvida.

Ya ha pasado, y salio caro: ``opentimestamps`` se anadio a ``pyproject.toml``
el 29 de agosto y no llego a ``requirements.txt`` hasta el dia siguiente. En
medio, produccion se quedo sin la libreria, y el anclaje en la cadena de
bloques fallaba con un mensaje que no decia por que. El sintoma aparecio lejos
de la causa, que es lo peor de este tipo de fallo.

Esto compara las dos listas y avisa antes de desplegar. No arregla nada por su
cuenta: reexportar es una decision, y hacerlo automaticamente desde una consola
web seria peor que el problema.

    manage.py check_requirements
"""

import re
import tomllib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# "django-redis>=5.4" -> "django-redis";  "redis==8.1.0 \" -> "redis"
NAME = re.compile(r'^[A-Za-z0-9._-]+')

# Normaliza como hace PyPI: guiones, puntos y guiones bajos son lo mismo.
SEPARATORS = re.compile(r'[-_.]+')


def normalize(name: str) -> str:
    return SEPARATORS.sub('-', name.strip().lower())


class Command(BaseCommand):
    help = (
        'Comprueba que requirements.txt (lo que instala produccion con pip) '
        'lleve todo lo declarado en pyproject.toml.'
    )

    def handle(self, *args, **options):
        root = Path(settings.BASE_DIR)

        declared = self._from_pyproject(root / 'pyproject.toml')
        exported = self._from_requirements(root / 'requirements.txt')

        if declared is None or exported is None:
            return None

        missing = sorted(declared - exported)

        self.stdout.write(
            f'Declaradas en pyproject.toml : {len(declared)}'
        )
        self.stdout.write(
            f'Presentes en requirements.txt: {len(exported)}'
        )

        if not missing:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(
                'Todo lo declarado esta exportado. Produccion instalara lo '
                'mismo que hay en local.'
            ))
            return None

        self.stdout.write('')
        self.stdout.write(self.style.ERROR(
            f'Faltan {len(missing)} en requirements.txt:'
        ))

        for name in missing:
            self.stdout.write(f'   {name}')

        self.stdout.write('')
        self.stdout.write(
            'Produccion instala con pip desde requirements.txt, asi que estas '
            'no llegarian al servidor y fallarian en tiempo de ejecucion, '
            'lejos de aqui. Se arregla en local:'
        )
        self.stdout.write('')
        self.stdout.write(
            '   uv export --format=requirements-txt > requirements.txt'
        )
        self.stdout.write('')
        self.stdout.write('y despues commit del fichero.')

        return None

    # ------------------------------------------------------------------
    def _from_pyproject(self, path: Path):
        if not path.exists():
            self.stdout.write(self.style.ERROR(
                f'No se encontro {path}.'
            ))
            return None

        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
        except tomllib.TOMLDecodeError as error:
            self.stdout.write(self.style.ERROR(
                f'{path} no es TOML valido: {error}'
            ))
            return None

        raw = data.get('project', {}).get('dependencies', [])

        return {
            normalize(match.group(0))
            for line in raw
            if (match := NAME.match(line.strip()))
        }

    def _from_requirements(self, path: Path):
        if not path.exists():
            self.stdout.write(self.style.ERROR(
                f'No se encontro {path}. Produccion no tendria que instalar.'
            ))
            return None

        found = set()

        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()

            # Se ignoran comentarios, continuaciones y los hashes que uv
            # exporta debajo de cada paquete.
            if not line or line.startswith(('#', '-', '--hash')):
                continue

            match = NAME.match(line)

            if match:
                found.add(normalize(match.group(0)))

        return found
