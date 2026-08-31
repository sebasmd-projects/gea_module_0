# apps/project/specific/internal/code_gen/tests_preview.py
"""
Que la vista previa dibuje lo que se va a estampar, y donde.

Dos cosas distintas, las dos reportadas mirando el resultado real.

**Muestras solo mientras no haya nada de verdad.** El editor de disposiciones
no tiene documento delante, asi que ahi una muestra es lo correcto --y por eso
deja elegir su longitud--. Pero en un documento ya certificado o en un resumen
ya compuesto el contenido existe, y dibujar una muestra engana justo en lo que
se esta mirando: el ancho de un Code128 depende de cuantos caracteres lleve,
asi que una muestra corta cabe donde el codigo real se sale de la caja.

Los codigos de los miembros van uno por miembro por lo mismo. Con un simbolo
compartido, cinco miembros de longitudes distintas se verian todos del mismo
ancho, que es precisamente la informacion que se busca.

**Y centrado.** Al estampar se conserva la proporcion del simbolo, asi que
casi nunca llena la caja asignada. Estaba anclado abajo a la izquierda
(``anchor='sw'``), con lo que todo el hueco sobrante caia a un lado.

    manage.py test apps.project.specific.internal.code_gen.tests_preview \\
        --settings=app_core.settings_test
"""

import json
import re
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.documents.certificates.models import (
    AegisSummaryDocumentModel, AegisSummaryModel, CertificationStatusChoices,
    DocumentVerificationModel)

from .preview import render_preview_container
from .services.master import seal_summary
from .services.samples import member_symbols, sample_symbols

PASSWORD = 'pw-for-tests-123'

ATTRIBUTE = re.compile(r'data-member-symbols="([^"]*)"')


def symbols_in(html: str) -> dict:
    """Los simbolos por miembro que viajan en el contenedor."""
    import html as html_module

    match = ATTRIBUTE.search(html)

    if not match:
        return {}

    return json.loads(html_module.unescape(match.group(1)))


class TestRealPayloadsBeatSamples(TestCase):

    def test_a_real_barcode_is_drawn_instead_of_filler(self):
        html = render_preview_container(barcode_payload='GEA-1-20260115-ABCD')

        self.assertIn('GEA-1-20260115-ABCD', html)

    def test_without_a_payload_it_still_draws_a_sample(self):
        """
        El editor de disposiciones no tiene documento delante: ahi la muestra
        es lo correcto, y quitarla dejaria la pagina sin nada que mirar.
        """
        html = render_preview_container()

        self.assertIn('data-symbols=', html)
        self.assertIn('data-sample-length=', html)

    def test_the_two_qr_are_drawn_apart(self):
        """
        El QR propio y el del anclaje no llevan lo mismo: uno apunta a la
        verificacion y el otro a la pagina de anclaje. En un QR el contenido
        cambia la densidad del dibujo, asi que dibujar los dos iguales seria
        enseñar uno que no es.
        """
        symbols = sample_symbols(
            qr_payload='https://ejemplo.test/verify/',
            anchor_payload='https://ejemplo.test/anchor/',
        )

        self.assertNotEqual(symbols['QR']['src'], symbols['ANCHOR']['src'])

    def test_the_anchor_falls_back_to_the_other_qr(self):
        symbols = sample_symbols(qr_payload='https://ejemplo.test/verify/')

        self.assertEqual(symbols['QR']['src'], symbols['ANCHOR']['src'])


class TestOneSymbolPerMember(TestCase):

    def test_each_member_gets_its_own_barcode(self):
        symbols = member_symbols({
            'AEGIS-1': 'CORTO',
            'AEGIS-2': 'UN-CODIGO-BASTANTE-MAS-LARGO-QUE-EL-OTRO',
        })

        self.assertEqual(set(symbols), {'AEGIS-1', 'AEGIS-2'})
        self.assertNotEqual(
            symbols['AEGIS-1']['src'], symbols['AEGIS-2']['src']
        )

    def test_a_longer_code_really_is_wider(self):
        """
        Es la razon de que haya uno por miembro. Si todos compartieran simbolo,
        la vista previa diria que caben en el mismo hueco.
        """
        symbols = member_symbols({
            'AEGIS-1': 'CORTO',
            'AEGIS-2': 'UN-CODIGO-BASTANTE-MAS-LARGO-QUE-EL-OTRO',
        })

        self.assertGreater(
            symbols['AEGIS-2']['ratio'], symbols['AEGIS-1']['ratio']
        )

    def test_a_member_that_cannot_be_drawn_does_not_take_the_rest_down(self):
        symbols = member_symbols({
            'AEGIS-1': 'BUENO',
            'AEGIS-2': '',
        })

        self.assertIn('AEGIS-1', symbols)
        self.assertNotIn('AEGIS-2', symbols)


class TestTheComposerPassesTheRealThing(TestCase):

    def setUp(self):
        self.staff = UserModel.objects.create_user(
            username='ops', email='ops@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.client.force_login(self.staff)

        self.member = DocumentVerificationModel.objects.create(
            document_title='The Golden Leaves 1872',
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash='a' * 64,
            code_payload='GEA-MIEMBRO-UNO-20260115',
        )

        self.summary = AegisSummaryModel.objects.create(title='Resumen')

        AegisSummaryDocumentModel.objects.create(
            summary=self.summary, document=self.member, code='AEGIS-1',
        )

    def compose(self):
        return self.client.get(
            reverse('code_gen:summary_compose', args=[self.summary.pk])
        )

    def test_the_member_barcode_carries_its_real_code(self):
        response = self.compose()

        symbols = symbols_in(response.content.decode())

        self.assertIn('AEGIS-1', symbols)
        self.assertEqual(
            symbols['AEGIS-1']['payload'], 'GEA-MIEMBRO-UNO-20260115'
        )

    def test_a_sealed_summary_shows_its_master_hash_in_the_barcode(self):
        digest = seal_summary(self.summary)

        response = self.compose()

        self.assertIn(digest[:32].upper(), response.content.decode())


class TestTheDocumentLinksAreRenderedByTheServer(TestCase):
    """
    Salian con href="#" y solo el JS los rellenaba, y solo justo despues de
    emitir. Al volver a entrar en un resumen ya emitido, los tres enlaces
    --certificado, copia publica y pagina de verificacion-- llevaban a la
    misma pagina en la que ya estabas.
    """

    def setUp(self):
        self.staff = UserModel.objects.create_user(
            username='ops2', email='ops2@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.client.force_login(self.staff)

        self.document = DocumentVerificationModel.objects.create(
            document_title='Resumen ya emitido',
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
        )

        self.summary = AegisSummaryModel.objects.create(
            title='Resumen', summary_document=self.document,
        )

    def test_the_three_links_point_somewhere_real(self):
        response = self.client.get(
            reverse('code_gen:summary_compose', args=[self.summary.pk])
        )

        html = response.content.decode()

        for kind in ('certified', 'public'):
            self.assertIn(
                reverse('certificates:document_file',
                        kwargs={'pk': self.document.pk, 'kind': kind}),
                html,
            )

        self.assertIn(
            reverse('certificates:summary_detail',
                    kwargs={'pk': self.summary.pk}),
            html,
        )

    def test_none_of_them_is_left_as_a_dead_link(self):
        response = self.client.get(
            reverse('code_gen:summary_compose', args=[self.summary.pk])
        )

        html = response.content.decode()

        for element in ('documentCertified', 'documentPublic',
                        'documentVerification'):
            fragment = html[html.index(element):html.index(element) + 200]
            self.assertNotIn('href="#"', fragment)
