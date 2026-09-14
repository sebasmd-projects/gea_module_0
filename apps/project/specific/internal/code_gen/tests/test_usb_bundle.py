# apps/project/specific/internal/code_gen/tests/test_usb_bundle.py
"""
El dossier que se graba en un USB: la puerta primero, el contenido despues.

Lo que de verdad se prueba aqui es **que no salga**. Un USB se entrega y ya no
vuelve: no se actualiza, no avisa y no se puede retirar. Un dossier de un
resumen a medias --sellado pero sin bloque, o con un anclaje que ya no cubre el
master hash de ahora-- parece prueba, no lo es, y quien lo recibe no tiene
forma de notarlo, porque el soporte no dice nada. De ahi que la mitad de este
fichero sean las cinco maneras de que no se genere.

La otra mitad comprueba lo que lleva dentro cuando si sale, y sobre todo dos
cosas que no se ven mirando el ZIP por encima:

- **El manifiesto de texto es el ultimo**, asi que cubre tambien
  `MANIFEST.json`. Si fuera al reves, el fichero con todas las huellas escritas
  seria justo el que ningun guion comprueba.
- **No va ningun `source_file`.** Perder el USB tiene que ser perder una copia,
  no un incidente.

Nada de aqui sale a internet: una prueba de OpenTimestamps se lee parseandola.

    manage.py test apps.project.specific.internal.code_gen.tests.test_usb_bundle \\
        --settings=app_core.settings_test
"""

import json
import os
import shutil
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.common.utils.testing import posix_only_because

from ..models import (AnchorStatusChoices, AnchorTypeChoices,
                      CertificationAnchorModel)
from ..services.usb_bundle import MANIFIESTO, NotReadyToExport, build_bundle
from ..services.usb_readiness import can_export, export_checks, export_state
from .test_check_anchoring import confirmed_proof, pending_proof
from .test_summary_issue import SummaryIssueTestCase, a_pdf


def checks_by_key(summary) -> dict:
    return {check.key: check for check in export_checks(summary)}


class ReadySummaryTestCase(SummaryIssueTestCase):
    """
    Un resumen en verde de verdad, armado por el camino normal.

    Se sella y se emite **pasando por la vista**, no escribiendo los campos a
    mano: lo que se quiere probar es que un resumen normal y corriente sale, y
    un resumen fabricado a mano puede estar en un estado que la plataforma no
    produce nunca. El unico atajo es el anclaje, porque enviarlo de verdad
    seria salir a la red.
    """

    def setUp(self):
        super().setUp()

        # El miembro necesita su copia publica en disco: es lo que se copia al
        # dossier, y el original nunca sale de aqui.
        self.member.public_copy_file.save(
            'miembro-copia.pdf',
            SimpleUploadedFile('miembro-copia.pdf', a_pdf()),
            save=True,
        )

        self.seal()
        response = self.issue()
        self.assertEqual(response.status_code, 200, response.content)

        self.summary.refresh_from_db()

        self.anchor = self.an_anchor()

    def an_anchor(self, *, status=AnchorStatusChoices.CONFIRMED,
                  proof=None, payload_hash=None):
        """
        Un anclaje de OpenTimestamps, sin salir a la red.

        La prueba se construye sobre el hash que se le pase, y no sobre uno
        fijo, porque media prueba de aqui consiste justamente en que un anclaje
        de otro hash no valga.
        """
        digest = payload_hash or self.summary.master_hash

        return CertificationAnchorModel.objects.create(
            summary=self.summary,
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
            payload_hash=digest,
            status=status,
            proof=confirmed_proof(digest) if proof is None else proof,
        )

    def unzip(self, contenido: bytes) -> dict:
        """`ruta sin la carpeta raiz -> bytes`."""
        with zipfile.ZipFile(BytesIO(contenido)) as zf:
            return {
                name.split('/', 1)[1]: zf.read(name)
                for name in zf.namelist()
                if '/' in name
            }


class TestTheGateIsTheWholePoint(ReadySummaryTestCase):
    """Las cinco, una a una. Cada una sola basta para que no salga nada."""

    def test_a_summary_that_is_green_does_export(self):
        """
        El caso de control. Sin el, las cinco pruebas de abajo pasarian igual
        con una puerta que no dejara salir nada nunca.
        """
        self.assertTrue(can_export(self.summary), export_checks(self.summary))

        nombre, contenido = build_bundle(self.summary)

        self.assertTrue(nombre.endswith('.zip'))
        self.assertTrue(contenido)

    def test_a_withdrawn_summary_is_not_handed_out(self):
        self.summary.is_active = False

        self.assertFalse(checks_by_key(self.summary)['active'].ok)
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_without_a_seal_there_is_nothing_to_attest(self):
        self.summary.master_hash = ''

        check = checks_by_key(self.summary)['sealed']

        self.assertFalse(check.ok)
        self.assertIn('seal it first', str(check.detail).lower())
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_a_seal_that_no_longer_matches_its_members_blocks_the_export(self):
        """
        El caso que hace falta que exista la comprobacion.

        Un resumen resellado despues de cambiar de miembros tiene master hash,
        tiene papel y tiene anclaje: por cualquier señal suelta esta en verde.
        Lo que ya no cuadra es el sello con lo que el resumen contiene hoy, y
        ese es el dossier que parece prueba sin serlo.
        """
        self.summary.canonical_payload = json.dumps({'members': []})

        check = checks_by_key(self.summary)['sealed']

        self.assertFalse(check.ok)
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_without_the_issued_paper_there_is_nothing_to_show(self):
        self.summary.summary_document = None

        check = checks_by_key(self.summary)['issued']

        self.assertFalse(check.ok)
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_a_pending_opentimestamps_proof_is_not_a_block(self):
        """
        Hay compromiso, no hay bloque: todavia no acredita fecha. Dejarlo
        pasar seria entregar un dossier que dice «en la cadena» y no lo esta.
        """
        self.anchor.status = AnchorStatusChoices.PENDING
        self.anchor.proof = pending_proof(self.summary.master_hash)
        self.anchor.save()

        check = checks_by_key(self.summary)['chain']

        self.assertFalse(check.ok)
        self.assertIn('pending', str(check.detail).lower())
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_never_sent_to_the_calendar_says_where_to_send_it(self):
        self.anchor.delete()

        check = checks_by_key(self.summary)['chain']

        self.assertFalse(check.ok)
        self.assertIn('never been sent', str(check.detail).lower())

    def test_a_timestamping_authority_alone_is_not_the_blockchain(self):
        """
        Una TSA vale, pero es otra cosa: caduca con su certificado. «En la
        cadena de bloques» significa un bloque.
        """
        self.anchor.anchor_type = AnchorTypeChoices.RFC3161
        self.anchor.save()

        self.assertFalse(checks_by_key(self.summary)['chain'].ok)

    def test_an_anchor_covering_an_older_master_hash_does_not_count(self):
        self.anchor.delete()
        self.an_anchor(payload_hash='f' * 64, proof=confirmed_proof('f' * 64))

        self.assertFalse(checks_by_key(self.summary)['chain'].ok)

    def test_a_failed_anchor_is_an_error_even_with_another_one_confirmed(self):
        CertificationAnchorModel.objects.create(
            summary=self.summary,
            anchor_type=AnchorTypeChoices.RFC3161,
            payload_hash=self.summary.master_hash,
            status=AnchorStatusChoices.FAILED,
        )

        check = checks_by_key(self.summary)['clean']

        self.assertFalse(check.ok)
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_a_member_without_its_public_copy_is_not_silently_skipped(self):
        """
        Lo que no esta en disco no se puede copiar, y descubrirlo a mitad del
        ZIP deja un PDF de cero bytes dentro sin decirlo.
        """
        self.member.public_copy_file.delete(save=True)

        check = checks_by_key(self.summary)['clean']

        self.assertFalse(check.ok)
        self.assertIn('AEGIS-1', str(check.detail))
        self.assertRaises(NotReadyToExport, build_bundle, self.summary)

    def test_a_public_copy_whose_file_is_gone_counts_as_missing(self):
        """
        El campo tiene nombre y el fichero no esta. `bool(FieldFile)` dice que
        si, y es el caso en que el dossier saldria con un PDF vacio.
        """
        self.member.public_copy_file.storage.delete(
            self.member.public_copy_file.name)

        check = checks_by_key(self.summary)['clean']

        self.assertFalse(check.ok)
        self.assertIn('not on disk', str(check.detail).lower())

    def test_the_five_are_always_reported_whole(self):
        """
        Cumplidas y no cumplidas. Arreglar una y descubrir la siguiente, de una
        en una, es la peor forma de enterarse de que falta algo.
        """
        self.summary.is_active = False

        estado = export_state(self.summary)

        self.assertEqual(len(estado.checks), 5)
        self.assertFalse(estado.ok)

        # Una sola causa, y las otras cuatro siguen saliendo en verde: la
        # lista es el estado del resumen, no el primer fallo que se encuentre.
        self.assertEqual(
            [check.key for check in estado.blocking], ['active'])

    def test_one_broken_thing_can_light_up_more_than_one_condition(self):
        """
        Borrar el sello apaga tambien «en la cadena», porque un anclaje que
        cubra el master hash de ahora no puede existir si no hay master hash.
        No es duplicar el aviso: son dos cosas que hay que rehacer, y la
        segunda no se arregla sola al arreglar la primera.
        """
        self.summary.master_hash = ''

        self.assertEqual(
            {check.key for check in export_state(self.summary).blocking},
            {'sealed', 'chain'},
        )


class TestWhatTravelsInside(ReadySummaryTestCase):

    def setUp(self):
        super().setUp()

        _, contenido = build_bundle(self.summary, requested_by=self.staff)
        self.archivos = self.unzip(contenido)

    def test_the_summary_its_record_and_its_payload_verbatim(self):
        self.assertTrue(self.archivos['resumen/resumen-aegis.pdf'])
        self.assertTrue(self.archivos['resumen/registro-certificacion.json'])

        # Verbatim: los bytes exactos que se hashearon, no una reconstruccion
        # (invariante 17). Rehacerlos aqui seria probar el mismo codigo consigo
        # mismo.
        self.assertEqual(
            self.archivos['resumen/master-payload.json'],
            self.summary.canonical_payload.encode('utf-8'),
        )

    def test_the_proof_travels_with_the_extension_of_what_it_is(self):
        pruebas = [
            ruta for ruta in self.archivos if ruta.startswith('resumen/anclaje/')
        ]

        self.assertEqual(len(pruebas), 1)
        self.assertTrue(pruebas[0].endswith('.ots'), pruebas)
        self.assertEqual(self.archivos[pruebas[0]], bytes(self.anchor.proof))

    def test_each_member_goes_with_its_code_and_its_record(self):
        self.assertIn('AEGIS-1', ' '.join(self.archivos))

        miembro = [
            ruta for ruta in self.archivos
            if ruta.startswith('documentos/AEGIS-1') and ruta.endswith('.pdf')
        ]

        self.assertEqual(len(miembro), 1)
        self.assertTrue(self.archivos[miembro[0]])

    def test_the_public_key_travels_so_it_can_be_checked_without_us(self):
        """
        El dossier tiene que sostenerse el dia que esta plataforma no conteste,
        que es justo el dia en que a alguien le hara falta.
        """
        clave = json.loads(self.archivos['claves/clave-publica-ed25519.json'])

        self.assertIn('public_key', clave)
        self.assertIn('key_id', clave)

    def test_the_three_scripts_go_and_no_executable_does(self):
        """
        Un `.exe` sin firmar copiado de una memoria es exactamente lo que un
        antivirus debe bloquear, y acostumbrar a alguien a saltarse ese aviso
        es peor que no traer verificador.
        """
        for guion in ('verificar-windows.cmd', 'verificar-macos.command',
                      'verificar-linux.sh'):
            self.assertIn(guion, self.archivos)

        self.assertFalse([
            ruta for ruta in self.archivos
            if ruta.endswith(('.exe', '.msi', '.dmg', '.app', '.bin'))
        ])

    def test_the_guides_travel_so_it_works_with_no_connection(self):
        self.assertIn('guias/verificar-certificado.html', self.archivos)
        self.assertIn('guias/verify-certificate.html', self.archivos)

    def test_no_source_file_ever_leaves(self):
        """
        Perder el USB tiene que ser perder una copia, no un incidente. Va la
        copia publica con su marca de agua, nunca el original sin codigos.
        """
        original = self.summary.summary_document.source_file.read()

        for ruta, contenido in self.archivos.items():
            if ruta.endswith('.pdf'):
                self.assertNotEqual(contenido, original, ruta)


class TestTheManifestCoversEverything(ReadySummaryTestCase):

    def setUp(self):
        super().setUp()

        _, contenido = build_bundle(self.summary)
        self.archivos = self.unzip(contenido)

        self.manifiesto = {
            linea.split('  ', 1)[1]: linea.split('  ', 1)[0]
            for linea in self.archivos[MANIFIESTO].decode('utf-8').splitlines()
            if linea.strip()
        }

    def test_every_file_is_listed_except_the_manifest_itself(self):
        esperado = set(self.archivos) - {MANIFIESTO}

        self.assertEqual(set(self.manifiesto), esperado)

    def test_the_manifest_covers_the_json_manifest_too(self):
        """
        El orden importa: si `MANIFEST.json` se escribiera despues, el fichero
        que lleva todas las huellas escritas seria justo el que ningun guion
        comprueba, que es donde mejor le vendria a alguien tocar algo.
        """
        self.assertIn('MANIFEST.json', self.manifiesto)

    def test_the_hashes_are_the_ones_of_what_travels(self):
        import hashlib

        for ruta, digest in self.manifiesto.items():
            self.assertEqual(
                hashlib.sha256(self.archivos[ruta]).hexdigest(), digest, ruta)

    def test_a_tampered_file_stops_matching_its_line(self):
        """La prueba de que el manifiesto sirve para algo."""
        import hashlib

        alterado = self.archivos['LEEME.txt'] + b'\nuna linea de mas'

        self.assertNotEqual(
            hashlib.sha256(alterado).hexdigest(), self.manifiesto['LEEME.txt'])

    def test_the_readme_says_which_of_the_two_checks_integrity(self):
        """
        La confusion que este dossier existe para no crear: el codigo publico
        busca una ficha, y solo subir el archivo lo compara.
        """
        leeme = self.archivos['LEEME.txt'].decode('utf-8')

        self.assertIn('SUBIR EL DOCUMENTO COMPRUEBA SU INTEGRIDAD', leeme)
        self.assertIn('TECLEAR EL CODIGO PUBLICO NO', leeme)
        self.assertIn('NO acredita VERACIDAD', leeme)

    def test_the_readme_lists_what_actually_travels(self):
        """
        Incluidos los dos manifiestos y el propio LEEME, que se escriben
        despues que el resto y se quedaban fuera de la lista.
        """
        leeme = self.archivos['LEEME.txt'].decode('utf-8')

        for ruta in self.archivos:
            self.assertIn(ruta, leeme)


class TestTheViewIsTheSameGate(ReadySummaryTestCase):
    """
    La puerta esta en el servicio, no en la plantilla: esconder el boton no es
    un control, porque basta con teclear la URL.
    """

    def export_url(self):
        # `self.url` ya lo usa la base: es la de emitir el documento.
        return reverse('code_gen:summary_usb_export', args=[self.summary.pk])

    def test_green_downloads_the_zip(self):
        response = self.client.get(self.export_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/zip')
        self.assertIn('attachment', response['Content-Disposition'])

    def test_typing_the_url_of_a_summary_that_is_not_green_downloads_nothing(self):
        self.anchor.delete()

        response = self.client.get(self.export_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn(str(self.summary.pk), response['Location'])

    def test_a_withdrawn_summary_is_a_404_and_not_a_redirect(self):
        self.summary.is_active = False
        self.summary.save()

        self.assertEqual(self.client.get(self.export_url()).status_code, 404)

    def test_it_is_not_open_to_anyone_who_is_logged_in(self):
        self.client.logout()

        response = self.client.get(self.export_url())

        self.assertNotEqual(response.status_code, 200)


class TestTheActionIsWhereTheSummariesAre(ReadySummaryTestCase):
    """
    El historico agrupado, que es de donde se exporta.

    Un boton que no esta en la pagina no lo pulsa nadie, por mucho que la URL
    funcione. Y cuando no se puede, lo que tiene que haber ahi no es un boton
    apagado --que invita a pulsarlo y a preguntarse por que no responde-- sino
    la lista de lo que falta.
    """

    def setUp(self):
        super().setUp()

        # Un codigo colgando del documento del resumen, para que la rama exista
        # en el arbol: sin ningun codigo emitido la pagina no tiene nada que
        # agrupar.
        from ..models import CodeRegistrationModel

        CodeRegistrationModel.objects.create(
            reference='RESUMEN',
            document=self.summary.summary_document,
            code_information='PAYLOAD-RESUMEN',
        )

        self.history = reverse('code_gen:code_history')

    def page(self) -> str:
        response = self.client.get(self.history)

        self.assertEqual(response.status_code, 200)

        return response.content.decode('utf-8')

    def test_a_green_summary_offers_the_export(self):
        html = self.page()

        self.assertIn(
            reverse('code_gen:summary_usb_export', args=[self.summary.pk]),
            html,
        )
        self.assertIn('Export to USB', html)

    def test_a_summary_that_is_not_green_offers_the_list_instead(self):
        self.anchor.delete()

        html = self.page()

        self.assertNotIn(
            reverse('code_gen:summary_usb_export', args=[self.summary.pk]),
            html,
        )
        self.assertIn('Not ready to export', html)

        # La condicion que falta, y las cuatro que no: quien lo lee ve el
        # conjunto, no el primer fallo.
        self.assertIn('Confirmed on the blockchain', html)
        self.assertIn('Sealed, and the seal still matches', html)

    def test_the_flat_view_does_not_pay_for_checks_it_cannot_show(self):
        """
        En la lista no hay ramas de resumen, asi que no hay donde poner la
        accion y no se comprueba nada: verificar el sello y leer las pruebas de
        anclaje de cada resumen del historial para no enseñarlo seria pagar por
        lo que no se ve.
        """
        response = self.client.get(self.history, {'view': 'flat'})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Export to USB', response.content.decode('utf-8'))


class TestTheVerifierActuallyVerifies(ReadySummaryTestCase):
    """
    El guion, ejecutado de verdad sobre un dossier de verdad.

    Es la unica pieza de todo esto que corre en la maquina de otro, meses
    despues y sin nosotros delante, asi que no vale con leerla: se extrae el ZIP
    y se ejecuta. Solo en POSIX, porque `sh` es lo que no hay en Windows -- el
    `.cmd` es el equivalente de alli y no se puede ejecutar aqui.

    Lo que se comprueba es que el **codigo de salida** diga lo mismo que la
    pantalla. Un guion que escribe «NO use este dossier» y sale con 0 le cuenta
    lo contrario a quien lo llame desde otro sitio.
    """

    def a_bundle_on_disk(self):
        import subprocess
        import tempfile

        carpeta = tempfile.mkdtemp(prefix='gea_usb_')
        self.addCleanup(shutil.rmtree, carpeta, True)

        _, contenido = build_bundle(self.summary)

        with zipfile.ZipFile(BytesIO(contenido)) as zf:
            zf.extractall(carpeta)

        raiz = os.path.join(carpeta, os.listdir(carpeta)[0])

        return raiz, subprocess

    @posix_only_because('el guion se ejecuta con sh, que Windows no trae')
    def test_an_untouched_bundle_comes_back_clean(self):
        raiz, subprocess = self.a_bundle_on_disk()

        hecho = subprocess.run(
            ['sh', 'verificar-linux.sh'], cwd=raiz,
            capture_output=True, text=True,
        )

        self.assertEqual(hecho.returncode, 0, hecho.stdout)
        self.assertIn('coinciden con el manifiesto', hecho.stdout)
        self.assertNotIn('ALTERADO', hecho.stdout)

    @posix_only_because('el guion se ejecuta con sh, que Windows no trae')
    def test_a_changed_file_is_reported_and_the_exit_code_says_so(self):
        raiz, subprocess = self.a_bundle_on_disk()

        with open(os.path.join(raiz, 'LEEME.txt'), 'ab') as fh:
            fh.write(b'una linea de mas')

        hecho = subprocess.run(
            ['sh', 'verificar-linux.sh'], cwd=raiz,
            capture_output=True, text=True,
        )

        self.assertEqual(hecho.returncode, 1, hecho.stdout)
        self.assertIn('ALTERADO', hecho.stdout)
        self.assertIn('NO use este dossier', hecho.stdout)

    @posix_only_because('el guion se ejecuta con sh, que Windows no trae')
    def test_a_missing_file_is_not_the_same_as_a_changed_one(self):
        """
        Se distinguen porque se arreglan distinto: uno es una copia incompleta,
        el otro un archivo tocado.
        """
        raiz, subprocess = self.a_bundle_on_disk()

        os.remove(os.path.join(raiz, 'guias', 'verify-certificate.html'))

        hecho = subprocess.run(
            ['sh', 'verificar-linux.sh'], cwd=raiz,
            capture_output=True, text=True,
        )

        self.assertEqual(hecho.returncode, 1, hecho.stdout)
        self.assertIn('FALTA', hecho.stdout)

    def test_the_scripts_travel_marked_executable(self):
        """
        Sin el bit hay que acordarse de `chmod +x` antes de poder usarlos, y ese
        es justo el paso donde alguien se rinde -- en macOS, donde el recorrido
        es doble clic en el `.command`, directamente no hay recorrido.

        Se mira el **modo guardado en el archivo**, no el del fichero extraido,
        y no por comodidad: `zipfile.extractall()` de Python ignora
        `external_attr` a proposito, asi que extraer con Python nunca deja el
        bit puesto por mucho que el ZIP lo lleve. Quien recibe el dossier no
        extrae con Python --usa `unzip`, el Finder o el explorador, que si lo
        respetan--, de modo que comprobarlo tras extraer probaria una limitacion
        de la biblioteca en vez de lo que se quiere fijar.
        """
        _, contenido = build_bundle(self.summary)

        with zipfile.ZipFile(BytesIO(contenido)) as zf:
            modos = {
                info.filename.split('/', 1)[1]: info.external_attr >> 16
                for info in zf.infolist()
            }

        for guion in ('verificar-linux.sh', 'verificar-macos.command'):
            self.assertTrue(modos[guion] & 0o100, guion)

        # Y lo demas no: un PDF ejecutable no tiene sentido y hace ruido en
        # cualquier revision del soporte.
        self.assertFalse(modos['LEEME.txt'] & 0o111)
