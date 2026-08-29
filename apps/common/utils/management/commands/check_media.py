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

            protected = any(
                str(value).startswith(PROTECTED_PREFIXES) for value in rows
            )
            mark = ' [sensible]' if protected else ''

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
            if os.path.isdir(path):
                self.stdout.write(f'  existe y debe estar bloqueado: {prefix}')

        self.stdout.write('')
        self.stdout.write(
            'Comprobacion final, desde fuera (debe responder 404):\n'
            f'  curl -I {settings.MEDIA_URL}certificates/documents/<archivo>.pdf'
        )
