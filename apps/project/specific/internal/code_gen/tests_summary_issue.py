# apps/project/specific/internal/code_gen/tests_summary_issue.py
"""
Emitir el documento del resumen, y que no espere a la cadena de bloques.

El resumen AEGIS es un documento como los demas --solo que su contenido es
agrupar a otros-- y como tal tiene sus tres archivos: el original sin codigos,
el certificado que hace fe y la copia publica con marca de agua. El servicio
que los produce estaba escrito y completo desde el principio; lo que no habia
era nada que lo llamara. Se sellaba el resumen, se anclaba, y ``summary_document``
se quedaba en ``null``: el resumen no tenia papel.

**Lo que se comprueba aqui, sobre todo, es que emitir no dependa del anclaje.**
Es la razon de que baste con un documento y no hagan falta dos. El QR que se
estampa lleva la URL de la pagina de anclaje, nunca la prueba (invariante 16),
y esa pagina se actualiza sola cuando el anclaje madura en un bloque de
Bitcoin. Asi que el PDF se emite una vez, con el resumen sellado, y no hay nada
que reestampar despues. Dos papeles --uno «sin blockchain» y otro «con»--
serian dos huellas distintas para el mismo resumen, y habria que decidir cual de
los dos hace fe.

Nada de aqui sale a internet.

    manage.py test apps.project.specific.internal.code_gen.tests_summary_issue \\
        --settings=app_core.settings_test
"""

import io
from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.documents.certificates.models import (
    AegisSummaryDocumentModel, AegisSummaryModel, CertificationStatusChoices,
    DocumentVerificationModel, SummaryStatusChoices)

from .models import (AnchorChoices, CodeKindChoices, PageSelectorChoices,
                     StampLayoutModel, StampPlacementModel)
from .services.master import seal_summary

PASSWORD = 'pw-for-tests-123'


def a_pdf(pages=1) -> bytes:
    """Un PDF de verdad, porque el estampado lee y reescribe uno de verdad."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer)

    for number in range(pages):
        sheet.drawString(72, 720, f'Resumen de prueba, pagina {number + 1}')
        sheet.showPage()

    sheet.save()

    return buffer.getvalue()


def an_upload(name='resumen.pdf'):
    return SimpleUploadedFile(name, a_pdf(), content_type='application/pdf')


class SummaryIssueTestCase(TestCase):
    """Un resumen con un miembro y una disposicion que usa los cuatro simbolos."""

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
            code_payload='GEA-1-20260115-ABCD',
        )

        self.summary = AegisSummaryModel.objects.create(title='Resumen de prueba')

        AegisSummaryDocumentModel.objects.create(
            summary=self.summary, document=self.member, code='AEGIS-1',
        )

        self.layout = self.a_layout()
        self.url = reverse('code_gen:summary_issue', args=[self.summary.pk])

    def a_layout(self):
        layout = StampLayoutModel.objects.create(name='Resumen AEGIS')

        kinds = [
            (CodeKindChoices.BARCODE, ''),
            (CodeKindChoices.QR, ''),
            (CodeKindChoices.ANCHOR_QR, ''),
            (CodeKindChoices.MEMBER_BARCODE, 'AEGIS-1'),
        ]

        for order, (kind, member_code) in enumerate(kinds):
            StampPlacementModel.objects.create(
                layout=layout,
                kind=kind,
                member_code=member_code,
                page_selector=PageSelectorChoices.FIRST,
                anchor=AnchorChoices.BOTTOM_LEFT,
                offset_x=20 + order * 10,
                offset_y=20,
                width=120,
                height=40,
            )

        return layout

    def seal(self):
        return seal_summary(self.summary)

    def issue(self, *, upload=True, layout=True):
        data = {}

        if upload:
            data['source_file'] = an_upload()

        if layout:
            data['layout'] = str(self.layout.pk)

        return self.client.post(self.url, data)


class TestIssuingNeedsASealedSummary(SummaryIssueTestCase):

    def test_an_unsealed_summary_has_no_document_to_issue(self):
        """
        El resumen lleva el master hash dentro de su codigo de barras: sin
        sellar, no hay nada que estampar.
        """
        response = self.issue()

        self.assertEqual(response.status_code, 400)
        self.assertIn('Seal the summary', response.json()['detail'])

        self.summary.refresh_from_db()
        self.assertIsNone(self.summary.summary_document)

    def test_without_an_original_there_is_nothing_to_stamp_over(self):
        self.seal()

        response = self.issue(upload=False)

        self.assertEqual(response.status_code, 400)
        self.assertIn('summary PDF', response.json()['detail'])

    def test_without_a_layout_there_is_nowhere_to_put_the_codes(self):
        self.seal()

        response = self.issue(layout=False)

        self.assertEqual(response.status_code, 400)
        self.assertIn('layout', response.json()['detail'])


class TestIssuingDoesNotWaitForTheBlockchain(SummaryIssueTestCase):
    """
    La razon de que baste con un documento.

    El QR estampado lleva la URL de la pagina de anclaje, no la prueba, y esa
    pagina se actualiza sola. Asi que emitir con el resumen recien sellado --sin
    ningun anclaje todavia-- produce el papel definitivo.
    """

    def test_a_summary_with_no_anchor_at_all_still_gets_its_document(self):
        self.seal()

        self.assertFalse(self.summary.anchors.exists())

        response = self.issue()

        self.assertEqual(response.status_code, 200, response.content)

        self.summary.refresh_from_db()
        self.assertIsNotNone(self.summary.summary_document)
        self.assertEqual(self.summary.status, SummaryStatusChoices.CERTIFIED)

    def test_the_anchor_qr_is_stamped_even_with_nothing_anchored(self):
        """
        Si el QR se omitiera cuando no hay anclaje, habria que reemitir el PDF
        al llegar el bloque -- y el anterior ya podria haberse repartido.
        """
        self.seal()

        response = self.issue()

        self.assertEqual(response.status_code, 200, response.content)
        # Los cuatro simbolos de la disposicion, ninguno omitido.
        self.assertEqual(response.json()['skipped'], [])

    def test_issuing_creates_no_anchor_and_touches_no_calendar(self):
        """Emitir y anclar son dos actos distintos, y este no es el otro."""
        self.seal()

        self.issue()

        self.assertFalse(self.summary.anchors.exists())


class TestTheDocumentThatComesOut(SummaryIssueTestCase):

    def issued(self):
        self.seal()
        response = self.issue()
        self.assertEqual(response.status_code, 200, response.content)
        self.summary.refresh_from_db()

        return response.json(), self.summary.summary_document

    def test_it_has_the_three_files_like_any_certificate(self):
        """
        Original sin codigos, certificado que hace fe, copia distribuible con
        marca de agua. El resumen no es una excepcion (invariante 8).
        """
        _, document = self.issued()

        self.assertTrue(document.source_file)
        self.assertTrue(document.document_file)
        self.assertTrue(document.public_copy_file)

    def test_the_certified_and_the_public_copy_share_the_content_hash(self):
        """
        Se distinguen solo por la marca de agua, que la huella de contenido
        ignora deliberadamente (invariante 10).
        """
        _, document = self.issued()

        self.assertTrue(document.certified_content_hash)
        self.assertEqual(
            document.certified_content_hash, document.public_copy_content_hash
        )
        self.assertNotEqual(document.document_hash, document.public_copy_hash)

    def test_the_files_are_offered_through_the_permission_checked_view(self):
        """
        Nunca por MEDIA_URL: la unica via es certificates:document_file, que
        comprueba permisos (invariante 13).
        """
        payload, document = self.issued()

        links = payload['document']

        self.assertEqual(
            links['certified_url'],
            reverse('certificates:document_file',
                    kwargs={'pk': document.pk, 'kind': 'certified'}),
        )
        self.assertEqual(
            links['public_url'],
            reverse('certificates:document_file',
                    kwargs={'pk': document.pk, 'kind': 'public'}),
        )
        self.assertNotIn('/media/', links['certified_url'])

    def test_the_summary_reports_itself_as_issued(self):
        payload, _ = self.issued()

        self.assertTrue(payload['issued'])
        self.assertEqual(payload['status'], SummaryStatusChoices.CERTIFIED)


class TestReissuing(SummaryIssueTestCase):

    def test_reissuing_keeps_the_original_already_stored(self):
        """
        El original no se vuelve a pedir: se rehacen el estampado, las huellas
        y la copia sobre el que ya estaba.
        """
        self.seal()
        self.issue()

        self.summary.refresh_from_db()
        before = self.summary.summary_document.source_hash

        response = self.issue(upload=False)

        self.assertEqual(response.status_code, 200, response.content)

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.summary_document.source_hash, before)

    def test_reissuing_keeps_the_same_public_code(self):
        """
        El codigo publico es el que circula impreso. Reemitir rehace el papel,
        no la identidad del documento.
        """
        self.seal()
        self.issue()

        self.summary.refresh_from_db()
        before = self.summary.summary_document.public_code

        self.issue(upload=False)

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.summary_document.public_code, before)


class TestWhenThingsGoWrong(SummaryIssueTestCase):

    def a_broken_pdf(self):
        return self.client.post(self.url, {
            'source_file': SimpleUploadedFile(
                'roto.pdf', b'esto no es un PDF',
                content_type='application/pdf',
            ),
            'layout': str(self.layout.pk),
        })

    def test_a_file_that_is_not_a_pdf_is_answered_not_crashed(self):
        """
        El estampado lee un archivo que sube el usuario. Con ATOMIC_REQUESTS,
        dejar escapar la excepcion seria un 500 que ademas desharia lo que ya
        se hubiera guardado.
        """
        self.seal()

        response = self.a_broken_pdf()

        self.assertEqual(response.status_code, 400)
        self.assertIn('not a readable PDF', response.json()['detail'])

    def test_a_failed_issue_leaves_no_half_made_document(self):
        """
        ``certify_summary`` es atomica: o sale el documento entero o no sale
        ninguno. Un resumen con un documento a medias diria que esta certificado
        sin tener papel.
        """
        self.seal()

        self.a_broken_pdf()

        self.summary.refresh_from_db()
        self.assertIsNone(self.summary.summary_document)
        self.assertNotEqual(self.summary.status, SummaryStatusChoices.CERTIFIED)

    def test_only_internal_staff_can_issue(self):
        self.seal()
        self.client.logout()

        outsider = UserModel.objects.create_user(
            username='fuera', email='fuera@example.com', password=PASSWORD,
        )
        self.client.force_login(outsider)

        response = self.issue()

        self.assertEqual(response.status_code, 403)

        self.summary.refresh_from_db()
        self.assertIsNone(self.summary.summary_document)


class TestThePublicCode(SummaryIssueTestCase):
    """
    Un resumen y su documento son una sola cosa para quien los mira.

    `DocumentVerificationModel.save()` se inventa un codigo publico cuando el
    campo viene vacio, y eso dejaba dos codigos distintos: el listado mostraba
    uno y el registro del PDF otro. Quien leyera el del papel no encontraria el
    del listado.
    """

    def test_the_document_carries_the_code_of_its_summary(self):
        self.seal()
        self.issue()

        self.summary.refresh_from_db()

        self.assertEqual(
            self.summary.summary_document.public_code,
            self.summary.public_code,
        )

    def test_reissuing_does_not_change_it(self):
        self.seal()
        self.issue()

        self.summary.refresh_from_db()
        before = self.summary.summary_document.public_code

        self.issue(upload=False)

        self.summary.refresh_from_db()
        self.assertEqual(self.summary.summary_document.public_code, before)

    def test_a_code_already_taken_does_not_break_the_issue(self):
        """
        Improbabilisimo --son doce caracteres al azar-- pero la alternativa a
        comprobarlo es un IntegrityError al guardar, que saldria como un 500
        sin explicacion.
        """
        DocumentVerificationModel.objects.create(
            document_title='Otro documento cualquiera',
            issued_at=date(2026, 1, 15),
            public_code=self.summary.public_code,
        )

        self.seal()
        response = self.issue()

        self.assertEqual(response.status_code, 200, response.content)

        self.summary.refresh_from_db()
        document = self.summary.summary_document

        self.assertIsNotNone(document)
        self.assertTrue(document.public_code)
        self.assertNotEqual(document.public_code, self.summary.public_code)
