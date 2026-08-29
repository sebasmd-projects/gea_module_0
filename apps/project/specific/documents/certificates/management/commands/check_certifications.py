# apps/project/specific/documents/certificates/management/commands/check_certifications.py
"""
Salud de los documentos certificados.

Comprueba dos cosas distintas, que fallan por motivos distintos:

1. **Que los tres archivos esten en disco.** Un registro puede seguir en la
   base de datos apuntando a un archivo borrado; la pagina de verificacion
   daria 404 sin explicar por que.

2. **Que las huellas almacenadas sigan correspondiendo a los archivos.** Es la
   promesa entera del producto: si el `document_hash` guardado ya no coincide
   con el PDF que hay en disco, o el archivo se sustituyo o se corrompio, y la
   certificacion esta mintiendo.

Por defecto solo diagnostica. ``--recertify`` rehace los que se pueden.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand

STATE_OK = 'OK'
STATE_RECERTIFIABLE = 'RECERTIFICABLE'
STATE_SOURCE_LOST = 'SIN ORIGINAL'
STATE_ORPHAN = 'HUERFANO'
STATE_DRAFT = 'SIN CERTIFICAR'
STATE_HASH_MISMATCH = 'HUELLA NO COINCIDE'


def _exists(file_field) -> bool:
    if not file_field:
        return False
    return os.path.isfile(
        os.path.join(str(settings.MEDIA_ROOT), str(file_field.name))
    )


def _hash_matches(file_field, expected: str):
    """
    Compara la huella guardada con la del archivo real.

    Returns:
        bool | None: ``None`` si no hay con que comparar.
    """
    from apps.project.specific.internal.code_gen.services.hashing import \
        sha256_hex

    if not expected or not _exists(file_field):
        return None

    try:
        with file_field.open('rb') as handle:
            return sha256_hex(handle) == expected
    except Exception:
        return None


def classify(document) -> dict:
    """Diagnostica un documento y dice que se puede hacer con el."""
    source = _exists(document.source_file)
    certified = _exists(document.document_file)
    public = _exists(document.public_copy_file)

    result = {
        'document': document,
        'source': source,
        'certified': certified,
        'public': public,
        'hash_certified': None,
        'hash_public': None,
        'state': STATE_OK,
        'action': '',
    }

    if not document.is_certified:
        result['state'] = STATE_DRAFT
        result['action'] = (
            'Sin certificar todavia. Subele el original y certificalo.'
            if not source else 'Listo para certificar.'
        )
        return result

    if not (source or certified or public):
        result['state'] = STATE_ORPHAN
        result['action'] = (
            'No queda ningun archivo. El registro apunta al vacio: vuelve a '
            'subir el original, o desactivalo para que deje de verificarse.'
        )
        return result

    if source and not (certified and public):
        result['state'] = STATE_RECERTIFIABLE
        result['action'] = (
            'Se puede recertificar desde el original. El estampado es '
            'reproducible -el codigo publico y la secuencia estan guardados-, '
            'asi que normalmente sale el MISMO PDF byte a byte y las copias ya '
            'repartidas siguen valiendo. El comando lo comprueba y avisa si no.'
        )
        return result

    if not source and (certified or public):
        result['state'] = STATE_SOURCE_LOST
        result['action'] = (
            'Falta el original archivado. El certificado sigue verificandose, '
            'pero ya no se puede recertificar: vuelve a subir el original.'
        )
        return result

    # Todo en su sitio: toca comprobar que las huellas siguen valiendo.
    result['hash_certified'] = _hash_matches(
        document.document_file, document.document_hash
    )
    result['hash_public'] = _hash_matches(
        document.public_copy_file, document.public_copy_hash
    )

    if result['hash_certified'] is False or result['hash_public'] is False:
        result['state'] = STATE_HASH_MISMATCH
        result['action'] = (
            'El archivo en disco NO es el que se certifico. O se sustituyo o '
            'se corrompio. No lo recertifiques sin averiguar por que.'
        )

    return result


class Command(BaseCommand):
    help = (
        'Comprueba que los tres archivos de cada documento certificado estan '
        'en disco y que sus huellas siguen coincidiendo. Solo diagnostica; '
        'usa --recertify para rehacer los que se puedan.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--recertify', action='store_true',
            help=(
                'Rehace los documentos marcados como RECERTIFICABLE a partir '
                'de su original, y comprueba si la huella se reproduce igual.'
            )
        )
        parser.add_argument(
            '--yes', action='store_true',
            help='No preguntar antes de recertificar.'
        )

    def handle(self, *args, **options):
        from apps.project.specific.documents.certificates.models import \
            DocumentVerificationModel

        documents = DocumentVerificationModel.objects.all().order_by('created')

        results = [classify(document) for document in documents]

        buckets = {}
        for result in results:
            buckets.setdefault(result['state'], []).append(result)

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'{len(results)} documento(s)'
        ))
        self.stdout.write('')

        styles = {
            STATE_OK: self.style.SUCCESS,
            STATE_DRAFT: self.style.WARNING,
            STATE_RECERTIFIABLE: self.style.WARNING,
            STATE_SOURCE_LOST: self.style.WARNING,
            STATE_ORPHAN: self.style.ERROR,
            STATE_HASH_MISMATCH: self.style.ERROR,
        }

        for state in (STATE_HASH_MISMATCH, STATE_ORPHAN, STATE_SOURCE_LOST,
                      STATE_RECERTIFIABLE, STATE_DRAFT, STATE_OK):
            items = buckets.get(state, [])

            if not items:
                continue

            style = styles.get(state, self.style.NOTICE)
            self.stdout.write(style(f'{state}  ({len(items)})'))

            for item in items:
                document = item['document']
                flags = ''.join([
                    'O' if item['source'] else '-',
                    'C' if item['certified'] else '-',
                    'P' if item['public'] else '-',
                ])
                self.stdout.write(
                    f'  [{flags}] {document.public_code or str(document.pk)[:8]}  '
                    f'{document.document_title[:52]}'
                )

            if items and items[0]['action']:
                self.stdout.write(f'      -> {items[0]["action"]}')

            self.stdout.write('')

        self.stdout.write('  Leyenda [OCP]: O original, C certificado, P copia publica')
        self.stdout.write('')

        recertifiable = buckets.get(STATE_RECERTIFIABLE, [])

        if not options['recertify']:
            if recertifiable:
                self.stdout.write(
                    f'{len(recertifiable)} se puede(n) recertificar. '
                    'Repite con --recertify para hacerlo.'
                )
            return

        if not recertifiable:
            self.stdout.write('No hay nada que recertificar.')
            return

        if not options['yes']:
            self.stdout.write(self.style.WARNING(
                'Se van a regenerar el PDF certificado y la copia publica a '
                'partir del original archivado. '
                'El estampado es reproducible, asi que lo normal es que salga '
                'el mismo archivo byte a byte y la huella no cambie. Si la '
                'certificacion original se hizo con otras opciones de codigo, '
                'la huella SI cambiaria y las copias ya repartidas dejarian de '
                'coincidir por huella exacta: el comando lo comprueba documento '
                'a documento y te lo dice.'
            ))
            answer = input('Escribe "si" para continuar: ').strip().lower()

            if answer not in ('si', 'sí'):
                self.stdout.write('Cancelado.')
                return

        from apps.project.specific.internal.code_gen.services.certification import (
            CertificationError, certify_document)

        done = 0
        changed = 0

        for item in recertifiable:
            document = item['document']
            previous_hash = document.document_hash
            previous_payload = document.code_payload

            try:
                certify_document(document)
            except CertificationError as error:
                self.stdout.write(self.style.ERROR(
                    f'  {document.public_code}: {error}'
                ))
                continue
            except Exception as error:
                self.stdout.write(self.style.ERROR(
                    f'  {document.public_code}: error inesperado ({error})'
                ))
                continue

            done += 1
            document.refresh_from_db()

            if previous_hash and document.document_hash != previous_hash:
                changed += 1
                self.stdout.write(self.style.WARNING(
                    f'  {document.public_code}: recertificado, pero la HUELLA '
                    f'CAMBIO ({previous_hash[:12]}... -> '
                    f'{document.document_hash[:12]}...). Las copias repartidas '
                    'antes ya no coinciden por huella exacta.'
                ))

                if previous_payload and document.code_payload != previous_payload:
                    self.stdout.write(
                        f'      el codigo tambien cambio: {previous_payload}'
                        f'  ->  {document.code_payload}'
                    )
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'  {document.public_code}: recertificado, huella '
                    'reproducida identica; las copias antiguas siguen valiendo.'
                ))

        self.stdout.write('')
        self.stdout.write(f'{done} documento(s) recertificado(s).')

        if changed:
            self.stdout.write(self.style.WARNING(
                f'{changed} cambiaron de huella. Reparte de nuevo la copia '
                'publica de esos, y regenera su registro de certificacion.'
            ))
