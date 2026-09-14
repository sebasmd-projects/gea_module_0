# apps/project/specific/internal/code_gen/tests/test_anchor_proof.py
"""
Poder comprobar un anclaje sin nosotros: el fichero de la prueba y la fecha.

Dos cosas que faltaban, y las dos apuntaban al mismo sitio.

**La prueba no se podia descargar de ninguna parte.** Vivia en la base de datos
y solo salia dentro del dossier del USB. La pagina decia «confirmado en el
bloque 964899» y eso, sin el fichero, es *esta plataforma diciendolo* — que es
exactamente lo que un anclaje existe para no tener que ser. Lo que acredita no
es la frase: es el camino desde el master hash hasta la transaccion que lo metio
en la cadena, y ese camino es un fichero que cualquiera tiene que poder bajarse.

**Y la fecha salia vacia con el anclaje confirmado.** Una prueba de
OpenTimestamps madura acreditando una **altura de bloque**, no una hora; la hora
esta en la cabecera de ese bloque y nadie iba a buscarla. `stamped_at` solo se
rellenaba en la rama de la TSA (`anchoring.py`), asi que la columna «Attested
time» enseñaba un guion al lado de un bloque de Bitcoin escrito.

Nada de aqui sale a internet: la busqueda de la hora del bloque se sustituye.

    manage.py test apps.project.specific.internal.code_gen.tests.test_anchor_proof \\
        --settings=app_core.settings_test
"""

from datetime import datetime, timezone
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.project.specific.documents.certificates.models import AegisSummaryModel

from ..models import (AnchorStatusChoices, AnchorTypeChoices,
                      CertificationAnchorModel)
from ..services import anchoring
from ..services.bitcoin_time import block_time
from .test_check_anchoring import DIGEST, confirmed_proof, pending_proof

BLOQUE = 964899

#: 31/08/2026 15:10 UTC — la cabecera del bloque 964899 de verdad.
HORA_DEL_BLOQUE = datetime(2026, 8, 31, 15, 10, 56, tzinfo=timezone.utc)

EXPLORERS = 'apps.project.specific.internal.code_gen.services.bitcoin_time.' \
            '_timestamp_from'


class AnchorTestCase(TestCase):
    """Un resumen sellado con un anclaje de OpenTimestamps confirmado."""

    def setUp(self):
        self.summary = AegisSummaryModel.objects.create(title='Resumen')
        AegisSummaryModel.objects.filter(pk=self.summary.pk).update(
            master_hash=DIGEST)
        self.summary.refresh_from_db()

        self.anchor = self.an_anchor()

    def an_anchor(self, **extra):
        campos = {
            'summary': self.summary,
            'anchor_type': AnchorTypeChoices.OPENTIMESTAMPS,
            'payload_hash': DIGEST,
            'status': AnchorStatusChoices.CONFIRMED,
            'proof': confirmed_proof(DIGEST, height=BLOQUE),
            'serial': str(BLOQUE),
        }
        campos.update(extra)

        return CertificationAnchorModel.objects.create(**campos)

    def proof_url(self, anchor=None):
        return reverse(
            'certificates:summary_anchor_proof',
            args=[self.summary.pk, (anchor or self.anchor).pk],
        )


class TestTheProofCanBeDownloaded(AnchorTestCase):
    """
    Sin el fichero no hay nada que comprobar, y entonces el anclaje es una
    frase nuestra en una pagina nuestra.
    """

    def test_anyone_can_download_it_without_logging_in(self):
        """
        Publica a proposito, como la pagina de la que cuelga. Cerrarla romperia
        lo unico que hace util a un anclaje.
        """
        response = self.client.get(self.proof_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, bytes(self.anchor.proof))

    def test_it_comes_down_as_a_file_with_the_right_extension(self):
        """
        `.ots` y `.tsr` van a herramientas distintas: quien lo recibe tiene que
        poder darselo a la correcta sin abrirlo para adivinar cual es.
        """
        response = self.client.get(self.proof_url())

        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('.ots', response['Content-Disposition'])

    def test_a_timestamping_authority_proof_comes_down_as_tsr(self):
        tsa = self.an_anchor(
            anchor_type=AnchorTypeChoices.RFC3161, proof=b'token DER de prueba')

        response = self.client.get(self.proof_url(tsa))

        self.assertEqual(response.status_code, 200)
        self.assertIn('.tsr', response['Content-Disposition'])
        self.assertEqual(response['Content-Type'], 'application/timestamp-reply')

    def test_an_anchor_of_another_summary_is_a_404(self):
        """
        Se pide por su resumen para que la URL diga de que es la prueba. Un id
        de otro resumen tiene que ser un 404, no una descarga desconcertante.
        """
        otro = AegisSummaryModel.objects.create(title='Otro resumen')

        url = reverse(
            'certificates:summary_anchor_proof',
            args=[otro.pk, self.anchor.pk],
        )

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_an_anchor_with_no_proof_offers_nothing(self):
        """
        Un anclaje fallido existe sin prueba. Devolver un fichero vacio seria
        peor que un 404: parece una prueba y no lo es.
        """
        vacio = self.an_anchor(
            status=AnchorStatusChoices.FAILED, proof=None, serial='')

        self.assertEqual(
            self.client.get(self.proof_url(vacio)).status_code, 404)

    def test_the_downloaded_proof_still_says_what_it_said(self):
        """
        Que baje byte a byte lo guardado. Si se transformara por el camino, la
        herramienta de quien lo recibe no lo reconoceria y el anclaje pareceria
        roto.
        """
        from ..services import ots

        response = self.client.get(self.proof_url())
        state = ots.inspect(response.content, DIGEST)

        self.assertTrue(state['valid'])
        self.assertTrue(state['confirmed'])
        self.assertEqual(state['bitcoin_block'], BLOQUE)


class TestTheDateIsResolvedFromTheBlock(AnchorTestCase):
    """
    La prueba dice una altura; la fecha esta en la cabecera de ese bloque.
    """

    def test_the_date_is_empty_until_someone_goes_and_gets_it(self):
        """El estado de partida, que es el que se veia en produccion."""
        self.assertIsNone(self.anchor.stamped_at)

        state = anchoring.summary_anchor_state(self.summary)

        self.assertTrue(state['anchored'])
        self.assertIsNone(state['attested_since'])

    def test_the_cron_fills_it_in(self):
        with mock.patch(EXPLORERS, return_value=int(HORA_DEL_BLOQUE.timestamp())):
            result = anchoring.fill_missing_block_times()

        self.assertEqual(result['dated'], 1)

        self.anchor.refresh_from_db()
        self.assertEqual(self.anchor.stamped_at, HORA_DEL_BLOQUE)

    def test_once_filled_the_page_shows_it(self):
        with mock.patch(EXPLORERS, return_value=int(HORA_DEL_BLOQUE.timestamp())):
            anchoring.fill_missing_block_times()

        state = anchoring.summary_anchor_state(self.summary)

        self.assertEqual(state['attested_since'], HORA_DEL_BLOQUE)

    def test_an_anchor_already_dated_is_not_looked_up_again(self):
        """
        Cuesta dos peticiones de red. Repetirlas en cada vuelta del cron seria
        pagarlas para siempre por un dato que no cambia nunca: la cabecera de un
        bloque de Bitcoin no se reescribe.
        """
        self.anchor.stamped_at = HORA_DEL_BLOQUE
        self.anchor.save(update_fields=['stamped_at'])

        with mock.patch(EXPLORERS) as fuente:
            result = anchoring.fill_missing_block_times()

        self.assertEqual(result['checked'], 0)
        fuente.assert_not_called()

    def test_a_pending_anchor_has_no_block_to_ask_about(self):
        self.anchor.delete()
        self.an_anchor(
            status=AnchorStatusChoices.PENDING,
            proof=pending_proof(DIGEST),
            serial='',
        )

        with mock.patch(EXPLORERS) as fuente:
            anchoring.fill_missing_block_times()

        fuente.assert_not_called()


class TestOneExplorerIsNotEnough(AnchorTestCase):
    """
    La pagina donde acaba esta fecha dice «un tercero acredito la fecha; no es
    esta plataforma diciendolo». Una fecha sacada de un solo explorador **si**
    es esta plataforma diciendolo, con un intermediario en medio.
    """

    def test_two_sources_that_agree_give_the_date(self):
        with mock.patch(EXPLORERS, return_value=1788189056):
            self.assertEqual(block_time(BLOQUE), HORA_DEL_BLOQUE)

    def test_one_source_alone_is_not_enough(self):
        """
        El segundo contesta `None` --no contesto, o no supo--. Con una sola
        respuesta no hay nada que corroborar, asi que no se escribe fecha.
        """
        with mock.patch(EXPLORERS, side_effect=[1788189056, None]):
            self.assertIsNone(block_time(BLOQUE))

    def test_two_sources_that_disagree_give_nothing(self):
        """
        El caso por el que existe todo esto: alguien esta equivocado sobre un
        bloque de Bitcoin, y esa fecha iba a ir en un certificado. Ante la duda
        no se escribe nada, que es distinto de escribir cualquiera de las dos.
        """
        with mock.patch(EXPLORERS, side_effect=[1788189056, 1788100000]):
            self.assertIsNone(block_time(BLOQUE))

    def test_nobody_answering_is_not_an_error(self):
        """
        Se reintenta en la siguiente vuelta del cron. Un explorador caido no
        puede tumbar el anclaje, que es valido con o sin fecha.
        """
        with mock.patch(EXPLORERS, return_value=None):
            self.assertIsNone(block_time(BLOQUE))

        self.anchor.refresh_from_db()
        self.assertEqual(self.anchor.status, AnchorStatusChoices.CONFIRMED)

    def test_a_failed_lookup_leaves_it_for_the_next_round(self):
        """
        Lo que hace falta que exista `anchors_without_block_time()`: sin el, un
        corte de red de un minuto dejaria la columna vacia para siempre, porque
        el anclaje ya no esta pendiente y el cron no lo miraria nunca mas.
        """
        with mock.patch(EXPLORERS, return_value=None):
            anchoring.fill_missing_block_times()

        self.assertIn(
            self.anchor, list(anchoring.anchors_without_block_time()))

        with mock.patch(EXPLORERS, return_value=int(HORA_DEL_BLOQUE.timestamp())):
            result = anchoring.fill_missing_block_times()

        self.assertEqual(result['dated'], 1)


class TestTheCronStaysQuietWithNothingToDo(AnchorTestCase):
    """
    La propiedad que tenia el comando y no se puede perder: sin nada pendiente
    no sale a la red, y por eso la tarea se apaga sola.
    """

    def run_command(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command('upgrade_ots_anchors', stdout=out)

        return out.getvalue()

    def test_with_everything_confirmed_and_dated_it_touches_nothing(self):
        self.anchor.stamped_at = HORA_DEL_BLOQUE
        self.anchor.save(update_fields=['stamped_at'])

        with mock.patch(EXPLORERS) as fuente:
            salida = self.run_command()

        fuente.assert_not_called()
        self.assertIn('nada que hacer', salida)

    def test_a_confirmed_anchor_with_no_date_is_work_to_do(self):
        """
        Antes no lo era, y esa es la razon de que la columna llevara meses
        vacia: el anclaje confirmaba, la fecha fallaba o no se pedia, y nadie
        volvia.
        """
        with mock.patch(EXPLORERS, return_value=int(HORA_DEL_BLOQUE.timestamp())):
            salida = self.run_command()

        self.assertNotIn('nada que hacer', salida)

        self.anchor.refresh_from_db()
        self.assertEqual(self.anchor.stamped_at, HORA_DEL_BLOQUE)


class TestThePagesOfferIt(AnchorTestCase):
    """El botón, en las dos páginas por las que se llega."""

    def test_the_anchor_page_offers_the_download_and_links_the_block(self):
        response = self.client.get(
            reverse('certificates:summary_anchor', args=[self.summary.pk]))

        html = response.content.decode('utf-8')

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.proof_url(), html)

        # El enlace al explorador, no solo la cifra suelta: el numero ya salia
        # dentro del texto de estado («Committed to Bitcoin block 964899») y
        # comprobar eso dejaria pasar que la columna no se pintara.
        self.assertIn(f'/{BLOQUE}"', html)

    def test_the_anchor_page_says_how_to_check_it_without_us(self):
        """
        El fichero sin instrucciones es un fichero que nadie sabe para que
        sirve, y entonces el boton no arregla lo que venia a arreglar.
        """
        response = self.client.get(
            reverse('certificates:summary_anchor', args=[self.summary.pk]))

        html = response.content.decode('utf-8')

        self.assertIn('ots info', html)
        self.assertIn('merkle root', html)

    def test_the_anchor_page_does_not_leave_a_dangling_utc(self):
        """
        Sin fecha, la cabecera decia «existed since:  UTC». Un «UTC» detras de
        un hueco se lee como que el anclaje no acredita nada.
        """
        self.assertIsNone(self.anchor.stamped_at)

        response = self.client.get(
            reverse('certificates:summary_anchor', args=[self.summary.pk]))

        html = response.content.decode('utf-8')

        self.assertNotIn('existed since:  UTC', html)
        self.assertIn('Confirmed in the blockchain', html)

    def test_the_summary_page_offers_it_too(self):
        """
        Quien llega al resumen ya tiene delante el master hash: el fichero es
        justo lo que le falta para comprobarlo. Obligarle a saltar a la otra
        pagina para bajarlo es esconder el unico paso que importa.
        """
        from apps.project.common.users.models import UserModel

        usuario = UserModel.objects.create_user(
            username='titular', email='titular@example.com',
            password='pw-for-tests-123',
        )
        self.client.force_login(usuario)

        response = self.client.get(
            reverse('certificates:summary_detail', args=[self.summary.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.proof_url(), response.content.decode('utf-8'))

    def test_a_proof_for_an_earlier_master_hash_is_not_offered_there(self):
        """
        El resumen se resello despues de anclarlo. Esa prueba sigue siendo
        valida, pero acredita **otro** hash: ofrecerla junto al de ahora
        invitaria a comprobar una cosa contra otra distinta. En la pagina de
        anclaje si sale, con su aviso, porque ahi el asunto es el historial.
        """
        from apps.project.common.users.models import UserModel

        self.anchor.payload_hash = 'f' * 64
        self.anchor.proof = confirmed_proof('f' * 64, height=BLOQUE)
        self.anchor.save()

        usuario = UserModel.objects.create_user(
            username='titular2', email='titular2@example.com',
            password='pw-for-tests-123',
        )
        self.client.force_login(usuario)

        response = self.client.get(
            reverse('certificates:summary_detail', args=[self.summary.pk]))

        self.assertNotIn(self.proof_url(), response.content.decode('utf-8'))
