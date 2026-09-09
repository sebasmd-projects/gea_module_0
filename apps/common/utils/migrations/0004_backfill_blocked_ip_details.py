# apps/common/utils/migrations/0004_backfill_blocked_ip_details.py
"""
Rellena las columnas nuevas de los bloqueos ya existentes.

Sin esto, las filas de antes de la migracion anterior salen con cero intentos,
cero rutas y sin fechas de deteccion -- justo las que llevan mas tiempo en la
tabla y mas dicen sobre quien esta escaneando. La informacion ya esta, dentro
de ``session_info``; lo que faltaba era sacarla.

Se recorre en lotes y sin instanciar el modelo real: en una migracion hay que
usar el modelo historico, porque el de hoy puede tener campos que en este
punto de la historia todavia no existen.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    IPBlockedModel = apps.get_model('utils', 'IPBlockedModel')

    # La clasificacion de red **si** se importa de verdad: es una funcion pura
    # sobre una tabla de prefijos, no toca la base de datos y no depende del
    # estado del modelo. Si el modulo no estuviera, la migracion sigue.
    try:
        from apps.common.utils.netintel import describe
    except Exception:  # noqa: BLE001
        def describe(_ip):
            return {'network_owner': None, 'is_datacenter': False,
                    'country': None}

    updated = []

    for entry in IPBlockedModel.objects.all().iterator(chunk_size=500):
        info = entry.session_info or {}

        entry.attempt_count = int(info.get('attempt_count') or 0)
        entry.unique_paths = len(set(info.get('paths') or []))

        # `created` es lo mas parecido a la primera deteccion que hay
        # guardado, y `updated` a la ultima: hasta ahora era el unico rastro
        # temporal de la fila.
        entry.first_seen = entry.created
        entry.last_seen = entry.updated or entry.created

        entry.user_agent = (info.get('user_agent') or '')[:500]

        intel = describe(entry.current_ip)
        entry.network_owner = (intel['network_owner'] or '')[:100]
        entry.is_datacenter = intel['is_datacenter']
        entry.country = (intel['country'] or '')[:2]

        updated.append(entry)

        if len(updated) >= 500:
            _flush(IPBlockedModel, updated)
            updated = []

    _flush(IPBlockedModel, updated)


def _flush(model, rows):
    if not rows:
        return

    model.objects.bulk_update(
        rows,
        ['attempt_count', 'unique_paths', 'first_seen', 'last_seen',
         'user_agent', 'network_owner', 'is_datacenter', 'country'],
    )


def noop(apps, schema_editor):
    """
    Volver atras no borra nada.

    Las columnas se van enteras con la migracion anterior si se revierte, y
    ``session_info`` --de donde salio todo esto-- no se ha tocado.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('utils', '0003_blocked_ip_details'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
