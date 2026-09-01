# apps/project/specific/internal/ops/registry.py
"""
Que comandos se pueden ejecutar desde el admin, y con que parametros.

Esto es, por diseno, una superficie de ejecucion remota: una pagina web que
lanza comandos en el servidor. Todo lo que hay aqui existe para acotarla.

Tres reglas, y ninguna es negociable:

1. **Lista blanca, nunca lista negra.** Solo se ejecuta lo que aparece en
   ``COMMANDS``. Django trae de serie ``flush``, ``sqlflush``, ``dumpdata``
   -- que volcaria la base entera por una pagina web -- y este proyecto trae
   ``delete_migrations`` y ``rename_migrations``, que borran ficheros de todo
   el repositorio. Nada de eso esta aqui, y anadirlo requiere escribirlo a
   mano en este fichero.

2. **Los parametros se declaran, no se escriben.** Cada comando dice que
   opciones admite y de que tipo. Nunca se acepta una cadena libre de
   argumentos: eso permitiria colar ``--settings=...`` o cualquier otra cosa.

3. **Nunca hay shell.** El ejecutor construye una lista de argumentos y la
   pasa a ``subprocess`` sin intermediario, asi que no hay nada que escapar.

El nivel de riesgo no es decorativo: la interfaz obliga a confirmar
escribiendo el nombre del comando cuando es ``DANGEROUS``.

Tres niveles de disponibilidad
------------------------------
No todos los comandos que tienen sentido en un portatil lo tienen en
produccion. ``start_app`` escribe ficheros nuevos en el repositorio: en
desarrollo es la forma normal de crear una app, en produccion no hay ninguna
razon legitima para hacerlo desde una pagina web. Por eso cada entrada declara
cuando esta disponible:

* ``AVAILABILITY_ALWAYS`` -- en desarrollo y en produccion.
* ``AVAILABILITY_DEBUG_ONLY`` -- solo con ``DEBUG = True``.
* Y un tercer nivel que no es un valor sino una ausencia: lo que no esta en
  ``COMMANDS`` no existe para la consola, pase lo que pase (``NEVER_EXPOSED``,
  mas abajo).

**El filtro vive en ``get_command()``, no en la plantilla.** Esconder una
tarjeta no es un control: si la comprobacion estuviera solo en la consola,
bastaria con teclear la URL del comando. Al filtrar en el registro, el
ejecutor recibe ``None`` y levanta ``CommandNotAllowed``, y la pagina responde
404 -- igual que un comando que no existe, que es exactamente lo que es en ese
entorno.

``DEBUG`` viene de una variable de entorno y una variable de entorno se puede
equivocar. Por eso la separacion por entorno **no** es donde se apoya la
seguridad: lo peligroso de verdad no esta en ningun nivel, esta fuera de la
lista. La separacion por entorno es para lo que es meramente inapropiado en
produccion, no para lo que seria un desastre si ``DEBUG`` quedara mal puesto.

Lo que NO esta aqui, y por que
------------------------------
``NEVER_EXPOSED`` recoge lo que no se expone en ningun entorno, con su razon
al lado, y hay una prueba que comprueba que ninguno se ha colado en
``COMMANDS``. Tres familias:

**Cumplimiento regulatorio.** ``auditlogflush``, ``axes_reset_logs`` y
``axes_reset_failure_logs`` destruyen el rastro de quien hizo que y cuando. La
certificacion de esta plataforma se apoya en poder demostrar la integridad de
lo que registra (ver ``docs/NORMATIVA.md``); un boton que borra la auditoria
--y que ademas dejaria su propia huella en ``CommandRunModel``, contando que
alguien borro la auditoria-- no es una herramienta de operacion, es un riesgo
sin contrapartida. Si algun dia hace falta purgar por retencion de datos, eso
es una politica escrita y un procedimiento con dos personas, no un clic.

**Ejecucion arbitraria y secretos.** ``shell`` y ``dbshell`` vacian de sentido
la lista blanca entera. ``diffsettings`` imprime ``SECRET_KEY``, la clave de la
base de datos y ``FIELD_ENCRYPTION_KEY``. ``generate_certification_key`` y
``generate_encryption_key`` imprimen claves privadas. Todos comparten el mismo
agravante: **la salida de la consola se guarda en ``CommandRunModel``**, asi
que lo que se imprima queda ademas escrito en una tabla que se lee desde el
propio panel. Un secreto que pasa por aqui deja de serlo.

**Destructivos o sin sentido remoto.** ``flush`` y ``sqlflush`` vacian la base
entera; ``dumpdata`` la volcaria a esa misma tabla y ``loaddata`` (y el
``import`` de import_export) inyectaria registros arbitrarios;
``delete_migrations`` y ``rename_migrations`` borran ficheros de todo el
repositorio; ``createsuperuser``, ``changepassword`` y ``addstatictoken``
crean o cambian credenciales; ``two_factor_disable`` le quitaria el segundo
factor a alguien desde una pagina que exige segundo factor para abrirse;
``remove_stale_contenttypes`` borra permisos en cascada; ``runserver``,
``testserver`` y ``startproject`` no significan nada en un servidor ya
arrancado.

Anadir cualquiera de ellos requiere quitarlo de ``NEVER_EXPOSED`` y escribirlo
a mano en ``COMMANDS``, y la prueba obliga a que sea deliberado.

Hay un tercer cajon, ``NOT_USEFUL_HERE``, para lo que no es peligroso sino
simplemente inutil en este proyecto (``startapp``, ``createcachetable``...).
Va aparte para que ``NEVER_EXPOSED`` siga diciendo una sola cosa. Y entre los
tres el inventario esta **completo**: una prueba comprueba que todo comando
instalado aparece en alguno, de modo que actualizar una dependencia y que
traiga comandos nuevos sea una decision que alguien toma, y no algo que pasa
inadvertido.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from django.conf import settings
from django.utils.translation import gettext_lazy as _

# --- Cuando esta disponible cada comando -------------------------------
AVAILABILITY_ALWAYS = 'ALWAYS'
AVAILABILITY_DEBUG_ONLY = 'DEBUG'

AVAILABILITY_CHOICES = (
    (AVAILABILITY_ALWAYS, _('Always')),
    (AVAILABILITY_DEBUG_ONLY, _('Development only')),
)

AVAILABILITY_LABELS = dict(AVAILABILITY_CHOICES)

#: Lo que no se expone en ningun entorno, y por que.
#:
#: No es documentacion suelta: ``tests.py`` comprueba que ninguno aparezca en
#: ``COMMANDS``, ni por su nombre de entrada ni como ``program``. Anadir uno
#: obliga a quitarlo de aqui primero, que es la friccion que se busca.
NEVER_EXPOSED = {
    # --- Cumplimiento regulatorio: destruyen el rastro de auditoria ---
    'auditlogflush': _(
        'Destroys the audit trail the certification relies on. Purging by '
        'retention policy is a written procedure, not a button.'
    ),
    'axes_reset_logs': _('Destroys the record of access attempts.'),
    'axes_reset_failure_logs': _('Destroys the record of failed logins.'),

    # --- Ejecucion arbitraria y secretos ---
    'shell': _('Arbitrary code execution: it voids the whole allowlist.'),
    'dbshell': _('Arbitrary SQL: it voids the whole allowlist.'),
    'diffsettings': _(
        'Prints SECRET_KEY, the database password and FIELD_ENCRYPTION_KEY — '
        'and the output is stored in CommandRunModel.'
    ),
    'generate_certification_key': _(
        'Prints a private key, which would end up written in a table.'
    ),
    'generate_encryption_key': _(
        'Prints the PII encryption key, which would end up written in a table.'
    ),

    # --- Destructivos con los datos ---
    'flush': _('Empties the entire database.'),
    'sqlflush': _('Prints the SQL that empties the entire database.'),
    'dumpdata': _(
        'Would dump every record into CommandRunModel, encrypted PII '
        'included.'
    ),
    'loaddata': _('Injects arbitrary records.'),
    'import': _('Bulk data injection from a web page.'),
    'export': _('Bulk data extraction into the run history.'),
    'delete_migrations': _('Deletes migration files across the repository.'),
    'rename_migrations': _('Renames migration files across the repository.'),
    'remove_stale_contenttypes': _('Cascades into deleting permissions.'),

    # --- Credenciales y segundo factor ---
    'createsuperuser': _('Creates credentials from a web page.'),
    'changepassword': _(
        'Changes credentials, and needs stdin, which here is DEVNULL.'
    ),
    'addstatictoken': _('Mints second-factor backup tokens for a user.'),
    'two_factor_disable': _(
        'Would strip the second factor from a user, from a page that requires '
        'a second factor to open.'
    ),

    # --- Sin sentido en un servidor ya arrancado ---
    'runserver': _('There is already a server running.'),
    'testserver': _('Starts a throwaway server with fixture data.'),
    'startproject': _('Creates a new project; meaningless here.'),
    'ping_google': _('This project publishes no sitemap.'),

    # --- Rastro de auditoria, por la puerta de atras ---
    'auditlogmigratejson': _(
        'Rewrites the audit table wholesale. It is a one-off upgrade step to '
        'run with a backup in hand, not a button on a panel.'
    ),
}

#: Lo que simplemente no aporta nada aqui, y por que.
#:
#: Es un tercer cajon a proposito. Sin el habria que meter en
#: ``NEVER_EXPOSED`` cosas que no son peligrosas --solo inutiles en este
#: proyecto-- y esa lista dejaria de leerse como lo que es: la de lo que no se
#: puede permitir. Separarlas mantiene cada una diciendo una sola cosa.
#:
#: Existe ademas para que el inventario este **completo**: hay una prueba que
#: comprueba que todo comando instalado aparece en uno de los tres sitios, de
#: modo que actualizar una dependencia y que traiga comandos nuevos sea una
#: decision que alguien toma, y no algo que pasa inadvertido.
NOT_USEFUL_HERE = {
    'startapp': _(
        'Superseded by start_app, which sets the dotted name, the urls.py '
        'and the locale folder this project needs.'
    ),
    'createcachetable': _(
        'This project caches in Redis, or in memory when there is none. '
        'There is no cache table to create.'
    ),
    'mtime_cache': _(
        'A warm-up helper for django-compressor. Precompiling the bundles '
        'with compress already covers what a deploy needs.'
    ),
    'squashmigrations': _(
        'Migration surgery belongs in an editor with the diff in front of '
        'you, and the result goes through git.'
    ),
    'optimizemigration': _('Same as squashing: it rewrites source code.'),
    'axes_reset_ip_username': _(
        'Covered by the two entries that are here: unlocking an address and '
        'unlocking a person.'
    ),
}

# --- Niveles de riesgo -------------------------------------------------
RISK_READ_ONLY = 'READ_ONLY'
RISK_WRITES = 'WRITES'
RISK_DANGEROUS = 'DANGEROUS'

RISK_CHOICES = (
    (RISK_READ_ONLY, _('Read only — only reports, changes nothing')),
    (RISK_WRITES, _('Writes — changes data or files')),
    (RISK_DANGEROUS, _('Dangerous — hard to undo, confirm before running')),
)

RISK_LABELS = dict(RISK_CHOICES)

RISK_ORDER = {RISK_READ_ONLY: 0, RISK_WRITES: 1, RISK_DANGEROUS: 2}

# --- Que binario se ejecuta -------------------------------------------
#
# Dos, y cerrados. No es una ruta libre a proposito: si una entrada del
# registro pudiera nombrar cualquier ejecutable, la lista blanca de comandos
# dejaria de acotar nada -- bastaria con declarar `bash`.
EXEC_MANAGE = 'manage'
EXEC_GIT = 'git'

#: Como se escribe cada uno cuando se le ensena al operador. La ruta real del
#: interprete y de manage.py no aporta nada para auditar: lo util es que se
#: ejecuto, no donde vive el python de este servidor.
EXEC_DISPLAY = {
    EXEC_MANAGE: 'manage.py',
    EXEC_GIT: 'git',
}

# --- Areas, para agrupar y filtrar en la consola -----------------------
AREA_DEPLOY = 'DEPLOY'
AREA_DIAGNOSTICS = 'DIAGNOSTICS'
AREA_CERTIFICATION = 'CERTIFICATION'
AREA_SCHEDULED = 'SCHEDULED'
AREA_ACCESS = 'ACCESS'
AREA_MAINTENANCE = 'MAINTENANCE'

AREA_CHOICES = (
    (AREA_DEPLOY, _('Deploy')),
    (AREA_DIAGNOSTICS, _('Diagnostics')),
    (AREA_CERTIFICATION, _('Certification')),
    (AREA_SCHEDULED, _('Scheduled tasks')),
    (AREA_ACCESS, _('Access and blocks')),
    (AREA_MAINTENANCE, _('Maintenance')),
)

AREA_LABELS = dict(AREA_CHOICES)

AREA_ORDER = {area: index for index, (area, _label) in enumerate(AREA_CHOICES)}

# --- Tipos de parametro ------------------------------------------------
KIND_FLAG = 'flag'
KIND_TEXT = 'text'
KIND_NUMBER = 'number'
KIND_CHOICE = 'choice'


@dataclass(frozen=True)
class Option:
    """Un parametro que el operador puede rellenar en la interfaz."""

    flag: str
    label: str
    kind: str = KIND_FLAG
    help: str = ''
    default: object = None
    choices: tuple = ()
    #: Para ``KIND_TEXT``: solo se aceptan valores que casen con esto.
    pattern: str = ''
    #: Va suelto al final, sin bandera delante (``findstatic css/x.css``).
    #: ``flag`` pasa a ser solo el nombre del campo en el formulario.
    positional: bool = False
    #: Sin el, el comando no se puede lanzar.
    required: bool = False

    @property
    def name(self) -> str:
        """Identificador para el formulario, sin guiones."""
        return self.flag.lstrip('-').replace('-', '_')


@dataclass(frozen=True)
class Command:
    """Un comando permitido, con todo lo que hace falta para entenderlo."""

    name: str
    title: str
    summary: str
    #: Que hace, en concreto, contado sin jerga.
    detail: str
    #: Un caso real de cuando se usa.
    example: str
    risk: str = RISK_READ_ONLY
    area: str = AREA_DIAGNOSTICS
    #: Cuando esta disponible. ``DEBUG_ONLY`` es para lo que tiene sentido en
    #: un portatil y ninguno en produccion -- crear una app, reescribir los
    #: catalogos de traduccion --, no para lo peligroso: eso no esta en la
    #: lista siquiera.
    availability: str = AVAILABILITY_ALWAYS
    options: List[Option] = field(default_factory=list)
    #: Segundos antes de cortarlo. La peticion HTTP espera, no hay cola.
    timeout: int = 120
    #: Texto de aviso extra que se pinta en rojo antes de ejecutar.
    warning: str = ''
    #: Que binario lo ejecuta: ``manage.py`` o ``git``.
    executable: str = EXEC_MANAGE
    #: Lo que se ejecuta de verdad, si no coincide con ``name``.
    #:
    #: ``name`` identifica la **entrada** del registro -- va en la URL y en el
    #: registro de auditoria -- y hay entradas distintas para el mismo comando:
    #: ``crontab add`` y ``crontab remove`` no tienen el mismo riesgo ni la
    #: misma explicacion, asi que no pueden ser una sola tarjeta con un
    #: desplegable.
    program: str = ''
    #: Argumentos que el operador no elige ni puede quitar.
    #:
    #: Es donde se fija lo que hace segura a una entrada: ``--ff-only`` en el
    #: pull, ``--check --dry-run`` en makemigrations. Si fueran opciones, se
    #: podrian desmarcar.
    fixed_args: tuple = ()

    @property
    def program_name(self) -> str:
        return self.program or self.name

    @property
    def display_line(self) -> str:
        """La invocacion tal y como se escribiria a mano, sin las opciones."""
        parts = [EXEC_DISPLAY.get(self.executable, self.executable),
                 self.program_name]
        parts.extend(str(part) for part in self.fixed_args)

        return ' '.join(parts)

    @property
    def needs_confirmation(self) -> bool:
        return self.risk == RISK_DANGEROUS

    @property
    def is_debug_only(self) -> bool:
        return self.availability == AVAILABILITY_DEBUG_ONLY

    @property
    def is_available(self) -> bool:
        """Si este entorno lo admite ahora mismo."""
        if self.availability == AVAILABILITY_ALWAYS:
            return True

        return bool(getattr(settings, 'DEBUG', False))

    @property
    def area_label(self):
        return AREA_LABELS.get(self.area, self.area)

    @property
    def risk_label(self):
        return RISK_LABELS.get(self.risk, self.risk)

    @property
    def search_text(self) -> str:
        """Lo que mira el buscador de la consola."""
        return ' '.join(str(part) for part in (
            self.name, self.program_name, self.title,
            self.summary, self.detail, self.example, self.area_label,
        )).lower()

    def option(self, name: str) -> Optional[Option]:
        for option in self.options:
            if option.name == name:
                return option
        return None


COMMANDS = (
    # ---------------------------------------------------------------
    # Despliegue: el codigo que hay en el servidor.
    # ---------------------------------------------------------------
    Command(
        name='git_status',
        title=_('Working tree state'),
        summary=_('Shows which branch is deployed and whether anything was '
                  'edited on the server.'),
        detail=_(
            'The question to answer before pulling. A file edited directly on '
            'the server stops the pull, and finding that out from the error '
            'message is the slow way. It also says how many commits behind '
            'the branch is, which is how you know whether a deploy is even '
            'needed.'
        ),
        example=_('Before every deploy, and when a fix does not seem to have '
                  'landed.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        executable=EXEC_GIT,
        program='status',
        fixed_args=('--short', '--branch'),
        timeout=60,
    ),
    Command(
        name='git_log',
        title=_('Deployed commits'),
        summary=_('Lists the last commits of the deployed code.'),
        detail=_(
            'What is actually running on this server, which is not always '
            'what was merged. If a change is missing here, the deploy did not '
            'happen — no need to go looking for the bug anywhere else.'
        ),
        example=_('To confirm a merged fix really reached production.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        executable=EXEC_GIT,
        program='log',
        fixed_args=('--oneline', '--decorate', '-n', '20'),
        timeout=60,
    ),
    Command(
        name='git_pull',
        title=_('Pull the latest code'),
        summary=_('Brings down what was merged, without ever creating a merge '
                  'commit.'),
        detail=_(
            'It runs with --ff-only, and that is the whole safety of it: if '
            'the server cannot fast-forward — because something was edited '
            'here, or the branch diverged — it stops and changes nothing, '
            'instead of leaving a merge commit on a production checkout that '
            'nobody will review. Check the working tree state first if it '
            'refuses. Pulling is not deploying: code that changes models '
            'needs migrations, and code that changes CSS or JS needs the '
            'static files collected. Neither happens on its own.'
        ),
        example=_('After merging to master, to bring the change to the '
                  'server.'),
        risk=RISK_WRITES,
        area=AREA_DEPLOY,
        executable=EXEC_GIT,
        program='pull',
        fixed_args=('--ff-only',),
        timeout=300,
        warning=_(
            'This changes the running code. Right afterwards: apply '
            'migrations and collect static files, or the site will be serving '
            'new code against an old database and old assets.'
        ),
    ),
    Command(
        name='makemigrations_check',
        title=_('Pending model changes'),
        summary=_('Says whether a model was changed without writing its '
                  'migration.'),
        detail=_(
            'It runs with --check --dry-run, so it writes nothing: it only '
            'answers yes or no. A model changed without its migration is a '
            'failure that shows up far from its cause — the code deploys '
            'fine and the database breaks on the first query that touches the '
            'new field.'
        ),
        example=_('Before deploying, together with the migration state.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        program='makemigrations',
        fixed_args=('--check', '--dry-run'),
        timeout=120,
    ),
    Command(
        name='sqlmigrate',
        title=_('SQL of a migration'),
        summary=_('Shows the SQL a migration would run, without running it.'),
        detail=_(
            'The way to know what a migration is going to do before it does '
            'it — whether it rewrites a table, whether it locks it, whether '
            'it drops a column. Reading it takes a minute; undoing a '
            'migration on a live database does not.'
        ),
        example=_('Before applying a migration on a table with a lot of '
                  'rows.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        options=[
            Option(
                flag='app_label',
                label=_('App'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('Label of the app, as it appears in the migration '
                       'state (for example: buyers).'),
                pattern=r'^[a-z][a-z0-9_]{0,60}$',
            ),
            Option(
                flag='migration_name',
                label=_('Migration'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('Its number or full name, for example 0012.'),
                pattern=r'^[A-Za-z0-9_]{1,120}$',
            ),
        ],
        timeout=120,
    ),
    Command(
        name='compress',
        title=_('Precompile CSS and JS bundles'),
        summary=_('Builds the compressed bundles django-compressor serves in '
                  'production.'),
        detail=_(
            'With offline compression on, the bundles are not built when a '
            'page is requested: they have to exist beforehand. If they are '
            'missing or stale, pages fail with "you have offline compression '
            'enabled but key is missing". Run it after collecting the static '
            'files, not before.'
        ),
        example=_('After a deploy that touched CSS or JS.'),
        risk=RISK_WRITES,
        area=AREA_DEPLOY,
        options=[
            Option(
                flag='--force',
                label=_('Rebuild everything'),
                kind=KIND_FLAG,
                help=_('Rebuilds even what looks up to date. Slower, and the '
                       'answer when something stale is being served.'),
            ),
        ],
        timeout=600,
    ),

    # ---------------------------------------------------------------
    # Diagnostico: no tocan nada.
    # ---------------------------------------------------------------
    Command(
        name='check',
        title=_('Django checks'),
        summary=_('Looks for configuration problems without touching anything.'),
        detail=_(
            'Runs the framework checks: models, admin, URLs, templates and '
            'security settings. It is what should come out clean before any '
            'deploy.'
        ),
        example=_('After changing settings.py, to confirm nothing broke.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        options=[
            Option(
                flag='--deploy',
                label=_('Deploy checks'),
                kind=KIND_FLAG,
                help=_(
                    'Adds the production-only checks: HTTPS, cookies, '
                    'HSTS. Expect warnings in development.'
                ),
            ),
        ],
        timeout=90,
    ),
    Command(
        name='check_media',
        title=_('Media storage'),
        summary=_(
            'Checks that MEDIA_ROOT points where the files really are and '
            'that the sensitive folders are not served by the web server.'
        ),
        detail=_(
            'FileField stores paths relative to MEDIA_ROOT. If the variable '
            'points somewhere else, nothing is lost but Django stops finding '
            'the files: every download 404s and new uploads land in the '
            'wrong place. It fails silently, which is why this exists. It '
            'also checks the .htaccess files that stop the web server from '
            'handing out certificates and identity documents on its own.'
        ),
        example=_('After moving the media folder, or after a deploy.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        options=[
            Option(
                flag='--sample',
                label=_('Files per field'),
                kind=KIND_NUMBER,
                default=25,
                help=_('How many files to check per model field.'),
            ),
            Option(
                flag='--find',
                label=_('Search under'),
                kind=KIND_TEXT,
                help=_(
                    'If a file is missing, look for it by name under this '
                    'path and say where it is.'
                ),
                pattern=r'^[A-Za-z0-9/_.\-]{1,200}$',
            ),
            Option(
                flag='--http',
                label=_('Check over HTTP'),
                kind=KIND_FLAG,
                help=_(
                    'Actually request a sensitive file from outside and '
                    'confirm the web server answers 404.'
                ),
            ),
        ],
        timeout=180,
    ),
    Command(
        name='check_certifications',
        title=_('Certified documents health'),
        summary=_(
            'Checks that the three files of every certified document are on '
            'disk and that their fingerprints still match.'
        ),
        detail=_(
            'Two different failures: a record pointing at a deleted file, '
            'and a file whose stored hash no longer matches what is on '
            'disk. The second one is the serious one — it means the '
            'certification is lying.'
        ),
        example=_('Monthly, and after any migration of the media folder.'),
        risk=RISK_READ_ONLY,
        area=AREA_CERTIFICATION,
        timeout=300,
    ),
    Command(
        name='check_cache',
        title=_('Cache'),
        summary=_(
            'Checks that the cache answers and that it is shared across '
            'processes.'
        ),
        detail=_(
            'Asking the VPS whether Redis is alive does not answer what '
            'matters: whether this application reaches it, and whether the '
            'rate counters are shared. And it cannot be judged by eye, '
            'because django-redis runs with IGNORE_EXCEPTIONS so an outage '
            'does not take the login down — the price is that an unreachable '
            'server returns None instead of raising, and a broken cache looks '
            'exactly like an empty one. The last check is the one that '
            'decides: it writes a key and reads it back from another process.'
        ),
        example=_('After pointing REDIS_URL at the VPS, and when rate limits '
                  'seem not to apply.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        timeout=90,
    ),
    Command(
        name='check_workers',
        title=_('Background workers'),
        summary=_(
            'Checks whether this server can hold a worker process outside the '
            'request.'
        ),
        detail=_(
            'A worker is not a library you install: it is a process that '
            'lives outside the request and does not die. Shared hosting often '
            'kills anything that is not serving a page, and never says so, so '
            'this is not decided by reading documentation — it is measured. '
            'It also checks something easy to miss: Redis working as a cache '
            'does not mean it works as a broker, because the ACL is written '
            'for the cache and a broker needs other keys and other commands. '
            'That one fails silently, with tasks simply vanishing.'
        ),
        example=_('Before deciding whether Celery is worth adopting here.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        timeout=120,
        options=[
            Option(
                flag='--spawn',
                label=_('Launch the test process'),
                kind=KIND_FLAG,
                help=_(
                    'Starts a detached process that does nothing but write '
                    'the time every 30 seconds. Come back later and run this '
                    'again: what matters is not that it starts, but that it '
                    'is still alive then.'
                ),
            ),
            Option(
                flag='--minutes',
                label=_('How long the test should last'),
                kind=KIND_NUMBER,
                default=30,
                help=_(
                    'Half an hour rules out the hosting that kills everything '
                    'right away, which is the common case. It says nothing '
                    'about the one that kills a process now and then, and for '
                    'that it has to run longer: 1440 is a full day.'
                ),
            ),
        ],
    ),
    Command(
        name='check_cron',
        title=_('Scheduled tasks'),
        summary=_(
            'Checks whether the scheduled tasks are actually installed in the '
            'crontab.'
        ),
        detail=_(
            'Declaring a task in CRONJOBS does not schedule it: django-crontab '
            'writes it into the crontab only when someone runs '
            '"manage.py crontab add". Until then the list exists in the code '
            'and nobody runs it — with no error and nothing in the log. There '
            'is a worse case too: the installed line carries a hash of the '
            'whole job definition, schedule included, so changing a schedule '
            'leaves the line pointing at a job that no longer exists. The '
            'cron fires and runs nothing, and from outside it looks exactly '
            'like everything working.'
        ),
        example=_('When something that should run on its own has not run.'),
        risk=RISK_READ_ONLY,
        area=AREA_SCHEDULED,
        timeout=60,
    ),
    Command(
        name='upgrade_ots_anchors',
        title=_('Mature blockchain proofs'),
        summary=_(
            'Asks the calendars whether the pending proofs are already in a '
            'Bitcoin block.'
        ),
        detail=_(
            'This is what the scheduled task does every 15 minutes. Running '
            'it by hand catches up without waiting — useful when the task was '
            'not installed, or right after installing it. It is safe to run '
            'at any time: with nothing pending it does not even reach the '
            'network, and a proof that has not matured yet is left for the '
            'next round rather than treated as an error.'
        ),
        example=_('When an anchor has been waiting longer than a few hours.'),
        risk=RISK_WRITES,
        area=AREA_CERTIFICATION,
        timeout=180,
    ),
    Command(
        name='check_requirements',
        title=_('Dependencies'),
        summary=_(
            'Checks that requirements.txt carries everything declared in '
            'pyproject.toml.'
        ),
        detail=_(
            'The project uses two dependency files: pyproject.toml with uv '
            'locally, and requirements.txt with pip in production, because '
            'cPanel has no uv. The bridge between them is a manual export, '
            'and a manual step is a step that gets forgotten. It already '
            'happened: opentimestamps was declared a day before it reached '
            'requirements.txt, and in between, production had no library and '
            'blockchain anchoring failed. The symptom showed up far from the '
            'cause, which is the worst kind.'
        ),
        example=_('Before every deploy, and after adding any dependency.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        timeout=60,
    ),
    Command(
        name='check_anchoring',
        title=_('Blockchain anchoring'),
        summary=_(
            'Checks whether this server can send hashes to the '
            'OpenTimestamps calendars.'
        ),
        detail=_(
            'When the composer says the box was sealed but not sent, the '
            'cause is almost never the code: either the opentimestamps '
            'library is not installed on this server, or the hosting blocks '
            'outbound connections. This tells the two apart, which is what '
            'decides whether the fix is a pip install of requirements.txt or '
            'a call to the provider. It also reports how the real anchors are '
            'doing: a proof that has been waiting for days means nothing is '
            'maturing it, not that the send failed.'
        ),
        example=_('When sealing reports that sending to the blockchain failed.'),
        risk=RISK_READ_ONLY,
        area=AREA_CERTIFICATION,
        timeout=120,
        options=[
            Option(
                flag='--stamp',
                label=_('Send a test hash'),
                kind=KIND_FLAG,
                help=_(
                    'Sends a made-up hash for real, to test the whole path, '
                    'and keeps the proof so it can be checked later. '
                    'Harmless: it belongs to no document.'
                ),
            ),
            Option(
                flag='--verify',
                label=_('Check the last test send'),
                kind=KIND_FLAG,
                help=_(
                    'Goes back to the last test hash and asks the calendars '
                    'whether it made it into a Bitcoin block. Nobody notifies '
                    'you when it does, so this is how you find out. Run it a '
                    'few hours after sending.'
                ),
            ),
        ],
    ),
    Command(
        name='check_attack_terms',
        title=_('Anti-scan trap'),
        summary=_(
            'Checks that no legitimate route collides with the scanner trap.'
        ),
        detail=_(
            'The trap catches any path containing one of COMMON_ATTACK_TERMS '
            'and blocks the IP. A badly chosen term hijacks a real route and '
            'locks out real users. This reports collisions respecting the '
            'URLconf order, which is what actually decides it.'
        ),
        example=_('Every time COMMON_ATTACK_TERMS changes.'),
        risk=RISK_READ_ONLY,
        area=AREA_ACCESS,
        timeout=90,
    ),
    Command(
        name='showmigrations',
        title=_('Migration state'),
        summary=_('Lists which migrations are applied and which are pending.'),
        detail=_(
            'Nothing runs. It is the way to see whether the database matches '
            'the code before deciding to migrate.'
        ),
        example=_('Right after deploying, before running migrate.'),
        risk=RISK_READ_ONLY,
        area=AREA_DEPLOY,
        options=[
            Option(
                flag='--plan',
                label=_('Show plan'),
                kind=KIND_FLAG,
                help=_('Lists them in the order they would be applied.'),
            ),
        ],
        timeout=90,
    ),

    # ---------------------------------------------------------------
    # Escriben, pero de forma prevista.
    # ---------------------------------------------------------------
    Command(
        name='migrate',
        title=_('Apply migrations'),
        summary=_('Brings the database schema up to date with the code.'),
        detail=_(
            'Applies every pending migration. Run the migration state check '
            'first to see what is going to happen.'
        ),
        example=_('After deploying code that adds fields or constraints.'),
        risk=RISK_WRITES,
        area=AREA_DEPLOY,
        options=[
            Option(
                flag='--noinput',
                label=_('No questions'),
                kind=KIND_FLAG,
                default=True,
                help=_('Required here: there is nobody to answer a prompt.'),
            ),
        ],
        timeout=600,
        warning=_(
            'A migration can lock tables. On a busy database, run it out of '
            'office hours.'
        ),
    ),
    Command(
        name='collectstatic',
        title=_('Collect static files'),
        summary=_('Publishes the CSS and JS so the browser gets them.'),
        detail=_(
            'In production static files are served with a hash in the name, '
            'so a change is invisible until this runs. If a page looks '
            'broken after a deploy, this is usually why.'
        ),
        example=_('After every deploy that touches CSS or JS.'),
        risk=RISK_WRITES,
        area=AREA_DEPLOY,
        options=[
            Option(
                flag='--noinput',
                label=_('No questions'),
                kind=KIND_FLAG,
                default=True,
                help=_('Required here: there is nobody to answer a prompt.'),
            ),
            Option(
                flag='--clear',
                label=_('Clear first'),
                kind=KIND_FLAG,
                help=_(
                    'Deletes what was collected before. Slower, but leaves '
                    'no orphan files behind.'
                ),
            ),
        ],
        timeout=600,
    ),
    Command(
        name='compilemessages',
        title=_('Compile translations'),
        summary=_('Turns the .po catalogs into the .mo files Django reads.'),
        detail=_(
            'Editing a translation changes the .po file, but Django only '
            'reads the compiled .mo. Until this runs, the new text shows in '
            'English.'
        ),
        example=_('After translating with Rosetta or editing a .po by hand.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        options=[
            Option(
                flag='--locale',
                label=_('Language'),
                kind=KIND_CHOICE,
                choices=('es', 'en'),
                default='es',
                help=_('Which catalog to compile.'),
            ),
        ],
        timeout=300,
    ),
    Command(
        name='clear_cache',
        title=_('Clear the cache'),
        summary=_('Empties the application cache.'),
        detail=_(
            'Useful when something stale is being served. Note that it also '
            'clears the public OTP rate-limit counters, which live in cache: '
            'right after running this, those limits start from zero.'
        ),
        example=_('After changing data that a page keeps cached.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        timeout=60,
        warning=_(
            'It resets the public OTP rate limits. Do not run it while '
            'someone is hammering the verification page.'
        ),
    ),
    Command(
        name='check_health',
        title=_('Health check'),
        summary=_('Checks the database, the cache and the mail server, from '
                  'inside and from outside.'),
        detail=_(
            'The two ways of asking do not answer the same thing, and telling '
            'them apart is the whole point. Asked from inside, it says '
            'whether the application reaches the database, Redis and the mail '
            'server. Asked over HTTP, it also crosses the web server, the '
            'certificate and the DNS. If the local one passes and the HTTP '
            'one does not, the problem is in front of the application and '
            'there is nothing to look for in the code. It is the same URL the '
            'warm-up task hits every three minutes.'
        ),
        example=_('Right after a deploy, and whenever the site feels broken '
                  'without an obvious error.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        options=[
            Option(
                flag='--http',
                label=_('Ask over HTTP'),
                kind=KIND_FLAG,
                help=_('Requests the real public URL instead of checking '
                       'inside this process.'),
            ),
        ],
        timeout=90,
    ),
    Command(
        name='show_log',
        title=_('Application log'),
        summary=_('Shows the last lines of the log without opening a '
                  'terminal.'),
        detail=_(
            'Reading the log was the last thing that still forced an SSH '
            'session, and it is the first thing needed when something fails. '
            'It reads from the end and never loads the whole file. Ask for '
            'few lines and filter: a log carries traces, paths, IP addresses '
            'and sometimes email addresses, and whatever is shown here is '
            'also written into the run history of this very console.'
        ),
        example=_('A page returned a 500 and there is no other clue.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        options=[
            Option(
                flag='--list',
                label=_('Only list the files'),
                kind=KIND_FLAG,
                help=_('Shows the current log and the rotated ones with '
                       'their size, without printing any content.'),
            ),
            Option(
                flag='--lines',
                label=_('Lines'),
                kind=KIND_NUMBER,
                default=100,
                help=_('How many lines from the end. The maximum is 2000.'),
            ),
            Option(
                flag='--contains',
                label=_('Containing'),
                kind=KIND_TEXT,
                help=_('Only lines carrying this text. Literal, not a regular '
                       'expression.'),
                pattern=r'^[\w .:,;/@\-\[\]()=]{1,80}$',
            ),
            Option(
                flag='--rotated',
                label=_('Rotated number'),
                kind=KIND_NUMBER,
                help=_('Read stderr_old_N.log instead of the current one. '
                       'Leave it empty for the current log.'),
            ),
        ],
        timeout=90,
    ),
    Command(
        name='rotate_logs',
        title=_('Rotate the log'),
        summary=_('Renames the log to stderr_old_N.log when it grows past its '
                  'size, and drops the oldest ones.'),
        detail=_(
            'It does nothing unless the file has passed the limit, so running '
            'it costs one stat. That is why it is scheduled hourly rather '
            'than weekly: with a weekly check, one bad day leaves the file at '
            'tens of megabytes before anyone looks, and the limit means '
            'nothing. It also keeps only the last few rotated files, because '
            'the disk here is a fixed quota and a log with no ceiling fills '
            'it — and when that happens every other write fails too, not just '
            'the log. The numbering continues from whatever is already there '
            'instead of starting over, so a file someone referred to in an '
            'email keeps its name.'
        ),
        example=_('It runs on its own every hour; by hand only to force it.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        options=[
            Option(
                flag='--force',
                label=_('Rotate now'),
                kind=KIND_FLAG,
                help=_('Rotates even if it has not reached the size.'),
            ),
            Option(
                flag='--max-mb',
                label=_('Size in MB'),
                kind=KIND_NUMBER,
                default=3,
                help=_('Rotate from this size on.'),
            ),
            Option(
                flag='--keep',
                label=_('Rotated files to keep'),
                kind=KIND_NUMBER,
                default=10,
                help=_('The older ones are deleted. 0 keeps them all, and '
                       'fills the disk sooner or later.'),
            ),
        ],
        timeout=120,
    ),
    Command(
        name='findstatic',
        title=_('Locate a static file'),
        summary=_('Says which folder a CSS, JS or image file is really being '
                  'served from.'),
        detail=_(
            'When a page looks broken after a deploy, the question is whether '
            'the file was collected at all and which copy won. This answers '
            'both: it lists every place the file appears, in the order Django '
            'searches them.'
        ),
        example=_('A stylesheet 404s, or a change to it does not show up.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        options=[
            Option(
                flag='staticfile',
                label=_('Path of the file'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('Relative to the static folder, for example '
                       'css/aegis_header.css.'),
                pattern=r'^[A-Za-z0-9/_.\-]{1,200}$',
            ),
            Option(
                flag='--first',
                label=_('Only the winning copy'),
                kind=KIND_FLAG,
                help=_('Stops at the first match, which is the one actually '
                       'served.'),
            ),
        ],
        timeout=90,
    ),
    Command(
        name='crontab_show',
        title=_('Installed scheduled lines'),
        summary=_('Lists the lines django-crontab has written into the '
                  'crontab.'),
        detail=_(
            'What is really installed, as opposed to what CRONJOBS declares. '
            'The two drift apart on their own: the installed line carries a '
            'hash of the whole job definition, so changing a schedule leaves '
            'the old line pointing at a job that no longer exists. Read it '
            'alongside the scheduled-tasks check, which compares the two.'
        ),
        example=_('When something that should run on its own has not run.'),
        risk=RISK_READ_ONLY,
        area=AREA_SCHEDULED,
        program='crontab',
        fixed_args=('show',),
        timeout=60,
    ),
    Command(
        name='crontab_add',
        title=_('Install the scheduled tasks'),
        summary=_('Writes every job declared in CRONJOBS into the crontab.'),
        detail=_(
            'Declaring a task in settings schedules nothing until this runs. '
            'It is also the fix when a schedule changed: it is safe to run '
            'repeatedly, because django-crontab removes its own lines before '
            'writing them again — it never touches lines it did not write.'
        ),
        example=_('After deploying a change to CRONJOBS, or when the '
                  'scheduled-tasks check reports nothing installed.'),
        risk=RISK_WRITES,
        area=AREA_SCHEDULED,
        program='crontab',
        fixed_args=('add',),
        timeout=90,
        warning=_(
            'It rewrites this account crontab lines for this project. Run the '
            'scheduled-tasks check afterwards to confirm what ended up there.'
        ),
    ),
    Command(
        name='crontab_remove',
        title=_('Uninstall the scheduled tasks'),
        summary=_('Removes this project lines from the crontab.'),
        detail=_(
            'Nothing scheduled runs after this: anchors stop maturing, the '
            'daily code stops being issued. It is half of the repair when a '
            'schedule changed — remove, then install — and on its own it is '
            'only for taking the platform out of service.'
        ),
        example=_('Before reinstalling the tasks after changing a schedule.'),
        risk=RISK_DANGEROUS,
        area=AREA_SCHEDULED,
        program='crontab',
        fixed_args=('remove',),
        timeout=90,
        warning=_(
            'Nothing runs on its own until the tasks are installed again.'
        ),
    ),
    Command(
        name='axes_list_attempts',
        title=_('Failed login attempts'),
        summary=_('Lists the login failures axes is counting right now.'),
        detail=_(
            'Where to look when someone says they cannot log in. It tells a '
            'lockout apart from a wrong password, which look identical from '
            'the outside. Note that a lockout is per (IP, user) pair, so the '
            'same person can be locked out from the office and get in from '
            'their phone.'
        ),
        example=_('A user reports that their password stopped working.'),
        risk=RISK_READ_ONLY,
        area=AREA_ACCESS,
        timeout=60,
    ),
    Command(
        name='axes_reset_ip',
        title=_('Unlock an IP'),
        summary=_('Clears the login lockout for one IP address.'),
        detail=_(
            'The surgical fix when a real user is locked out: it frees that '
            'address and nobody else. This is about the login lockout, which '
            'is a different thing from the anti-scan IP block — that one is '
            'undone from the blocked-IP table or the whitelist, and shows up '
            'as a plain 404 rather than a login error.'
        ),
        example=_('An office got locked out after several typed passwords.'),
        risk=RISK_WRITES,
        area=AREA_ACCESS,
        options=[
            Option(
                flag='ip',
                label=_('IP address'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('The one showing in the failed attempts.'),
                pattern=r'^[0-9a-fA-F.:]{3,45}$',
            ),
        ],
        timeout=60,
    ),
    Command(
        name='axes_reset_username',
        title=_('Unlock one person'),
        summary=_('Clears the login lockout for one username, from any '
                  'address.'),
        detail=_(
            'The lockout is per (IP, user) pair, so someone locked out at the '
            'office is still locked out from there after moving to their '
            'phone and back. This frees that person everywhere without '
            'touching anyone else who shares their address.'
        ),
        example=_('A user is still locked out after changing network.'),
        risk=RISK_WRITES,
        area=AREA_ACCESS,
        options=[
            Option(
                flag='username',
                label=_('Username'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('As it appears in the failed attempts.'),
                pattern=r'^[A-Za-z0-9._@\-]{1,150}$',
            ),
        ],
        timeout=60,
    ),
    Command(
        name='two_factor_status',
        title=_('Second-factor status'),
        summary=_('Says whether a user has their second factor set up.'),
        detail=_(
            'It changes nothing and shows no secret: only whether the device '
            'is registered. It is the first question to answer when someone '
            'says they cannot get into the panel, because the admin turns '
            'away anyone without a verified second factor — and it does so '
            'with a 404, which from outside looks like the page not existing.'
        ),
        example=_('Someone reports the admin URL "does not exist" for them.'),
        risk=RISK_READ_ONLY,
        area=AREA_ACCESS,
        options=[
            Option(
                flag='username',
                label=_('Username'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('Whose status to check.'),
                pattern=r'^[A-Za-z0-9._@\-]{1,150}$',
            ),
        ],
        timeout=60,
    ),
    Command(
        name='axes_reset',
        title=_('Unlock every login'),
        summary=_('Clears all login lockouts at once.'),
        detail=_(
            'It frees everyone, an attacker in the middle of guessing '
            'passwords included. Prefer unlocking a single IP: this one is '
            'for when the lockout is clearly the platform own fault and '
            'several people are stuck.'
        ),
        example=_('After a change that locked out legitimate users in bulk.'),
        risk=RISK_DANGEROUS,
        area=AREA_ACCESS,
        timeout=60,
        warning=_(
            'It also resets the counter of anyone currently guessing '
            'passwords.'
        ),
    ),
    Command(
        name='clearsessions',
        title=_('Expired sessions'),
        summary=_('Deletes sessions that already expired.'),
        detail=_(
            'Django never cleans up the session table on its own, so it only '
            'grows. It removes nothing that is still valid: nobody gets '
            'logged out by running this.'
        ),
        example=_('Housekeeping, when the session table has grown a lot.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        timeout=300,
    ),
    Command(
        name='sendtestemail',
        title=_('Send a test email'),
        summary=_('Sends one message to check the mail settings really work.'),
        detail=_(
            'Email fails silently more often than anything else here, and it '
            'fails where it hurts: the OTP of the public verification, the '
            'password recovery link, the daily code, the service order. This '
            'separates a bad configuration from a message that left and was '
            'filtered — if it arrives, the platform did its part.'
        ),
        example=_('After changing the mail settings, or when OTPs are not '
                  'arriving.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        options=[
            Option(
                flag='email',
                label=_('Recipient'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('An address you can actually check.'),
                pattern=r'^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}'
                        r'\.[A-Za-z]{2,20}$',
            ),
        ],
        timeout=120,
        warning=_('This sends real email.'),
    ),
    Command(
        name='generate_gea_code',
        title=_('Daily GEA code'),
        summary=_('Issues the daily code and mails it to its recipients.'),
        detail=_(
            'The same thing the scheduled job does. Running it by hand sends '
            'real email, so only use it if the scheduled run failed.'
        ),
        example=_('The cron did not run and the code for today is missing.'),
        risk=RISK_WRITES,
        area=AREA_SCHEDULED,
        timeout=180,
        warning=_('This sends real email to the configured recipients.'),
    ),

    # ---------------------------------------------------------------
    # Solo en desarrollo.
    #
    # Nada de esto es peligroso -- lo peligroso no esta en la lista, esta en
    # NEVER_EXPOSED --; es que no tiene sentido en produccion. Escriben en el
    # repositorio, y un repositorio de produccion se despliega, no se edita:
    # un fichero creado ahi no esta en git y desaparece en el siguiente
    # `git pull` o queda estorbando para siempre.
    # ---------------------------------------------------------------
    Command(
        name='start_app',
        title=_('Create an app'),
        summary=_('Creates a new app with the project layout already set up.'),
        detail=_(
            'It writes the app with its full dotted name, its urls.py and its '
            'locale folder, which is what makes it fit this project — a plain '
            'startapp leaves the name wrong and the URLconf empty. It does '
            'not register it: adding it to the right group in settings.py is '
            'still a manual step, and that ordering decides the URLconf and '
            'LOCALE_PATHS order.'
        ),
        example=_('Starting a new domain area, on a development machine.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        availability=AVAILABILITY_DEBUG_ONLY,
        options=[
            Option(
                flag='path',
                label=_('Path of the app'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('For example apps/project/specific/documents/reports.'),
                pattern=r'^[A-Za-z0-9/_\-]{1,200}$',
            ),
        ],
        timeout=120,
        warning=_(
            'It writes new files into the repository. They are not in git '
            'until someone commits them.'
        ),
    ),
    Command(
        name='makemigrations',
        title=_('Write migrations'),
        summary=_('Writes the migration files for the model changes.'),
        detail=_(
            'The writing version of the pending-changes check. It belongs on '
            'a development machine because a migration is source code: it '
            'goes through git, gets reviewed and gets deployed. Generated on '
            'the server it is a file nobody has seen, which the next pull '
            'either wipes out or conflicts with.'
        ),
        example=_('After changing a model, before committing.'),
        risk=RISK_WRITES,
        area=AREA_DEPLOY,
        availability=AVAILABILITY_DEBUG_ONLY,
        timeout=180,
        warning=_(
            'A migration is source code: commit it, do not leave it on a '
            'server.'
        ),
    ),
    Command(
        name='makemessages',
        title=_('Extract translatable text'),
        summary=_('Rewrites the .po catalogs with the strings found in the '
                  'code.'),
        detail=_(
            'It rewrites every catalog in the project, so it belongs where '
            'the result can be reviewed and committed. It also needs gettext '
            'installed. On the server the useful half is the other one — '
            'compiling the catalogs — which is available everywhere.'
        ),
        example=_('After adding text wrapped in gettext, on a development '
                  'machine.'),
        risk=RISK_WRITES,
        area=AREA_MAINTENANCE,
        availability=AVAILABILITY_DEBUG_ONLY,
        options=[
            Option(
                flag='--locale',
                label=_('Language'),
                kind=KIND_CHOICE,
                choices=('es', 'en'),
                default='es',
                help=_('Which catalog to rebuild.'),
            ),
        ],
        timeout=300,
    ),
    Command(
        name='inspectdb',
        title=_('Models from the schema'),
        summary=_('Prints the models that would match the tables already in '
                  'the database.'),
        detail=_(
            'Reads the schema and writes nothing. It is for comparing what '
            'the database really has against what the code declares, when the '
            'two have drifted apart. The output is a draft, never something '
            'to paste in as is.'
        ),
        example=_('Chasing a mismatch between a table and its model.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        availability=AVAILABILITY_DEBUG_ONLY,
        timeout=120,
    ),
    Command(
        name='sqlsequencereset',
        title=_('SQL to fix the sequences'),
        summary=_('Prints the SQL that puts the auto-increment counters back '
                  'in place.'),
        detail=_(
            'It only prints: nothing runs. It is what is needed after loading '
            'rows with explicit ids, when the counter is left behind and the '
            'next insert collides with an existing row.'
        ),
        example=_('After importing data with fixed ids into a development '
                  'database.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        availability=AVAILABILITY_DEBUG_ONLY,
        options=[
            Option(
                flag='app_label',
                label=_('App'),
                kind=KIND_TEXT,
                positional=True,
                required=True,
                help=_('Label of the app, for example buyers.'),
                pattern=r'^[a-z][a-z0-9_]{0,60}$',
            ),
        ],
        timeout=120,
    ),
    Command(
        name='test',
        title=_('Run the test suite'),
        summary=_('Runs the tests against SQLite in memory.'),
        detail=_(
            'They run with app_core.settings_test because the MySQL user on '
            'cPanel cannot create the test_ database — which is also why '
            'this is a development-only entry. Half of the suite reproduces '
            'holes that were already closed, so a red result is worth reading '
            'before assuming the test is stale.'
        ),
        example=_('Before pushing, on a development machine.'),
        risk=RISK_READ_ONLY,
        area=AREA_DIAGNOSTICS,
        availability=AVAILABILITY_DEBUG_ONLY,
        fixed_args=('--settings=app_core.settings_test',),
        timeout=900,
    ),

    # ---------------------------------------------------------------
    # Dificiles de deshacer.
    # ---------------------------------------------------------------
    Command(
        name='db_backup',
        title=_('Database backup'),
        summary=_('Writes a full dump of the database to disk.'),
        detail=_(
            'Produces a file with everything in the database. Where it lands '
            'matters: anyone who can read that path can read every record, '
            'including the encrypted personal data fields.'
        ),
        example=_('Right before applying a risky migration.'),
        risk=RISK_DANGEROUS,
        area=AREA_MAINTENANCE,
        options=[
            Option(
                flag='-o',
                label=_('Output folder'),
                kind=KIND_TEXT,
                default='backups/',
                help=_('Folder for the dump, relative to the project root.'),
                pattern=r'^[A-Za-z0-9/_.\-]{1,120}$',
            ),
        ],
        timeout=900,
        warning=_(
            'The dump contains every record. Keep it out of any folder the '
            'web server can serve.'
        ),
    ),
)

COMMANDS_BY_NAME = {command.name: command for command in COMMANDS}

# Un nombre duplicado dejaria una entrada inalcanzable desde su URL, en
# silencio. Con varias entradas apuntando al mismo programa (`crontab add` y
# `crontab remove`) eso es facil de provocar con un copiar y pegar.
assert len(COMMANDS_BY_NAME) == len(COMMANDS), 'duplicate command name'


def get_command(name: str) -> Optional[Command]:
    """
    El comando permitido con ese nombre, o ``None``.

    ``None`` tambien para un comando que existe pero no esta disponible en
    este entorno. Es a proposito: el filtro tiene que estar **aqui** y no en
    la plantilla, porque esconder una tarjeta no es un control -- bastaria con
    teclear la URL. Devolviendo ``None``, el ejecutor levanta
    ``CommandNotAllowed`` y la pagina responde 404, que es exactamente lo que
    ese comando es en este entorno: algo que no existe.
    """
    command = COMMANDS_BY_NAME.get(name)

    if command is None or not command.is_available:
        return None

    return command


def all_commands(include_unavailable: bool = False):
    """
    Los comandos del registro.

    Por defecto solo los que este entorno admite. ``include_unavailable`` es
    para las pruebas y para revisar el registro entero, nunca para ejecutar.
    """
    if include_unavailable:
        return list(COMMANDS)

    return [command for command in COMMANDS if command.is_available]


def grouped_commands():
    """
    Los comandos agrupados por area, en el orden de ``AREA_CHOICES``.

    Antes se agrupaban por riesgo, que es la unica dimension que habia. Con la
    lista corta funcionaba; con esta ya no: nadie llega a la consola pensando
    "quiero algo que escriba", llega pensando "voy a desplegar" o "no llega el
    correo". El riesgo sigue estando en cada tarjeta -- y se puede filtrar por
    el -- pero como aviso, que es lo que es.
    """
    groups = {}

    for command in all_commands():
        groups.setdefault(command.area, []).append(command)

    return [
        (area, AREA_LABELS[area], groups[area])
        for area in sorted(groups, key=lambda a: AREA_ORDER.get(a, 99))
    ]


def risk_facets():
    """Los riesgos presentes, con cuantos comandos hay de cada uno."""
    counts = {}

    for command in all_commands():
        counts[command.risk] = counts.get(command.risk, 0) + 1

    return [
        (risk, RISK_LABELS[risk], counts[risk])
        for risk in sorted(counts, key=lambda r: RISK_ORDER.get(r, 99))
        if counts.get(risk)
    ]
