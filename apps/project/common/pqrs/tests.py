# apps/project/common/pqrs/tests.py
"""
PQRS: el plazo, la rama natural/juridica, y lo que no puede ensenarse.

Lo que de verdad se prueba aqui es **el conteo en dias habiles**. El resto
--un formulario, un correo de acuse-- es trabajo corriente; lo que se puede
hacer mal sin que nadie lo note es la fecha de vencimiento, y de ella depende
si el despacho responde a tiempo o incumple.

Contar dias corridos da de menos. Un plazo de quince habiles que cruce Semana
Santa son mas de tres semanas de calendario, y una fecha calculada de menos
hace que el panel marque en verde una solicitud que ya vencio.

    manage.py test apps.project.common.pqrs --settings=app_core.settings_test
"""

from datetime import date, timedelta

from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .deadlines import (add_business_days, business_days_between,
                        easter_sunday, holidays, is_business_day)
from .models import (COMPLAINT_DAYS, QUERY_DAYS, PQRSRequest,
                     RequestTypeChoices)


class TestTheColombianCalendar(TestCase):
    """
    Dieciocho festivos, y la mayoria moviles.

    La Ley 51 de 1983 traslada buena parte al lunes siguiente, y otros cinco
    dependen de la Pascua. Sin esto, "quince dias habiles" es una cuenta que
    no coincide con la del que reclama.
    """

    def test_easter_matches_the_known_dates(self):
        """El computus de Gauss, contra fechas comprobables."""
        for year, expected in (
            (2024, date(2024, 3, 31)),
            (2025, date(2025, 4, 20)),
            (2026, date(2026, 4, 5)),
            (2027, date(2027, 3, 28)),
        ):
            with self.subTest(year=year):
                self.assertEqual(easter_sunday(year), expected)

    def test_there_are_eighteen_holidays_a_year(self):
        """
        Dieciocho, salvo los anos en que dos caen encima.

        Se comprueba contra el numero de **dias** no laborables, no contra el
        numero de festivos del calendario: son la misma cifra casi siempre, y
        cuando no lo son, la que importa para contar plazos es la primera.
        """
        for year in (2024, 2026, 2027, 2028):
            with self.subTest(year=year):
                self.assertEqual(len(holidays(year)), 18)

    def test_two_holidays_can_land_on_the_same_day(self):
        """
        2025 es el caso: San Pedro y San Pablo cae en domingo 29 de junio y se
        traslada al lunes 30, que es justo donde ya estaba el Sagrado Corazon.
        Ese ano Colombia tiene diecisiete dias festivos, no dieciocho.

        Se fija porque la tentacion al leer el modulo es "son siempre 18", y
        con esa idea alguien acabaria sumando festivos en vez de recogerlos en
        un conjunto -- que es lo que da el numero correcto.
        """
        self.assertEqual(len(holidays(2025)), 17)
        self.assertIn(date(2025, 6, 30), holidays(2025))
        self.assertFalse(is_business_day(date(2025, 6, 30)))

    def test_the_moved_ones_land_on_a_monday(self):
        """
        La Ley Emiliani. Sin trasladarlos, un festivo que cae en miercoles se
        contaria como habil el lunes en que de verdad no se trabaja.
        """
        moved = {
            date(2026, 1, 12),   # Reyes
            date(2026, 3, 23),   # San Jose
            date(2026, 6, 29),   # San Pedro y San Pablo
            date(2026, 8, 17),   # Asuncion
            date(2026, 10, 12),  # Dia de la raza
        }

        for day in moved:
            with self.subTest(day=day):
                self.assertIn(day, holidays(2026))
                self.assertEqual(day.weekday(), 0, 'should be a Monday')

    def test_good_friday_is_not_moved(self):
        """Jueves y Viernes Santo se quedan donde caen."""
        self.assertIn(date(2026, 4, 3), holidays(2026))

    def test_christmas_is_a_holiday_whatever_day_it_falls_on(self):
        for year in (2025, 2026, 2027):
            with self.subTest(year=year):
                self.assertFalse(is_business_day(date(year, 12, 25)))

    def test_weekends_are_not_business_days(self):
        # 2026-09-05 es sabado.
        self.assertFalse(is_business_day(date(2026, 9, 5)))
        self.assertFalse(is_business_day(date(2026, 9, 6)))
        self.assertTrue(is_business_day(date(2026, 9, 7)))


class TestCountingBusinessDays(TestCase):

    def test_the_starting_day_does_not_count(self):
        """
        El articulo dice "contados a partir del dia siguiente". Contar el
        propio dia de radicacion regala un dia de plazo que no existe.
        """
        monday = date(2026, 9, 7)

        self.assertEqual(add_business_days(monday, 1), date(2026, 9, 8))

    def test_it_jumps_the_weekend(self):
        friday = date(2026, 9, 4)

        self.assertEqual(add_business_days(friday, 1), date(2026, 9, 7))

    def test_it_jumps_a_holiday(self):
        """
        Del viernes 9 de octubre de 2026, el lunes 12 es festivo trasladado,
        asi que el primer habil es el martes 13.
        """
        friday = date(2026, 10, 9)

        self.assertEqual(add_business_days(friday, 1), date(2026, 10, 13))

    def test_fifteen_business_days_are_more_than_fifteen_days(self):
        """La razon de todo este modulo."""
        start = date(2026, 9, 7)

        due = add_business_days(start, 15)

        self.assertGreater((due - start).days, 15)

    def test_easter_week_stretches_the_term(self):
        """
        Radicado el lunes 30 de marzo de 2026, con Jueves y Viernes Santo en
        medio: quince habiles se van a mas de tres semanas.
        """
        start = date(2026, 3, 30)

        due = add_business_days(start, 15)

        self.assertGreaterEqual((due - start).days, 21)

    def test_counting_back_and_forth_agrees(self):
        start = date(2026, 9, 7)

        for days in (1, 5, 10, 15, 30):
            with self.subTest(days=days):
                end = add_business_days(start, days)

                self.assertEqual(business_days_between(start, end), days)

    def test_a_past_date_counts_negative(self):
        """Es lo que dice cuantos dias de retraso lleva una solicitud."""
        start = date(2026, 9, 21)
        earlier = date(2026, 9, 14)

        self.assertLess(business_days_between(start, earlier), 0)


class PQRSFixtureMixin:

    def make_request(self, **kwargs):
        data = {
            'request_type': RequestTypeChoices.QUERY,
            'person_type': PQRSRequest.PersonTypeChoices.NATURAL,
            'first_name': 'Ana',
            'last_name': 'Lopez',
            'identification_type': PQRSRequest.IdentificationTypeChoices.CC,
            'identification_number': '123456789',
            'country': 'Colombia',
            'city': 'Marinilla',
            'address': 'Cll 12 #45-46',
            'email': 'ana@example.com',
            'phone_number': '3000000001',
            'description': 'Quiero saber que datos mios tienen.',
            'accepted_terms': True,
        }
        data.update(kwargs)

        return PQRSRequest.objects.create(**data)


class TestTheDeadlineDependsOnTheType(PQRSFixtureMixin, TestCase):
    """
    La distincion consulta/reclamo no es cosmetica: decide el plazo, y por eso
    el tipo se pregunta en el primer paso y no en el ultimo.
    """

    def test_a_query_gets_ten_business_days(self):
        record = self.make_request(request_type=RequestTypeChoices.QUERY)

        self.assertEqual(
            record.due_on,
            add_business_days(record.received_on, QUERY_DAYS),
        )

    def test_access_counts_as_a_query(self):
        record = self.make_request(request_type=RequestTypeChoices.ACCESS)

        self.assertFalse(record.is_complaint)

    def test_a_complaint_gets_fifteen(self):
        record = self.make_request(request_type=RequestTypeChoices.COMPLAINT)

        self.assertEqual(
            record.due_on,
            add_business_days(record.received_on, COMPLAINT_DAYS),
        )

    def test_deletion_counts_as_a_complaint(self):
        """
        Suprimir, rectificar y actualizar son reclamos en el sentido del
        articulo 15: piden que se corrija algo.
        """
        for kind in (RequestTypeChoices.DELETION,
                     RequestTypeChoices.RECTIFICATION,
                     RequestTypeChoices.UPDATE):
            with self.subTest(kind=kind):
                record = self.make_request(request_type=kind)

                self.assertTrue(record.is_complaint)

    def test_the_due_date_falls_on_a_business_day(self):
        for kind in RequestTypeChoices.values:
            with self.subTest(kind=kind):
                record = self.make_request(request_type=kind)

                self.assertTrue(is_business_day(record.due_on))


class TestTheExtension(PQRSFixtureMixin, TestCase):
    """La ley permite **una** prorroga, y solo una."""

    def test_it_moves_the_deadline(self):
        record = self.make_request()
        original = record.due_on

        record.extend()

        self.assertGreater(record.due_on, original)

    def test_it_counts_from_the_end_of_the_first_term(self):
        """
        "Siguientes al vencimiento del primer termino", no desde la
        radicacion. Contarla desde la recepcion acorta la prorroga.
        """
        record = self.make_request(request_type=RequestTypeChoices.QUERY)
        first = record.due_on

        record.extend()

        self.assertEqual(record.due_on, add_business_days(first, 5))

    def test_a_second_one_is_refused(self):
        record = self.make_request()
        record.extend()

        with self.assertRaises(ValidationError):
            record.extend()


class TestOverdue(PQRSFixtureMixin, TestCase):

    def test_a_fresh_request_is_not_overdue(self):
        self.assertFalse(self.make_request().is_overdue)

    def test_a_past_deadline_is(self):
        record = self.make_request()
        PQRSRequest.objects.filter(pk=record.pk).update(
            due_on=timezone.localdate() - timedelta(days=1))
        record.refresh_from_db()

        self.assertTrue(record.is_overdue)

    def test_an_answered_one_never_is(self):
        """
        Una solicitud contestada fuera de plazo se incumplio en su momento,
        pero ya no esta pendiente: dejarla en rojo para siempre esconde las
        que si necesitan atencion hoy.
        """
        record = self.make_request()
        PQRSRequest.objects.filter(pk=record.pk).update(
            due_on=timezone.localdate() - timedelta(days=5),
            status=PQRSRequest.StatusChoices.ANSWERED,
        )
        record.refresh_from_db()

        self.assertFalse(record.is_overdue)


class TestTheReferenceNumber(PQRSFixtureMixin, TestCase):

    def test_it_is_assigned_on_creation(self):
        self.assertTrue(self.make_request().radicado)

    def test_it_carries_the_year(self):
        record = self.make_request()

        self.assertIn(str(timezone.localdate().year), record.radicado)

    def test_two_requests_do_not_share_one(self):
        first = self.make_request()
        second = self.make_request(email='otra@example.com')

        self.assertNotEqual(first.radicado, second.radicado)

    def test_it_is_not_a_running_count(self):
        """
        Un consecutivo le dice a cualquiera que radique dos veces cuantas
        solicitudes entraron en medio. Eso es informacion del despacho, y va
        impresa en el acuse de recibo.
        """
        numbers = [self.make_request(email=f'{n}@example.com').radicado
                   for n in range(5)]
        tails = [value.rsplit('-', 1)[1] for value in numbers]

        self.assertEqual(len(set(tails)), 5)
        # Si fuera consecutivo, ordenarlos daria el mismo orden que crearlos.
        self.assertNotEqual(tails, sorted(tails))


class TestValidation(PQRSFixtureMixin, TestCase):

    def test_a_natural_person_needs_a_name(self):
        record = PQRSRequest(
            request_type=RequestTypeChoices.QUERY,
            person_type=PQRSRequest.PersonTypeChoices.NATURAL,
            identification_type='CC', identification_number='1',
            country='Colombia', city='Marinilla', address='x',
            email='a@example.com', phone_number='300',
            description='x', accepted_terms=True,
        )

        with self.assertRaises(ValidationError):
            record.clean()

    def test_a_legal_entity_needs_a_company_and_a_representative(self):
        record = PQRSRequest(
            request_type=RequestTypeChoices.QUERY,
            person_type=PQRSRequest.PersonTypeChoices.LEGAL,
            identification_type='NIT', identification_number='9',
            country='Colombia', city='Marinilla', address='x',
            email='a@example.com', phone_number='300',
            description='x', accepted_terms=True,
        )

        with self.assertRaises(ValidationError):
            record.clean()

    def test_without_accepting_the_policy_it_does_not_go_through(self):
        """
        Sin autorizacion no se puede tratar el dato (art. 9). Aceptar no es
        una formalidad del formulario: es lo que habilita todo lo demas.
        """
        record = PQRSRequest(
            request_type=RequestTypeChoices.QUERY,
            person_type=PQRSRequest.PersonTypeChoices.NATURAL,
            first_name='Ana', last_name='Lopez',
            identification_type='CC', identification_number='1',
            country='Colombia', city='Marinilla', address='x',
            email='a@example.com', phone_number='300',
            description='x', accepted_terms=False,
        )

        with self.assertRaises(ValidationError):
            record.clean()

    def test_accepting_records_when(self):
        """
        "Marco una casilla" no es constancia de la autorizacion si no se
        guarda cuando.
        """
        record = self.make_request()

        self.assertIsNotNone(record.accepted_at)


class TestTheReceiptShowsNothingPersonal(PQRSFixtureMixin, TestCase):
    """
    La URL del comprobante lleva el radicado, y un radicado circula por
    correo, por WhatsApp y en capturas. Cualquiera que lo tenga abre esta
    pagina.
    """

    def setUp(self):
        self.record = self.make_request(
            first_name='Ana', last_name='Lopez',
            description='Un dato muy concreto que no debe salir en pantalla.',
        )
        self.url = reverse(
            'pqrs:receipt', kwargs={'radicado': self.record.radicado})

    def test_it_opens_without_a_session(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_it_shows_the_reference_and_the_dates(self):
        body = self.client.get(self.url).content.decode()

        self.assertIn(self.record.radicado, body)
        self.assertIn(self.record.due_on.strftime('%d/%m/%Y'), body)

    def test_it_does_not_show_the_name(self):
        body = self.client.get(self.url).content.decode()

        self.assertNotIn('Ana', body)
        self.assertNotIn('Lopez', body)

    def test_it_does_not_show_the_description(self):
        body = self.client.get(self.url).content.decode()

        self.assertNotIn('Un dato muy concreto', body)

    def test_it_does_not_show_the_identification(self):
        body = self.client.get(self.url).content.decode()

        self.assertNotIn('123456789', body)


class TestTheContactUsed(PQRSFixtureMixin, TestCase):

    def test_by_default_it_answers_to_the_holder(self):
        record = self.make_request()

        self.assertEqual(record.reply_to, 'ana@example.com')

    def test_an_alternate_contact_wins(self):
        record = self.make_request(
            use_titular_contact=False, contact_email='otro@example.com')

        self.assertEqual(record.reply_to, 'otro@example.com')


class TestTheWizard(TestCase):
    """El formulario de verdad, por HTTP y por los cinco pasos."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse('pqrs:new')

    def step(self, name, data):
        payload = {f'{name}-{key}': value for key, value in data.items()}
        payload['pqrs_wizard_view-current_step'] = name

        return self.client.post(self.url, payload)

    def walk(self, *, person_type='NATURAL', kind='QUERY'):
        self.client.get(self.url)

        self.step('type', {'request_type': kind, 'person_type': person_type})

        if person_type == 'NATURAL':
            holder = {
                'first_name': 'Ana', 'last_name': 'Lopez',
                'identification_type': 'CC',
            }
        else:
            holder = {
                'company_name': 'Empresa SAS',
                'legal_representative': 'Ana Lopez',
                'identification_type': 'NIT',
            }

        holder.update({
            'identification_number': '123456789',
            'country': 'Colombia', 'city': 'Marinilla',
            'address': 'Cll 12 #45-46',
            'email': 'ana@example.com',
            'confirm_email': 'ana@example.com',
            'phone_code': '+57', 'phone_number': '3000000001',
        })

        self.step('holder', holder)
        self.step('description', {
            'description': 'Quiero saber que datos mios tienen guardados.'})
        self.step('contact', {'use_titular_contact': 'on'})

        return self.step('confirm', {'accepted_terms': 'on'})

    def test_it_files_a_request(self):
        self.walk()

        self.assertEqual(PQRSRequest.objects.count(), 1)

    def test_it_lands_on_the_receipt(self):
        response = self.walk()

        record = PQRSRequest.objects.get()

        self.assertRedirects(
            response,
            reverse('pqrs:receipt', kwargs={'radicado': record.radicado}),
        )

    def test_it_sends_the_acknowledgement_with_the_deadline(self):
        """
        El acuse lleva la fecha limite dentro: es la diferencia entre un
        "recibido" y un compromiso comprobable.
        """
        self.walk()

        record = PQRSRequest.objects.get()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(record.radicado, mail.outbox[0].body)
        self.assertIn(str(record.due_on), mail.outbox[0].body)

    def test_the_legal_branch_asks_for_a_company(self):
        self.walk(person_type='LEGAL')

        record = PQRSRequest.objects.get()

        self.assertEqual(record.company_name, 'Empresa SAS')
        self.assertEqual(record.legal_representative, 'Ana Lopez')

    def test_the_type_chosen_sets_the_deadline(self):
        self.walk(kind='COMPLAINT')

        record = PQRSRequest.objects.get()

        self.assertTrue(record.is_complaint)
        self.assertEqual(
            record.due_on,
            add_business_days(record.received_on, COMPLAINT_DAYS),
        )

    def test_it_records_where_it_came_from(self):
        """Parte de la constancia de la autorizacion."""
        self.walk()

        self.assertIsNotNone(PQRSRequest.objects.get().submitted_ip)


class TestTheLegalPages(TestCase):
    """
    Las cuatro se pintan y se enlazan entre si.

    `privacy` y `terms` eran ficheros de cero bytes: devolvian 200 con el
    cuerpo vacio, asi que comprobar el codigo de estado no habria detectado
    nada. Aqui se mira que haya contenido.
    """

    PAGES = ('core:terms', 'core:privacy', 'core:cookies', 'core:data_policy')

    def test_they_render_with_content(self):
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))

                self.assertEqual(response.status_code, 200)
                self.assertGreater(len(response.content), 3000)

    def test_they_show_their_version_and_date(self):
        """
        Sin version no se puede demostrar que texto acepto alguien el dia que
        se registro.
        """
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))

                self.assertContains(response, '1.0.0')

    def test_they_all_point_at_the_pqrs_form(self):
        """
        Es la via por la que se ejercen los derechos: una politica que los
        enumera y no dice como usarlos deja al titular en el mismo sitio.
        """
        for name in self.PAGES:
            with self.subTest(page=name):
                self.assertContains(
                    self.client.get(reverse(name)), reverse('pqrs:new'))

    def test_the_data_policy_declares_the_openai_transfer(self):
        """
        La traduccion automatica manda texto a OpenAI. Es transferencia
        internacional, y una politica que no la declara es una politica que no
        coincide con el codigo.
        """
        response = self.client.get(reverse('core:data_policy'))

        self.assertContains(response, 'OpenAI')

    def test_the_data_policy_says_only_a_hash_leaves_for_the_anchoring(self):
        """
        Es la diferencia que importa: al anclaje sube el hash, nunca el
        documento. Confundirlo asusta a quien lea la politica por una razon
        que no existe.
        """
        response = self.client.get(reverse('core:data_policy'))

        self.assertContains(response, 'SHA-256')

    def test_the_terms_say_what_a_certification_does_not_prove(self):
        """
        Invariante 11: la plataforma acredita integridad, no veracidad. Unos
        terminos que den a entender lo contrario contradicen al producto en el
        punto que mas caro sale.
        """
        response = self.client.get(reverse('core:terms'))
        body = response.content.decode().lower()

        self.assertIn('integrity', body)
        self.assertIn('true', body)

    def test_the_terms_bound_the_translation_claim(self):
        """Que la traduccion es automatica y no certificada."""
        body = self.client.get(reverse('core:terms')).content.decode().lower()

        self.assertIn('translation', body)
        self.assertIn('not a certified', body)
