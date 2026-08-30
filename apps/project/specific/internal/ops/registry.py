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
"""

from dataclasses import dataclass, field
from typing import List, Optional

from django.utils.translation import gettext_lazy as _

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
    options: List[Option] = field(default_factory=list)
    #: Segundos antes de cortarlo. La peticion HTTP espera, no hay cola.
    timeout: int = 120
    #: Texto de aviso extra que se pinta en rojo antes de ejecutar.
    warning: str = ''

    @property
    def needs_confirmation(self) -> bool:
        return self.risk == RISK_DANGEROUS

    def option(self, name: str) -> Optional[Option]:
        for option in self.options:
            if option.name == name:
                return option
        return None


COMMANDS = (
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
        timeout=300,
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
            'decides whether the fix is «uv sync» or a call to the provider.'
        ),
        example=_('When sealing reports that sending to the blockchain failed.'),
        risk=RISK_READ_ONLY,
        timeout=120,
        options=[
            Option(
                flag='--stamp',
                label=_('Send a test hash'),
                kind=KIND_FLAG,
                help=_(
                    'Sends a made-up hash for real, to test the whole path. '
                    'Harmless: it belongs to no document.'
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
        timeout=60,
        warning=_(
            'It resets the public OTP rate limits. Do not run it while '
            'someone is hammering the verification page.'
        ),
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
        timeout=180,
        warning=_('This sends real email to the configured recipients.'),
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


def get_command(name: str) -> Optional[Command]:
    """El comando permitido con ese nombre, o ``None`` si no esta en la lista."""
    return COMMANDS_BY_NAME.get(name)


def grouped_commands():
    """Los comandos agrupados por riesgo, de menos a mas."""
    groups = {}

    for command in COMMANDS:
        groups.setdefault(command.risk, []).append(command)

    return [
        (risk, RISK_LABELS[risk], groups.get(risk, []))
        for risk in sorted(groups, key=lambda r: RISK_ORDER.get(r, 99))
    ]
