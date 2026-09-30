# apps/project/specific/documents/certificates/tests/test_external_issuer.py
"""
Certificacion para emisores externos: autenticacion, cupo, idempotencia,
estampado, copia distribuible y revocacion.

No hay decodificador de QR ni de Code128 en el entorno, asi que lo que se
comprueba del estampado son los argumentos: con que texto se renderizan los
dos simbolos y en que posicion se estampan.

    manage.py test apps.project.specific.documents.certificates.tests.test_external_issuer \\
        --settings=app_core.settings_test
"""

import io
import json
from unittest import mock

from django.core.cache import cache
from django.core import checks
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from reportlab.pdfgen import canvas

from apps.common.utils.tests.test_throttling import dead_cache
from apps.project.common.users.models import UserModel
from apps.project.specific.internal.code_gen.services.hashing import \
    sha256_hex
from apps.project.specific.internal.code_gen.services.pdf_stamp import \
    stamp_pdf
from apps.project.specific.internal.code_gen.services.watermark import \
    read_watermark_reference

from .. import external
from ..checks import check_external_issuer_keys
from ..models import (CertificationStatusChoices, DocumentCopyKind,
                      DocumentVerificationModel)
from ..verification import MATCH_EXACT, identify_uploaded_document

KEY = 'k' * 48
OTHER_KEY = 'o' * 48

ISSUERS = {
    'propensiones': {'name': 'Propensiones Abogados', 'key': KEY},
    'otro': {'name': 'Otro', 'key': OTHER_KEY},
    'apagado': {'name': 'Sin clave', 'key': ''},
}

QR_URL = 'https://propensionesabogados.com/verificar/abc123'
BARCODE = 'PAZ-2026-000123'

CERTIFY = (
    'apps.project.specific.documents.certificates.external.certify_document'
)


def a_pdf(pages=2) -> bytes:
    buffer = io.BytesIO()
    sheet = canvas.Canvas(buffer, pagesize=(612, 792))

    for number in range(pages):
        sheet.drawString(72, 700, f'Paz y salvo, pagina {number + 1}')
        sheet.showPage()

    sheet.save()
    return buffer.getvalue()


def a_placement():
    return {
        'qr': {'page': 1, 'x': 40.0, 'y': 30.0, 'size': 90.0},
        'barcode': {'page': 2, 'x': 200.0, 'y': 30.0,
                    'width': 220.0, 'height': 60.0},
    }


@override_settings(GEA_EXTERNAL_ISSUERS=ISSUERS)
class ExternalTestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.pdf = a_pdf()

    def payload(self, **changes):
        data = {
            'issuer': 'propensiones',
            'source': SimpleUploadedFile(
                'paz.pdf', self.pdf, content_type='application/pdf'),
            'reference': 'caso-0001',
            'title': 'Paz y salvo 0001',
            'qr_payload': QR_URL,
            'barcode_text': BARCODE,
            'placement': json.dumps(a_placement()),
            'idempotency_key': 'key-0001',
        }
        data.update(changes)
        return {k: v for k, v in data.items() if v is not None}

    def issue(self, key=KEY, **changes):
        headers = {'HTTP_X_ISSUER_KEY': key} if key is not None else {}
        return self.client.post(
            reverse('certificates:external_issue'),
            self.payload(**changes), **headers,
        )

    def headers(self, slug='propensiones', key=KEY):
        return {'HTTP_X_ISSUER': slug, 'HTTP_X_ISSUER_KEY': key}

    def issued(self, **changes):
        response = self.issue(**changes)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()


class TestAuthentication(ExternalTestCase):

    def test_the_right_key_gets_the_full_contract(self):
        body = self.issued()

        self.assertEqual(
            set(body),
            {'document_id', 'code', 'verification_url', 'source_hash',
             'public_copy_hash', 'public_copy_url', 'issued_at'},
        )

        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])

        self.assertEqual(body['code'], document.public_code)
        self.assertEqual(body['source_hash'], sha256_hex(self.pdf))
        self.assertEqual(body['public_copy_hash'], document.public_copy_hash)
        self.assertEqual(
            body['verification_url'],
            'https://geausa.propensionesabogados.com' + reverse(
                'certificates:detail_document_verification_aegis',
                kwargs={'pk': document.pk}),
        )
        self.assertEqual(
            body['public_copy_url'],
            'https://geausa.propensionesabogados.com' + reverse(
                'certificates:external_public_copy',
                kwargs={'document_id': document.pk}),
        )
        self.assertTrue(body['issued_at'])

        self.assertEqual(document.external_issuer, 'propensiones')
        self.assertEqual(document.external_reference, 'caso-0001')
        self.assertEqual(
            document.certification_status, CertificationStatusChoices.CERTIFIED)
        self.assertEqual(document.holders.count(), 0)

    def test_the_gea_code_is_the_barcode_text(self):
        body = self.issued()
        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])

        self.assertEqual(document.code_payload, BARCODE)
        self.assertEqual(document.qr_payload, QR_URL)

    def test_a_bad_key_is_a_generic_403(self):
        response = self.issue(key='x' * 48)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'error': 'forbidden'})
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_no_key_is_403(self):
        self.assertEqual(self.issue(key=None).status_code, 403)

    def test_another_issuers_key_is_403(self):
        self.assertEqual(self.issue(key=OTHER_KEY).status_code, 403)

    def test_an_unknown_issuer_is_403(self):
        self.assertEqual(self.issue(issuer='nadie').status_code, 403)

    def test_an_issuer_without_key_is_disabled(self):
        for key in ('', 'no-key-configured', None):
            with self.subTest(key=key):
                self.assertEqual(
                    self.issue(issuer='apagado', key=key).status_code, 403)

    def test_a_missing_issuer_is_403(self):
        self.assertEqual(self.issue(issuer=None).status_code, 403)

    def test_only_post_is_accepted(self):
        response = self.client.get(reverse('certificates:external_issue'))
        self.assertEqual(response.status_code, 405)

    def test_no_csrf_token_is_needed(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse('certificates:external_issue'), self.payload(),
            HTTP_X_ISSUER_KEY=KEY,
        )
        self.assertEqual(response.status_code, 201)


class TestValidation(ExternalTestCase):

    def assertRejected(self, response, field):
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()['field'], field)
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_a_missing_source(self):
        self.assertRejected(self.issue(source=None), 'source')

    def test_not_a_pdf_by_name(self):
        upload = SimpleUploadedFile('paz.txt', self.pdf)
        self.assertRejected(self.issue(source=upload), 'source')

    def test_not_a_pdf_by_content(self):
        upload = SimpleUploadedFile('paz.pdf', b'hola, no soy un pdf')
        self.assertRejected(self.issue(source=upload), 'source')

    def test_a_broken_pdf(self):
        upload = SimpleUploadedFile('paz.pdf', b'%PDF-1.4 roto')
        self.assertRejected(self.issue(source=upload), 'source')

    def test_a_file_over_the_limit(self):
        with mock.patch.object(external, 'MAX_UPLOAD_BYTES', 10):
            self.assertRejected(self.issue(), 'source')

    def test_missing_texts(self):
        for name in ('reference', 'title', 'idempotency_key'):
            with self.subTest(name=name):
                self.assertRejected(self.issue(**{name: ''}), name)

    def test_qr_payload_must_be_https(self):
        for value in ('http://x.com/a', 'ftp://x.com', 'javascript:alert(1)',
                      'https://', 'no es url', 'https://x.com/a b', ''):
            with self.subTest(value=value):
                self.assertRejected(self.issue(qr_payload=value), 'qr_payload')

    def test_barcode_text_follows_the_gea_rules(self):
        for value in ('', 'https://x.com', 'con/barra', 'ñandú', 'A' * 81):
            with self.subTest(value=value):
                self.assertRejected(
                    self.issue(barcode_text=value), 'barcode_text')

    def test_placement_must_be_valid(self):
        def bad(mutate):
            placement = a_placement()
            mutate(placement)
            return json.dumps(placement)

        cases = {
            'not json': 'esto no es json',
            'not an object': '[1, 2]',
            'no qr': bad(lambda p: p.pop('qr')),
            'no barcode': bad(lambda p: p.pop('barcode')),
            'page zero': bad(lambda p: p['qr'].update(page=0)),
            'page beyond': bad(lambda p: p['qr'].update(page=3)),
            'page as text': bad(lambda p: p['qr'].update(page='1')),
            'negative x': bad(lambda p: p['qr'].update(x=-1)),
            'text number': bad(lambda p: p['qr'].update(x='40')),
            'bool number': bad(lambda p: p['qr'].update(y=True)),
            'zero size': bad(lambda p: p['qr'].update(size=0)),
            'qr off the right': bad(lambda p: p['qr'].update(x=600)),
            'qr off the top': bad(lambda p: p['qr'].update(y=790)),
            'barcode too wide': bad(
                lambda p: p['barcode'].update(width=700)),
            'barcode too tall': bad(
                lambda p: p['barcode'].update(y=750)),
            'missing height': bad(lambda p: p['barcode'].pop('height')),
        }

        for name, value in cases.items():
            with self.subTest(name):
                self.assertRejected(self.issue(placement=value), 'placement')

    def test_non_finite_numbers(self):
        # json.loads acepta NaN e Infinity; hay que rechazarlos igual.
        raw = ('{"qr": {"page": 1, "x": NaN, "y": 30, "size": 90}, '
               '"barcode": {"page": 1, "x": 10, "y": 10, "width": 100, '
               '"height": 40}}')
        self.assertRejected(self.issue(placement=raw), 'placement')

        raw = raw.replace('NaN', '10').replace('"size": 90', '"size": Infinity')
        self.assertRejected(self.issue(placement=raw), 'placement')

    def test_a_placement_on_the_edge_is_fine(self):
        placement = a_placement()
        placement['qr'].update(x=612 - 90, y=0)
        self.issued(placement=json.dumps(placement))


class TestIdempotency(ExternalTestCase):

    def test_the_same_key_returns_the_same_result_without_certifying_again(self):
        first = self.issued()

        with mock.patch(CERTIFY) as certify:
            again = self.issue()

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first)
        certify.assert_not_called()
        self.assertEqual(DocumentVerificationModel.objects.count(), 1)

    def test_a_retry_does_not_need_to_repeat_the_body(self):
        first = self.issued()

        again = self.issue(source=None, placement='basura', title='otro')

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first)

    def test_another_key_is_another_document(self):
        one = self.issued()
        two = self.issued(idempotency_key='key-0002')

        self.assertNotEqual(one['document_id'], two['document_id'])
        self.assertEqual(DocumentVerificationModel.objects.count(), 2)

    def test_two_issuers_can_use_the_same_key(self):
        one = self.issued()
        two = self.issue(key=OTHER_KEY, issuer='otro')

        self.assertEqual(two.status_code, 201)
        self.assertNotEqual(one['document_id'], two.json()['document_id'])

    def test_a_failed_attempt_leaves_nothing_behind(self):
        with mock.patch(CERTIFY, side_effect=RuntimeError('boom')):
            response = self.issue()

        self.assertEqual(response.status_code, 500)
        self.assertFalse(DocumentVerificationModel.objects.exists())

        # ... y reintentar con la misma clave certifica de verdad.
        self.assertEqual(self.issue().status_code, 201)


class TestRateLimit(ExternalTestCase):

    def test_the_issuer_quota_answers_429(self):
        with mock.patch.object(external, 'issue_limit',
                               external.RateLimit('t_issue', limit=2,
                                                  window=60)):
            self.assertEqual(self.issue(idempotency_key='a').status_code, 201)
            self.assertEqual(self.issue(idempotency_key='b').status_code, 201)
            self.assertEqual(self.issue(idempotency_key='c').status_code, 429)

            # El cupo es del emisor, no compartido con los demas.
            other = self.issue(
                issuer='otro', key=OTHER_KEY, idempotency_key='c')
            self.assertEqual(other.status_code, 201)

    def test_a_dead_cache_answers_429(self):
        with dead_cache():
            response = self.issue()

        self.assertEqual(response.status_code, 429)
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_bad_keys_do_not_spend_the_issuer_quota(self):
        with mock.patch.object(external, 'issue_limit',
                               external.RateLimit('t_issue2', limit=1,
                                                  window=60)):
            for _ in range(3):
                self.assertEqual(self.issue(key='x' * 48).status_code, 403)

            self.assertEqual(self.issue().status_code, 201)

    def test_repeated_bad_keys_from_one_address_are_throttled(self):
        with mock.patch.object(external, 'auth_failures',
                               external.RateLimit('t_auth', limit=2,
                                                  window=60)):
            codes = [self.issue(key='x' * 48).status_code for _ in range(4)]

        self.assertEqual(codes, [403, 403, 429, 429])


class TestStamping(ExternalTestCase):

    def test_the_symbols_carry_exactly_what_was_sent(self):
        with mock.patch.object(
                external, 'render_qr_png',
                wraps=external.render_qr_png) as qr, \
                mock.patch.object(
                    external, 'render_barcode_png',
                    wraps=external.render_barcode_png) as barcode:
            self.issued()

        qr.assert_called_once_with(QR_URL)
        barcode.assert_called_once_with(BARCODE)

    def test_the_symbols_go_where_placement_says(self):
        target = ('apps.project.specific.internal.code_gen.services.'
                  'certification.stamp_pdf')

        with mock.patch(target, wraps=stamp_pdf) as stamper:
            self.issued()

        specs = stamper.call_args.args[1]
        qr, barcode = specs

        self.assertEqual((qr.pages, qr.anchor, qr.offset_x, qr.offset_y,
                          qr.width, qr.height),
                         ([0], 'BL', 40.0, 30.0, 90.0, 90.0))
        self.assertEqual((barcode.pages, barcode.anchor, barcode.offset_x,
                          barcode.offset_y, barcode.width, barcode.height),
                         ([1], 'BL', 200.0, 30.0, 220.0, 60.0))

    def test_certify_document_gets_the_received_payload(self):
        with mock.patch(CERTIFY, wraps=external.certify_document) as certify:
            self.issued()

        kwargs = certify.call_args.kwargs

        self.assertEqual(kwargs['qr_payload'], QR_URL)
        self.assertIsNotNone(kwargs['specs_builder'])
        self.assertEqual(kwargs['options'].custom_text, BARCODE)

    def test_the_certified_file_has_the_two_images_on_their_pages(self):
        from pypdf import PdfReader

        body = self.issued()
        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])

        with document.document_file.open('rb') as handle:
            reader = PdfReader(io.BytesIO(handle.read()))

        def images(page):
            resources = page.get('/Resources') or {}
            xobjects = (resources.get('/XObject') or {}).get_object()
            return [
                name for name, item in xobjects.items()
                if item.get_object().get('/Subtype') == '/Image'
            ]

        self.assertEqual(len(images(reader.pages[0])), 1)
        self.assertEqual(len(images(reader.pages[1])), 1)

    def test_gea_keeps_the_certified_original_too(self):
        body = self.issued()
        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])

        self.assertTrue(document.source_file)
        self.assertTrue(document.document_file)
        self.assertTrue(document.document_hash)
        self.assertNotEqual(document.document_hash, document.source_hash)


class TestPublicCopy(ExternalTestCase):

    def download(self, body, **headers):
        return self.client.get(
            reverse('certificates:external_public_copy',
                    kwargs={'document_id': body['document_id']}),
            **(headers or self.headers()),
        )

    def test_it_downloads_with_the_key(self):
        body = self.issued()
        response = self.download(body)

        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['Content-Type'], 'application/pdf')

        data = b''.join(response.streaming_content)

        self.assertEqual(sha256_hex(data), body['public_copy_hash'])

    def test_it_needs_the_key(self):
        body = self.issued()

        self.assertEqual(
            self.download(body, HTTP_X_ISSUER='propensiones').status_code, 403)
        self.assertEqual(
            self.download(body, **self.headers(key='x' * 48)).status_code, 403)

    def test_another_issuer_gets_404(self):
        body = self.issued()

        response = self.download(body, **self.headers('otro', OTHER_KEY))

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_document_gets_404(self):
        response = self.client.get(
            reverse('certificates:external_public_copy',
                    kwargs={'document_id': 'b3b1c1c0-0000-4000-8000-000000000000'}),
            **self.headers())

        self.assertEqual(response.status_code, 404)

    def test_gea_verification_recognises_it_by_fingerprint(self):
        body = self.issued()
        data = b''.join(self.download(body).streaming_content)

        match = identify_uploaded_document(data)

        self.assertIsNotNone(match)
        self.assertEqual(str(match.document.pk), body['document_id'])
        self.assertEqual(match.copy_kind, DocumentCopyKind.PUBLIC_COPY)
        self.assertEqual(match.match_level, MATCH_EXACT)
        self.assertTrue(match.is_valid)

    def test_the_copy_carries_the_hidden_watermark(self):
        body = self.issued()
        data = b''.join(self.download(body).streaming_content)

        self.assertEqual(read_watermark_reference(data), body['document_id'])


class TestRevocation(ExternalTestCase):

    def revoke(self, body, reason=None, **headers):
        data = {'reason': reason} if reason is not None else {}
        return self.client.post(
            reverse('certificates:external_revoke',
                    kwargs={'document_id': body['document_id']}),
            data, **(headers or self.headers()),
        )

    def test_revoking_marks_the_document(self):
        body = self.issued()
        response = self.revoke(body, 'Emitido por error')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'REVOKED')

        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])

        self.assertEqual(
            document.certification_status, CertificationStatusChoices.REVOKED)
        self.assertEqual(document.revocation_reason, 'Emitido por error')
        self.assertIsNotNone(document.revoked_at)

    def test_the_public_verification_shows_it_as_revoked(self):
        body = self.issued()
        self.revoke(body)

        user = UserModel.objects.create_user(
            username='viewer', email='viewer@example.com', password='pw-123-x')
        self.client.force_login(user)

        response = self.client.get(reverse(
            'certificates:detail_document_verification_aegis',
            kwargs={'pk': body['document_id']}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['record_status'], 'REVOKED')
        self.assertEqual(response.context['record_status_class'], 'danger')
        self.assertContains(response, 'alert alert-danger shadow-sm')
        # La etiqueta sale traducida: se busca la que la vista puso.
        self.assertContains(
            response,
            'badge bg-danger float-end">%s</span>'
            % response.context['record_status_label'])

    def test_it_is_idempotent(self):
        body = self.issued()
        self.revoke(body, 'primer motivo')
        first = DocumentVerificationModel.objects.get(
            pk=body['document_id']).revoked_at

        again = self.revoke(body, 'otro motivo')

        self.assertEqual(again.status_code, 200)

        document = DocumentVerificationModel.objects.get(
            pk=body['document_id'])
        self.assertEqual(document.revoked_at, first)
        self.assertEqual(document.revocation_reason, 'primer motivo')

    def test_the_reason_is_optional(self):
        body = self.issued()

        self.assertEqual(self.revoke(body).status_code, 200)

    def test_another_issuer_cannot_revoke(self):
        body = self.issued()

        response = self.revoke(body, **self.headers('otro', OTHER_KEY))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            DocumentVerificationModel.objects.get(
                pk=body['document_id']).certification_status,
            CertificationStatusChoices.CERTIFIED)

    def test_it_needs_the_key(self):
        body = self.issued()

        self.assertEqual(
            self.revoke(body, **self.headers(key='x' * 48)).status_code, 403)

    def test_get_is_not_allowed(self):
        body = self.issued()
        response = self.client.get(
            reverse('certificates:external_revoke',
                    kwargs={'document_id': body['document_id']}),
            **self.headers())

        self.assertEqual(response.status_code, 405)


class TestSystemCheck(ExternalTestCase):

    def run_check(self, issuers, debug):
        with override_settings(GEA_EXTERNAL_ISSUERS=issuers, DEBUG=debug):
            return check_external_issuer_keys()

    def test_a_short_key_is_an_error_without_debug(self):
        errors = self.run_check({'x': {'name': 'X', 'key': 'corta'}}, False)

        self.assertEqual([e.id for e in errors], ['gea.E001'])
        self.assertIsInstance(errors[0], checks.Error)

    def test_a_short_key_is_tolerated_with_debug(self):
        self.assertEqual(
            self.run_check({'x': {'name': 'X', 'key': 'corta'}}, True), [])

    def test_no_key_is_just_disabled(self):
        self.assertEqual(
            self.run_check({'x': {'name': 'X', 'key': ''}}, False), [])

    def test_a_long_key_is_fine(self):
        self.assertEqual(
            self.run_check({'x': {'name': 'X', 'key': 'k' * 32}}, False), [])
