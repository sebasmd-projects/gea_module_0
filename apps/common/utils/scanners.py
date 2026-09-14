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
* **pip-audit** y **safety** comparan las dependencias con una base de
  vulnerabilidades publicadas. Son las únicas que responden a «¿la versión de
  la biblioteca que tengo instalada tiene un CVE?», que no se puede contestar
  leyendo este repositorio.

Dos escáneres de dependencias, y no es redundancia
---------------------------------------------------
**En el servidor manda ``pip-audit``.** Consulta la base pública de avisos de
PyPI y OSV, **sin cuenta y sin credencial**: no hay ninguna clave que rotar, ni
que guardar en el entorno de producción, ni que se pueda filtrar. Esa es toda
la razón por la que es la de producción — un chequeo que depende de un secreto
es un chequeo que deja de funcionar el día que el secreto caduca, y nadie se
entera hasta el despliegue siguiente.

**``safety`` se queda en local.** Su base es más rica y da contexto que la
pública no tiene, pero Safety CLI 3 **siempre se autentica**: sin credencial
abre un navegador o se queda esperando en el terminal. Eso, en un servidor
--donde esto corre por cron y desde la consola de operaciones, sin nadie que
conteste-- es un cuelgue. Así que allí ni se intenta, y saltársela en
producción **no se cuenta como un hueco**: es la configuración prevista, y un
aviso que sale en cada despliegue por algo que está bien acaba ignorándose
junto con los que no lo están.

Cuando sí se lanza (en local, con clave), va con ``--stage cicd`` y con la
entrada estándar cerrada, para que no pueda pedir nada aunque una versión
futura cambie de opinión. Y **la clave va por entorno, nunca como argumento**:
un ``--key=...`` en la línea de comandos lo ve cualquiera que liste procesos, y
además esta consola guarda la línea ejecutada y su salida en
``CommandRunModel`` — un secreto que pase por ahí queda escrito en una tabla
que se lee desde el propio panel.

Todas son opcionales
--------------------
Ninguna está en ``requirements.txt``, y es deliberado: son herramientas de
diagnóstico y el servidor no las necesita para servir páginas. Si no están
instaladas, la sección lo **dice en voz alta** y sigue. No inventa un hallazgo
--no haberla ejecutado no es una vulnerabilidad-- pero tampoco se calla, que
sería lo peor de los dos mundos: un informe de seguridad que parece completo y
no lo es.

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

#: Tope de espera de cada escáner. Los de dependencias salen a la red; bandit
#: no (tarda unos tres segundos sobre este proyecto).
#:
#: Los dos son **más cortos que el del comando en la consola de operaciones**
#: (600 s en ``registry.py``), y a propósito: si el tope que salta primero es
#: el de fuera, lo que se lee es «el comando se cortó» y hay que adivinar por
#: dónde iba. Saltando el de dentro, el informe dice cuál de los dos no
#: respondió y en cuánto tiempo.
BANDIT_TIMEOUT = 120
SAFETY_TIMEOUT = 240
PIP_AUDIT_TIMEOUT = 240

#: Rutas que salen en más de una entrada, para que un fichero que se mueva se
#: renombre en un sitio y no en cinco.
_WORKERS = 'apps/common/utils/management/commands/check_workers.py'
_CACHE = 'apps/common/utils/management/commands/check_cache.py'
_CRON = 'apps/common/utils/management/commands/check_cron.py'
_REPORT = 'apps/common/utils/management/commands/test_report.py'
_FFMPEG = 'apps/project/specific/documents/video_masonry/utils.py'
_RUNNER = 'apps/project/specific/internal/ops/runner.py'
_ADMIN = 'apps/common/utils/admin.py'
_FILTERS = 'apps/common/utils/templatetags/custom_filters.py'
_CERT_VIEWS = 'apps/project/specific/documents/certificates/views.py'

#: Las dos remisiones y el motivo que se repite. Se escriben una vez porque
#: significan lo mismo en cada sitio: si cambia el razonamiento, cambia entero.
SEE_B308 = 'Ver B308 del mismo fichero.'
SEE_B404 = 'Ver B404 del mismo fichero.'
NO_SHELL = 'subprocess sin shell, con lista de argumentos.'

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
    ('B105', 'app_core/env.py'): (
        'Son los NOMBRES de las variables de entorno y su explicacion: la '
        'entrada DJANGO_SECRET_KEY vale "Clave de firma de Django. Generala '
        'con...", y DB_PASSWORD vale "Contrasena de la base de datos". Bandit '
        've una clave que suena a secreto con una cadena al lado y no puede '
        'saber que la cadena es la ayuda que se imprime cuando falta. Ese '
        'fichero no toca valores: solo comprueba si estan puestos.'
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
    ('B110', _WORKERS): (
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
    ('B308', _ADMIN): (
        'Etiquetas y colores fijos; los dos valores que vienen de la fila '
        '(user_agent, network_owner, country) pasan por escape() o '
        'format_html().'
    ),
    ('B308', _FILTERS): (
        'add_class y add_attrs devuelven lo que ya produjo field.as_widget(), '
        'que Django genera escapado; currency interpola dos trozos de '
        'f"{float(x):,.2f}", o sea digitos, comas y un punto.'
    ),
    ('B308', _CERT_VIEWS): (
        'El QR y el codigo de barras son imagenes que genera este mismo '
        'proyecto en functions.py; lo que se marca como seguro es el markup '
        'que produce la libreria, no texto de nadie.'
    ),
    ('B703', _ADMIN): SEE_B308,
    ('B703', _FILTERS):
        SEE_B308,
    ('B703', _CERT_VIEWS):
        SEE_B308,

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
    ('B603', 'apps/common/utils/scanners.py'): SEE_B404,
    ('B404', _CACHE):
        NO_SHELL,
    ('B404', _CRON):
        NO_SHELL,
    ('B404', _WORKERS):
        NO_SHELL,
    ('B404', _REPORT):
        NO_SHELL,
    ('B404', _FFMPEG):
        'Llama a ffmpeg sin shell, con lista de argumentos.',
    ('B404', _RUNNER): (
        'Es el ejecutor de la consola de operaciones. Ejecutar en subproceso '
        'y sin shell no es el riesgo: es el diseno (ver el docstring de '
        'registry.py).'
    ),
    ('B603', _CACHE):
        SEE_B404,
    ('B603', _CRON):
        SEE_B404,
    ('B603', _WORKERS):
        SEE_B404,
    ('B603', _REPORT):
        SEE_B404,
    ('B603', _FFMPEG):
        SEE_B404,
    ('B603', _RUNNER):
        SEE_B404,
}


@dataclass
class ScanResult:
    """Lo que devuelve un escáner, esté instalado o no."""

    #: ``False`` cuando la herramienta no está o no se pudo ejecutar. No es un
    #: hallazgo: es que no se miró, y eso se cuenta aparte.
    ran: bool = False
    #: Por qué no se ejecutó, en una línea para imprimir tal cual.
    skipped: str = ''
    #: Si ese salto es la configuración prevista y no un hueco.
    #:
    #: Safety no se ejecuta en el servidor **a propósito**. Contarlo como
    #: «sin mirar» sacaría un aviso en cada despliegue por algo que está bien,
    #: y un aviso que siempre sale se acaba ignorando junto con los que no
    #: deberían salir.
    by_design: bool = False
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


def _listed(container, key) -> list:
    """
    El valor de ``key`` como lista, venga como venga.

    Lo usan los dos informes de dependencias. El de safety anida cuatro
    niveles y cualquiera puede faltar, ser ``None`` o no ser un diccionario
    segun la version; el de pip-audit es mas plano pero igual de opcional.
    Concentrar esa tolerancia aqui deja los recorridos legibles; repartida
    por los bucles, cada nivel llevaba su propio ``or []`` y no se veia la
    forma del dato.
    """
    if not isinstance(container, dict):
        return []

    value = container.get(key)

    return value if isinstance(value, list) else []


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
def run_pip_audit() -> ScanResult:
    """
    Contrasta lo instalado con la base pública de avisos (PyPI y OSV).

    Es la comprobación de dependencias **del servidor**, y lo es justamente
    porque no lleva credencial: no hay clave que rotar, ni que guardar en el
    entorno de producción, ni que se pueda filtrar. Un chequeo que depende de
    un secreto deja de funcionar el día que el secreto caduca, y eso no se
    nota hasta el despliegue siguiente.

    Mira el **entorno instalado**, no ``requirements.txt``: lo que importa es
    la versión que se está ejecutando, que es la que puede tener el fallo.
    """
    result = ScanResult()

    if not _module_available('pip_audit'):
        result.skipped = (
            'pip-audit no esta instalado, asi que las dependencias no se han '
            'contrastado con ninguna base de vulnerabilidades. Es la '
            'comprobacion que deberia correr en el servidor, porque no '
            'necesita credencial. Para tenerla: uv add pip-audit'
        )
        return result

    argv = [
        _python(), '-m', 'pip_audit',
        '--format', 'json',
        # Sin la ruleta giratoria: escribe caracteres de control que en un log
        # o en CommandRunModel son ruido.
        '--progress-spinner', 'off',
    ]

    try:
        done = subprocess.run(
            argv, capture_output=True, text=True,
            cwd=str(settings.BASE_DIR), timeout=PIP_AUDIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        result.error = (
            f'pip-audit no respondio en {PIP_AUDIT_TIMEOUT}s. Consulta la base '
            f'de avisos por red: si el servidor no tiene salida, esta '
            f'comprobacion no se puede hacer desde aqui.'
        )
        return result
    except (OSError, subprocess.SubprocessError) as error:
        result.error = f'no se pudo ejecutar pip-audit: {error}'
        return result

    payload = _first_json_object(done.stdout)

    if payload is None:
        result.error = (
            f'pip-audit no devolvio JSON (codigo {done.returncode}): '
            f'{(done.stderr or done.stdout).strip()[:300]}'
        )
        return result

    result.ran = True
    result.findings = _pip_audit_findings(payload)

    return result


def _pip_audit_findings(payload) -> List[str]:
    """
    Una línea por paquete afectado, con la versión que lo corrige.

    Por paquete y no por aviso: doce paquetes dan sesenta y siete avisos, y
    sesenta y siete líneas no se leen. Lo accionable es «sube este paquete a
    esta versión», y eso es una línea.

    Los identificadores **se deduplican**: pip-audit consulta más de una
    fuente y el mismo aviso vuelve por cada una, así que contarlos en crudo
    triplica la cifra y asusta de más.
    """
    findings = []

    for dependency in _listed(payload, 'dependencies'):
        issues = _listed(dependency, 'vulns')

        if not issues:
            continue

        identifiers = sorted({
            issue.get('id') for issue in issues if issue.get('id')
        })
        fixes = sorted({
            version
            for issue in issues
            for version in (issue.get('fix_versions') or [])
        })

        remedy = f'corrige en {fixes[0]}' if fixes else 'sin version que lo corrija'
        shown = ', '.join(identifiers[:3])

        if len(identifiers) > 3:
            shown += f' (+{len(identifiers) - 3})'

        findings.append(
            f'{dependency.get("name", "?")} '
            f'{dependency.get("version", "?")} — '
            f'{len(identifiers)} aviso(s), {remedy}: {shown}'
        )

    return findings


# ----------------------------------------------------------------------
def run_safety() -> ScanResult:
    """
    Lo mismo que ``run_pip_audit``, con una base más rica — y sólo en local.

    En el servidor ni se intenta: Safety CLI 3 siempre se autentica y sin
    credencial se queda esperando en el terminal, donde no hay nadie. Ese
    salto es la configuración prevista, no un hueco.
    """
    result = ScanResult()

    # Primero el entorno, antes que nada: en produccion esto no se ejecuta
    # aunque este instalada y aunque haya clave.
    if not getattr(settings, 'DEBUG', False):
        result.by_design = True
        result.skipped = (
            'safety solo se ejecuta en local. En el servidor la comprobacion '
            'de dependencias la hace pip-audit, que no necesita credencial; '
            'safety se autentica siempre y sin nadie que conteste se quedaria '
            'esperando.'
        )
        return result

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




def _lines_for(dependency, location) -> List[str]:
    """Las vulnerabilidades de un paquete, ya escritas."""
    name = dependency.get('name', '?')
    lines = []

    for spec in _listed(dependency, 'specifications'):
        for issue in _listed(
                spec.get('vulnerabilities'), 'known_vulnerabilities'):
            lines.append(
                f'{name} {spec.get("raw", "")} — '
                f'{issue.get("id", "?")} '
                f'({issue.get("severity") or "sin severidad"})'
                f'  [{location}]'
            )

    return lines


def _safety_findings(payload) -> List[str]:
    """
    Las vulnerabilidades del informe, una linea por paquete afectado.

    El formato de safety ha cambiado entre versiones mayores, asi que se
    recorre defensivamente: lo que importa es no perder un hallazgo por un
    cambio de forma, aunque la linea salga menos bonita.
    """
    findings = []

    for entry in _listed(payload.get('scan_results')
                         if isinstance(payload, dict) else None, 'files'):
        location = entry.get('location', '?')

        for dependency in _listed(entry.get('results'), 'dependencies'):
            findings.extend(_lines_for(dependency, location))

    return findings
