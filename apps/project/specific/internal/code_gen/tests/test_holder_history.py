# apps/project/specific/internal/code_gen/tests/test_holder_history.py
"""
El historial visto por el titular de un certificado, y no por el operador.

Lo que faltaba
--------------
Un certificado **no tenia dueño**. `DocumentVerificationModel` no tenia ningun
campo que dijera para quien se emitio, asi que la frase «este certificado es de
este usuario» no se podia escribir en ninguna parte, y el historial era una
herramienta interna a la que o entrabas entero o no entrabas. De ahi el campo
`holders` y este modulo. Empezo siendo un FK (uno solo) y paso a M2M cuando
hizo falta que un mismo certificado pudiera ser de varias personas a la vez
--los integrantes de una organizacion, no solo quien lo tramito--, sin que
ninguna de las reglas de mas abajo cambiara de fondo.

Que se prueba, y por que cada cosa
----------------------------------
El titular ve **sus** certificados y nada mas. Eso no se comprueba mirando la
plantilla sino pidiendo las URL: lo que decide es el queryset, y esconder un
boton no es un control porque basta con teclearla.

Y no ve las piezas con las que se monta un certificado: el original **sin los
codigos estampados**, los simbolos sueltos en PNG, y las coordenadas exactas
donde van en la pagina. Las tres juntas son el plano de una falsificacion; por
separado cada una parece inofensiva, y por eso las tres responden a la misma
pregunta en `access.py` y aqui se comprueban las tres.

Nada de esto toca la red ni escribe archivos.

    manage.py test apps.project.specific.internal.code_gen.tests.test_holder_history \\
        --settings=app_core.settings_test
"""

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.documents.certificates.models import (
    AegisSummaryDocumentModel, AegisSummaryModel, CertificationStatusChoices,
    DocumentVerificationModel)

from ..access import (can_generate_codes, can_see_internals, can_use_history,
                      can_view_registration, is_holder, is_operator,
                      visible_registrations)
from ..models import CodeRegistrationModel

PASSWORD = 'pw-for-tests-123'


class HolderTestCase(TestCase):
    """
    Un operador, dos titulares, y un certificado de cada uno.

    El tercer codigo no tiene documento: es un codigo suelto, y no es de nadie.
    """

    def setUp(self):
        self.operator = UserModel.objects.create_user(
            username='ops', email='ops@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.ana = UserModel.objects.create_user(
            username='ana', email='ana@example.com', password=PASSWORD,
        )
        self.beto = UserModel.objects.create_user(
            username='beto', email='beto@example.com', password=PASSWORD,
        )

        self.de_ana = self.a_document('Bonos de Ana', holders=[self.ana])
        self.de_beto = self.a_document('Oro de Beto', holders=[self.beto])
        self.de_nadie = self.a_document('Certificado institucional')

        self.codigo_ana = self.a_code('ANA', self.de_ana)
        self.codigo_beto = self.a_code('BETO', self.de_beto)
        self.codigo_nadie = self.a_code('NADIE', self.de_nadie)
        self.codigo_suelto = self.a_code('SUELTO')

        self.history = reverse('code_gen:code_history')

    def a_document(self, title, holders=()):
        document = DocumentVerificationModel.objects.create(
            document_title=title,
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash=f'{abs(hash(title)):064x}'[:64],
            code_payload=f'GEA-{title[:10]}',
        )

        # M2M: no se puede pasar al constructor, hace falta la PK de arriba.
        if holders:
            document.holders.set(holders)

        # Con archivo original: el boton que lo ofrece solo existe si lo hay,
        # asi que sin esto la prueba del operador pasaria por no haber archivo
        # y no por tener permiso -- justo lo contrario de lo que comprueba.
        document.source_file.save(
            'original.pdf',
            SimpleUploadedFile('original.pdf', b'%PDF-1.4 de prueba'),
            save=True,
        )

        return document

    def a_code(self, reference, document=None):
        return CodeRegistrationModel.objects.create(
            reference=reference,
            document=document,
            code_information=f'PAYLOAD-{reference}',
            generated_qr=True,
            qr_payload='https://example.test/verify',
        )

    def listing(self):
        return CodeRegistrationModel.objects.select_related('document')

    def detail_url(self, registration):
        return reverse('code_gen:code_detail', args=[registration.pk])


class TestWhoIsWho(HolderTestCase):

    def test_staff_is_an_operator(self):
        self.assertTrue(is_operator(self.operator))
        self.assertFalse(is_holder(self.operator))

    def test_anyone_else_who_logged_in_is_a_holder(self):
        self.assertTrue(is_holder(self.ana))
        self.assertFalse(is_operator(self.ana))

    def test_a_deactivated_account_is_neither(self):
        """
        Dar de baja a alguien tiene que cerrarle la puerta aqui tambien, y no
        solo el login: `is_active` es como se borra en este proyecto.
        """
        self.ana.is_active = False

        self.assertFalse(is_holder(self.ana))
        self.assertFalse(can_use_history(self.ana))

    def test_the_role_does_not_depend_on_user_type(self):
        """
        Un certificado se emite para quien sea --un tenedor, un comprador, un
        tercero-- y lo que decide que ve es de que es titular, no la etiqueta
        de su cuenta. Atado al `user_type`, un tipo nuevo se quedaria fuera sin
        que nadie lo notara.
        """
        for user_type in ('H', 'B', 'R', 'I'):
            self.ana.user_type = user_type

            self.assertTrue(is_holder(self.ana), user_type)


class TestAHolderSeesOnlyTheirOwn(HolderTestCase):

    def test_the_operator_sees_everything(self):
        visibles = visible_registrations(self.listing(), self.operator)

        self.assertEqual(visibles.count(), 4)

    def test_a_holder_sees_only_their_certificates(self):
        visibles = visible_registrations(self.listing(), self.ana)

        self.assertEqual(
            [row.reference for row in visibles], ['ANA'])

    def test_a_holder_does_not_see_loose_codes(self):
        """
        Un codigo sin documento no es de nadie, asi que no puede ser suyo. Sin
        esto, «lo que no es de otro» se leeria como «lo mio».
        """
        visibles = visible_registrations(self.listing(), self.ana)

        self.assertNotIn(self.codigo_suelto, list(visibles))
        self.assertNotIn(self.codigo_nadie, list(visibles))

    def test_an_anonymous_visitor_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        visibles = visible_registrations(self.listing(), AnonymousUser())

        self.assertEqual(visibles.count(), 0)

    def test_the_page_only_lists_their_own(self):
        """
        Se mira la **referencia**, que es lo que la fila enseña: el titulo del
        documento no sale en el listado, asi que buscarlo ahi daria una prueba
        que pasa sin comprobar nada.
        """
        self.client.force_login(self.ana)

        html = self.client.get(self.history).content.decode('utf-8')

        self.assertIn('PAYLOAD-ANA', html)
        self.assertNotIn('PAYLOAD-BETO', html)
        self.assertNotIn('PAYLOAD-NADIE', html)
        self.assertNotIn('PAYLOAD-SUELTO', html)

    def test_searching_does_not_answer_about_someone_elses(self):
        """
        El recorte va **antes** de buscar. Despues, el numero de resultados ya
        diria si existe algo con ese texto, que es media respuesta.
        """
        self.client.force_login(self.ana)

        response = self.client.get(self.history, {'q': 'Oro de Beto'})

        # Sobre la cifra y no sobre el HTML: la caja de busqueda devuelve lo
        # tecleado, asi que el texto buscado sale siempre en la pagina.
        self.assertEqual(response.context['code_count'], 0)
        self.assertNotIn('PAYLOAD-BETO', response.content.decode('utf-8'))

    def test_opening_someone_elses_code_is_a_404(self):
        """
        404 y no 403: un 403 le confirmaria que ese codigo existe, que es justo
        lo que no tiene que poder averiguar (invariantes 7 y 20).
        """
        self.client.force_login(self.ana)

        response = self.client.get(self.detail_url(self.codigo_beto))

        self.assertEqual(response.status_code, 404)

    def test_opening_their_own_works(self):
        self.client.force_login(self.ana)

        response = self.client.get(self.detail_url(self.codigo_ana))

        self.assertEqual(response.status_code, 200)

    def test_can_view_registration_agrees_with_the_queryset(self):
        """
        Las dos puertas tienen que decir lo mismo: una filtra listas y la otra
        contesta por un objeto, y si divergen una de las dos deja pasar.
        """
        for registration in self.listing():
            esperado = registration in list(
                visible_registrations(self.listing(), self.ana))

            self.assertEqual(
                can_view_registration(self.ana, registration),
                esperado,
                registration.reference,
            )


class TestTheHolderDoesNotGetTheWorkshop(HolderTestCase):
    """
    El original sin codigos, los simbolos sueltos y donde se estamparon.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ana)
        self.html = self.client.get(
            self.detail_url(self.codigo_ana)).content.decode('utf-8')

    def test_the_symbols_are_not_even_rendered(self):
        """
        No se esconden: no se producen. Renderizar un QR para no enseñarlo lo
        deja en la memoria del proceso y a una linea de plantilla de distancia
        de salir.
        """
        response = self.client.get(self.detail_url(self.codigo_ana))

        self.assertNotIn('qr_image', response.context)
        self.assertNotIn('barcode_image', response.context)

    def test_there_is_no_download_for_the_symbols(self):
        self.assertNotIn('Download QR', self.html)
        self.assertNotIn('Download barcode', self.html)

    def test_it_does_not_claim_there_were_no_symbols(self):
        """
        Esconder solo los botones dejaba en pantalla «no se generaron simbolos
        para este codigo», que es falso: se generaron y estan estampados en su
        documento.
        """
        self.assertNotIn('No symbols were generated', self.html)

    def test_the_original_without_codes_is_not_offered(self):
        self.assertNotIn('Original filed', self.html)
        self.assertNotIn("'source'", self.html)

    def test_where_the_codes_were_placed_is_not_shown(self):
        response = self.client.get(self.detail_url(self.codigo_ana))

        self.assertNotIn('Where the codes were placed', self.html)
        self.assertNotIn('stamp_preview', response.context)
        self.assertNotIn('layout_placements', response.context)

    def test_they_are_told_how_to_check_it_instead(self):
        """
        Es la pregunta que trae a alguien a esta pantalla, y la respuesta no
        esta aqui sino en la pagina publica.
        """
        self.assertIn('How to check it', self.html)

    def test_the_operator_still_gets_all_of_it(self):
        """
        El caso de control. Sin el, todo lo de arriba pasaria igual con una
        pantalla que no enseñara nada a nadie.
        """
        self.client.force_login(self.operator)

        response = self.client.get(self.detail_url(self.codigo_ana))
        html = response.content.decode('utf-8')

        self.assertIn('qr_image', response.context)
        self.assertIn('Download QR', html)
        self.assertIn('Where the codes were placed', html)
        self.assertIn('Original filed', html)


class TestTheActionsAreTheOperatorsOnly(HolderTestCase):

    def setUp(self):
        super().setUp()

        self.summary = AegisSummaryModel.objects.create(title='Resumen')
        AegisSummaryDocumentModel.objects.create(
            summary=self.summary, document=self.de_ana, code='AEGIS-1')

    def page(self, user):
        self.client.force_login(user)

        response = self.client.get(self.history)
        self.assertEqual(response.status_code, 200)

        return response.content.decode('utf-8')

    def test_a_holder_gets_no_compose_and_no_usb(self):
        html = self.page(self.ana)

        self.assertNotIn('Compose', html)
        self.assertNotIn('Export to USB', html)
        self.assertNotIn('Not ready to export', html)

    def test_a_holder_gets_no_generate(self):
        """
        Lo que le falta no es este boton: es **pedir** un certificado, con su
        solicitud y su traza, y eso todavia no existe. Un boton que emitiera de
        verdad le daria la capacidad del operador.
        """
        html = self.page(self.ana)

        self.assertNotIn('Generate a new code', html)

        # Con comillas: `/generate/code/` es **prefijo** de la URL de esta
        # misma pagina (`/generate/code/history/`), asi que buscarlo suelto da
        # un falso positivo. Es el mismo error que hizo que el termino `env`
        # bloqueara `/envio/` (invariante 14).
        self.assertNotIn(
            'href="%s"' % reverse('code_gen:code_generate'), html)

    def test_the_generator_itself_says_no(self):
        """Y no solo el boton: esconderlo no seria un control."""
        self.client.force_login(self.ana)

        response = self.client.get(reverse('code_gen:code_generate'))

        self.assertNotEqual(response.status_code, 200)

    def test_a_holder_cannot_export_a_summary_by_typing_the_url(self):
        self.client.force_login(self.ana)

        response = self.client.get(
            reverse('code_gen:summary_usb_export', args=[self.summary.pk]))

        self.assertNotEqual(response.status_code, 200)

    def test_a_holder_cannot_open_the_composer(self):
        self.client.force_login(self.ana)

        response = self.client.get(
            reverse('code_gen:summary_compose', args=[self.summary.pk]))

        self.assertNotEqual(response.status_code, 200)

    def test_a_holder_cannot_open_the_layouts(self):
        """
        Las disposiciones son la geometria del estampado de **todos** los
        certificados, no solo del suyo.
        """
        self.client.force_login(self.ana)

        response = self.client.get(reverse('code_gen:layout_list'))

        self.assertNotEqual(response.status_code, 200)

    def test_the_operator_keeps_all_three(self):
        html = self.page(self.operator)

        self.assertIn('Compose', html)
        self.assertIn('Generate a new code', html)

    def test_the_holder_still_sees_which_summary_it_belongs_to(self):
        """
        La rama del resumen se le sigue enseñando: saber de que resumen es su
        certificado es suyo. Lo que se le quitan son las acciones.
        """
        html = self.page(self.ana)

        self.assertIn('Resumen', html)


class TestTheAccessRuleIsOneRule(HolderTestCase):
    """
    Las tres piezas de taller responden a la misma pregunta a proposito.
    Separarlas invitaria a contestar distinto a una por descuido.
    """

    def test_internals_are_the_operators(self):
        self.assertTrue(can_see_internals(self.operator))
        self.assertFalse(can_see_internals(self.ana))

    def test_generating_is_the_operators(self):
        self.assertTrue(can_generate_codes(self.operator))
        self.assertFalse(can_generate_codes(self.ana))


class TestLosingTheHolderDoesNotWidenAccess(HolderTestCase):
    """
    Quitar a alguien de `holders` (M2M) es la version de hoy de lo que antes
    hacia `on_delete=SET_NULL` en el FK: de las formas de perder un titular,
    ninguna ensancha el acceso. Sin ningun titular no encaja nadie.
    """

    def test_a_certificate_with_no_holder_belongs_to_nobody(self):
        self.de_ana.holders.clear()

        for usuario in (self.ana, self.beto):
            visibles = visible_registrations(self.listing(), usuario)

            self.assertNotIn(self.codigo_ana, list(visibles), usuario.username)

    def test_and_the_operator_still_sees_it(self):
        self.de_ana.holders.clear()

        self.assertIn(
            self.codigo_ana,
            list(visible_registrations(self.listing(), self.operator)),
        )

    def test_removing_one_of_several_holders_only_drops_that_one(self):
        """
        La otra mitad de M2M: quitar a una persona no toca a las demas.
        """
        self.de_ana.holders.add(self.beto)

        self.de_ana.holders.remove(self.ana)

        self.assertNotIn(
            self.codigo_ana,
            list(visible_registrations(self.listing(), self.ana)),
        )
        self.assertIn(
            self.codigo_ana,
            list(visible_registrations(self.listing(), self.beto)),
        )


class TestACertificateCanHaveSeveralHolders(HolderTestCase):
    """
    El motivo del cambio: una organizacion tiene varios integrantes, ninguno
    "el" titular por encima de los demas, y antes solo cabia uno.
    """

    def setUp(self):
        super().setUp()
        self.de_ana.holders.add(self.beto)

    def test_both_holders_see_it_in_the_listing(self):
        for usuario in (self.ana, self.beto):
            visibles = visible_registrations(self.listing(), usuario)

            self.assertIn(self.codigo_ana, list(visibles), usuario.username)

    def test_both_holders_can_open_the_detail(self):
        for usuario in (self.ana, self.beto):
            self.client.force_login(usuario)

            response = self.client.get(self.detail_url(self.codigo_ana))

            self.assertEqual(
                response.status_code, 200, usuario.username)

    def test_a_third_person_still_gets_a_404(self):
        alguien_mas = UserModel.objects.create_user(
            username='otra', email='otra@example.com', password=PASSWORD,
        )
        self.client.force_login(alguien_mas)

        response = self.client.get(self.detail_url(self.codigo_ana))

        self.assertEqual(response.status_code, 404)

    def test_neither_holder_sees_the_others_certificate_through_this_one(self):
        """
        Compartir un certificado no comparte los demas: Beto es titular de
        `de_ana` ademas de `de_beto`, pero eso no le abre nada nuevo de Ana.
        """
        visibles_de_beto = visible_registrations(self.listing(), self.beto)

        self.assertEqual(
            {row.reference for row in visibles_de_beto},
            {'ANA', 'BETO'},
        )


class TestImpersonationShowsWhatThatPersonSees(HolderTestCase):
    """
    Impersonar es ver la plataforma **como la ve esa persona**, y eso incluye
    el recorte del historial.

    Vino de un desconcierto real: impersonando a alguien con seis certificados
    asignados se veian los diecisiete. La causa no era el filtro sino **quien
    estaba siendo impersonado**: si el objetivo es personal interno, ve todo,
    porque eso es exactamente lo que ve cuando entra por su cuenta. Estas
    pruebas dejan los dos casos escritos para que nadie vuelva a perseguir un
    fallo donde no lo hay.
    """

    def impersonate(self, target):
        self.client.force_login(self.operator)
        self.client.get(
            reverse('impersonate-start', args=[str(target.pk)]))

    def test_impersonating_a_holder_shows_only_their_own(self):
        """
        El caso que se creia roto. `request.user` **si** se sustituye por el
        impersonado (el middleware de `impersonate` va el ultimo), asi que
        `is_operator()` contesta por el titular y el recorte se aplica.
        """
        self.impersonate(self.ana)

        response = self.client.get(self.history)

        self.assertFalse(response.context['is_operator'])
        self.assertEqual(response.context['code_count'], 1)

        html = response.content.decode('utf-8')
        self.assertIn('PAYLOAD-ANA', html)
        self.assertNotIn('PAYLOAD-BETO', html)

    def test_impersonating_an_operator_shows_everything(self):
        """
        Y esto **no es un fallo**: si el impersonado es personal interno, ve
        todo, porque es lo que ve por su cuenta. Impersonar no puede enseñar
        menos de lo que esa persona tiene.
        """
        interno = UserModel.objects.create_user(
            username='interno', email='interno@example.com',
            password=PASSWORD, is_staff=True)

        self.impersonate(interno)

        response = self.client.get(self.history)

        self.assertTrue(response.context['is_operator'])
        self.assertEqual(response.context['code_count'], 4)


class TestTheHolderCanGetThere(HolderTestCase):
    """
    La vista se abrio al titular y el enlace se quedo dentro del bloque de
    `is_staff`: para llegar a lo suyo habia que saberse la URL.
    """

    SIDENAV = 'dashboard/partials/sidenav/dashboard_sidenav.html'

    def sidenav(self, user) -> str:
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        request = RequestFactory().get('/')
        request.user = user

        return render_to_string(self.SIDENAV, request=request)

    def test_a_holder_has_a_link_to_the_history(self):
        html = self.sidenav(self.ana)

        self.assertIn(self.history, html)

    def test_and_it_is_called_what_they_actually_see(self):
        """
        «Codigos generados» describe la pantalla del operador. Al titular, que
        solo ve los suyos, le describe otra.
        """
        self.assertIn('My certificates', self.sidenav(self.ana))
        self.assertIn('Generated codes', self.sidenav(self.operator))

    def test_the_operator_keeps_the_rest_of_the_block(self):
        """Sacar un enlace del bloque no puede sacar los demas."""
        html = self.sidenav(self.operator)

        self.assertIn('href="%s"' % reverse('code_gen:code_generate'), html)
        self.assertIn('href="%s"' % reverse('code_gen:layout_list'), html)

    def test_a_holder_still_gets_none_of_those(self):
        # Con `href="…"`: `/generate/code/` es **prefijo** de
        # `/generate/code/history/`, que ahora si esta en su menu, asi que
        # buscarlo suelto da un falso positivo. Es el mismo error que hizo que
        # el termino `env` bloqueara `/envio/` (invariante 14).
        html = self.sidenav(self.ana)

        self.assertNotIn(
            'href="%s"' % reverse('code_gen:code_generate'), html)
        self.assertNotIn(
            'href="%s"' % reverse('code_gen:layout_list'), html)


class TestAnOperatorCanLookUpSomeonesCertificates(HolderTestCase):
    """«Ver todos o los asignados»: lo segundo, por el buscador que ya habia."""

    def search(self, user, term):
        self.client.force_login(user)

        return self.client.get(self.history, {'q': term})

    def test_searching_a_username_finds_their_certificates(self):
        response = self.search(self.operator, 'ana')

        self.assertEqual(response.context['code_count'], 1)
        self.assertIn('PAYLOAD-ANA', response.content.decode('utf-8'))

    def test_searching_by_surname_works_too(self):
        self.beto.last_name = 'Restrepo'
        self.beto.save(update_fields=['last_name'])

        response = self.search(self.operator, 'Restrepo')

        self.assertEqual(response.context['code_count'], 1)

    def test_a_holder_cannot_look_up_anyone(self):
        """
        Buscar por titular es del operador. Ofrecerselo a un titular sugeriria
        que puede preguntar por otros, y el recorte ya lo impide: lo unico que
        conseguiria es una pagina vacia que parece una averia.
        """
        response = self.search(self.ana, 'beto')

        self.assertEqual(response.context['code_count'], 0)
