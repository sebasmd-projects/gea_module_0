# apps/common/utils/migrations/0002_cap_legacy_ip_blocks.py
"""
Recorta los bloqueos que se emitieron antes de que hubiera techo.

El bloqueo por IP crecia sumando un intervalo en cada peticion, sin limite:
un escaner insistente lo empujaba a anos vista. Hay filas en produccion con
``blocked_until`` en 2027 -- una de ellas por siete intentos.

``MAX_BLOCK`` puso el techo en 24 horas, pero solo para los bloqueos que se
crean o se alargan a partir de entonces. Las filas viejas se quedaron como
estaban, y mientras sigan ahi cualquier usuario legitimo que herede una de
esas IP --y una IP domestica cambia de manos-- se queda fuera durante anos
sin que nadie sepa por que.

Esto no borra nada: la fila, su historial y sus rutas siguen ahi para
diagnosticar. Solo se acorta la fecha de expiracion a lo que la politica
actual habria puesto como maximo.
"""

from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def cap_legacy_blocks(apps, schema_editor):
    IPBlockedModel = apps.get_model('utils', 'IPBlockedModel')

    ceiling = timezone.now() + timedelta(hours=24)

    IPBlockedModel.objects.filter(
        blocked_until__gt=ceiling
    ).update(blocked_until=ceiling)


def noop(apps, schema_editor):
    """
    Sin vuelta atras.

    Restaurar las fechas originales exigiria haberlas guardado, y guardarlas
    solo serviria para volver a dejar gente fuera durante anos.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('utils', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(cap_legacy_blocks, noop),
    ]
