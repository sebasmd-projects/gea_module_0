"""
El dossier que se graba en un USB y se le entrega al titular.

Que es esto, y sobre todo que no es
-----------------------------------
Es una **copia fechada** para transportar y enseñar, no el original y no la
autoridad. En esta plataforma lo que acredita es la huella, el sello Ed25519 y
el anclaje; un soporte no puede añadir garantia que la cadena no de ya. Si el
USB acabara pareciendo «el original», habriamos fabricado un objeto que la
gente trata como prueba y no lo es — y eso es peor que no entregarlo.

De ahi tres decisiones:

- **Todo lo que se necesita para comprobarlo va dentro**, incluida la clave
  publica. El dossier tiene que sostenerse el dia que esta plataforma no
  conteste, que es justo el dia en que a alguien le hara falta.
- **Ningun secreto, ninguna credencial y ningun archivo interno.** Va la copia
  publica, nunca el `source_file`. Perder el USB tiene que ser perder una
  copia, no un incidente.
- **Sin ejecutables.** Los verificadores son tres guiones que usan lo que ya
  trae cada sistema (`Get-FileHash`, `shasum`, `sha256sum`). Un `.exe` sin
  firmar copiado de una memoria es exactamente lo que un antivirus debe
  bloquear, y acostumbrar a alguien a saltarse ese aviso es peor que no traer
  verificador. Firmar de verdad --Authenticode y notarizacion de Apple-- es
  una cadena de certificados y un tramite anual que hoy no existe aqui.

Lo que el guion comprueba y lo que no
-------------------------------------
Comprueba **el manifiesto**: que ningun archivo del USB haya cambiado. Eso se
puede hacer sin red y sin instalar nada, y es lo que responde a «¿me han
cambiado el PDF?».

Lo que **no** hace sin conexion es verificar el sello Ed25519 ni consultar el
bloque de Bitcoin: eso pide criptografia que Windows no trae por linea de
comandos y que `LibreSSL` de macOS no cubre igual. Para eso el dossier manda a
la pagina de verificacion, y lo dice en vez de fingir que no hace falta.

La distincion que hay que repetir
---------------------------------
**Subir el documento comprueba su integridad. Teclear el codigo publico no.**
El codigo solo busca una ficha; la comparacion byte a byte es la unica que
prueba que el archivo que tienes en la mano es el que se certifico. Va escrito
en el LEEME, en la salida de los tres guiones y en la propia pagina.
"""

import json
import zipfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from apps.common.utils.functions.generate_hash import sha256_hex

from ..models import AnchorTypeChoices
from .certification import public_base_url
from .record import build_certification_record, key_id, public_key_b64
from .usb_readiness import export_state

#: Los guiones, que viajan con el codigo y no se generan.
KIT = Path(__file__).resolve().parent.parent / 'usb_kit'

#: Las guias ya escritas «para enseñar fuera» (ver CLAUDE.md). Van dentro para
#: que el USB funcione sin conexion; su URL publica va ademas en el LEEME.
GUIAS = Path(settings.BASE_DIR) / 'docs'

GUIA_URLS = {
    'verificar-certificado.html':
        'https://propensionesabogados.com/verificar-certificado.html',
    'verify-certificate.html':
        'https://propensionesabogados.com/verify-certificate.html',
}

#: El nombre del manifiesto. No se incluye a si mismo, por razones obvias.
MANIFIESTO = 'manifiesto.sha256'


class NotReadyToExport(Exception):
    """El resumen no esta en verde. Lleva las razones dentro."""

    def __init__(self, checks):
        self.checks = checks
        super().__init__('El resumen no esta listo para exportar.')


def _verification_url():
    return public_base_url() + reverse(
        'certificates:input_document_verification_aegis')


def _anchor_url(summary):
    return public_base_url() + reverse(
        'certificates:summary_anchor', kwargs={'pk': summary.pk})


def _json_bytes(data) -> bytes:
    return json.dumps(
        data, indent=2, ensure_ascii=False, default=str
    ).encode('utf-8')


def _file_bytes(campo) -> bytes:
    """Lee un FileField completo. Devuelve b'' si no hay nada que leer."""
    if not campo:
        return b''

    campo.open('rb')

    try:
        return campo.read()
    finally:
        campo.close()


def _anchor_name(anchor, indice: int) -> str:
    """
    El nombre dice el tipo y la extension que le corresponde de verdad.

    `.tsr` es un token RFC 3161 en DER y `.ots` una prueba de OpenTimestamps:
    quien reciba el dossier tiene que poder dárselos a la herramienta correcta
    sin abrirlos para adivinar cuál es cuál.
    """
    if anchor.anchor_type == AnchorTypeChoices.OPENTIMESTAMPS:
        return f'anclaje/{indice:02d}-opentimestamps-bitcoin.ots'

    return f'anclaje/{indice:02d}-rfc3161-tsa.tsr'


def _readme(summary, nombres) -> bytes:
    """
    El LEEME. Corto, en los dos idiomas, y con la advertencia arriba.

    Va primero lo que no se puede malentender, no lo que queda bonito: quien
    abra esto en dos años lee tres lineas, no una pagina.
    """
    ahora = timezone.now().strftime('%d/%m/%Y %H:%M %Z')
    verificar = _verification_url()
    anclaje = _anchor_url(summary)

    lineas = [
        '=' * 70,
        f'  GEA · {summary.title}',
        f'  {summary.public_code or summary.uuid_prefix}',
        '=' * 70,
        '',
        'ESTO ES UNA COPIA FECHADA, NO EL ORIGINAL.',
        f'Generada el {ahora}.',
        '',
        'Lo que acredita un certificado de GEA no es este soporte: es la',
        'huella del archivo, el sello Ed25519 del registro y el anclaje en el',
        'tiempo. Todo eso viaja aqui dentro para que se pueda comprobar sin',
        'depender de nosotros.',
        '',
        '-' * 70,
        'COMO COMPROBARLO',
        '-' * 70,
        '',
        '1) Sin conexion, que nada de este USB haya cambiado:',
        '',
        '   Windows .... doble clic en  verificar-windows.cmd',
        '   macOS ...... doble clic en  verificar-macos.command',
        '   Linux ...... ejecutar       sh verificar-linux.sh',
        '',
        '   No hay que instalar nada: los tres usan lo que ya trae el',
        '   sistema. No hay ningun ejecutable a proposito.',
        '',
        '2) Con conexion, ademas el sello y la cadena de bloques:',
        '',
        f'   {verificar}',
        '',
        '   >>> SUBIR EL DOCUMENTO COMPRUEBA SU INTEGRIDAD.',
        '   >>> TECLEAR EL CODIGO PUBLICO NO: solo muestra la ficha.',
        '',
        '   Son dos cosas distintas. El codigo busca un registro; solo la',
        '   comparacion del archivo prueba que lo que tienes en la mano es',
        '   lo que se certifico.',
        '',
        '3) El estado del anclaje se actualiza solo, aqui:',
        '',
        f'   {anclaje}',
        '',
        '-' * 70,
        'QUE ACREDITA, Y QUE NO',
        '-' * 70,
        '',
        'Acredita INTEGRIDAD: que el archivo no ha cambiado desde que se',
        'registro, y que existia a mas tardar en una fecha.',
        '',
        'NO acredita VERACIDAD: no dice que sea cierto lo que el documento',
        'afirma, ni nada sobre la autenticidad, la titularidad o el valor de',
        'ningun activo que describa.',
        '',
        '-' * 70,
        'GUIAS',
        '-' * 70,
        '',
        'Dentro de guias/ estan las dos versiones, y tambien en linea:',
        '',
    ]

    for url in GUIA_URLS.values():
        lineas.append(f'   {url}')

    lineas += [
        '',
        '-' * 70,
        'CONTENIDO',
        '-' * 70,
        '',
    ]

    for ruta in sorted(nombres):
        lineas.append(f'   {ruta}')

    lineas += [
        '',
        '=' * 70,
        '  THIS IS A DATED COPY, NOT THE ORIGINAL.',
        '',
        '  UPLOADING THE DOCUMENT CHECKS ITS INTEGRITY.',
        '  TYPING THE PUBLIC CODE DOES NOT: it only shows the record.',
        '',
        '  It attests INTEGRITY, never the truth of what the document says.',
        f'  Verify at: {verificar}',
        '=' * 70,
        '',
    ]

    return '\n'.join(lineas).encode('utf-8')


def build_bundle(summary, *, requested_by=None) -> tuple:
    """
    Arma el dossier del resumen. Devuelve `(nombre_del_zip, bytes)`.

    Levanta `NotReadyToExport` si el resumen no esta en verde: exportar a
    medias reparte un dossier que parece prueba y no lo es, y quien lo reciba
    no tiene forma de notarlo.
    """
    # Una sola pasada: preguntar «¿se puede?» y «¿que falta?» por separado
    # verificaria el sello y leeria las pruebas de anclaje dos veces.
    estado = export_state(summary)

    if not estado.ok:
        raise NotReadyToExport(list(estado.checks))

    # `ruta dentro del zip -> bytes`. Se junta todo antes de escribir nada,
    # porque el manifiesto se calcula sobre el conjunto y tiene que cubrirlo
    # entero menos a si mismo.
    archivos = {}

    # --- el resumen ---
    documento = summary.summary_document
    archivos['resumen/resumen-aegis.pdf'] = _file_bytes(
        documento.public_copy_file)
    archivos['resumen/registro-certificacion.json'] = _json_bytes(
        build_certification_record(documento))

    # Verbatim: son los bytes exactos que se hashearon, no una
    # reconstruccion (invariante 17).
    archivos['resumen/master-payload.json'] = (
        summary.canonical_payload or '').encode('utf-8')

    for indice, anchor in enumerate(
        summary.anchors.all().order_by('created'), start=1
    ):
        proof = bytes(anchor.proof or b'')

        if proof:
            archivos[f'resumen/{_anchor_name(anchor, indice)}'] = proof

    # --- los miembros ---
    for member in summary.ordered_members():
        miembro = member.document
        base = f'documentos/{member.code}-{slugify(miembro.document_title)[:60]}'

        archivos[f'{base}.pdf'] = _file_bytes(miembro.public_copy_file)
        archivos[f'{base}-registro.json'] = _json_bytes(
            build_certification_record(miembro))

    # --- con que se comprueba ---
    archivos['claves/clave-publica-ed25519.json'] = _json_bytes({
        'algorithm': 'Ed25519' if public_key_b64() else None,
        'key_id': key_id(),
        'public_key': public_key_b64(),
        'encoding': 'base64 of the 32-byte raw Ed25519 public key',
        'verifies': (
            'El campo seal.signature de un registro de certificacion de GEA.'
        ),
        'note': (
            'Sin clave publica el registro se sello con HMAC y solo la propia '
            'plataforma puede verificarlo.'
        ) if not public_key_b64() else '',
    })

    for guion in sorted(KIT.iterdir()):
        if guion.is_file():
            archivos[guion.name] = guion.read_bytes()

    for nombre in GUIA_URLS:
        ruta = GUIAS / nombre

        if ruta.exists():
            archivos[f'guias/{nombre}'] = ruta.read_bytes()

    # --- lo que ata todo lo anterior ---
    #
    # El orden de estos tres no es de gusto. El LEEME enumera el contenido, asi
    # que se escribe cuando ya estan los archivos; `MANIFEST.json` lleva las
    # huellas, asi que va despues del LEEME para cubrirlo; y el manifiesto de
    # texto --el unico que comprueban los guiones-- va **el ultimo**, para que
    # cubra tambien `MANIFEST.json`. Al reves, el fichero que lleva todas las
    # huellas escritas seria justo el que nadie comprueba, que es donde mejor
    # le vendria a alguien tocar algo.
    archivos['LEEME.txt'] = _readme(
        summary,
        list(archivos) + ['LEEME.txt', 'MANIFEST.json', MANIFIESTO],
    )

    archivos['MANIFEST.json'] = _json_bytes({
        'schema': 'gea.usb-bundle/1',
        'summary': {
            'id': str(summary.pk),
            'title': summary.title,
            'public_code': summary.public_code,
            'master_hash': summary.master_hash,
        },
        'generated_at': timezone.now(),
        'generated_by': getattr(requested_by, 'username', None),
        'anchor_page': _anchor_url(summary),
        'verification_page': _verification_url(),
        'integrity_note': (
            'Subir el documento comprueba su integridad. Teclear el codigo '
            'publico no: solo muestra la ficha.'
        ),
        'files': {
            ruta: sha256_hex(contenido)
            for ruta, contenido in sorted(archivos.items())
        },
    })

    # El ultimo, y por eso cubre `MANIFEST.json`. No se cubre a si mismo, por
    # razones obvias: el guion lo lee para saber que comparar.
    manifiesto = '\n'.join(
        f'{sha256_hex(contenido)}  {ruta}'
        for ruta, contenido in sorted(archivos.items())
    ) + '\n'

    archivos[MANIFIESTO] = manifiesto.encode('utf-8')

    raiz = f'GEA-{summary.public_code or summary.uuid_prefix}'

    buffer = BytesIO()

    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for ruta, contenido in sorted(archivos.items()):
            info = zipfile.ZipInfo(f'{raiz}/{ruta}')

            # Los guiones salen ejecutables. Sin esto, en macOS y Linux hay
            # que acordarse de `chmod +x` antes de poder usarlos, que es
            # justo el paso donde alguien se rinde.
            ejecutable = ruta.endswith(('.sh', '.command'))
            info.external_attr = (0o755 if ejecutable else 0o644) << 16
            info.date_time = timezone.localtime().timetuple()[:6]

            zf.writestr(info, contenido)

    return f'{raiz}.zip', buffer.getvalue()
