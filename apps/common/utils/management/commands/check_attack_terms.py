# apps/common/utils/management/commands/check_attack_terms.py

from django.core.management.base import BaseCommand

from apps.common.utils.attack_patterns import (build_pattern, find_conflicts,
                                               normalize_terms)


class Command(BaseCommand):
    help = (
        'Comprueba que ningun termino de COMMON_ATTACK_TERMS secuestre una '
        'ruta legitima del proyecto. La trampa anti-escaneo va antes que '
        'varias apps en el URLconf, asi que una colision deja la ruta '
        'inaccesible y bloquea la IP del usuario.'
    )

    def handle(self, *args, **options):
        from django.conf import settings

        terms = normalize_terms(
            getattr(settings, 'COMMON_ATTACK_TERMS', [])
        )

        if not terms:
            self.stdout.write(self.style.WARNING(
                'COMMON_ATTACK_TERMS esta vacio: la trampa esta desactivada.'
            ))
            return

        pattern = build_pattern(terms)
        conflicts = find_conflicts(pattern)

        self.stdout.write(f'Terminos: {len(terms)}')
        self.stdout.write('')

        if not conflicts:
            self.stdout.write(self.style.SUCCESS(
                'Ninguna ruta propia colisiona con la trampa.'
            ))
            return

        self.stdout.write(self.style.ERROR(
            f'{len(conflicts)} ruta(s) del proyecto quedarian secuestradas:'
        ))
        self.stdout.write('')

        for conflict in conflicts:
            name = conflict['name'] or '(sin nombre)'
            self.stdout.write(f'  {conflict["path"]:60} {name}')

        self.stdout.write('')
        self.stdout.write(
            'Quita o afina el termino responsable en COMMON_ATTACK_TERMS.'
        )
