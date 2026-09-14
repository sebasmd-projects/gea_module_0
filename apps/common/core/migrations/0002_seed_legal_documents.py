"""
Siembra los cuatro documentos con el texto que ya estaba publicado.

El texto no va escrito aqui dentro sino en `core/legal_seed/*.html`, uno por
documento e idioma, por dos razones. Una practica: son 53 KB y una migracion de
53 KB no se revisa, se acepta. Y otra de fondo: **esos ficheros son el texto que
estaba publicado el dia del cambio**, extraido de las plantillas que lo servian,
asi que se pueden leer y comparar contra lo que habia sin descifrar una cadena
de Python escapada.

Entran como **borrador**, que es exactamente lo que decian las plantillas
(`1.0.0-borrador` en el ajuste que se retira, y el recuadro de aviso dentro de
cada una). Aprobar es un acto de alguien, con su nombre y su fecha; una
migracion no puede firmar por un abogado.
"""

from pathlib import Path

from django.db import migrations

from apps.common.utils.functions.generate_hash import sha256_hex

SEMILLA = Path(__file__).resolve().parent.parent / 'legal_seed'

#: `clave -> (nombre es, nombre en, orden)`. El orden es el del pie de pagina.
DOCUMENTOS = {
    'terms': ('Términos y condiciones', 'Terms and conditions', 1),
    'data_policy': (
        'Política de tratamiento de datos personales',
        'Personal data processing policy',
        2,
    ),
    'privacy': ('Aviso de privacidad', 'Privacy notice', 3),
    'cookies': ('Política de cookies', 'Cookie policy', 4),
}

PRIMERA_VERSION = '1.0.0'


def _leer(clave: str, idioma: str) -> str:
    ruta = SEMILLA / f'{clave}.{idioma}.html'
    return ruta.read_text(encoding='utf-8')


def sembrar(apps, schema_editor):
    Documento = apps.get_model('core', 'LegalDocumentModel')
    Version = apps.get_model('core', 'LegalDocumentVersionModel')

    for orden, (clave, (es_name, en_name, default_order)) in enumerate(
        DOCUMENTOS.items(), start=1
    ):
        documento, _creado = Documento.objects.get_or_create(
            key=clave,
            defaults={
                'es_name': es_name,
                'en_name': en_name,
                'default_order': default_order,
            },
        )

        # Idempotente a proposito: volver a aplicar la migracion sobre una base
        # que ya tiene textos aprobados no puede pisarlos.
        if documento.versions.exists():
            continue

        es_body = _leer(clave, 'es')
        en_body = _leer(clave, 'en')

        # El modelo historico de una migracion no trae los metodos del real,
        # asi que la huella se calcula aqui con la misma regla que
        # `LegalDocumentVersionModel.compute_hash()`. Si esa regla cambiara,
        # esta linea tiene que cambiar con ella --o la semilla naceria con una
        # huella que no cuadra con la que se recalcula al primer guardado.
        content_hash = sha256_hex(
            '\x1f'.join([clave, PRIMERA_VERSION, es_body, en_body])
        )

        Version.objects.create(
            document=documento,
            version=PRIMERA_VERSION,
            es_body=es_body,
            en_body=en_body,
            content_hash=content_hash,
            status='DRAFT',
            change_note_es=(
                'Primera versión en la plataforma. Es el mismo texto que ya '
                'estaba publicado, trasladado de las plantillas a un documento '
                'editable. Sigue siendo un borrador: no lo ha revisado un '
                'abogado.'
            ),
            change_note_en=(
                'First version on the platform. The same text that was already '
                'published, moved from the templates into an editable '
                'document. Still a draft: it has not been reviewed by counsel.'
            ),
            notify_users=False,
        )


def desmontar(apps, schema_editor):
    """
    Solo borra lo que la semilla puso, y solo si nadie lo ha tocado.

    Una version aprobada o con aceptaciones detras no se va con un
    `migrate` hacia atras: eso destruiria constancia de autorizaciones, que es
    lo que el articulo 9 de la Ley 1581 obliga a conservar.
    """
    Documento = apps.get_model('core', 'LegalDocumentModel')
    Version = apps.get_model('core', 'LegalDocumentVersionModel')

    intactas = Version.objects.filter(
        document__key__in=DOCUMENTOS,
        version=PRIMERA_VERSION,
        status='DRAFT',
        acceptances__isnull=True,
    )
    intactas.delete()

    Documento.objects.filter(
        key__in=DOCUMENTOS, versions__isnull=True
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(sembrar, desmontar),
    ]
