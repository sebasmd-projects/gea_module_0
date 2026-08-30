# apps/project/specific/internal/code_gen/tests.py
"""
Sellar y enviar a la cadena de bloques: dos actos, y por que van separados.

Sellar es una escritura nuestra e instantanea. Enviar sale a la red, a unos
calendarios publicos de OpenTimestamps que pueden tardar o no responder. Con
``ATOMIC_REQUESTS`` cada peticion es una transaccion, asi que dejar escapar un
fallo del envio **desharia tambien el sellado**: el usuario habria pulsado
«sellar y enviar» para acabar sin ninguna de las dos cosas. De ahi que el envio
se degrade a aviso y el sello se quede guardado.

Un matiz sobre lo que estas pruebas comprueban de verdad: ``settings_test``
apaga ``ATOMIC_REQUESTS`` porque se lleva mal con las transacciones de
``TestCase``, asi que aqui se ve la mitad visible del problema -- que el fallo
del envio no se convierte en un error 500 y que el sello queda guardado. La
otra mitad, que ese 500 ademas se llevaria por delante el sellado, es la
consecuencia en produccion y es la razon de que esto importe.

Ninguna prueba de aqui sale a internet: se sustituye la llamada al calendario.

    manage.py test apps.project.specific.internal.code_gen \\
        --settings=app_core.settings_test
"""

import json
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.documents.certificates.models import (
    AegisSummaryDocumentModel, AegisSummaryModel, CertificationStatusChoices,
    DocumentVerificationModel)

from .models import (AnchorStatusChoices, AnchorTypeChoices,
                     CertificationAnchorModel)

PASSWORD = 'pw-for-tests-123'

FAKE_PROOF = {'proof': b'not-a-real-ots-proof', 'calendars': ['calendar.test']}

# Se parchea la funcion que habla con los calendarios, no la fachada: asi se
# ejercita todo el camino real hasta el borde de la red.
STAMP = 'apps.project.specific.internal.code_gen.services.ots.stamp'


class SealAndSendTestCase(TestCase):
    """Una caja con un miembro certificado, lista para sellar."""

    def setUp(self):
        self.staff = UserModel.objects.create_user(
            username='ops', email='ops@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.client.force_login(self.staff)

        self.document = self.certified_document(
            'The Golden Leaves 1872', digest='a',
        )

        self.summary = AegisSummaryModel.objects.create(
            title='Caja de prueba',
        )

        AegisSummaryDocumentModel.objects.create(
            summary=self.summary,
            document=self.document,
            code='AEGIS-1',
        )

        self.seal_url = reverse(
            'code_gen:summary_seal', args=[self.summary.pk]
        )
        self.anchor_url = reverse(
            'code_gen:summary_anchor', args=[self.summary.pk]
        )

    def certified_document(self, title, *, digest):
        return DocumentVerificationModel.objects.create(
            document_title=title,
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash=digest * 64,
            certified_content_hash=digest.upper() * 64,
        )

    def post(self, url, payload=None):
        return self.client.post(
            url,
            data=json.dumps(payload or {}),
            content_type='application/json',
        )

    def ots_anchors(self):
        return CertificationAnchorModel.objects.filter(
            summary=self.summary,
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS,
        )


class SealOnlyTests(SealAndSendTestCase):
    """El boton «solo sellar»."""

    def test_sealing_alone_does_not_touch_the_network(self):
        with mock.patch(STAMP) as stamp:
            response = self.post(self.seal_url, {'anchor': False})

        self.assertEqual(response.status_code, 200)
        self.summary.refresh_from_db()
        self.assertTrue(self.summary.master_hash)
        stamp.assert_not_called()
        self.assertFalse(self.ots_anchors().exists())

    def test_a_sealed_box_offers_to_be_sent_later(self):
        """Es la derivacion que pide el flujo: sellar ahora, enviar despues."""
        response = self.post(self.seal_url, {'anchor': False})

        self.assertTrue(response.json()['can_send_to_blockchain'])
        self.assertFalse(response.json()['sent_to_blockchain'])


class SealAndSendTests(SealAndSendTestCase):
    """El boton «sellar y enviar»."""

    def test_it_seals_and_sends_in_one_go(self):
        with mock.patch(STAMP, return_value=FAKE_PROOF):
            response = self.post(self.seal_url, {'anchor': True})

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload['anchor_result'], 'anchored')
        self.assertTrue(payload['sent_to_blockchain'])
        self.assertFalse(payload['can_send_to_blockchain'])

        anchor = self.ots_anchors().get()
        self.assertEqual(anchor.status, AnchorStatusChoices.PENDING)
        self.assertEqual(anchor.payload_hash, payload['master_hash'])

    def test_a_dead_calendar_does_not_cost_the_seal(self):
        """
        El caso que justifica todo el diseno.

        Si el fallo del calendario escapara, ``ATOMIC_REQUESTS`` desharia la
        transaccion entera y el sellado se perderia con el: quien pulso
        «sellar y enviar» se quedaria sin lo uno y sin lo otro.
        """
        from .services import ots

        with mock.patch(STAMP,
                        side_effect=ots.OTSError('calendarios caidos')):
            response = self.post(self.seal_url, {'anchor': True})

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertEqual(payload['anchor_result'], 'failed')

        self.summary.refresh_from_db()
        self.assertTrue(
            self.summary.master_hash,
            'el sello tiene que sobrevivir a un fallo del envio',
        )
        self.assertTrue(
            payload['can_send_to_blockchain'],
            'y el envio tiene que quedar disponible para reintentarlo',
        )

    def test_the_failure_says_why_it_failed(self):
        """
        Un «fallo» a secas obliga a ir a buscar stderr.log en el servidor para
        distinguir dos arreglos completamente distintos: instalar una libreria
        o abrir la salida a internet. La pantalla es solo para personal
        interno, asi que la causa va en el aviso.
        """
        from .services import ots

        with mock.patch(STAMP, side_effect=ots.OTSError(
                'No OpenTimestamps calendar could be reached.')):
            response = self.post(self.seal_url, {'anchor': True})

        detail = response.json()['detail']

        self.assertIn('calendar could be reached', detail)
        self.assertIn('operations console', detail)

    def test_a_missing_library_is_named_as_such(self):
        """
        Es la otra causa, y su arreglo no esta en esta pantalla ni en la
        consola: produccion instala con pip desde requirements.txt, no con
        uv, que aqui solo se usa en local. Decirlo ahorra la busqueda.
        """
        with mock.patch(STAMP, side_effect=ImportError(
                "No module named 'opentimestamps'")):
            response = self.post(self.seal_url, {'anchor': True})

        detail = response.json()['detail']

        self.assertEqual(response.json()['anchor_result'], 'failed')
        self.assertIn('not installed', detail)
        self.assertIn('pip', detail)
        self.assertIn('requirements.txt', detail)

        self.summary.refresh_from_db()
        self.assertTrue(self.summary.master_hash)

    def test_an_unexpected_failure_is_contained_too(self):
        """No solo OTSError: cualquier fallo de red haria el mismo dano."""
        with mock.patch(STAMP,
                        side_effect=RuntimeError('conexion rota')):
            response = self.post(self.seal_url, {'anchor': True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['anchor_result'], 'failed')

        self.summary.refresh_from_db()
        self.assertTrue(self.summary.master_hash)


class SendLaterTests(SealAndSendTestCase):
    """El segundo tiempo: enviar algo que ya estaba sellado."""

    def test_an_unsealed_box_has_nothing_to_send(self):
        response = self.post(self.anchor_url)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.ots_anchors().exists())

    def test_sealing_first_and_sending_after_works(self):
        self.post(self.seal_url, {'anchor': False})

        with mock.patch(STAMP, return_value=FAKE_PROOF):
            response = self.post(self.anchor_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['anchor_result'], 'anchored')
        self.assertEqual(self.ots_anchors().count(), 1)

    def test_the_same_hash_is_not_sent_twice(self):
        """
        Pulsar dos veces no puede mandar dos veces lo mismo: seria ruido en el
        calendario y dos pruebas del mismo hecho.
        """
        self.post(self.seal_url, {'anchor': False})

        with mock.patch(STAMP, return_value=FAKE_PROOF):
            self.post(self.anchor_url)
            second = self.post(self.anchor_url)

        self.assertEqual(second.json()['anchor_result'], 'already')
        self.assertEqual(self.ots_anchors().count(), 1)

    def test_resealing_with_a_new_hash_can_be_sent_again(self):
        """
        Si cambian los miembros, el master hash cambia y el envio anterior
        cubre un hash que ya no es el de la caja: hace falta enviar de nuevo.
        """
        self.post(self.seal_url, {'anchor': False})

        with mock.patch(STAMP, return_value=FAKE_PROOF):
            self.post(self.anchor_url)

        other = self.certified_document('Otro certificado', digest='c')
        AegisSummaryDocumentModel.objects.create(
            summary=self.summary, document=other, code='AEGIS-2',
        )

        response = self.post(self.seal_url, {'anchor': False})

        self.assertTrue(
            response.json()['can_send_to_blockchain'],
            'un master hash nuevo no esta cubierto por el envio anterior',
        )


class SealAccessTests(SealAndSendTestCase):
    """Ni sellar ni enviar son operaciones publicas."""

    def test_an_outsider_cannot_seal_or_send(self):
        self.client.logout()

        self.assertNotEqual(self.post(self.seal_url).status_code, 200)
        self.assertNotEqual(self.post(self.anchor_url).status_code, 200)
        self.assertFalse(self.ots_anchors().exists())
