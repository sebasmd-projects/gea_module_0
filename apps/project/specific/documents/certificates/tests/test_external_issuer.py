# apps/project/specific/documents/certificates/tests/test_external_issuer.py
"""
Certificacion para emisores externos: autenticacion, cupo, idempotencia,
estampado, copia distribuible y revocacion.

Los emisores son filas de ``ExternalIssuerModel`` (antes, un diccionario de
``settings``): cada prueba los crea en la base de datos. ``propensiones`` ya
existe de antes --lo crea la migracion de datos--, asi que se actualiza en vez
de crearse.

No hay decodificador de QR ni de Code128 en el entorno, asi que lo que se
comprueba del estampado son los argumentos: con que texto se renderizan los
dos simbolos y en que posicion se estampan.

    manage.py test apps.project.specific.documents.certificates.tests.test_external_issuer \\
        --settings=app_core.settings_test
"""

import importlib
import io
import json
import re
from unittest import mock

from auditlog.models import LogEntry
from django.apps import apps as django_apps
from django.core import checks
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from reportlab.pdfgen import canvas

from apps.common.utils.testing import login_with_otp
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
from ..admin import ExternalIssuerAdminForm
from ..models import (CertificationStatusChoices, DocumentCertificateTypeChoices,
                      DocumentCopyKind, DocumentVerificationModel,
                      ExternalIssuerKindChoices, ExternalIssuerModel)
from ..verification import MATCH_EXACT, identify_uploaded_document

KEY = 'k' * 48
OTHER_KEY = 'o' * 48

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


def make_issuer(slug, name, key=None, **fields):
    """Un emisor en la base de datos, con clave propia si se da una."""
    issuer = ExternalIssuerModel(slug=slug, name=name, **fields)

    if key:
        issuer.set_key(key)

    issuer.save()
    return issuer


def a_logo() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGBA', (32, 32), (200, 30, 30, 255)).save(buffer, 'PNG')
    return buffer.getvalue()


# `propensiones` usa SERVER_KEY, que en el entorno de pruebas puede ser
# cualquier cosa (o estar vacia): se fija aqui.
@override_settings(SERVER_KEY=KEY)
class ExternalTestCase(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.pdf = a_pdf()

        # Existe desde la migracion de datos; se deja como lo dejaria el admin.
        self.propensiones, _ = ExternalIssuerModel.objects.update_or_create(
            slug='propensiones',
            defaults={
                'name': 'Propensiones Abogados',
                'kind': ExternalIssuerKindChoices.GROUP,
                'uses_server_key': True,
                'is_active': True,
            },
        )
        self.other = make_issuer('otro', 'Otro', OTHER_KEY)
        self.off = make_issuer('apagado', 'Sin clave')

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
        self.propensiones.issue_limit_per_hour = 2
        self.propensiones.save()

        self.assertEqual(self.issue(idempotency_key='a').status_code, 201)
        self.assertEqual(self.issue(idempotency_key='b').status_code, 201)
        self.assertEqual(self.issue(idempotency_key='c').status_code, 429)

        # El cupo es del emisor, no compartido con los demas.
        other = self.issue(issuer='otro', key=OTHER_KEY, idempotency_key='c')
        self.assertEqual(other.status_code, 201)

    def test_each_issuer_has_its_own_limits(self):
        self.propensiones.issue_limit_per_hour = 1
        self.propensiones.save()
        self.other.issue_limit_per_hour = 3
        self.other.save()

        codes = [
            self.issue(idempotency_key=f'p{n}').status_code
            for n in range(3)
        ]
        others = [
            self.issue(issuer='otro', key=OTHER_KEY,
                       idempotency_key=f'o{n}').status_code
            for n in range(4)
        ]

        self.assertEqual(codes, [201, 429, 429])
        self.assertEqual(others, [201, 201, 201, 429])

    def test_the_access_quota_is_separate_from_the_issue_quota(self):
        body = self.issued()
        self.propensiones.access_limit_per_hour = 1
        self.propensiones.save()

        url = reverse('certificates:external_public_copy',
                      kwargs={'document_id': body['document_id']})

        self.assertEqual(self.client.get(url, **self.headers()).status_code,
                         200)
        self.assertEqual(self.client.get(url, **self.headers()).status_code,
                         429)

    def test_changing_the_limit_in_the_admin_applies_without_losing_the_count(
            self):
        self.assertEqual(self.issue(idempotency_key='a').status_code, 201)
        self.assertEqual(self.issue(idempotency_key='b').status_code, 201)

        self.propensiones.issue_limit_per_hour = 2
        self.propensiones.save()
        self.assertEqual(self.issue(idempotency_key='c').status_code, 429)

        self.propensiones.issue_limit_per_hour = 10
        self.propensiones.save()
        self.assertEqual(self.issue(idempotency_key='c').status_code, 201)

    def test_a_dead_cache_answers_429(self):
        with dead_cache():
            response = self.issue()

        self.assertEqual(response.status_code, 429)
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_bad_keys_do_not_spend_the_issuer_quota(self):
        self.propensiones.issue_limit_per_hour = 1
        self.propensiones.save()

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
    """Los issuers estan en la base de datos: el check solo mira SERVER_KEY."""

    def run_check(self, key, debug, **extra):
        with override_settings(SERVER_KEY=key, DEBUG=debug, **extra):
            return check_external_issuer_keys()

    def test_a_short_server_key_is_an_error_without_debug(self):
        errors = self.run_check('corta', False)

        self.assertEqual([e.id for e in errors], ['gea.E001'])
        self.assertIsInstance(errors[0], checks.Error)

    def test_a_short_server_key_is_tolerated_with_debug(self):
        self.assertEqual(self.run_check('corta', True), [])

    def test_no_server_key_is_just_disabled(self):
        self.assertEqual(self.run_check('', False), [])

    def test_a_long_server_key_is_fine(self):
        self.assertEqual(self.run_check('k' * 32, False), [])

    def test_it_does_not_touch_the_database(self):
        with self.assertNumQueries(0):
            self.run_check('k' * 32, False)

    def test_a_legacy_variable_in_use_warns(self):
        problems = self.run_check(
            'k' * 32, False,
            SERVER_KEY_LEGACY_VARS_IN_USE=['GEA_ISSUER_KEY_PROPENSIONES'])

        self.assertEqual([e.id for e in problems], ['gea.W001'])
        self.assertIsInstance(problems[0], checks.Warning)

    def test_the_issuers_are_no_longer_a_setting(self):
        from django.conf import settings

        self.assertFalse(hasattr(settings, 'GEA_EXTERNAL_ISSUERS'))


class TestKeyIsNeverStored(ExternalTestCase):

    def test_only_the_hash_and_the_last_four_characters_are_kept(self):
        issuer = make_issuer('nuevo', 'Nuevo', 'secreto-' + 'z' * 40)

        row = ExternalIssuerModel.objects.filter(pk=issuer.pk).values().get()

        self.assertNotIn('secreto-', ' '.join(str(v) for v in row.values()))
        self.assertEqual(len(row['key_hash']), 64)
        self.assertEqual(row['key_hint'], 'zzzz')
        self.assertIsNotNone(row['key_rotated_at'])

    def test_the_hash_is_not_a_bare_sha256_of_the_key(self):
        import hashlib

        issuer = make_issuer('nuevo', 'Nuevo', 'q' * 48)

        self.assertNotEqual(
            issuer.key_hash, hashlib.sha256(b'q' * 48).hexdigest())

    def test_the_hash_does_not_reach_the_audit_history(self):
        issuer = make_issuer('nuevo', 'Nuevo', 'h' * 48)
        issuer.set_key('i' * 48)
        issuer.save()

        entries = LogEntry.objects.get_for_object(issuer)
        dump = ' '.join(f'{e.changes} {e.serialized_data}' for e in entries)

        self.assertGreaterEqual(entries.count(), 2)
        self.assertNotIn(issuer.key_hash, dump)
        self.assertNotIn('h' * 48, dump)
        self.assertNotIn('i' * 48, dump)
        self.assertNotIn('key_hash', dump)

    def test_a_short_key_is_refused(self):
        with self.assertRaises(ValidationError):
            ExternalIssuerModel(slug='x', name='X').set_key('corta')

    def test_the_right_key_checks_and_a_wrong_one_does_not(self):
        issuer = make_issuer('nuevo', 'Nuevo', 'a' * 48)

        self.assertTrue(issuer.check_key('a' * 48))
        self.assertFalse(issuer.check_key('a' * 47))
        self.assertFalse(issuer.check_key(''))
        self.assertFalse(issuer.check_key(None))


class TestIssuerStates(ExternalTestCase):

    def forbidden(self, **kwargs):
        response = self.issue(**kwargs)
        self.assertEqual(response.status_code, 403, response.content)
        return response

    def test_an_inactive_issuer_gets_the_same_403_as_a_wrong_key(self):
        self.other.is_active = False
        self.other.save()

        wrong = self.forbidden(key='x' * 48)
        inactive = self.forbidden(issuer='otro', key=OTHER_KEY)
        unknown = self.forbidden(issuer='nadie', key=OTHER_KEY)

        self.assertEqual(wrong.content, inactive.content)
        self.assertEqual(wrong.content, unknown.content)
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_an_issuer_without_key_gets_the_same_403(self):
        no_key = self.forbidden(issuer='apagado', key=OTHER_KEY)
        wrong = self.forbidden(key='x' * 48)

        self.assertEqual(no_key.content, wrong.content)

    def test_reactivating_an_issuer_lets_it_in_again(self):
        self.other.is_active = False
        self.other.save()
        self.forbidden(issuer='otro', key=OTHER_KEY)

        self.other.is_active = True
        self.other.save()

        self.assertEqual(
            self.issue(issuer='otro', key=OTHER_KEY).status_code, 201)

    def test_replacing_the_key_cuts_off_the_old_one(self):
        self.other.set_key('n' * 48)
        self.other.save()

        self.forbidden(issuer='otro', key=OTHER_KEY)
        self.assertEqual(
            self.issue(issuer='otro', key='n' * 48).status_code, 201)


class TestServerKey(ExternalTestCase):

    def test_it_authenticates_with_the_environment_key(self):
        self.assertEqual(self.issue(key=KEY).status_code, 201)

    def test_the_own_key_hash_is_ignored_while_it_uses_the_server_key(self):
        self.propensiones.set_key(OTHER_KEY)
        self.propensiones.save()

        self.assertEqual(self.issue(key=OTHER_KEY).status_code, 403)
        self.assertEqual(self.issue(key=KEY).status_code, 201)

    def test_without_a_server_key_it_cannot_authenticate(self):
        for empty in ('', None):
            with self.subTest(empty=empty), override_settings(SERVER_KEY=empty):
                self.assertEqual(self.issue(key='').status_code, 403)
                self.assertEqual(self.issue(key=KEY).status_code, 403)
                self.assertEqual(
                    self.issue(key='no-key-configured').status_code, 403)

    def test_changing_the_environment_key_applies_at_once(self):
        with override_settings(SERVER_KEY='r' * 48):
            self.assertEqual(self.issue(key=KEY).status_code, 403)
            self.assertEqual(self.issue(key='r' * 48).status_code, 201)

    def test_another_issuer_does_not_inherit_the_server_key(self):
        self.assertEqual(
            self.issue(issuer='otro', key=KEY).status_code, 403)

    def test_the_server_key_works_for_a_second_issuer_that_asks_for_it(self):
        make_issuer('hermana', 'Hermana', uses_server_key=True)

        self.assertEqual(
            self.issue(issuer='hermana', key=KEY).status_code, 201)


class TestIsolation(ExternalTestCase):

    def test_an_issuer_does_not_see_the_documents_of_another(self):
        mine = self.issued()
        theirs = self.issue(issuer='otro', key=OTHER_KEY,
                            idempotency_key='ajena')
        self.assertEqual(theirs.status_code, 201)
        theirs = theirs.json()

        for body, headers in (
            (theirs, self.headers()),
            (mine, self.headers('otro', OTHER_KEY)),
        ):
            copy = self.client.get(
                reverse('certificates:external_public_copy',
                        kwargs={'document_id': body['document_id']}),
                **headers)
            revoke = self.client.post(
                reverse('certificates:external_revoke',
                        kwargs={'document_id': body['document_id']}),
                {}, **headers)

            self.assertEqual(copy.status_code, 404)
            self.assertEqual(revoke.status_code, 404)

        for body in (mine, theirs):
            self.assertEqual(
                DocumentVerificationModel.objects.get(
                    pk=body['document_id']).certification_status,
                CertificationStatusChoices.CERTIFIED)

    def test_idempotency_keys_do_not_cross_issuers(self):
        mine = self.issued(idempotency_key='misma')
        theirs = self.issue(issuer='otro', key=OTHER_KEY,
                            idempotency_key='misma')

        self.assertEqual(theirs.status_code, 201)
        self.assertNotEqual(theirs.json()['document_id'], mine['document_id'])

    def test_documents_are_tagged_with_the_slug_of_their_issuer(self):
        theirs = self.issue(issuer='otro', key=OTHER_KEY).json()

        self.assertEqual(
            DocumentVerificationModel.objects.get(
                pk=theirs['document_id']).external_issuer, 'otro')


class TestDecorator(ExternalTestCase):

    def test_the_view_gets_the_authenticated_issuer(self):
        seen = {}

        @external.issuer_required('access')
        def view(request):
            seen['issuer'] = request.external_issuer
            return external._json({})

        from django.test import RequestFactory

        request = RequestFactory().get(
            '/x', HTTP_X_ISSUER='otro', HTTP_X_ISSUER_KEY=OTHER_KEY)

        self.assertEqual(view(request).status_code, 200)
        self.assertEqual(seen['issuer'], self.other)

    def test_the_view_does_not_run_without_authenticating(self):
        calls = []

        @external.issuer_required('issue')
        def view(request):
            calls.append(1)
            return external._json({})

        from django.test import RequestFactory

        request = RequestFactory().get('/x', HTTP_X_ISSUER='otro')

        self.assertEqual(view(request).status_code, 403)
        self.assertEqual(calls, [])

    def test_an_unknown_kind_is_refused_when_decorating(self):
        with self.assertRaises(ValueError):
            external.issuer_required('nope')


class TestQrHosts(ExternalTestCase):

    def allow(self, hosts):
        self.propensiones.allowed_qr_hosts = hosts
        self.propensiones.save()

    def test_without_a_list_any_https_url_goes(self):
        self.issued(qr_payload='https://cualquiera.example/a')

    def test_with_a_list_only_those_hosts_go(self):
        self.allow('propensionesabogados.com\nverify.example.org\n')

        self.issued(qr_payload='https://propensionesabogados.com/v/1')
        self.issued(qr_payload='https://VERIFY.example.org/v/2',
                    idempotency_key='k2')

    def test_another_host_is_a_400_on_qr_payload(self):
        self.allow('propensionesabogados.com')

        response = self.issue(qr_payload='https://otro.example/v/1')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['field'], 'qr_payload')
        self.assertFalse(DocumentVerificationModel.objects.exists())

    def test_tricks_do_not_get_through(self):
        self.allow('propensionesabogados.com')

        for url in (
            'https://propensionesabogados.com.malo.example/x',
            'https://malo.example/propensionesabogados.com',
            'https://propensionesabogados.com@malo.example/x',
            'https://malopropensionesabogados.com/x',
            'https://sub.propensionesabogados.com/x',
        ):
            with self.subTest(url=url):
                self.assertEqual(
                    self.issue(qr_payload=url).status_code, 400)

    def test_the_list_is_the_issuers_own(self):
        self.allow('propensionesabogados.com')

        response = self.issue(
            issuer='otro', key=OTHER_KEY, qr_payload='https://x.example/a')

        self.assertEqual(response.status_code, 201)

    def test_a_retry_still_answers_before_checking_the_hosts(self):
        first = self.issued()
        self.allow('propensionesabogados.com')

        again = self.issue(qr_payload='https://otro.example/v/1')

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first)

    def test_the_admin_form_refuses_what_is_not_a_host(self):
        for bad in ('https://x.com', 'x.com/path', 'a b.com', 'user@x.com'):
            with self.subTest(bad=bad):
                self.propensiones.allowed_qr_hosts = bad

                with self.assertRaises(ValidationError) as caught:
                    self.propensiones.full_clean()

                self.assertIn('allowed_qr_hosts', caught.exception.message_dict)


class TestIssuerLogo(ExternalTestCase):

    def give_logo(self, issuer):
        issuer.qr_logo.save('logo.png', ContentFile(a_logo()), save=True)

    def test_the_issuer_logo_reaches_the_qr_renderer(self):
        self.give_logo(self.propensiones)

        with mock.patch.object(
                external, 'render_qr_png',
                wraps=external.render_qr_png) as qr:
            self.issued()

        qr.assert_called_once_with(QR_URL, logo_bytes=a_logo())

    def test_without_a_logo_it_is_the_default_one(self):
        with mock.patch.object(
                external, 'render_qr_png',
                wraps=external.render_qr_png) as qr:
            self.issued()

        qr.assert_called_once_with(QR_URL)

    def test_the_logo_of_one_issuer_is_not_used_for_another(self):
        self.give_logo(self.propensiones)

        with mock.patch.object(
                external, 'render_qr_png',
                wraps=external.render_qr_png) as qr:
            self.issue(issuer='otro', key=OTHER_KEY)

        qr.assert_called_once_with(QR_URL)

    def test_a_logo_that_vanished_from_disk_does_not_stop_the_issuing(self):
        self.give_logo(self.propensiones)
        self.propensiones.qr_logo.storage.delete(self.propensiones.qr_logo.name)

        with mock.patch.object(
                external, 'render_qr_png',
                wraps=external.render_qr_png) as qr:
            self.issued()

        qr.assert_called_once_with(QR_URL)

    def test_a_huge_logo_is_refused(self):
        issuer = make_issuer('grande', 'Grande')
        issuer.qr_logo.save(
            'logo.png', ContentFile(b'0' * (1024 * 1024 + 1)), save=False)

        with self.assertRaises(ValidationError) as caught:
            issuer.full_clean()

        self.assertIn('qr_logo', caught.exception.message_dict)

    def test_the_issuer_logo_is_really_printed_in_the_certificate(self):
        # Sin mock: el QR con logo del emisor se estampa y el PDF sale bien.
        self.give_logo(self.propensiones)

        self.assertEqual(self.issue().status_code, 201)


class TestCertificateType(ExternalTestCase):

    def test_the_default_is_generic(self):
        body = self.issued()

        self.assertEqual(
            DocumentVerificationModel.objects.get(
                pk=body['document_id']).certificate_type,
            DocumentCertificateTypeChoices.GENERIC)

    def test_it_comes_from_the_issuer(self):
        self.other.default_certificate_type = DocumentCertificateTypeChoices.AEGIS
        self.other.save()

        body = self.issue(issuer='otro', key=OTHER_KEY).json()

        self.assertEqual(
            DocumentVerificationModel.objects.get(
                pk=body['document_id']).certificate_type,
            DocumentCertificateTypeChoices.AEGIS)


class TestSlugIsFrozenOnceUsed(ExternalTestCase):

    def test_with_documents_the_slug_cannot_change(self):
        self.issued()
        self.propensiones.slug = 'propensiones-2'

        with self.assertRaises(ValidationError) as caught:
            self.propensiones.full_clean()

        self.assertIn('slug', caught.exception.message_dict)

    def test_a_direct_save_cannot_orphan_the_documents_either(self):
        self.issued()
        self.propensiones.slug = 'propensiones-2'

        with self.assertRaises(ValidationError):
            self.propensiones.save()

        self.assertTrue(ExternalIssuerModel.objects.filter(
            slug='propensiones').exists())

    def test_without_documents_it_can_change(self):
        self.other.slug = 'otro-2'
        self.other.full_clean()
        self.other.save()

        self.assertEqual(
            self.issue(issuer='otro-2', key=OTHER_KEY).status_code, 201)

    def test_other_fields_can_change_with_documents(self):
        self.issued()
        self.propensiones.name = 'Propensiones S.A.S.'
        self.propensiones.full_clean()
        self.propensiones.save()

    def test_a_slug_is_unique(self):
        with self.assertRaises(ValidationError):
            ExternalIssuerModel(slug='otro', name='Repetido').full_clean()


class TestDataMigration(ExternalTestCase):

    migration = importlib.import_module(
        'apps.project.specific.documents.certificates.migrations.'
        '0012_create_propensiones_issuer')

    def test_propensiones_exists_after_migrating(self):
        # La base de pruebas sale de las migraciones: lo que haya aqui lo puso
        # la 0012, no esta prueba (su `setUp` solo lo deja como el admin).
        ExternalIssuerModel.objects.all().delete()
        self.migration.create_propensiones(django_apps, None)

        issuer = ExternalIssuerModel.objects.get(slug='propensiones')

        self.assertEqual(issuer.name, 'Propensiones Abogados')
        self.assertEqual(issuer.kind, ExternalIssuerKindChoices.GROUP)
        self.assertTrue(issuer.uses_server_key)
        self.assertTrue(issuer.is_active)
        self.assertEqual(issuer.key_hash, '')
        self.assertEqual(issuer.issue_limit_per_hour, 60)
        self.assertEqual(issuer.access_limit_per_hour, 300)

    def test_it_is_idempotent_and_does_not_overwrite_a_hand_edit(self):
        self.propensiones.name = 'Cambiado a mano'
        self.propensiones.issue_limit_per_hour = 7
        self.propensiones.save()

        self.migration.create_propensiones(django_apps, None)

        self.assertEqual(
            ExternalIssuerModel.objects.filter(slug='propensiones').count(), 1)
        issuer = ExternalIssuerModel.objects.get(slug='propensiones')
        self.assertEqual(issuer.name, 'Cambiado a mano')
        self.assertEqual(issuer.issue_limit_per_hour, 7)

    def test_propensiones_authenticates_with_server_key_right_after(self):
        ExternalIssuerModel.objects.all().delete()
        self.migration.create_propensiones(django_apps, None)

        self.assertEqual(self.issue().status_code, 201)


class TestAdmin(ExternalTestCase):

    def setUp(self):
        super().setUp()

        from apps.project.common.users.models import UserModel

        self.superuser = UserModel.objects.create_user(
            username='root', email='root@example.com', password='pw-123-xx',
            is_staff=True, is_superuser=True)
        self.changelist = reverse(
            'admin:certificates_externalissuermodel_changelist')

    def generate(self, *issuers):
        return self.client.post(
            self.changelist,
            {'action': 'action_generate_issuer_key',
             '_selected_action': [str(i.pk) for i in issuers]},
            follow=True,
        )

    def test_generating_a_key_shows_it_once_and_stores_only_the_hash(self):
        login_with_otp(self.client, self.superuser)

        response = self.generate(self.other)
        shown = re.findall(r'<code>([^<]+)</code>', response.content.decode())

        self.assertEqual(len(shown), 1)

        raw = shown[0]
        self.other.refresh_from_db()

        self.assertGreaterEqual(len(raw), 32)
        self.assertNotEqual(self.other.key_hash, raw)
        self.assertNotIn(raw, ' '.join(
            str(v) for v in ExternalIssuerModel.objects.filter(
                pk=self.other.pk).values().get().values()))
        self.assertEqual(self.other.key_hint, raw[-4:])
        self.assertTrue(self.other.check_key(raw))

        # Una vez: al volver a abrir el listado ya no esta.
        again = self.client.get(self.changelist)
        self.assertNotContains(again, raw)

        # ... ni tampoco en la ficha.
        detail = self.client.get(reverse(
            'admin:certificates_externalissuermodel_change',
            args=[self.other.pk]))
        self.assertNotContains(detail, raw)
        self.assertNotContains(detail, self.other.key_hash)

    def test_the_new_key_replaces_the_old_one(self):
        login_with_otp(self.client, self.superuser)

        raw = re.findall(
            r'<code>([^<]+)</code>',
            self.generate(self.other).content.decode())[0]

        self.assertEqual(
            self.issue(issuer='otro', key=OTHER_KEY).status_code, 403)
        self.assertEqual(
            self.issue(issuer='otro', key=raw).status_code, 201)

    def test_an_issuer_without_a_key_can_get_one(self):
        login_with_otp(self.client, self.superuser)

        raw = re.findall(
            r'<code>([^<]+)</code>',
            self.generate(self.off).content.decode())[0]

        self.assertEqual(
            self.issue(issuer='apagado', key=raw).status_code, 201)

    def test_an_issuer_on_the_server_key_cannot_get_one_generated(self):
        login_with_otp(self.client, self.superuser)

        response = self.generate(self.propensiones)
        self.propensiones.refresh_from_db()

        self.assertNotContains(response, '<code>')
        self.assertContains(response, 'SERVER_KEY')
        self.assertEqual(self.propensiones.key_hash, '')
        self.assertIsNone(self.propensiones.key_rotated_at)
        self.assertEqual(self.issue().status_code, 201)

    def test_the_list_shows_the_state_of_the_key_and_the_documents(self):
        login_with_otp(self.client, self.superuser)
        self.issued()

        response = self.client.get(self.changelist)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)

        chunks = html.split('<tr>')
        rows = {
            slug: next(c for c in chunks if f'field-slug">{slug}<' in c)
            for slug in ('propensiones', 'otro', 'apagado')
        }

        self.assertIn('SERVER_KEY', rows['propensiones'])
        self.assertIn('...oooo', rows['otro'])
        self.assertNotIn('oooo', rows['propensiones'])
        self.assertIn('cannot authenticate', rows['apagado'])

        def documents(row):
            return re.search(
                r'field-documents_issued">\s*([^<\s]+)\s*<', row).group(1)

        self.assertEqual(documents(rows['propensiones']), '1')
        self.assertEqual(documents(rows['otro']), '0')

    def change_data(self, issuer, **changes):
        data = {
            'name': issuer.name, 'slug': issuer.slug, 'kind': issuer.kind,
            'contact_email': '', 'is_active': 'on', 'notes': '',
            'issue_limit_per_hour': 60, 'access_limit_per_hour': 300,
            'default_certificate_type': issuer.default_certificate_type,
            'allowed_qr_hosts': '', 'new_key': '',
        }
        data.update(changes)
        return {k: v for k, v in data.items() if v is not None}

    def test_a_key_typed_in_the_form_is_hashed(self):
        login_with_otp(self.client, self.superuser)
        typed = 't' * 40

        response = self.client.post(
            reverse('admin:certificates_externalissuermodel_change',
                    args=[self.other.pk]),
            self.change_data(self.other, new_key=typed),
        )

        self.assertEqual(response.status_code, 302, response.content[:2000])
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_key(typed))
        self.assertNotEqual(self.other.key_hash, typed)
        self.assertEqual(self.other.key_hint, typed[-4:])
        self.assertFalse(self.other.check_key(OTHER_KEY))

    def test_the_form_never_prints_a_key_back(self):
        login_with_otp(self.client, self.superuser)

        response = self.client.post(
            reverse('admin:certificates_externalissuermodel_change',
                    args=[self.other.pk]),
            self.change_data(self.other, new_key='corta'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'value="corta"')
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_key(OTHER_KEY))

    def test_leaving_the_key_empty_keeps_the_current_one(self):
        login_with_otp(self.client, self.superuser)

        self.client.post(
            reverse('admin:certificates_externalissuermodel_change',
                    args=[self.other.pk]),
            self.change_data(self.other, name='Otro S.A.', new_key=''),
        )

        self.other.refresh_from_db()
        self.assertEqual(self.other.name, 'Otro S.A.')
        self.assertTrue(self.other.check_key(OTHER_KEY))

    def test_a_key_is_refused_for_an_issuer_on_the_server_key(self):
        form = ExternalIssuerAdminForm(
            data=self.change_data(
                self.propensiones, new_key='k' * 40, uses_server_key='on'),
            instance=self.propensiones,
        )

        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_the_slug_is_read_only_once_there_are_documents(self):
        login_with_otp(self.client, self.superuser)
        self.issued()

        url = reverse('admin:certificates_externalissuermodel_change',
                      args=[self.propensiones.pk])
        html = self.client.get(url).content.decode()

        self.assertNotIn('name="slug"', html)

        html = self.client.get(reverse(
            'admin:certificates_externalissuermodel_change',
            args=[self.other.pk])).content.decode()

        self.assertIn('name="slug"', html)

    def test_it_cannot_be_exported_with_the_hash_in_it(self):
        # No hereda de `GeneralAdminModel`, que trae importar y exportar: la
        # exportacion sacaria `key_hash` a un CSV.
        from django.contrib import admin as django_admin

        model_admin = django_admin.site._registry[ExternalIssuerModel]

        self.assertFalse(hasattr(model_admin, 'get_export_queryset'))

    def test_a_visitor_and_an_ordinary_user_get_a_404(self):
        from apps.project.common.users.models import UserModel

        self.assertEqual(self.client.get(self.changelist).status_code, 404)

        user = UserModel.objects.create_user(
            username='cliente', email='c@example.com', password='pw-123-xx')
        login_with_otp(self.client, user)

        self.assertEqual(self.client.get(self.changelist).status_code, 404)

        response = self.generate(self.other)
        self.assertEqual(response.status_code, 404)

        self.other.refresh_from_db()
        self.assertTrue(self.other.check_key(OTHER_KEY))

    def test_staff_without_the_second_factor_cannot_generate_keys(self):
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.changelist,
            {'action': 'action_generate_issuer_key',
             '_selected_action': [str(self.other.pk)]})

        self.assertNotEqual(response.status_code, 200)
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_key(OTHER_KEY))

    def test_staff_without_permission_on_the_model_cannot_generate_keys(self):
        from apps.project.common.users.models import UserModel

        staff = UserModel.objects.create_user(
            username='operador', email='o@example.com', password='pw-123-xx',
            is_staff=True)
        login_with_otp(self.client, staff)

        response = self.generate(self.other)

        self.assertIn(response.status_code, (403, 404))
        self.other.refresh_from_db()
        self.assertTrue(self.other.check_key(OTHER_KEY))


class TestIssuedBy(ExternalTestCase):

    def detail(self, document_id):
        from apps.project.common.users.models import UserModel

        user = UserModel.objects.create_user(
            username='viewer', email='viewer@example.com', password='pw-123-x')
        self.client.force_login(user)

        return self.client.get(reverse(
            'certificates:detail_document_verification_aegis',
            kwargs={'pk': document_id}))

    def test_the_detail_page_names_the_issuer(self):
        self.other.name = 'Fundacion Atlas'
        self.other.save()

        body = self.issue(issuer='otro', key=OTHER_KEY).json()
        response = self.detail(body['document_id'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['external_issuer_name'],
                         'Fundacion Atlas')
        self.assertContains(response, 'Issued by:')
        self.assertContains(response, 'Fundacion Atlas')

    def test_an_issuer_that_was_removed_falls_back_to_the_slug(self):
        body = self.issue(issuer='otro', key=OTHER_KEY).json()
        self.other.delete()

        response = self.detail(body['document_id'])

        self.assertEqual(response.context['external_issuer_name'], 'otro')

    def test_a_deactivated_issuer_still_shows_its_name(self):
        body = self.issued()
        self.propensiones.is_active = False
        self.propensiones.save()

        response = self.detail(body['document_id'])

        self.assertEqual(response.context['external_issuer_name'],
                         'Propensiones Abogados')

    def test_a_document_issued_by_gea_itself_says_nothing(self):
        document = DocumentVerificationModel.objects.create(
            document_title='Propio', certificate_type='GENERIC',
            issued_at='2026-01-01')

        response = self.detail(document.pk)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['external_issuer_name'], '')
        self.assertNotContains(response, 'Issued by:')
