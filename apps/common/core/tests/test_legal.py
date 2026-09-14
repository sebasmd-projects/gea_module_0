# apps/common/core/tests/test_legal.py
"""
Los documentos legales: aprobar, publicar y dejar constancia de quien acepto.

Los cuatro textos vivian en plantillas con su contenido dentro de `{% trans %}`.
Eso dejaba tres agujeros, y los tres eran de cumplimiento:

* cambiar una coma exigia un despliegue, asi que el texto vigente dependia de
  que quien lo redacta encontrara a quien lo despliega;
* el estado «borrador» estaba escrito **en dos sitios** --un recuadro dentro de
  la plantilla y un sufijo en `settings.py`-- que nada obligaba a mantener de
  acuerdo;
* y no habia forma de demostrar **que texto** acepto nadie, que es exactamente
  lo que obliga a conservar el articulo 9 de la Ley 1581 de 2012.

Lo que se fija aqui:

- Una version aprobada **no se edita**. Se aprueba otra.
- Aprobar deja quien, cuando, desde cuando y con que huella, y la base se niega
  a guardar una aprobada sin fecha o sin huella aunque no se pase por
  `approve()`.
- La aceptacion guarda **la huella**, no una referencia a secas: es lo unico
  que sigue probando algo si el texto cambia despues.
- **Entrar no acepta lo que no se ha avisado.** Aceptacion por conducta sin
  aviso previo no es aceptacion; el aviso va primero y este orden es el
  invariante, no un detalle de implementacion.
- Lo que se publica se **sanea**: son paginas publicas y el editor tiene boton
  de codigo fuente.

Nada de aqui sale a internet.

    manage.py test apps.common.core.tests.test_legal \\
        --settings=app_core.settings_test
"""

import io

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.common.utils.testing import login_with_otp
from apps.project.common.users.models import UserModel

from ..legal import (accept_on_login, accept_on_registration, pending_for,
                     record_acceptance)
from ..legal_html import sanitize_legal_html
from ..legal_pdf import render_document_pdf
from ..models import (AcceptanceMethod, LegalAcceptanceModel,
                      LegalDocumentModel, LegalDocumentVersionModel,
                      LegalVersionStatus)

PASSWORD = 'pw-para-pruebas-123'


class LegalBase(TestCase):
    """Los cuatro documentos ya existen: los crea la migracion de semilla."""

    def setUp(self):
        self.user = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD)
        self.staff = UserModel.objects.create_user(
            username='jefa', email='jefa@example.com', password=PASSWORD,
            is_staff=True)
        self.terms = LegalDocumentModel.objects.get(key='terms')

    def a_version(self, **extra):
        datos = {
            'document': self.terms,
            'version': '9.9.9',
            'es_body': '<p>Texto nuevo</p>',
            'en_body': '<p>New text</p>',
        }
        datos.update(extra)
        return LegalDocumentVersionModel.objects.create(**datos)


class SeedTestCase(LegalBase):
    """La semilla trae lo que ya estaba publicado, y como borrador."""

    def test_los_cuatro_documentos_estan(self):
        self.assertEqual(
            set(LegalDocumentModel.objects.values_list('key', flat=True)),
            {'terms', 'data_policy', 'privacy', 'cookies'},
        )

    def test_entran_como_borrador_y_con_texto_en_los_dos_idiomas(self):
        for documento in LegalDocumentModel.objects.all():
            version = documento.displayed_version()

            with self.subTest(documento.key):
                self.assertEqual(version.status, LegalVersionStatus.DRAFT)
                self.assertGreater(len(version.es_body), 500)
                self.assertGreater(len(version.en_body), 500)

    def test_un_borrador_tambien_lleva_huella(self):
        """
        Hace falta porque se puede aceptar un borrador: mientras no haya nada
        aprobado, es lo que el alta enseña, y una aceptacion sin huella no
        acredita **que** se acepto.
        """
        version = self.terms.displayed_version()

        self.assertEqual(len(version.content_hash), 64)
        self.assertEqual(version.content_hash, version.compute_hash())

    def test_nada_esta_vigente_todavia(self):
        """Nadie ha firmado: una migracion no puede firmar por un abogado."""
        self.assertIsNone(self.terms.current_version())


class ApprovalTestCase(LegalBase):

    def test_aprobar_deja_quien_cuando_y_con_que_huella(self):
        version = self.a_version()

        self.assertEqual(version.status, LegalVersionStatus.DRAFT)

        version.approve(user=self.staff)
        version.refresh_from_db()

        self.assertTrue(version.is_approved)
        self.assertEqual(version.approved_by, self.staff)
        self.assertIsNotNone(version.approved_at)
        self.assertEqual(version.effective_from, timezone.localdate())
        self.assertEqual(len(version.content_hash), 64)

    def test_una_version_aprobada_no_se_edita(self):
        version = self.a_version()
        version.approve(user=self.staff)

        version.es_body = '<p>Otra cosa</p>'

        with self.assertRaises(ValidationError):
            version.full_clean()

    def test_la_huella_se_congela_al_aprobar(self):
        """
        Si se recalculara en cada guardado, editar el texto despues cambiaria
        la huella de algo que alguien ya habia aceptado — que es justo lo que
        esta tabla existe para impedir.
        """
        version = self.a_version()
        version.approve(user=self.staff)
        huella = version.content_hash

        version.es_body = '<p>Otra cosa</p>'
        version.save(update_fields=['es_body'])
        version.refresh_from_db()

        self.assertEqual(version.content_hash, huella)

    def test_la_base_se_niega_a_una_aprobada_sin_fecha_ni_huella(self):
        """
        `approve()` no es el unico camino hasta una fila, asi que la regla
        tambien esta en la base — igual que las CheckConstraint del flujo de
        ordenes.
        """
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LegalDocumentVersionModel.objects.filter(
                    pk=self.a_version().pk
                ).update(status=LegalVersionStatus.APPROVED,
                         effective_from=None, content_hash='')

    def test_dos_versiones_no_pueden_llamarse_igual(self):
        self.a_version(version='2.0.0')

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.a_version(version='2.0.0')

    def test_la_vigente_es_la_aprobada_mas_reciente_ya_en_vigor(self):
        vieja = self.a_version(version='1.5.0')
        vieja.approve(user=self.staff)

        nueva = self.a_version(version='1.6.0')
        nueva.approve(user=self.staff)

        # Una aprobada para mañana todavia no manda.
        futura = self.a_version(version='1.7.0')
        futura.approve(
            user=self.staff,
            effective_from=timezone.localdate() + timezone.timedelta(days=1),
        )

        self.assertEqual(self.terms.current_version().pk, nueva.pk)


class AcceptanceTestCase(LegalBase):

    def test_el_alta_registra_los_cuatro_documentos_con_su_huella(self):
        filas = accept_on_registration(self.user)

        self.assertEqual(len(filas), 4)

        for fila in filas:
            with self.subTest(fila.version.document.key):
                self.assertEqual(fila.method, AcceptanceMethod.REGISTRATION)
                self.assertEqual(fila.content_hash, fila.version.content_hash)
                self.assertEqual(len(fila.content_hash), 64)

    def test_aceptar_dos_veces_es_una_sola_autorizacion(self):
        accept_on_registration(self.user)
        accept_on_registration(self.user)

        self.assertEqual(
            LegalAcceptanceModel.objects.filter(user=self.user).count(), 4)

    def test_la_constancia_guarda_desde_donde(self):
        """«Marco una casilla» no es constancia si no se guarda como."""
        peticion = self.client.request().wsgi_request
        peticion.META['HTTP_X_FORWARDED_FOR'] = '198.51.100.7, 10.0.0.1'
        peticion.META['HTTP_USER_AGENT'] = 'Navegador/1.0'

        fila = record_acceptance(
            self.user, self.terms.displayed_version(),
            AcceptanceMethod.REGISTRATION, peticion,
        )

        # La del cliente, no la del proxy: en produccion la aplicacion va
        # detras del servidor web y REMOTE_ADDR seria siempre la misma.
        self.assertEqual(fila.ip_address, '198.51.100.7')
        self.assertEqual(fila.user_agent, 'Navegador/1.0')

    def test_una_version_nueva_queda_pendiente(self):
        accept_on_registration(self.user)
        self.assertEqual(pending_for(self.user), [])

        nueva = self.a_version()
        nueva.approve(user=self.staff)

        self.assertEqual([v.pk for v in pending_for(self.user)], [nueva.pk])

    def test_entrar_no_acepta_lo_que_no_se_ha_avisado(self):
        """
        El invariante del consentimiento por conducta.

        Seguir usando la plataforma solo vale como aceptacion **si antes se
        aviso**. Sin el aviso no hay nada que el titular haya podido leer, y
        registrar su acceso como autorizacion seria darla por hecha.
        """
        accept_on_registration(self.user)

        nueva = self.a_version()
        nueva.approve(user=self.staff)

        self.assertEqual(accept_on_login(self.user), [])
        self.assertEqual(len(pending_for(self.user)), 1)

    def test_entrar_tras_el_aviso_si_acepta(self):
        accept_on_registration(self.user)

        nueva = self.a_version(change_note_es='Cambia el apartado 5.')
        nueva.approve(user=self.staff)

        call_command('notify_legal_changes', verbosity=0)

        filas = accept_on_login(self.user)

        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0].method, AcceptanceMethod.CONTINUED_USE)
        self.assertEqual(pending_for(self.user), [])

    def test_una_correccion_sin_aviso_se_acepta_al_entrar(self):
        """Lo que no requiere aviso no tiene que esperarlo."""
        accept_on_registration(self.user)

        menor = self.a_version(notify_users=False)
        menor.approve(user=self.staff)

        self.assertEqual(len(accept_on_login(self.user)), 1)

    def test_la_senal_del_login_lo_registra_sola(self):
        """No hay que acordarse de llamarla desde cada camino de acceso."""
        accept_on_registration(self.user)

        nueva = self.a_version(notify_users=False)
        nueva.approve(user=self.staff)

        self.client.force_login(self.user)

        self.assertTrue(
            LegalAcceptanceModel.objects.filter(
                user=self.user, version=nueva,
                method=AcceptanceMethod.CONTINUED_USE,
            ).exists()
        )


class NotificationTestCase(LegalBase):

    def test_avisa_una_vez_y_deja_constancia(self):
        version = self.a_version(change_note_es='Cambia el apartado 5.')
        version.approve(user=self.staff)

        call_command('notify_legal_changes', verbosity=0)
        version.refresh_from_db()

        self.assertEqual(len(mail.outbox), 2, 'los dos usuarios con correo')
        self.assertIsNotNone(version.notified_at)
        self.assertEqual(version.notified_count, 2)

        # Y no se repite: un aviso legal duplicado es peor que uno perdido.
        mail.outbox.clear()
        call_command('notify_legal_changes', verbosity=0)

        self.assertEqual(mail.outbox, [])

    def test_el_correo_dice_que_documento_y_que_cambio(self):
        version = self.a_version(change_note_es='Cambia el apartado 5.')
        version.approve(user=self.staff)

        call_command('notify_legal_changes', verbosity=0)
        cuerpo = mail.outbox[0].alternatives[0][0]

        self.assertIn('Cambia el apartado 5.', cuerpo)
        self.assertIn('/terms/', cuerpo)

    def test_en_seco_no_manda_ni_marca(self):
        version = self.a_version()
        version.approve(user=self.staff)

        call_command('notify_legal_changes', '--dry-run', verbosity=0)
        version.refresh_from_db()

        self.assertEqual(mail.outbox, [])
        self.assertIsNone(version.notified_at)

    def test_un_borrador_no_se_anuncia(self):
        self.a_version()

        call_command('notify_legal_changes', verbosity=0)

        self.assertEqual(mail.outbox, [])


class SanitizerTestCase(TestCase):
    """
    El texto se publica en paginas **publicas y sin autenticar**, y el editor
    tiene boton de codigo fuente. Sin sanear, perder una cuenta de personal
    seria un `<script>` en la cara de cada visitante.
    """

    def test_el_script_se_cae_pero_el_texto_se_queda(self):
        limpio = sanitize_legal_html(
            '<p>Antes<script>alert(1)</script>despues</p>'
        )

        self.assertNotIn('<script', limpio)
        self.assertIn('Antes', limpio)
        self.assertIn('despues', limpio)

    def test_los_manejadores_de_eventos_no_pasan(self):
        limpio = sanitize_legal_html('<p onclick="robar()">Hola</p>')

        self.assertNotIn('onclick', limpio)
        self.assertIn('Hola', limpio)

    def test_un_enlace_javascript_pierde_el_destino(self):
        limpio = sanitize_legal_html('<a href="javascript:alert(1)">Pulsa</a>')

        self.assertNotIn('javascript', limpio)
        self.assertIn('Pulsa', limpio)

    def test_un_enlace_normal_sobrevive(self):
        for destino in ('https://propensionesabogados.com', '/data-policy/',
                        'mailto:info@example.com', '#seccion-5'):
            with self.subTest(destino):
                self.assertIn(destino, sanitize_legal_html(
                    f'<a href="{destino}">x</a>'))

    def test_un_enlace_sin_esquema_a_otro_sitio_no(self):
        """`//otro.sitio` empieza por barra y aun asi se va fuera."""
        limpio = sanitize_legal_html('<a href="//evil.example">x</a>')

        self.assertNotIn('evil.example', limpio)

    def test_lo_que_hace_falta_para_el_texto_se_conserva(self):
        original = (
            '<h2>1. Titulo</h2><p>Con <b>negrita</b> y una '
            '<a href="/terms/">referencia</a>.</p>'
            '<table><tr><th>A</th><td>B</td></tr></table>'
        )
        limpio = sanitize_legal_html(original)

        for etiqueta in ('<h2>', '<p>', '<b>', '<a ', '<table>', '<th>', '<td>'):
            with self.subTest(etiqueta):
                self.assertIn(etiqueta, limpio)

    def test_una_etiqueta_sin_cerrar_no_se_come_el_resto(self):
        limpio = sanitize_legal_html('<p>Uno<p>Dos')

        self.assertIn('Uno', limpio)
        self.assertIn('Dos', limpio)


class PublicPagesTestCase(LegalBase):

    def test_las_cuatro_paginas_leen_de_la_base(self):
        for clave in ('terms', 'data_policy', 'privacy', 'cookies'):
            with self.subTest(clave):
                respuesta = self.client.get(reverse(f'core:{clave}'))

                self.assertEqual(respuesta.status_code, 200)
                self.assertEqual(respuesta.context['document'].key, clave)

    def test_el_aviso_de_borrador_sale_del_estado(self):
        """
        Una sola marca. Antes eran dos --el recuadro de la plantilla y el
        sufijo del ajuste-- y nada impedia que dijeran cosas distintas.
        """
        respuesta = self.client.get(reverse('core:terms'))

        self.assertTrue(respuesta.context['is_draft'])
        self.assertContains(respuesta, 'class="legal__draft"')

        nueva = self.a_version()
        nueva.approve(user=self.staff)

        respuesta = self.client.get(reverse('core:terms'))

        self.assertFalse(respuesta.context['is_draft'])
        self.assertNotContains(respuesta, 'class="legal__draft"')

    def test_lo_que_se_publica_va_saneado(self):
        cuerpo = '<p>Legitimo</p><script>alert(1)</script>'
        version = self.a_version(es_body=cuerpo, en_body=cuerpo)
        version.approve(user=self.staff)

        respuesta = self.client.get(reverse('core:terms'))

        self.assertContains(respuesta, 'Legitimo')
        self.assertNotContains(respuesta, '<script>alert(1)</script>')

    def test_el_pdf_se_genera_al_vuelo(self):
        respuesta = self.client.get(
            reverse('core:legal_pdf', args=['cookies']))

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta['Content-Type'], 'application/pdf')
        self.assertTrue(respuesta.content.startswith(b'%PDF'))

    def test_el_pdf_lleva_el_texto_y_la_huella(self):
        from pypdf import PdfReader

        version = self.terms.displayed_version()
        pdf = render_document_pdf(version, 'es')
        lector = PdfReader(io.BytesIO(pdf))
        texto = '\n'.join(p.extract_text() or '' for p in lector.pages)

        self.assertIn('Términos y condiciones', texto)
        # La huella cierra el documento: es lo que permite comprobar que este
        # papel y lo que alguien acepto son el mismo texto.
        self.assertIn(version.content_hash[:20], texto.replace('\n', ''))

    def test_una_clave_inventada_es_un_404(self):
        self.assertEqual(
            self.client.get('/legal/inventado.pdf').status_code, 404)


class ApproveFromTheFormTestCase(LegalBase):
    """
    Aprobar desde el formulario de la version, que es donde se redacta.

    Estaba **solo** en el desplegable de acciones del listado, y ahi no lo
    encuentra nadie: quien acaba de escribir el texto esta en el formulario, y
    alli los campos de estado y aprobador salen en gris sin decir donde se
    cambian. Se reporto exactamente asi: «no veo donde cambiar el aprobador y
    estado».

    La accion del listado sigue existiendo --sirve para aprobar varias de una
    vez-- pero la que se usa de verdad es esta.
    """

    def setUp(self):
        super().setUp()

        self.boss = UserModel.objects.create_superuser(
            username='jefe', email='jefe@example.com', password=PASSWORD)
        login_with_otp(self.client, self.boss)

    def form_url(self, version):
        return reverse(
            'admin:core_legaldocumentversionmodel_change', args=[version.pk])

    def payload(self, version, **extra):
        """
        El formulario entero, como lo manda el navegador.

        El boton de aprobar es un `submit` dentro del formulario, asi que
        arrastra todos los campos — y el admin valida antes de llegar a
        `response_change()`. Mandar solo `_approve` probaria un envio que no
        existe.
        """
        datos = {
            'document': str(version.document_id),
            'version': version.version,
            'es_body': version.es_body,
            'en_body': version.en_body,
            'change_note_es': version.change_note_es,
            'change_note_en': version.change_note_en,
            'effective_from': '',
        }

        if version.notify_users:
            datos['notify_users'] = 'on'

        datos.update(extra)
        return datos

    def test_el_boton_esta_en_el_formulario(self):
        version = self.a_version()

        html = self.client.get(self.form_url(version)).content.decode()

        self.assertIn('name="_approve"', html)

    def test_el_boton_aprueba_y_deja_quien(self):
        version = self.a_version()

        respuesta = self.client.post(
            self.form_url(version),
            self.payload(version, _approve='1'),
            follow=True,
        )
        version.refresh_from_db()

        self.assertEqual(respuesta.status_code, 200)
        self.assertTrue(version.is_approved)
        self.assertEqual(version.approved_by, self.boss)
        self.assertEqual(version.effective_from, timezone.localdate())
        self.assertEqual(len(version.content_hash), 64)

    def test_una_aprobada_ya_no_ofrece_el_boton(self):
        version = self.a_version()
        version.approve(user=self.staff)

        html = self.client.get(self.form_url(version)).content.decode()

        self.assertNotIn('name="_approve"', html)
        # En su lugar dice quien la aprobo: un boton apagado invita a
        # intentarlo y a preguntarse por que no responde.
        self.assertIn('jefa', html)

    def test_sin_texto_en_espanol_no_se_aprueba(self):
        version = self.a_version(es_body='', en_body='<p>Only English</p>')

        self.client.post(
            self.form_url(version),
            self.payload(version, _approve='1'),
            follow=True,
        )
        version.refresh_from_db()

        self.assertFalse(version.is_approved)

    def test_guardar_no_aprueba(self):
        """
        Guardar es lo que se hace veinte veces mientras se redacta, y aprobar
        pasa una sola vez: mezclarlos convertiria un guardado distraido en una
        publicacion.
        """
        version = self.a_version()

        self.client.post(
            self.form_url(version),
            self.payload(version, es_body='<p>Otra redaccion</p>', _save='Save'),
            follow=True,
        )
        version.refresh_from_db()

        self.assertFalse(version.is_approved)
        self.assertIsNone(version.approved_by)
