# apps/common/utils/logs.py
"""
Donde estan los logs y como se rotan.

El fichero de log no tenia rotacion de ninguna clase: `stderr.log` crecia sin
fin. Rotar a mano dejaba `stderr_old_1.log`, `stderr_old_2.log`... hasta el
cinco, cuando alguien se acordaba.

La trampa de rotar un log en varios procesos
--------------------------------------------
Rotar es renombrar el fichero y empezar uno nuevo. En Linux, renombrar no
afecta a quien ya lo tiene abierto: el descriptor sigue apuntando al mismo
**inodo**, ahora con otro nombre. Y en cPanel la aplicacion corre en varios
procesos, cada uno con su descriptor abierto desde que arranco.

Asi que con el ``logging.FileHandler`` de siempre, rotar tiene este efecto:
todos los workers siguen escribiendo en ``stderr_old_6.log``, el nuevo
``stderr.log`` se queda vacio para siempre, y el "viejo" es el que sigue
creciendo. El log no se rompe con un error -- se rompe en silencio, y no se
nota hasta que hace falta mirarlo, que es el peor momento posible.

Por eso el handler es ``WatchedFileHandler``: antes de cada escritura comprueba
si el fichero que tiene abierto sigue siendo el que hay en esa ruta, y si no,
lo reabre. Es exactamente el handler pensado para que rote otro. Sin ese
cambio, este modulo haria mas dano que bien.

Por que no ``RotatingFileHandler``
----------------------------------
Porque rota el proceso que escribe, y aqui hay varios: dos workers pueden
cruzar el renombrado, y el resultado es un log partido o perdido. Rotar desde
fuera --un solo proceso, el del cron-- y que los workers se enteren, es la
combinacion que aguanta.
"""

import re
from pathlib import Path

from django.conf import settings

#: A partir de aqui se rota. Tres megas es un fichero que todavia se puede
#: abrir y buscar dentro sin que la herramienta se atragante.
DEFAULT_MAX_BYTES = 3 * 1024 * 1024

#: Cuantos rotados se conservan. El disco de cPanel es una cuota fija, y un
#: log sin tope acaba llenandola: cuando eso pasa fallan las escrituras de
#: todo lo demas, no solo las del log.
DEFAULT_KEEP = 10

#: ``stderr_old_5.log`` -- el numero es lo unico que se lee.
ROTATED = re.compile(r'^(?P<stem>.+)_old_(?P<number>\d+)\.log$')


def log_file() -> Path:
    """El fichero que la aplicacion esta escribiendo ahora mismo."""
    configured = getattr(settings, 'LOG_FILE', None)

    if configured:
        return Path(configured)

    return Path(settings.BASE_DIR) / 'stderr.log'


def rotated_name(current: Path, number: int) -> Path:
    """``stderr.log`` + 6 -> ``stderr_old_6.log``."""
    return current.with_name(f'{current.stem}_old_{number}.log')


def rotated_files(current: Path = None) -> list:
    """
    Los rotados que ya existen, del mas nuevo al mas viejo.

    Returns:
        list[tuple[int, Path]]: el numero de cada uno y su ruta.
    """
    current = current or log_file()
    found = []

    for path in current.parent.glob(f'{current.stem}_old_*.log'):
        match = ROTATED.match(path.name)

        if not match or match.group('stem') != current.stem:
            continue

        found.append((int(match.group('number')), path))

    return sorted(found, reverse=True)


def next_number(current: Path = None) -> int:
    """
    El siguiente numero libre.

    Se sigue la cuenta que ya venia --produccion va por el 5-- en vez de
    empezar de cero: renumerar lo existente cambiaria el nombre de ficheros a
    los que quiza alguien ya se refirio en un correo o en una incidencia.
    """
    current = current or log_file()
    existing = rotated_files(current)

    return (existing[0][0] + 1) if existing else 1


def should_rotate(current: Path = None, max_bytes: int = DEFAULT_MAX_BYTES) -> bool:
    """Si el fichero ya paso del tamano al que se rota."""
    current = current or log_file()

    try:
        return current.stat().st_size >= max_bytes
    except OSError:
        # Sin fichero no hay nada que rotar. No es un error: puede que aun no
        # se haya escrito nada.
        return False


def rotate(current: Path = None) -> Path:
    """
    Renombra el log actual y deja su sitio libre.

    No crea el fichero nuevo: lo crea el propio handler en la primera
    escritura. Crearlo aqui solo serviria para dejarlo con el dueno y los
    permisos del proceso del cron, que no tienen por que ser los del worker.

    Returns:
        Path: el fichero rotado.

    Raises:
        OSError: si no se puede renombrar. Se deja subir a proposito: que la
            rotacion falle en silencio es como no tenerla.
    """
    current = current or log_file()
    target = rotated_name(current, next_number(current))

    current.rename(target)

    return target


def prune(current: Path = None, keep: int = DEFAULT_KEEP) -> list:
    """
    Borra los rotados que sobran, empezando por los mas viejos.

    Returns:
        list[Path]: los que se han borrado.
    """
    current = current or log_file()

    if keep is None or keep <= 0:
        return []

    removed = []

    for _number, path in rotated_files(current)[keep:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            # Un rotado que no se deja borrar no puede impedir la rotacion
            # del siguiente, que es lo que de verdad importa.
            continue

    return removed


def human_size(size: int) -> str:
    """Bytes en algo que se lee de un vistazo."""
    value = float(size)

    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            return f'{value:.1f} {unit}' if unit != 'B' else f'{int(value)} B'
        value /= 1024

    return f'{value:.1f} GB'
