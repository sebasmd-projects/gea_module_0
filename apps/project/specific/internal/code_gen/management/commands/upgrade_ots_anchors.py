# apps/project/specific/internal/code_gen/management/commands/upgrade_ots_anchors.py

from django.core.management.base import BaseCommand

from apps.project.specific.internal.code_gen.services.anchoring import \
    upgrade_pending_anchors


class Command(BaseCommand):
    help = (
        'Madura las pruebas de OpenTimestamps pendientes. Una prueba nace '
        'comprometida pero sin bloque de Bitcoin; entre 1 y 6 horas despues '
        'el calendario ya puede dar el camino completo. Pensado para un cron '
        'cada hora: que una prueba no este lista todavia no es un error.'
    )

    def handle(self, *args, **options):
        result = upgrade_pending_anchors()

        self.stdout.write(
            f"Revisados: {result['checked']}  "
            f"Confirmados: {result['confirmed']}"
        )

        if result['confirmed']:
            self.stdout.write(self.style.SUCCESS(
                'Las paginas de anclaje se actualizan solas: no hay que '
                'reestampar ningun PDF.'
            ))
