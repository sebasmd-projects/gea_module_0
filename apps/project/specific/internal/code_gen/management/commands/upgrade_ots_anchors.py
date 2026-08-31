# apps/project/specific/internal/code_gen/management/commands/upgrade_ots_anchors.py
"""
Madurar las pruebas de OpenTimestamps pendientes.

Una prueba nace comprometida pero sin bloque de Bitcoin; al cabo de unas horas
el calendario ya puede dar el camino completo. Nadie avisa cuando eso pasa
--OpenTimestamps no manda correos ni devuelve ningun enlace diferido--, asi que
la unica forma de enterarse es volver a preguntar. Esto es quien pregunta.

Corre cada 15 minutos. Cuando no hay nada pendiente **no hace nada y no sale a
la red**: una sola consulta a la base de datos y termina. Cuando la ultima caja
confirma, la tarea se queda efectivamente inactiva sola, sin que haya que
apagarla.

Que una prueba no este lista todavia no es un error: se deja para la vuelta
siguiente.
"""

from django.core.management.base import BaseCommand

from apps.project.specific.internal.code_gen.services.anchoring import \
    upgrade_pending_anchors


class Command(BaseCommand):
    help = (
        'Madura las pruebas de OpenTimestamps pendientes. Una prueba nace '
        'comprometida pero sin bloque de Bitcoin; unas horas despues el '
        'calendario ya puede dar el camino completo. Pensado para un cron '
        'cada 15 minutos: si no hay nada pendiente no sale a la red, y que '
        'una prueba no este lista todavia no es un error.'
    )

    def handle(self, *args, **options):
        pending = self._pending()

        # Sin pendientes no se toca la red. Es lo que hace que la tarea se
        # apague sola: mientras todo este confirmado, cada vuelta cuesta una
        # consulta y nada mas.
        if not pending.exists():
            self.stdout.write(
                'No hay anclajes pendientes: nada que madurar.'
            )
            return

        result = upgrade_pending_anchors(pending)

        self.stdout.write(
            f"Revisados: {result['checked']}  "
            f"Confirmados: {result['confirmed']}"
        )

        if result['confirmed']:
            self.stdout.write(self.style.SUCCESS(
                'Las paginas de anclaje se actualizan solas: no hay que '
                'reestampar ningun PDF.'
            ))
        else:
            self.stdout.write(
                'Ninguno ha entrado todavia en un bloque. Es lo normal '
                'durante las primeras horas; se vuelve a mirar en la '
                'siguiente vuelta.'
            )

    def _pending(self):
        from apps.project.specific.internal.code_gen.models import (
            AnchorStatusChoices, AnchorTypeChoices, CertificationAnchorModel)

        return CertificationAnchorModel.objects.filter(
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
            status=AnchorStatusChoices.PENDING,
        )
