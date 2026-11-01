from django.db import migrations

SLUG = 'propensiones'


def create_propensiones(apps, schema_editor):
    """
    El unico emisor que existia, que estaba en ``GEA_EXTERNAL_ISSUERS``.

    Se crea con ``uses_server_key``: su clave es ``SERVER_KEY``, la misma que
    comparten pag y Vercel, y no se puede copiar a la base de datos sin dejar
    de ser la misma. Si la fila ya existe (otro despliegue, a mano) no se toca.
    """
    Issuer = apps.get_model('certificates', 'ExternalIssuerModel')

    Issuer.objects.get_or_create(
        slug=SLUG,
        defaults={
            'name': 'Propensiones Abogados',
            'kind': 'GROUP',
            'uses_server_key': True,
            'is_active': True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('certificates', '0011_externalissuermodel'),
    ]

    operations = [
        # Al deshacer, la tabla se borra con la 0011: no hay nada que hacer.
        migrations.RunPython(create_propensiones, migrations.RunPython.noop),
    ]
