from django.db import migrations

LAYOUT_NAME = 'AEGIS - default'

PLACEMENTS = [
    # kind, page_selector, anchor, offset_x, offset_y, width, height, order
    ('QR', 'LAST', 'BR', 28.0, 28.0, 84.0, 84.0, 1),
    ('BARCODE', 'LAST', 'BC', 0.0, 28.0, 216.0, 54.0, 2),
]


def create_default_layout(apps, schema_editor):
    StampLayoutModel = apps.get_model('code_gen', 'StampLayoutModel')
    StampPlacementModel = apps.get_model('code_gen', 'StampPlacementModel')

    if StampLayoutModel.objects.filter(name=LAYOUT_NAME).exists():
        return

    layout = StampLayoutModel.objects.create(
        name=LAYOUT_NAME,
        description=(
            'Posiciones por defecto para los certificados AEGIS: QR abajo a la '
            'derecha y codigo de barras centrado, ambos en la ultima pagina. '
            'Duplica este layout y ajusta las coordenadas para otras plantillas.'
        ),
        is_default=True,
    )

    for kind, selector, anchor, offset_x, offset_y, width, height, order in PLACEMENTS:
        StampPlacementModel.objects.create(
            layout=layout,
            kind=kind,
            page_selector=selector,
            anchor=anchor,
            offset_x=offset_x,
            offset_y=offset_y,
            width=width,
            height=height,
            opacity=1.0,
            default_order=order,
        )


def remove_default_layout(apps, schema_editor):
    StampLayoutModel = apps.get_model('code_gen', 'StampLayoutModel')
    StampLayoutModel.objects.filter(name=LAYOUT_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('code_gen', '0002_codesequencemodel_stamplayoutmodel_and_more'),
    ]

    operations = [
        migrations.RunPython(create_default_layout, remove_default_layout),
    ]
