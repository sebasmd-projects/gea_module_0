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

from .registry import (EXEC_DISPLAY, EXEC_GIT, EXEC_MANAGE, KIND_CHOICE,
                       KIND_FLAG, KIND_NUMBER, KIND_TEXT, get_command)

logger = logging.getLogger(__name__)

#: Tope absoluto, pase lo que pase en el registro.
MAX_TIMEOUT = 900

#: La salida se guarda en la base de datos; un comando charlatan no puede
#: llenarla. Se corta por el final, que es donde esta el resultado.
MAX_OUTPUT_CHARS = 200_000

MANAGE_PY = Path(settings.BASE_DIR) / 'manage.py'

#: Cuantos elementos del argv son el andamiaje y no forman parte de lo que el
#: operador pidio. Depende del binario, asi que se calcula al construirlo.
MANAGE_PREFIX_LENGTH = 4
GIT_PREFIX_LENGTH = 1


class CommandNotAllowed(Exception):
    """Se pidio algo que no esta en la lista blanca."""


def base_argv(command) -> tuple:
    """
    El andamiaje del comando, y cuanto de el no se le ensena al operador.

    Solo hay dos binarios posibles y estan cerrados en el registro. No es una
    ruta configurable a proposito: si una entrada pudiera nombrar cualquier
    ejecutable, la lista blanca dejaria de acotar nada.

    Returns:
        tuple[list, int]: el prefijo del argv y cuantos elementos suyos se
        quitan al imprimirlo.
    """
    if command.executable == EXEC_MANAGE:
        return (
            [sys.executable, '-X', 'utf8', str(MANAGE_PY),
             command.program_name],
            MANAGE_PREFIX_LENGTH,
        )

    if command.executable == EXEC_GIT:
        # Sin ruta absoluta: se resuelve por PATH, como cualquier despliegue
        # manual. `shell=False` sigue en pie, asi que no hay nada que escapar.
        return (['git', command.program_name], GIT_PREFIX_LENGTH)

    raise CommandNotAllowed(f'unknown executable: {command.executable}')


def build_argv(command, values: dict) -> list:
    """
    Traduce los valores del formulario a una lista de argumentos.

    Cada valor pasa por el tipo que el comando declaro. Lo que no encaje se
    rechaza: aqui no se "limpia" nada para que cuele, se para.

    Los posicionales van al final, en el orden en que se declararon, porque un
    posicional depende del sitio que ocupa: ``sqlmigrate app 0003`` no es lo
    mismo que ``sqlmigrate 0003 app``.

    Raises:
        ValidationError: si algun valor no encaja con lo declarado.
    """
    argv, _prefix = base_argv(command)

    # Lo que el operador no elige ni puede quitar. Va antes que nada suyo, y
    # es donde se fija lo que hace segura a la entrada: `--ff-only` en el
    # pull, `--check --dry-run` en makemigrations.
    argv.extend(str(part) for part in command.fixed_args)

    positionals = []

    for option in command.options:
        raw = values.get(option.name, None)

        if option.kind == KIND_FLAG:
            if raw:
                argv.append(option.flag)
            continue

        if raw in (None, ''):
            if option.required:
                raise ValidationError(
                    _('%(label)s is required.') % {'label': option.label}
                )
            continue

        if option.kind == KIND_NUMBER:
            try:
                value = str(int(raw))
            except (TypeError, ValueError):
                raise ValidationError(
                    _('%(label)s must be a whole number.')
                    % {'label': option.label}
                )

        elif option.kind == KIND_CHOICE:
            if str(raw) not in option.choices:
                raise ValidationError(
                    _('%(label)s: "%(value)s" is not one of the allowed '
                      'values.') % {'label': option.label, 'value': raw}
                )
            value = str(raw)

        elif option.kind == KIND_TEXT:
            value = str(raw).strip()

            # Sin patron declarado no se acepta texto libre: seria la puerta
            # por la que entra cualquier cosa.
            if not option.pattern:
                raise CommandNotAllowed(
                    f'{command.name}.{option.name} has no pattern declared'
                )

            if not re.match(option.pattern, value):
                raise ValidationError(
                    _('%(label)s contains characters that are not allowed.')
                    % {'label': option.label}
                )

        else:
            raise CommandNotAllowed(f'unknown option kind: {option.kind}')

        if option.positional:
            # Un posicional es el valor a secas; su `flag` solo da nombre al
            # campo del formulario.
            positionals.append(value)
        else:
            argv.extend([option.flag, value])

    if positionals:
        # `--` separa banderas de posicionales: sin el, un valor que empiece
        # por guion se leeria como una opcion. Los patrones ya lo impiden,
        # pero apoyarse solo en eso deja el argumento a merced de un patron
        # mal escrito. Solo en manage.py: en git, `--` significa "lo que sigue
        # es una ruta", que es otra cosa.
        if command.executable == EXEC_MANAGE:
            argv.append('--')

        argv.extend(positionals)

    return argv


def printable_argv(command, argv: list) -> str:
    """
    La linea tal y como se escribiria a mano.

    Se quita el interprete y la ruta absoluta de manage.py, y se pone en su
    lugar el nombre corto: lo util para auditar es que se ejecuto, no donde
    vive el python de este servidor. El nombre del programa si va -- sin el,
    `git pull --ff-only` y `manage.py migrate` se leerian igual de sueltos.
    """
    _base, prefix_length = base_argv(command)
    display = EXEC_DISPLAY.get(command.executable, command.executable)

    return ' '.join([display] + argv[prefix_length:])


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

    logger.info('Ops console running: %s', printable_argv(command, argv))

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
            'printable': printable_argv(command, argv),
            'output': _(
                'The program could not be found. For manage.py, check '
                'BASE_DIR; for git, check that it is on the PATH.'
            ),
            'exit_code': None,
            'duration': 0.0,
            'timed_out': False,
        }

    duration = time.monotonic() - started

    return {
        'argv': argv,
        'printable': printable_argv(command, argv),
        'output': _clip(output.strip()),
        'exit_code': exit_code,
        'duration': round(duration, 2),
        'timed_out': timed_out,
    }
