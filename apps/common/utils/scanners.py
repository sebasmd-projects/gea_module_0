# apps/common/utils/scanners.py
"""
Los dos escáneres de terceros que alimentan ``manage.py check_security``.

``check_security`` mira lo que es propio de este proyecto: vistas sin guardia,
formularios sin freno, carpetas de subidas que reparte el servidor web. Eso no
lo sabe ninguna herramienta de fuera. Pero hay dos cosas que sí saben mucho
mejor que nosotros, y que estaban sin cubrir:

* **bandit** lee el código y reconoce patrones peligrosos de Python — un hash
  débil, un ``mark_safe`` con una interpolación dentro, un ``urlopen`` que
  aceptaría ``file://``.
* **safety** compara las dependencias con una base de vulnerabilidades
  publicadas. Es la única de las dos que responde a la pregunta «¿la versión de
  la biblioteca que tengo instalada tiene un CVE?», que no se puede contestar
  leyendo este repositorio.

Las dos son opcionales
----------------------
Ninguna está en ``requirements.txt``, y es deliberado: son herramientas de
desarrollo y el servidor no las necesita para servir páginas. Si no están
instaladas, la sección lo **dice en voz alta** y sigue. No inventa un hallazgo
--no haberla ejecutado no es una vulnerabilidad-- pero tampoco se calla, que
sería lo peor de los dos mundos: un informe de seguridad que parece completo y
no lo es.

Por qué `safety` necesita una clave, y qué pasa sin ella
--------------------------------------------------------
Safety CLI 3 **siempre** se autentica. Sin credencial abre un navegador o se
queda esperando en el terminal, y ahí se colgaría: esto se ejecuta por cron y
desde la consola de operaciones, donde no hay nadie que conteste. Por eso:

* se lanza sólo si hay ``SAFETY_API_KEY`` en el entorno;
* se lanza con ``--stage cicd`` y con la entrada estándar cerrada, de modo que
  no pueda pedir nada aunque cambie de opinión en una versión futura;
* **la clave va por entorno, nunca como argumento.** Un ``--key=...`` en la
  línea de comandos lo ve cualquiera que liste procesos, y además esta consola
  guarda la línea ejecutada y su salida en ``CommandRunModel``: un secreto que
  pase por ahí queda escrito en una tabla que se lee desde el propio panel.

Lo que se da por bueno, y por qué
---------------------------------
``BANDIT_ACCEPTED`` es una lista de excepciones **razonadas**, igual que
``INTENTIONALLY_PUBLIC`` en ``check_security`` o ``NEVER_EXPOSED`` en el
registro de la consola: cada entrada dice por qué ese aviso no es un problema
aquí. No es una lista para silenciar ruido.

La clave es ``(regla, fichero)``, y conviene saber exactamente qué atrapa y
qué no. Una regla nueva, o la misma regla en un fichero nuevo, **aparece**.
Una segunda ocurrencia de la misma regla en un fichero ya aceptado, **no**.
Es el mismo trato que ``INTENTIONALLY_PUBLIC`` da a una vista, y el precio de
que la lista no se invalide cada vez que se mueve una línea de sitio.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from django.conf import settings

#: La variable que lee safety por su cuenta. Se le pasa por el entorno.
SAFETY_KEY_ENV = 'SAFETY_API_KEY'

#: Qué mira bandit. Las pruebas quedan fuera --un `assert` en una prueba es
#: su forma normal de trabajar, no un hallazgo-- y las migraciones también,
#: que son un histórico que no se vuelve a ejecutar.
BANDIT_TARGETS = ('apps', 'app_core')
BANDIT_EXCLUDE = '*/tests/*,*/migrations/*'

#: Tope de espera de cada escáner. Safety sale a la red; bandit no (tarda unos
#: tres segundos sobre este proyecto).
#:
#: Los dos son **más cortos que el del comando en la consola de operaciones**
#: (600 s en ``registry.py``), y a propósito: si el tope que salta primero es
#: el de fuera, lo que se lee es «el comando se cortó» y hay que adivinar por
#: dónde iba. Saltando el de dentro, el informe dice cuál de los dos no
#: respondió y en cuánto tiempo.
BANDIT_TIMEOUT = 120
SAFETY_TIMEOUT = 240

#: Avisos de bandit que aquí no son un problema, con la razón al lado.
#:
#: La clave es ``(regla, ruta relativa)``. Añadir una entrada obliga a escribir
#: por qué, que es la fricción que se busca: una lista de exclusión sin motivos
#: es una forma cómoda de no mirar.
BANDIT_ACCEPTED = {
    # --- B104: "bind a todas las interfaces" ---
    ('B104', 'apps/common/utils/client_ip.py'): (
        'No es una direccion de escucha: es el centinela UNKNOWN_IP para '
        'cuando no se puede determinar de donde viene la peticion. La cadena '
        'coincide, el significado no.'
    ),
    ('B104', 'apps/common/utils/management/commands/runserver.py'): (
        'Es el servidor de desarrollo, y sirve en 0.0.0.0 a proposito, para '
        'poder abrirlo desde el movil en la misma red. En produccion no se '
        'ejecuta: alli sirve el WSGI de cPanel.'
    ),

    # --- B105: "contrasena en el codigo" ---
    ('B105', 'apps/common/utils/backup_crypto.py'): (
        'Es el NOMBRE de la variable de entorno (GEA_BACKUP_PASSPHRASE), no '
        'su valor. El valor no esta en el repositorio y el comando se niega a '
        'escribir PII sin el.'
    ),
    ('B105', 'apps/common/utils/management/commands/check_security.py'): (
        'Son claves del diccionario de vistas publicas a proposito '
        '(account:forgot_password, account:change_password). Bandit ve '
        '"password" en una cadena; lo que hay es el nombre de una ruta.'
    ),
    ('B105', 'apps/project/common/account/login_view.py'): (
        'MODE_PASSWORD es el identificador del modo del asistente de acceso, '
        'el que distingue entrar con contrasena de entrar con codigo.'
    ),
    ('B105', 'apps/project/specific/internal/code_gen/services/watermark.py'): (
        'TOKEN_SEPARATOR es el caracter que separa los campos de la marca de '
        'agua. Se llama token y no es un secreto.'
    ),

    # --- B110: try/except/pass ---
    ('B110', 'apps/common/utils/management/commands/check_workers.py'): (
        'Un diagnostico no puede fallar por lo que esta diagnosticando: si '
        'leer /proc o el estado de un proceso revienta, se informa de lo que '
        'si se pudo leer en vez de abortar el informe entero.'
    ),
    ('B110', 'apps/project/specific/assets_management/buyers/form.py'): (
        'Formateo de un valor para mostrarlo. Si no se puede formatear se '
        'ensena en crudo; que un formulario no se pinte seria peor que un '
        'numero sin separador de miles.'
    ),
    ('B110', 'apps/project/specific/internal/code_gen/services/hashing.py'): (
        'La huella canonica ignora deliberadamente la marca de agua; si el '
        'PDF no se deja leer por esa via se cae a la huella exacta, que es la '
        'que hace fe. El fallo esta contemplado, no tragado.'
    ),
    ('B110', 'apps/project/specific/internal/code_gen/services/tsa.py'): (
        'El sellado de tiempo sale a la red y NUNCA puede propagar su fallo: '
        'con ATOMIC_REQUESTS puesto, una excepcion aqui desharia el sellado '
        'que ya se escribio. Se degrada a aviso, que es el diseno (ver '
        'docs/ANCLAJE.md).'
    ),

    # --- B308 / B703: mark_safe ---
    # Son la misma llamada contada por dos reglas. Se aceptan por fichero
    # porque en los tres el contenido es seguro por construccion; el caso que
    # NO lo era --una URL de fichero subido interpolada en un <img>-- se
    # arreglo con format_html en vez de aceptarse.
    ('B308', 'apps/common/utils/admin.py'): (
        'Etiquetas y colores fijos; los dos valores que vienen de la fila '
        '(user_agent, network_owner, country) pasan por escape() o '
        'format_html().'
    ),
    ('B308', 'apps/common/utils/templatetags/custom_filters.py'): (
        'add_class y add_attrs devuelven lo que ya produjo field.as_widget(), '
        'que Django genera escapado; currency interpola dos trozos de '
        'f"{float(x):,.2f}", o sea digitos, comas y un punto.'
    ),
    ('B308', 'apps/project/specific/documents/certificates/views.py'): (
        'El QR y el codigo de barras son imagenes que genera este mismo '
        'proyecto en functions.py; lo que se marca como seguro es el markup '
        'que produce la libreria, no texto de nadie.'
    ),
    ('B703', 'apps/common/utils/admin.py'): 'Ver B308 del mismo fichero.',
    ('B703', 'apps/common/utils/templatetags/custom_filters.py'):
        'Ver B308 del mismo fichero.',
    ('B703', 'apps/project/specific/documents/certificates/views.py'):
        'Ver B308 del mismo fichero.',

    # --- B310: urlopen admite file:// ---
    # La regla es sintactica: mira la llamada, no lo que se hizo antes. En los
    # dos sitios se comprueba el esquema justo encima, con require_http_url().
    ('B310', 'apps/common/utils/cron.py'): (
        'El esquema se valida con outbound.require_http_url() antes de abrir. '
        'Bandit no puede verlo porque solo mira la llamada.'
    ),
    ('B310', 'apps/common/utils/management/commands/check_health.py'): (
        'Idem: require_http_url() en la linea de encima.'
    ),

    # --- B311: random no criptografico ---
    ('B311', 'apps/common/utils/management/commands/rename_migrations.py'): (
        'Un sufijo de cuatro caracteres para no pisar un fichero al renombrar '
        'migraciones. No protege nada; solo evita una colision de nombres.'
    ),

    # --- B404 / B603: subprocess ---
    # Aqui bandit avisa de lo que en este proyecto es precisamente la medida
    # de seguridad. `runner.py` ejecuta SIN shell y con una lista de
    # argumentos construida a mano justamente para que no haya nada que
    # escapar; lo mismo hacen los comandos de diagnostico. Usar el shell seria
    # el hallazgo, no evitarlo.
    ('B404', 'apps/common/utils/scanners.py'): (
        'Este mismo fichero: lanza bandit y safety en subproceso, sin shell. '
        'Aparecio en la primera ejecucion despues de escribirlo, que es '
        'exactamente lo que tiene que pasar con un fichero nuevo.'
    ),
    ('B603', 'apps/common/utils/scanners.py'): 'Ver B404 del mismo fichero.',
    ('B404', 'apps/common/utils/management/commands/check_cache.py'):
        'subprocess sin shell, con lista de argumentos.',
    ('B404', 'apps/common/utils/management/commands/check_cron.py'):
        'subprocess sin shell, con lista de argumentos.',
    ('B404', 'apps/common/utils/management/commands/check_workers.py'):
        'subprocess sin shell, con lista de argumentos.',
    ('B404', 'apps/common/utils/management/commands/test_report.py'):
        'subprocess sin shell, con lista de argumentos.',
    ('B404', 'apps/project/specific/documents/video_masonry/utils.py'):
        'Llama a ffmpeg sin shell, con lista de argumentos.',
    ('B404', 'apps/project/specific/internal/ops/runner.py'): (
        'Es el ejecutor de la consola de operaciones. Ejecutar en subproceso '
        'y sin shell no es el riesgo: es el diseno (ver el docstring de '
        'registry.py).'
    ),
    ('B603', 'apps/common/utils/management/commands/check_cache.py'):
        'Ver B404 del mismo fichero.',
    ('B603', 'apps/common/utils/management/commands/check_cron.py'):
        'Ver B404 del mismo fichero.',
    ('B603', 'apps/common/utils/management/commands/check_workers.py'):
        'Ver B404 del mismo fichero.',
    ('B603', 'apps/common/utils/management/commands/test_report.py'):
        'Ver B404 del mismo fichero.',
    ('B603', 'apps/project/specific/documents/video_masonry/utils.py'):
        'Ver B404 del mismo fichero.',
    ('B603', 'apps/project/specific/internal/ops/runner.py'):
        'Ver B404 del mismo fichero.',
}


@dataclass
class ScanResult:
    """Lo que devuelve un escáner, esté instalado o no."""

    #: ``False`` cuando la herramienta no está o no se pudo ejecutar. No es un
    #: hallazgo: es que no se miró, y eso se cuenta aparte.
    ran: bool = False
    #: Por qué no se ejecutó, en una línea para imprimir tal cual.
    skipped: str = ''
    #: Hallazgos vivos, ya descontados los aceptados.
    findings: List[str] = field(default_factory=list)
    #: Avisos aceptados, sólo para poder decir cuántos se dieron por buenos.
    accepted: int = 0
    #: Un fallo de la propia herramienta (no un hallazgo suyo).
    error: str = ''


def _python() -> str:
    return sys.executable


def _module_available(module: str) -> bool:
    """Si el intérprete que nos ejecuta tiene ese módulo a mano."""
    try:
        return subprocess.run(
            [_python(), '-c', f'import {module}'],
            capture_output=True, timeout=60,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ----------------------------------------------------------------------
def run_bandit(min_severity: str = 'LOW') -> ScanResult:
    """
    Pasa bandit sobre el código del proyecto y descuenta lo ya razonado.

    Args:
        min_severity: ``LOW``, ``MEDIUM`` o ``HIGH``. Por debajo no se
            reporta.
    """
    result = ScanResult()

    if not _module_available('bandit'):
        result.skipped = (
            'bandit no esta instalado, asi que el codigo no se ha analizado. '
            'Es herramienta de desarrollo y no esta en requirements.txt; '
            'para tenerla: uv add --dev bandit'
        )
        return result

    base = Path(settings.BASE_DIR)
    argv = [
        _python(), '-m', 'bandit', '-r', *BANDIT_TARGETS,
        '-f', 'json', '-q', '-x', BANDIT_EXCLUDE,
    ]

    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, cwd=str(base),
            timeout=BANDIT_TIMEOUT, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as error:
        result.error = f'no se pudo ejecutar bandit: {error}'
        return result

    try:
        report = json.loads(done.stdout)
    except ValueError:
        result.error = (
            f'bandit no devolvio JSON (codigo {done.returncode}): '
            f'{done.stderr.strip()[:300]}'
        )
        return result

    result.ran = True
    order = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    floor = order.get(min_severity.upper(), 0)

    for issue in report.get('results', []):
        if order.get(issue.get('issue_severity', 'LOW'), 0) < floor:
            continue

        path = issue.get('filename', '')

        try:
            path = str(Path(path).resolve().relative_to(base.resolve()))
        except ValueError:
            pass

        path = path.replace('\\', '/')

        if (issue.get('test_id'), path) in BANDIT_ACCEPTED:
            result.accepted += 1
            continue

        result.findings.append(
            f'{path}:{issue.get("line_number")} '
            f'[{issue.get("issue_severity")}] {issue.get("test_id")} '
            f'{issue.get("issue_text", "").splitlines()[0][:120]}'
        )

    return result


# ----------------------------------------------------------------------
def run_safety() -> ScanResult:
    """
    Compara las dependencias instaladas con la base de vulnerabilidades.

    Nunca puede quedarse esperando una respuesta: sin clave ni se lanza, y
    cuando se lanza va con ``--stage cicd`` y con la entrada cerrada.
    """
    result = ScanResult()

    if not _module_available('safety'):
        result.skipped = (
            'safety no esta instalado, asi que las dependencias no se han '
            'contrastado con ninguna base de vulnerabilidades. '
            'Para tenerla: uv add --dev safety'
        )
        return result

    if not os.environ.get(SAFETY_KEY_ENV):
        result.skipped = (
            f'safety esta instalado pero no hay {SAFETY_KEY_ENV} en el '
            f'entorno. Safety CLI 3 siempre se autentica, y sin credencial se '
            f'queda esperando en el terminal — aqui no hay nadie que conteste. '
            f'Pon la clave en el entorno (nunca en el repositorio).'
        )
        return result

    argv = [
        _python(), '-m', 'safety', '--disable-optional-telemetry',
        # `cicd` es lo que le dice que no hay nadie delante.
        '--stage', 'cicd',
        'scan', '--target', '.', '--output', 'json',
    ]

    try:
        done = subprocess.run(
            argv, capture_output=True, text=True,
            cwd=str(settings.BASE_DIR), timeout=SAFETY_TIMEOUT,
            # La clave viaja en el entorno, que es como safety la busca. Nunca
            # como `--key=...`: eso la deja en la linea de comandos, visible a
            # cualquiera que liste procesos y escrita en CommandRunModel.
            env=dict(os.environ),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        result.error = (
            f'safety no respondio en {SAFETY_TIMEOUT}s. Sale a la red: si el '
            f'servidor no tiene salida, esta comprobacion no se puede hacer '
            f'desde aqui.'
        )
        return result
    except (OSError, subprocess.SubprocessError) as error:
        result.error = f'no se pudo ejecutar safety: {error}'
        return result

    payload = _first_json_object(done.stdout)

    if payload is None:
        result.error = (
            f'safety no devolvio JSON (codigo {done.returncode}): '
            f'{(done.stderr or done.stdout).strip()[:300]}'
        )
        return result

    result.ran = True
    result.findings = _safety_findings(payload)

    return result


def _first_json_object(text: str):
    """
    El JSON de la salida, saltandose lo que safety imprime antes.

    Safety escribe avisos de deprecacion de sus propias dependencias antes del
    informe. Buscar la primera llave evita que un aviso nuevo en una version
    futura rompa la lectura.
    """
    if not text:
        return None

    start = text.find('{')

    if start < 0:
        return None

    try:
        return json.loads(text[start:])
    except ValueError:
        return None


def _safety_findings(payload) -> List[str]:
    """
    Las vulnerabilidades del informe, una linea por paquete afectado.

    El formato de safety ha cambiado entre versiones mayores, asi que se
    recorre defensivamente: lo que importa es no perder un hallazgo por un
    cambio de forma, aunque la linea salga menos bonita.
    """
    findings = []

    files = (payload.get('scan_results', {}) or {}).get('files', []) or []

    for entry in files:
        location = entry.get('location', '?')

        for dependency in (entry.get('results', {}) or {}).get(
                'dependencies', []) or []:
            name = dependency.get('name', '?')

            for spec in dependency.get('specifications', []) or []:
                known = (spec.get('vulnerabilities', {}) or {}).get(
                    'known_vulnerabilities', []) or []

                for vulnerability in known:
                    findings.append(
                        f'{name} {spec.get("raw", "")} — '
                        f'{vulnerability.get("id", "?")} '
                        f'({vulnerability.get("severity") or "sin severidad"})'
                        f'  [{location}]'
                    )

    return findings
