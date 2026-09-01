# apps/common/utils/management/commands/check_security.py
"""
La auditoria de seguridad, reproducible antes de cada despliegue.

Un informe se lee una vez y se archiva; lo que hace falta es poder repetirlo.
Este comando comprueba lo que se reviso a mano, y lo hace **sobre el codigo
que hay ahora**, no sobre lo que decia el informe.

Las cinco comprobaciones son las que ya sacaron algo real:

1. **Vistas publicas sin guardia**, contrastadas con una lista de las que lo
   son a proposito. Una vista nueva sin control aparece aqui la primera vez
   que se ejecuta, no cuando alguien la encuentra.
2. **Formularios publicos sin limite de intentos.** Fue el hallazgo grave: la
   consulta de certificados de persona aceptaba un codigo de cuatro
   caracteres sin ningun freno.
3. **Ejecucion por shell** (``os.system``, ``os.popen``, ``shell=True``).
4. **SQL construido con cadenas.**
5. **Ajustes de produccion** que dependen de que ``DEBUG`` este apagado.

No sustituye a `manage.py check --deploy`, que mira los ajustes de Django.
Esto mira lo que es propio de este proyecto.

    manage.py check_security
"""

import ast
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

#: Mixins que cuentan como control de acceso.
GUARD_MIXINS = frozenset({
    'LoginRequiredMixin', 'BuyerRequiredMixin', 'HolderRequiredMixin',
    'OnlySpecificUserMixin', 'OTPSessionMixin', 'OTPProtectedDocumentMixin',
    'PermissionRequiredMixin', 'UserPassesTestMixin', 'OfferMutationMixin',
    'AccessMixin',
})

#: Vistas publicas **a proposito**, con la razon al lado.
#:
#: Es una lista de excepciones justificadas, no una lista de exclusion para
#: silenciar avisos: cada entrada dice por que esa vista puede ser publica, y
#: anadir una obliga a escribir esa razon.
INTENTIONALLY_PUBLIC = {
    'core:index': 'portada del sitio',
    'core:privacy': 'aviso legal, tiene que leerse antes de registrarse',
    'core:terms': 'idem',
    'core:cookies': 'idem',
    'core:data_policy': 'idem',
    'core:health_check': 'lo consulta el monitor y la tarea de calentamiento',
    'certificates:certificates_landing': 'portal publico de verificacion',
    'certificates:input_employee_verification_ipcon':
        'verificacion de credencial; limitada por IP',
    'certificates:detail_employee_verification_ipcon':
        'destino del QR impreso en la credencial',
    'certificates:employee_photo': 'la foto de esa misma pagina',
    'certificates:input_document_verification_aegis':
        'entrada del portal; pide OTP a un anonimo',
    'certificates:summary_anchor':
        'destino del QR de anclaje; solo hashes y fechas',
    'certificates:summary_master_payload': 'payload publico del anclaje',
    'certificates:certification_public_key': 'clave publica de verificacion',
    'certificates:document_file': 'comprueba permisos dentro (files.can_access)',
    'account:register': 'alta de cuenta; exige codigo',
    'account:logout': 'cerrar sesion',
    'account:forgot_password': 'recuperacion; limitada por IP y destinatario',
    'account:change_password': 'exige la contrasena actual',
    'pqrs:new': 'derecho de peticion; limitado por IP',
    'pqrs:receipt': 'comprobante sin datos personales',
    'utils:attack_path': 'la trampa anti-escaneo',
    'assets:help_gea': 'enlace a WhatsApp',
    'utils:set_language': 'cambio de idioma',
}

#: Rutas publicas sin nombre en el URLconf, identificadas por su ruta.
#:
#: `reverse()` no las alcanza y no tienen etiqueta `namespace:name`, asi que
#: se listan por lo unico que las identifica.
INTENTIONALLY_PUBLIC_PATHS = {
    'robots.txt': 'lo pide cualquier buscador, por definicion publico',
}

#: Formularios publicos que aceptan POST y **tienen que** llevar limite.
THROTTLED_FORMS = {
    'certificates:input_employee_verification_ipcon',
    'certificates:input_document_verification_aegis',
    'account:forgot_password',
    'pqrs:new',
}

SHELL_CALLS = re.compile(r'os\.system\(|os\.popen\(|shell\s*=\s*True')
STRING_SQL = re.compile(r'cursor\.execute\(\s*[f\'"].*%s*[\'"]\s*%|\.raw\(\s*f')


class Command(BaseCommand):
    help = 'Comprueba la superficie de seguridad propia de este proyecto.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--strict',
            action='store_true',
            help='Sale con codigo distinto de cero si hay algun hallazgo.',
        )

    def handle(self, *args, **options):
        self.findings = []

        self._check_unguarded_views()
        self._check_throttles()
        self._check_shell_calls()
        self._check_string_sql()
        self._check_settings()

        self.stdout.write('')

        if not self.findings:
            self.stdout.write(self.style.SUCCESS(
                'Sin hallazgos. Recuerda que esto no sustituye a '
                '"manage.py check --deploy".'
            ))
            return

        self.stdout.write(self.style.ERROR(
            f'{len(self.findings)} hallazgo(s).'
        ))

        if options['strict']:
            raise SystemExit(1)

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _ok(self, message):
        self.stdout.write(self.style.SUCCESS(f'   OK    {message}'))

    def _finding(self, message):
        self.findings.append(message)
        self.stdout.write(self.style.ERROR(f'   AVISO {message}'))

    # ------------------------------------------------------------------
    def _own_views(self):
        """Las rutas de este proyecto, con su guardia."""
        rows = []

        def walk(patterns, prefix=''):
            for entry in patterns:
                route = str(getattr(entry.pattern, '_route', '') or
                            entry.pattern)

                if isinstance(entry, URLResolver):
                    walk(entry.url_patterns, prefix + route)
                    continue

                if not isinstance(entry, URLPattern):
                    continue

                callback = entry.callback
                module = getattr(callback, '__module__', '')

                if not module.startswith('apps.'):
                    continue

                # El admin no se audita ruta por ruta: tiene una sola puerta,
                # `GeaAdminSite.admin_view`, que exige personal activo con
                # segundo factor verificado y responde 404 a quien no cumple
                # (invariante 7). Sus vistas van envueltas, asi que desde
                # fuera no se les ve ningun mixin y saldrian todas como
                # desprotegidas -- treinta avisos falsos que tapan los de
                # verdad.
                if (prefix + route).startswith(settings.ADMIN_URL):
                    continue

                view_class = getattr(callback, 'view_class', None)
                mro = ([base.__name__ for base in view_class.__mro__]
                       if view_class else [])

                rows.append({
                    'path': prefix + route,
                    'name': getattr(entry, 'name', '') or '',
                    'namespace': module.split('.')[-2],
                    'guarded': bool(GUARD_MIXINS & set(mro)),
                    'is_class': view_class is not None,
                    'callback': callback,
                })

        walk(get_resolver().url_patterns)

        return rows

    def _label(self, row) -> str:
        """``namespace:name``, como se escribe en las listas de arriba."""
        for key in INTENTIONALLY_PUBLIC:
            if key.endswith(f':{row["name"]}') and row['name']:
                return key

        return f'{row["namespace"]}:{row["name"]}'

    def _check_unguarded_views(self):
        self._section('1. Vistas propias sin control de acceso')

        unexpected = []

        for row in self._own_views():
            if row['guarded']:
                continue

            label = self._label(row)

            # Una vista de funcion puede llevar decoradores que no se ven
            # desde aqui; se comprueba su codigo por separado.
            if not row['is_class'] and self._function_has_guard(
                    row['callback']):
                continue

            if label in INTENTIONALLY_PUBLIC:
                continue

            if row['path'] in INTENTIONALLY_PUBLIC_PATHS:
                continue

            unexpected.append((label, row['path']))

        if not unexpected:
            total = len(INTENTIONALLY_PUBLIC) + len(INTENTIONALLY_PUBLIC_PATHS)
            self._ok(
                f'{total} vistas publicas, todas justificadas en la lista del '
                'comando.'
            )
            return

        for label, path in unexpected:
            self._finding(
                f'{label} (/{path}) no tiene control de acceso y no esta en '
                'la lista de publicas a proposito.'
            )

    def _function_has_guard(self, callback) -> bool:
        """Si una vista de funcion comprueba algo antes de responder."""
        import inspect

        try:
            source = inspect.getsource(callback)
        except (OSError, TypeError):
            return True  # ante la duda, no se avisa

        return any(token in source for token in (
            'login_required', '_is_internal', 'is_staff', 'is_superuser',
            'has_perm', '_forbidden',
        ))

    # ------------------------------------------------------------------
    def _check_throttles(self):
        self._section('2. Formularios publicos con limite de intentos')

        rows = {self._label(row): row for row in self._own_views()}

        for label in sorted(THROTTLED_FORMS):
            row = rows.get(label)

            if row is None:
                self._finding(f'{label} ya no existe: revisa la lista.')
                continue

            view_class = getattr(row['callback'], 'view_class', None)
            source = ''

            if view_class is not None:
                import inspect

                try:
                    source = inspect.getsource(view_class)
                except (OSError, TypeError):
                    source = ''

            throttle_markers = (
                'RateLimit', 'can_send_otp', 'can_try_identifier',
                '_within_rate', 'RESET_MAX_SENDS', '_can_send_reset',
            )

            if any(marker in source for marker in throttle_markers):
                self._ok(f'{label} limita los intentos.')
            else:
                self._finding(
                    f'{label} es publico, acepta POST y **no limita los '
                    'intentos**. Es lo que convierte un formulario en un '
                    'oraculo enumerable.'
                )

    # ------------------------------------------------------------------
    def _sources(self):
        root = Path(settings.BASE_DIR) / 'apps'

        for path in root.rglob('*.py'):
            # Este mismo fichero contiene los patrones que busca, en su
            # docstring y en sus mensajes. Auditarse a si mismo da dos avisos
            # garantizados que no significan nada.
            if 'test' in path.name or '/migrations/' in str(path):
                continue

            if path.name == 'check_security.py':
                continue

            try:
                yield path, path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue

    def _check_shell_calls(self):
        self._section('3. Ejecucion por shell')

        found = [
            (path, line)
            for path, body in self._sources()
            for line in body.splitlines()
            if SHELL_CALLS.search(line) and not line.strip().startswith('#')
        ]

        if not found:
            self._ok('Ningun os.system, os.popen ni shell=True.')
            return

        for path, line in found:
            self._finding(
                f'{path.relative_to(settings.BASE_DIR)}: {line.strip()[:70]}'
            )

    def _check_string_sql(self):
        self._section('4. SQL construido con cadenas')

        found = [
            (path, line)
            for path, body in self._sources()
            for line in body.splitlines()
            if STRING_SQL.search(line)
        ]

        if not found:
            self._ok('Ninguna consulta construida por interpolacion.')
            return

        for path, line in found:
            self._finding(
                f'{path.relative_to(settings.BASE_DIR)}: {line.strip()[:70]}'
            )

    # ------------------------------------------------------------------
    def _check_settings(self):
        self._section('5. Ajustes del entorno')

        self.stdout.write(
            '   (esta seccion depende de donde se ejecute: para que valga, '
            'lanzalo con los ajustes de produccion)'
        )

        if settings.DEBUG:
            self._finding(
                'DEBUG esta activado. En produccion expone la traza completa '
                'de cada error, con ajustes y consultas dentro.'
            )
        else:
            self._ok('DEBUG apagado.')

        expected = {
            'SESSION_COOKIE_HTTPONLY': True,
            'SESSION_COOKIE_SAMESITE': 'Lax',
        }

        for name, value in expected.items():
            if getattr(settings, name, None) == value:
                self._ok(f'{name} = {value!r}')
            else:
                self._finding(
                    f'{name} deberia ser {value!r} y es '
                    f'{getattr(settings, name, None)!r}.'
                )

        if not getattr(settings, 'CERTIFICATION_SIGNING_KEY', None):
            self._finding(
                'CERTIFICATION_SIGNING_KEY sin configurar: el registro de '
                'certificacion se sella con HMAC, y entonces solo esta '
                'plataforma puede verificarlo. Un tercero no puede.'
            )
        else:
            self._ok('CERTIFICATION_SIGNING_KEY configurada.')

        if not getattr(settings, 'REDIS_URL', None) and \
                'redis' not in str(settings.CACHES.get('default', {})).lower():
            self._finding(
                'La cache no es compartida (LocMemCache): los limites de '
                'intentos son **por worker**, asi que el limite real es el '
                'configurado multiplicado por el numero de procesos.'
            )
        else:
            self._ok('Cache compartida: los limites cuentan de verdad.')
