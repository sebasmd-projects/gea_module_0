# apps/project/specific/internal/code_gen/tests_check_anchoring.py
"""
Que el envio a la cadena de bloques se pueda comprobar, no solo lanzar.

Antes ``--stamp`` mandaba un hash de prueba, decia «aceptado» y tiraba la
prueba. Y «aceptado» es menos de lo que parece: el calendario solo promete
incluir el hash en su proximo arbol, el bloque de Bitcoin llega horas despues,
y **nadie avisa cuando llega** -- OpenTimestamps no manda correos ni devuelve
ningun enlace diferido. Sin guardar la prueba no habia a donde volver a mirar,
asi que la comprobacion se quedaba a medias: confirmaba que el camino de salida
estaba abierto y no que lo enviado hubiera cuajado.

Aqui se comprueba lo que cierra ese hueco: que la prueba se guarda, que
volviendo sobre ella se distingue «todavia sin bloque» de «en el bloque N», y
que la espera normal no se presenta como un fallo. Y por separado, que el
estado de los anclajes de verdad se lee de la base de datos, porque una prueba
lleva dias pendiente cuando nadie la esta madurando -- y eso no se arregla
volviendo a enviar.

Ninguna prueba de aqui sale a internet: los .ots se construyen a mano y las
conexiones a los calendarios se sustituyen.

    manage.py test apps.project.specific.internal.code_gen \\
        --settings=app_core.settings_test
"""

import base64
import hashlib
import tempfile
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.project.specific.documents.certificates.models import AegisSummaryModel

from .models import (AnchorStatusChoices, AnchorTypeChoices,
                     CertificationAnchorModel)
from .services import ots

CREATE_CONNECTION = (
    'apps.project.specific.internal.code_gen.management.commands.'
    'check_anchoring.socket.create_connection'
)
STAMP = 'apps.project.specific.internal.code_gen.services.ots.stamp'
UPGRADE = 'apps.project.specific.internal.code_gen.services.ots.upgrade'

DIGEST = hashlib.sha256(b'un hash de prueba').hexdigest()


def pending_proof(digest_hex=DIGEST, uri='https://alice.calendar.test'):
    """Una prueba recien enviada: hay compromiso, no hay bloque."""
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

    timestamp = Timestamp(bytes.fromhex(digest_hex))
    timestamp.attestations.add(PendingAttestation(uri))

    return ots.serialize(DetachedTimestampFile(OpSHA256(), timestamp))


def confirmed_proof(digest_hex=DIGEST, height=800000):
    """La misma prueba ya madura: el camino llega a una cabecera de bloque."""
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

    timestamp = Timestamp(bytes.fromhex(digest_hex))
    timestamp.attestations.add(BitcoinBlockHeaderAttestation(height))

    return ots.serialize(DetachedTimestampFile(OpSHA256(), timestamp))


def stamp_pending(digest_hex, **kwargs):
    """
    Un calendario que acepta: devuelve la promesa sobre *ese* hash.

    Se construye a partir del hash que recibe, y no de uno fijo, porque el
    comando se inventa el suyo en cada ejecucion y una prueba sobre otro hash
    no acredita nada -- que es justamente lo que comprueba una de las pruebas
    de aqui.
    """
    return {
        'proof': pending_proof(digest_hex),
        'calendars': ['https://alice.calendar.test'],
        'pending': True,
    }


class AnchoringCheckTestCase(TestCase):
    """Base: sin red, y con un sitio propio donde guardar las pruebas."""

    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)

        # Las dos primeras secciones abren TCP a los calendarios. Aqui no se
        # sale a internet: interesan las secciones siguientes.
        patched = mock.patch(CREATE_CONNECTION)
        self.create_connection = patched.start()
        self.addCleanup(patched.stop)

    def run_command(self, **options):
        out = StringIO()

        with override_settings(MEDIA_ROOT=self.media.name):
            call_command('check_anchoring', stdout=out,
                         stderr=out, no_color=True, **options)

        return out.getvalue()

    def saved_proofs(self):
        from pathlib import Path

        return sorted(Path(self.media.name).glob('ots_selftest/*.ots'))


class TestSendKeepsTheProof(AnchoringCheckTestCase):
    """Enviar sin guardar es no poder comprobar despues."""

    def test_the_test_send_leaves_the_proof_on_disk(self):
        sent = {}

        def remember(digest_hex, **kwargs):
            result = stamp_pending(digest_hex)
            sent['proof'] = result['proof']
            return result

        with mock.patch(STAMP, side_effect=remember):
            output = self.run_command(stamp=True)

        saved = self.saved_proofs()

        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), sent['proof'])
        self.assertIn(saved[0].name, output)

    def test_the_new_directory_is_not_left_open_to_the_web(self):
        """
        Cuelga de MEDIA_ROOT, donde el servidor web sirve por defecto y solo
        se bloquean tres subdirectorios por nombre. Uno nuevo nace publico, y
        crearlo sin cerrarlo seria dejarlo abierto sin decirlo.
        """
        with mock.patch(STAMP, side_effect=stamp_pending):
            self.run_command(stamp=True)

        guard = self.saved_proofs()[0].parent / '.htaccess'

        self.assertTrue(guard.exists())
        self.assertIn('denied', guard.read_text())

    def test_it_says_the_commitment_exists_and_the_block_does_not(self):
        """
        «Aceptado» no es «anclado», y la diferencia hay que decirla.

        Lo que devuelve el calendario es una promesa de incluirlo, y esa
        promesa es lo que se lee de la prueba recien recibida.
        """
        with mock.patch(STAMP, side_effect=stamp_pending):
            output = self.run_command(stamp=True)

        self.assertIn('Todavia sin bloque', output)
        self.assertIn('alice.calendar.test', output)

    def test_it_says_that_nobody_will_notify(self):
        """La expectativa importa tanto como el resultado."""
        with mock.patch(STAMP, side_effect=stamp_pending):
            output = self.run_command(stamp=True)

        self.assertIn('Nadie avisa', output)
        self.assertIn('--verify', output)

    def test_a_proof_for_another_hash_is_not_reported_as_waiting(self):
        """
        Una prueba que no cubre el hash enviado no es un compromiso pendiente:
        es una prueba que no sirve. Presentarla como «esperando bloque» seria
        mandar a esperar algo que no va a llegar nunca.
        """
        otro = hashlib.sha256(b'otro hash distinto').hexdigest()

        with mock.patch(STAMP, return_value={
            'proof': pending_proof(otro),
            'calendars': ['https://alice.calendar.test'],
            'pending': True,
        }):
            output = self.run_command(stamp=True)

        self.assertIn('no acredita este hash', output)
        self.assertNotIn('Todavia sin bloque', output)
        self.assertIn('NO puede anclar', output)

    def test_a_send_that_cannot_be_saved_is_still_recoverable(self):
        """
        Si el disco no deja escribir, el hash llego igual a los calendarios.

        Lo que se pierde es poder volver sobre el, asi que la prueba se imprime
        para que al menos quede en la traza de la consola de operaciones.
        """
        sent = {}

        def remember(digest_hex, **kwargs):
            result = stamp_pending(digest_hex)
            sent['proof'] = result['proof']
            return result

        with mock.patch(STAMP, side_effect=remember):
            with mock.patch('pathlib.Path.write_bytes',
                            side_effect=OSError('disco de solo lectura')):
                output = self.run_command(stamp=True)

        self.assertIn('No se pudo guardar', output)
        self.assertIn('disco de solo lectura', output)
        # La prueba entera, para que no se pierda con el fichero.
        self.assertIn(base64.b64encode(sent['proof']).decode(), output)


class TestGoingBackOverTheSend(AnchoringCheckTestCase):
    """Volver a preguntar es la unica forma de saber si cuajo."""

    def save(self, proof, *, name='20260830-120000-abcdef12.ots'):
        from pathlib import Path

        target = Path(self.media.name) / 'ots_selftest' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proof)

        return target

    def test_with_nothing_sent_it_says_so_instead_of_failing(self):
        output = self.run_command(verify=True)

        self.assertIn('No hay ningun envio de prueba guardado', output)

    def test_still_pending_is_reported_as_normal_waiting(self):
        """
        Que no haya bloque todavia no es un fallo, y decirlo como si lo fuera
        manda a buscar una averia que no existe.
        """
        self.save(pending_proof())

        with mock.patch(UPGRADE, return_value={
            'upgraded': False, 'proof': pending_proof(),
        }):
            output = self.run_command(verify=True)

        self.assertIn('Todavia sin bloque', output)
        self.assertIn('Es lo normal', output)
        self.assertNotIn('bloque de Bitcoin 8', output)

    def test_a_matured_proof_names_the_block_and_where_to_look(self):
        self.save(pending_proof())

        with mock.patch(UPGRADE, return_value={
            'upgraded': True, 'proof': confirmed_proof(height=812345),
        }):
            output = self.run_command(verify=True)

        self.assertIn('812345', output)
        self.assertIn('bloque de Bitcoin', output)
        # Comprobable fuera de la plataforma, que es de lo que se trata.
        self.assertIn('blockstream.info/block-height/812345', output)

    def test_maturing_rewrites_the_stored_proof(self):
        """
        Si no se guarda lo madurado, la proxima consulta vuelve a empezar.
        """
        target = self.save(pending_proof())
        matured = confirmed_proof()

        with mock.patch(UPGRADE, return_value={
            'upgraded': True, 'proof': matured,
        }):
            self.run_command(verify=True)

        self.assertEqual(target.read_bytes(), matured)

    def test_it_goes_back_over_the_last_one(self):
        """Con varios envios, el que interesa es el ultimo."""
        self.save(pending_proof(), name='20260101-000000-11111111.ots')
        recent = hashlib.sha256(b'el mas reciente').hexdigest()
        self.save(pending_proof(recent), name='20260830-120000-22222222.ots')

        with mock.patch(UPGRADE, return_value={
            'upgraded': False, 'proof': pending_proof(recent),
        }):
            output = self.run_command(verify=True)

        self.assertIn(recent, output)
        self.assertIn('22222222', output)

    def test_an_unreadable_proof_is_a_failure_and_says_which_file(self):
        self.save(b'esto no es una prueba .ots')

        output = self.run_command(verify=True)

        self.assertIn('No se pudo leer', output)
        self.assertIn('abcdef12', output)


class TestRealAnchorState(AnchoringCheckTestCase):
    """
    El estado de los resumenes de verdad, que es lo que de verdad importa.

    Un envio de prueba dice si el camino esta abierto. Esto dice si lo que se
    sello esta llegando a un bloque, y distingue la espera normal del anclaje
    olvidado -- que no se arregla volviendo a enviar, sino haciendo correr el
    cron que lo madura.
    """

    def anchor(self, *, status, age_hours):
        summary = AegisSummaryModel.objects.create(title='Caja')

        anchor = CertificationAnchorModel.objects.create(
            summary=summary,
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
            payload_hash=DIGEST,
            status=status,
            proof=pending_proof(),
        )

        # ``created`` lo pone auto_now_add: para envejecerlo hay que escribirlo.
        CertificationAnchorModel.objects.filter(pk=anchor.pk).update(
            created=timezone.now() - timedelta(hours=age_hours)
        )

        return anchor

    def test_with_no_anchors_it_says_nothing_has_been_anchored(self):
        output = self.run_command()

        self.assertIn('Todavia no se ha anclado ningun resumen', output)

    def test_a_recent_pending_anchor_is_normal_waiting(self):
        self.anchor(status=AnchorStatusChoices.PENDING, age_hours=2)

        output = self.run_command()

        self.assertIn('Esperando bloque: 1', output)
        self.assertIn('Es lo normal', output)

    def test_an_anchor_pending_for_days_points_at_the_cron(self):
        """
        Lo que hay que mirar entonces no es el envio, que salio bien, sino
        quien deberia estar madurando la prueba.
        """
        self.anchor(status=AnchorStatusChoices.PENDING, age_hours=72)

        output = self.run_command()

        self.assertIn('upgrade_ots_anchors', output)
        self.assertIn('El envio salio bien', output)

    def test_maturing_costs_nothing_when_there_is_nothing_pending(self):
        """
        La tarea corre cada 15 minutos, y eso solo sale barato si sin
        pendientes no sale a la red. Cuando la ultima caja confirma, la tarea
        se apaga sola: una consulta y termina.
        """
        self.anchor(status=AnchorStatusChoices.CONFIRMED, age_hours=10)

        out = StringIO()

        with mock.patch(UPGRADE) as upgrade:
            call_command('upgrade_ots_anchors', stdout=out, no_color=True)

        upgrade.assert_not_called()
        self.assertIn('No hay anclajes pendientes', out.getvalue())

    def test_maturing_runs_when_something_is_waiting(self):
        self.anchor(status=AnchorStatusChoices.PENDING, age_hours=3)

        out = StringIO()

        with mock.patch(UPGRADE, return_value={
            'upgraded': False, 'proof': pending_proof(),
        }) as upgrade:
            call_command('upgrade_ots_anchors', stdout=out, no_color=True)

        self.assertTrue(upgrade.called)
        self.assertIn('Revisados: 1', out.getvalue())

    def test_confirmed_and_pending_are_counted_apart(self):
        self.anchor(status=AnchorStatusChoices.CONFIRMED, age_hours=100)
        self.anchor(status=AnchorStatusChoices.CONFIRMED, age_hours=50)
        self.anchor(status=AnchorStatusChoices.PENDING, age_hours=1)

        output = self.run_command()

        self.assertIn('Confirmados en un bloque: 2', output)
        self.assertIn('Esperando bloque: 1', output)
