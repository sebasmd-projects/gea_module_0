# apps/project/specific/internal/ops/runner.py
"""
Ejecucion de un comando permitido.

**En subproceso, nunca en la peticion.** Tres razones, todas concretas:

* ``ATOMIC_REQUESTS = True``: cada peticion es una transaccion. Lanzar
  ``migrate`` ahi dentro mete DDL en una transaccion ajena, que es justo como
  se corrompe un esquema a medias.
* Un comando que reviente no puede llevarse por delante el proceso web.
* ``call_command`` comparte el estado del proceso -- conexiones, cache de
  ajustes, ficheros abiertos --; un subproceso arranca limpio, igual que
  cuando se lanza a mano por SSH.

**Nunca hay shell.** Se construye una lista de argumentos y se pasa tal cual;
no hay nada que escapar porque no hay nadie interpretando comillas.

Los argumentos no se aceptan como texto libre: se validan uno a uno contra lo
que el comando declaro en ``registry.py``. Sin eso, un ``--settings=`` colado
en un campo bastaria para ejecutar con otra configuracion.
"""

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .registry import (KIND_CHOICE, KIND_FLAG, KIND_NUMBER, KIND_TEXT,
                       get_command)

logger = logging.getLogger(__name__)

#: Tope absoluto, pase lo que pase en el registro.
MAX_TIMEOUT = 900

#: La salida se guarda en la base de datos; un comando charlatan no puede
#: llenarla. Se corta por el final, que es donde esta el resultado.
MAX_OUTPUT_CHARS = 200_000

MANAGE_PY = Path(settings.BASE_DIR) / 'manage.py'

#: Cuantos elementos del argv son el andamiaje (interprete, -X utf8,
#: manage.py) y no forman parte de lo que el operador pidio.
PREFIX_LENGTH = 4


class CommandNotAllowed(Exception):
    """Se pidio algo que no esta en la lista blanca."""


def build_argv(command, values: dict) -> list:
    """
    Traduce los valores del formulario a una lista de argumentos.

    Cada valor pasa por el tipo que el comando declaro. Lo que no encaje se
    rechaza: aqui no se "limpia" nada para que cuele, se para.

    Raises:
        ValidationError: si algun valor no encaja con lo declarado.
    """
    argv = [sys.executable, '-X', 'utf8', str(MANAGE_PY), command.name]

    for option in command.options:
        raw = values.get(option.name, None)

        if option.kind == KIND_FLAG:
            if raw:
                argv.append(option.flag)
            continue

        if raw in (None, ''):
            continue

        if option.kind == KIND_NUMBER:
            try:
                number = int(raw)
            except (TypeError, ValueError):
                raise ValidationError(
                    _('%(label)s must be a whole number.')
                    % {'label': option.label}
                )
            argv.extend([option.flag, str(number)])
            continue

        if option.kind == KIND_CHOICE:
            if str(raw) not in option.choices:
                raise ValidationError(
                    _('%(label)s: "%(value)s" is not one of the allowed '
                      'values.') % {'label': option.label, 'value': raw}
                )
            argv.extend([option.flag, str(raw)])
            continue

        if option.kind == KIND_TEXT:
            text = str(raw).strip()

            # Sin patron declarado no se acepta texto libre: seria la puerta
            # por la que entra cualquier cosa.
            if not option.pattern:
                raise CommandNotAllowed(
                    f'{command.name}.{option.name} has no pattern declared'
                )

            if not re.match(option.pattern, text):
                raise ValidationError(
                    _('%(label)s contains characters that are not allowed.')
                    % {'label': option.label}
                )

            argv.extend([option.flag, text])
            continue

        raise CommandNotAllowed(f'unknown option kind: {option.kind}')

    return argv


def printable_argv(argv: list) -> str:
    """
    La parte del argv que el operador reconoce.

    Se quita el interprete y la ruta de manage.py: lo util para auditar es
    que se ejecuto, no donde vive el python de este servidor.
    """
    return ' '.join(argv[PREFIX_LENGTH:])


def _clip(text: str) -> str:
    """Recorta por el principio: lo importante de una salida esta al final."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text

    removed = len(text) - MAX_OUTPUT_CHARS

    return (
        f'[... {removed} caracteres omitidos ...]\n'
        + text[-MAX_OUTPUT_CHARS:]
    )


def run(name: str, values: dict) -> dict:
    """
    Ejecuta un comando de la lista blanca y devuelve que paso.

    Returns:
        dict: ``argv``, ``printable``, ``output``, ``exit_code``,
        ``duration``, ``timed_out``.

    Raises:
        CommandNotAllowed: si el nombre no esta permitido.
        ValidationError: si algun parametro no encaja.
    """
    command = get_command(name)

    if command is None:
        # No se filtra si existe o no: lo unico que importa es que no se puede.
        raise CommandNotAllowed(name)

    argv = build_argv(command, values or {})
    timeout = min(command.timeout, MAX_TIMEOUT)

    # Que el hijo no herede una consola que no sepa escribir acentos: en
    # Windows la salida por defecto es cp1252 y un simple emoji la tumba.
    environment = dict(os.environ)
    environment.setdefault('PYTHONIOENCODING', 'utf-8')
    environment.setdefault('PYTHONUTF8', '1')

    logger.info('Ops console running: %s', printable_argv(argv))

    started = time.monotonic()
    timed_out = False

    try:
        completed = subprocess.run(
            argv,
            cwd=str(settings.BASE_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout,
            env=environment,
            # Sin shell y sin stdin: un comando que pregunte algo muere en el
            # acto en vez de quedarse colgado esperando para siempre.
            stdin=subprocess.DEVNULL,
        )
        output = (completed.stdout or '') + (completed.stderr or '')
        exit_code = completed.returncode

    except subprocess.TimeoutExpired as expired:
        timed_out = True
        exit_code = None
        partial = (expired.stdout or b'') if expired.stdout else b''
        stderr = (expired.stderr or b'') if expired.stderr else b''

        def decode(chunk):
            if isinstance(chunk, bytes):
                return chunk.decode('utf-8', errors='replace')
            return chunk or ''

        output = (
            decode(partial) + decode(stderr)
            + f'\n\n--- cortado a los {timeout} s ---\n'
        )

    except FileNotFoundError:
        return {
            'argv': argv,
            'printable': printable_argv(argv),
            'output': _('manage.py could not be found. Check BASE_DIR.'),
            'exit_code': None,
            'duration': 0.0,
            'timed_out': False,
        }

    duration = time.monotonic() - started

    return {
        'argv': argv,
        'printable': printable_argv(argv),
        'output': _clip(output.strip()),
        'exit_code': exit_code,
        'duration': round(duration, 2),
        'timed_out': timed_out,
    }
