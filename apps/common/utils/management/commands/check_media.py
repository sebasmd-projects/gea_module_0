# apps/common/utils/management/commands/check_media.py
"""
Diagnostico del almacenamiento de media.

``FileField`` guarda la ruta **relativa** a ``MEDIA_ROOT``. Si la variable
apunta a un sitio y los archivos estan en otro, no se pierde nada, pero Django
deja de encontrarlos: todas las descargas dan 404 y las subidas nuevas van al
directorio equivocado. Es un fallo silencioso —ni error ni traza— y por eso
merece un comando que lo diga a la cara.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

# Subarboles que NO deben servirse directamente por el servidor web.
PROTECTED_PREFIXES = (
    'certificates/',
    'passport_images/',
    'signature_images/',
)


def _check_fields():
    """Campos de archivo del proyecto y si son sensibles."""
    from django.apps import apps

    fields = []

    for model in apps.get_models():
        if not model._meta.app_label.startswith(('certificates', 'users',
                                                 'assets', 'buyers',
                                                 'video_masonry')):
            continue

        for field in model._meta.get_fields():
            if field.__class__.__name__ not in ('FileField', 'ImageField'):
                continue
            fields.append((model, field))

    return fields


class Command(BaseCommand):
    help = (
        'Comprueba que MEDIA_ROOT apunta a donde estan los archivos, que los '
        'referenciados desde la base de datos existen en disco, y que los '
        'subarboles sensibles no quedan servidos por el servidor web.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sample', type=int, default=25,
            help='Cuantos archivos por campo se comprueban en disco.'
        )
        parser.add_argument(
            '--find', metavar='RUTA', default='',
            help=(
                'Si falta algun archivo, lo busca por nombre bajo esta ruta '
                'y dice donde esta. Util despues de mover MEDIA_ROOT.'
            )
        )
        parser.add_argument(
            '--http', action='store_true',
            help=(
                'Comprueba de verdad, por HTTP contra PUBLIC_BASE_URL, que un '
                'archivo sensible responde 404 y no se sirve.'
            )
        )

    def handle(self, *args, **options):
        root = str(settings.MEDIA_ROOT)
        sample = options['sample']

        self.stdout.write(self.style.MIGRATE_HEADING('MEDIA_ROOT'))
        self.stdout.write(f'  {root}')
        self.stdout.write(f'  MEDIA_URL: {settings.MEDIA_URL}')
        self.stdout.write('')

        if not os.path.isdir(root):
            self.stdout.write(self.style.ERROR(
                '  El directorio NO existe. Django no encontrara ningun '
                'archivo y las subidas nuevas fallaran o crearan el arbol '
                'en el sitio equivocado.'
            ))
            self.stdout.write('')
        else:
            entries = sorted(
                name for name in os.listdir(root)
                if not name.startswith('.')
            )
            self.stdout.write(f'  Contenido: {", ".join(entries) or "(vacio)"}')
            self.stdout.write('')

        # ---- Archivos referenciados desde la base de datos ----
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Archivos referenciados en la base de datos'
        ))

        total_missing = 0
        total_checked = 0
        missing_all = []
        protected_missing = []

        for model, field in _check_fields():
            name = field.name
            label = f'{model._meta.label}.{name}'

            try:
                rows = (
                    model.objects
                    .exclude(**{f'{name}': ''})
                    .exclude(**{f'{name}__isnull': True})
                    .values_list(name, flat=True)[:sample]
                )
                rows = list(rows)
            except Exception as error:
                self.stdout.write(f'  {label}: no se pudo consultar ({error})')
                continue

            if not rows:
                continue

            missing = [
                value for value in rows
                if not os.path.isfile(os.path.join(root, str(value)))
            ]

            total_checked += len(rows)
            total_missing += len(missing)
            missing_all.extend(str(value) for value in missing)

            protected = any(
                str(value).startswith(PROTECTED_PREFIXES) for value in rows
            )
            mark = ' [sensible]' if protected else ''

            if protected:
                present = [
                    str(value) for value in rows
                    if os.path.isfile(os.path.join(root, str(value)))
                ]
                if present:
                    protected_missing.append(present[0])

            if missing:
                self.stdout.write(self.style.ERROR(
                    f'  {label}{mark}: {len(missing)}/{len(rows)} NO estan en disco'
                ))
                for value in missing[:3]:
                    self.stdout.write(f'      falta: {value}')
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'  {label}{mark}: {len(rows)}/{len(rows)} correctos'
                ))

        self.stdout.write('')

        if total_missing:
            self.stdout.write(self.style.ERROR(
                f'{total_missing} de {total_checked} archivos comprobados no '
                'aparecen bajo MEDIA_ROOT.'
            ))
            self.stdout.write(
                '  Los archivos no se han perdido: lo mas probable es que '
                'MEDIA_ROOT no apunte a donde estan. Corrige la variable, o '
                'mueve los archivos, pero que ambos coincidan.'
            )
        elif total_checked:
            self.stdout.write(self.style.SUCCESS(
                f'Los {total_checked} archivos comprobados estan donde '
                'MEDIA_ROOT dice.'
            ))

        # ---- Donde estan los que faltan ----
        search_root = options['find']

        if missing_all and search_root:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(
                f'Buscando los archivos que faltan bajo {search_root}'
            ))

            index = {}

            for base, _dirs, names in os.walk(search_root):
                for name in names:
                    index.setdefault(name, []).append(
                        os.path.join(base, name)
                    )

            for relative in missing_all:
                name = os.path.basename(relative)
                found = index.get(name, [])

                if found:
                    self.stdout.write(self.style.WARNING(
                        f'  {relative}'
                    ))
                    for path in found[:3]:
                        self.stdout.write(f'      esta en: {path}')
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  {relative}: no aparece por ningun lado. '
                        'Probablemente se borro; el registro sigue en la base '
                        'de datos apuntando a un archivo inexistente.'
                    ))
        elif missing_all:
            self.stdout.write('')
            self.stdout.write(
                '  Para saber donde estan, repite con:  '
                '--find /home/propensi'
            )

        # ---- Exposicion web ----
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(
            'Proteccion de los subarboles sensibles'
        ))

        htaccess = os.path.join(root, '.htaccess')

        if os.path.isfile(htaccess):
            self.stdout.write(self.style.SUCCESS(
                f'  Hay un .htaccess en MEDIA_ROOT: {htaccess}'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  NO hay .htaccess en MEDIA_ROOT ({htaccess}).'
            ))
            self.stdout.write(
                '  Sin el, el servidor web sigue entregando los PDF de '
                'certificacion y los documentos de identidad sin pasar por '
                'Django. Copia deploy/media.htaccess ahi.'
            )

        for prefix in PROTECTED_PREFIXES:
            path = os.path.join(root, prefix.rstrip('/'))

            if not os.path.isdir(path):
                continue

            inner = os.path.join(path, '.htaccess')

            if os.path.isfile(inner):
                self.stdout.write(self.style.SUCCESS(
                    f'  {prefix} protegido por su propio .htaccess'
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f'  {prefix} SIN .htaccess propio (solo depende del de la '
                    'raiz). Copia deploy/media-protected.htaccess dentro.'
                ))

        self.stdout.write('')

        sample_protected = (
            protected_missing[0] if protected_missing else None
        )

        base = str(getattr(settings, 'PUBLIC_BASE_URL', '') or '').rstrip('/')
        url = (
            f'{base}{settings.MEDIA_URL}{sample_protected}'
            if sample_protected else None
        )

        if not options['http'] or not url:
            self.stdout.write(
                'Comprobacion final, desde fuera (debe responder 404):'
            )
            self.stdout.write(
                f'  curl -I {url}' if url
                else f'  curl -I {base}{settings.MEDIA_URL}certificates/...'
            )
            if url:
                self.stdout.write('  o repite con --http para hacerlo aqui.')
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            'Comprobacion real por HTTP'
        ))
        self.stdout.write(f'  {url}')

        try:
            import requests

            response = requests.head(url, timeout=15, allow_redirects=False)
            status = response.status_code
        except Exception as error:
            self.stdout.write(self.style.WARNING(
                f'  No se pudo comprobar: {error}'
            ))
            return

        if status in (403, 404):
            self.stdout.write(self.style.SUCCESS(
                f'  {status}: el servidor web NO entrega el archivo. Correcto.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'  {status}: el servidor web SIGUE ENTREGANDO el archivo '
                'sensible sin pasar por Django. El bloqueo no esta activo.'
            ))
