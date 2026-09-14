# apps/project/specific/internal/code_gen/management/commands/upgrade_ots_anchors.py
"""
Madurar las pruebas de OpenTimestamps pendientes.

Una prueba nace comprometida pero sin bloque de Bitcoin; al cabo de unas horas
el calendario ya puede dar el camino completo. Nadie avisa cuando eso pasa
--OpenTimestamps no manda correos ni devuelve ningun enlace diferido--, asi que
la unica forma de enterarse es volver a preguntar. Esto es quien pregunta.

Corre cada 15 minutos. Cuando no hay nada pendiente **no hace nada y no sale a
la red**: dos consultas a la base de datos y termina. Cuando el ultimo resumen
confirma, la tarea se queda efectivamente inactiva sola, sin que haya que
apagarla.

Que una prueba no este lista todavia no es un error: se deja para la vuelta
siguiente.

Hace ademas un segundo trabajo, y por eso son dos consultas y no una: **poner
fecha** a los anclajes que confirmaron sin ella. Una prueba madura acreditando
una *altura de bloque*, no una hora; la hora esta en la cabecera de ese bloque y
hay que ir a pedirla (`services/bitcoin_time.py`, que exige que dos exploradores
independientes coincidan). Si esa peticion falla, el anclaje se confirma igual y
se queda sin fecha — y sin este repaso nadie volveria a por ella, porque ya no
esta pendiente. Era justo lo que dejaba la columna «Attested time» vacia con el
anclaje confirmado y el bloque escrito al lado.
"""

from django.core.management.base import BaseCommand

from apps.project.specific.internal.code_gen.services.anchoring import (
    anchors_without_block_time, fill_missing_block_times,
    upgrade_pending_anchors)


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
        undated = anchors_without_block_time()

        # Sin nada que hacer no se toca la red. Es lo que hace que la tarea se
        # apague sola: mientras todo este confirmado y fechado, cada vuelta
        # cuesta dos consultas y nada mas.
        hay_pendientes = pending.exists()
        hay_sin_fecha = undated.exists()

        if not hay_pendientes and not hay_sin_fecha:
            self.stdout.write(
                'No hay anclajes pendientes ni sin fecha: nada que hacer.'
            )
            return

        fechados = 0

        if hay_pendientes:
            result = upgrade_pending_anchors(pending)
            fechados += result['dated']

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

        # Los que confirmaron en vueltas anteriores y se quedaron sin fecha.
        # Se recalcula la consulta porque la de arriba acaba de dejar algunos
        # ya fechados.
        rezagados = anchors_without_block_time()

        if rezagados.exists():
            recogidos = fill_missing_block_times(rezagados)
            fechados += recogidos['dated']

            if recogidos['dated'] < recogidos['checked']:
                self.stdout.write(
                    f"Sin fecha todavia: "
                    f"{recogidos['checked'] - recogidos['dated']}. El anclaje "
                    f"es valido igual; se reintenta en la siguiente vuelta."
                )

        if fechados:
            self.stdout.write(self.style.SUCCESS(
                f'Fecha del bloque establecida en {fechados} anclaje(s).'
            ))

    def _pending(self):
        from apps.project.specific.internal.code_gen.models import (
            AnchorStatusChoices, AnchorTypeChoices, CertificationAnchorModel)

        return CertificationAnchorModel.objects.filter(
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
            status=AnchorStatusChoices.PENDING,
        )
