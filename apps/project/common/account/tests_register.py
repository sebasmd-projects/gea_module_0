# apps/project/common/account/tests_register.py
"""
El wizard de registro: la unica puerta por la que se crean cuentas.

Cuatro pasos, y una bifurcacion en el tercero -- el comprador da un correo y
recibe un codigo por email; el proveedor usa el codigo del dia que le entrega
un asesor. Son dos secretos distintos con dos ciclos de vida distintos, y
confundirlos deja la puerta abierta por el lado que no se mira.

Lo que se comprueba aqui:

* Que sin codigo valido no se crea ninguna cuenta. Es lo unico que separa el
  formulario de un alta libre.
* Que el codigo de comprador no vale para un proveedor ni al reves.
* Que el codigo se gasta: reutilizarlo no crea una segunda cuenta.
* Que el ``next`` de la URL no puede sacar al recien registrado fuera del
  sitio. Al terminar, el wizard **inicia la sesion** y luego redirige; un
  ``next`` externo manda a una sesion recien abierta a un sitio ajeno.

    manage.py test apps.project.common.account.tests_register \\
        --settings=app_core.settings_test
"""

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.common.utils.models import GeaDailyUniqueCode
from apps.project.common.users.models import UserModel

from .views import (STEP_CODE, STEP_CONTACT, STEP_SECURITY, STEP_USER,
                    GeaUserRegisterWizardView)

PASSWORD = 'una-clave-larga-de-prueba-123'


class WizardMixin:
    """
    Recorre los cuatro pasos.

    Se hace por HTTP y no llamando a ``done()`` a mano: el wizard guarda cada
    paso en la sesion, y lo que se quiere comprobar --que el codigo se valida
    al final, con lo que se escribio al principio-- solo ocurre si se pasa por
    el almacenamiento de verdad.
    """

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

        self.url = reverse('account:register')

    def wizard_url(self, **params):
        if not params:
            return self.url

        query = '&'.join(f'{k}={v}' for k, v in params.items())

        return f'{self.url}?{query}'

    def step(self, name, data, url=None, expect_ok=True):
        payload = {f'{name}-{key}': value for key, value in data.items()}
        payload['gea_user_register_wizard_view-current_step'] = name

        response = self.client.post(url or self.url, payload)

        if expect_ok:
            self.assert_step_was_accepted(response, name)

        return response

    def assert_step_was_accepted(self, response, name):
        """
        Que el paso paso de verdad.

        Sin esto, un campo mal escrito en el arnes deja el wizard parado en el
        primer paso, no se crea ningun usuario, y **las pruebas negativas
        pasan en vacio**: comprueban que no hay cuenta cuando no la habria
        habido de todos modos. Es la forma mas facil de tener una bateria
        verde que no comprueba nada.
        """
        form = (response.context or {}).get('form') if response.context else None

        if form is not None and getattr(form, 'errors', None):
            self.fail(
                f'the wizard rejected step {name!r}: {form.errors.as_json()}'
            )

    def register(self, *, user_type, code, email='nuevo@example.com',
                 username='nuevo', url=None):
        self.client.get(url or self.url)

        self.step(STEP_USER, {
            'user_type': user_type,
            'username': username,
            'first_name': 'Ana',
            'last_name': 'Lopez',
        }, url=url)

        self.step(STEP_SECURITY, {
            'password': PASSWORD,
            'confirm_password': PASSWORD,
        }, url=url)

        self.step(STEP_CONTACT, {
            'email': email,
            'confirm_email': email,
            'phone_number_code': UserModel.PhoneCodeChoices.COLOMBIA,
            'phone_number': '3001234567',
        }, url=url)

        return self.step(STEP_CODE, {'unique_code': code},
                         url=url, expect_ok=False)

    def daily_code(self, code='CODIGODELDIA', kind=None):
        return GeaDailyUniqueCode.objects.create(
            valid_on=timezone.localdate(),
            code=code,
            kind=kind or GeaDailyUniqueCode.KindChoices.GENERAL,
        )

    def buyer_code_for(self, email):
        """El codigo que el wizard dejo en cache al terminar el paso 3."""
        view = GeaUserRegisterWizardView()

        return cache.get(view._buyer_cache_key(email.strip().lower()))


class TestTheCodeIsWhatGatesTheDoor(WizardMixin, TestCase):
    """Sin codigo valido no hay cuenta. Es toda la puerta."""

    def test_a_supplier_registers_with_the_daily_code(self):
        self.daily_code('CODIGODELDIA')

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA',
        )

        self.assertTrue(UserModel.objects.filter(username='nuevo').exists())

    def test_a_wrong_code_creates_nothing(self):
        self.daily_code('CODIGODELDIA')

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='INVENTADO',
        )

        self.assertFalse(UserModel.objects.filter(username='nuevo').exists())

    def test_no_code_at_all_creates_nothing(self):
        self.daily_code('CODIGODELDIA')

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='',
        )

        self.assertFalse(UserModel.objects.filter(username='nuevo').exists())

    def test_yesterdays_code_does_not_work(self):
        """
        El codigo del dia caduca por fecha, no por uso. Si valiera el de ayer,
        cualquiera que lo hubiera recibido una vez entraria para siempre.
        """
        GeaDailyUniqueCode.objects.create(
            valid_on=timezone.localdate() - timezone.timedelta(days=1),
            code='CODIGODEAYER',
            kind=GeaDailyUniqueCode.KindChoices.GENERAL,
        )

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODEAYER',
        )

        self.assertFalse(UserModel.objects.filter(username='nuevo').exists())

    def test_the_buyer_daily_code_does_not_open_the_supplier_door(self):
        """
        Hay dos codigos diarios, uno por cada tipo de destinatario. El del
        comprador se manda a una lista distinta; si abriera tambien la puerta
        del proveedor, la separacion no significaria nada.
        """
        self.daily_code('CODIGODECOMPRA',
                        kind=GeaDailyUniqueCode.KindChoices.BUYER)

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODECOMPRA',
        )

        self.assertFalse(UserModel.objects.filter(username='nuevo').exists())


class TestTheBuyerCodeGoesToTheirEmail(WizardMixin, TestCase):
    """
    El comprador no recibe el codigo del dia: se le manda uno propio al correo
    que acaba de escribir. Eso es lo que prueba que el correo es suyo.
    """

    # El correo de un comprador tiene que ser de uno de los dominios de la
    # casa: `BuyerContactForm` lo exige.
    BUYER_EMAIL = 'comprador@propensionesabogados.com'

    def start_buyer(self, email=None):
        email = email or self.BUYER_EMAIL

        self.client.get(self.url)

        self.step(STEP_USER, {
            'user_type': UserModel.UserTypeChoices.BUYER,
            'username': 'comprador',
            'first_name': 'Ana',
            'last_name': 'Lopez',
        })
        self.step(STEP_SECURITY, {
            'password': PASSWORD, 'confirm_password': PASSWORD,
        })
        self.step(STEP_CONTACT, {
            'email': email,
            'confirm_email': email,
            'phone_number_code': UserModel.PhoneCodeChoices.COLOMBIA,
            'phone_number': '3001234567',
        })

        return email

    def test_finishing_the_contact_step_sends_a_code(self):
        from django.core import mail

        email = self.start_buyer()

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [email])
        self.assertIsNotNone(self.buyer_code_for(email))

    def test_the_emailed_code_lets_them_in(self):
        email = self.start_buyer()

        self.step(STEP_CODE, {'unique_code': self.buyer_code_for(email)},
                  expect_ok=False)

        self.assertTrue(UserModel.objects.filter(username='comprador').exists())

    def test_someone_elses_code_does_not(self):
        """
        El codigo esta atado al correo. Si no lo estuviera, uno cualquiera
        serviria para registrar a nombre de otra direccion.
        """
        self.start_buyer()

        other = GeaUserRegisterWizardView()
        cache.set(
            other._buyer_cache_key('otro@propensionesabogados.com'),
            'AAAAAAAAAA', 600,
        )

        self.step(STEP_CODE, {'unique_code': 'AAAAAAAAAA'}, expect_ok=False)

        self.assertFalse(
            UserModel.objects.filter(username='comprador').exists())

    def test_the_code_is_burned_after_use(self):
        """
        Si quedara en cache, el mismo codigo abriria una segunda cuenta
        durante los diez minutos que dura.
        """
        email = self.start_buyer()
        code = self.buyer_code_for(email)

        self.step(STEP_CODE, {'unique_code': code}, expect_ok=False)

        self.assertIsNone(self.buyer_code_for(email))

    def test_the_daily_code_does_not_work_for_a_buyer(self):
        """La otra mitad de la separacion entre los dos secretos."""
        self.daily_code('CODIGODELDIA')
        self.start_buyer()

        self.step(STEP_CODE, {'unique_code': 'CODIGODELDIA'}, expect_ok=False)

        self.assertFalse(
            UserModel.objects.filter(username='comprador').exists())


class TestTheAccountItCreates(WizardMixin, TestCase):

    def setUp(self):
        super().setUp()
        self.daily_code('CODIGODELDIA')

    def test_the_email_hash_is_set(self):
        """
        Sin el, el usuario recien creado no podria entrar ni recuperar su
        contrasena: las dos cosas buscan por ese hash.
        """
        from apps.common.utils.functions import sha256_hex

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA', email='Nueva@Example.COM',
        )

        user = UserModel.objects.get(username='nuevo')

        self.assertEqual(user.email_hash, sha256_hex('nueva@example.com'))

    def test_the_password_is_not_stored_in_the_clear(self):
        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA',
        )

        user = UserModel.objects.get(username='nuevo')

        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_the_new_account_is_logged_in(self):
        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA',
        )

        self.assertIn('_auth_user_id', self.client.session)

    def test_a_duplicate_email_does_not_create_a_second_account(self):
        UserModel.objects.create_user(
            username='yaestaba', email='nuevo@example.com',
            password=PASSWORD, first_name='a', last_name='b',
        )

        self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA', email='nuevo@example.com',
        )

        self.assertFalse(UserModel.objects.filter(username='nuevo').exists())


class TestTheNextParameterCannotLeaveTheSite(WizardMixin, TestCase):
    """
    Al terminar, el wizard **inicia la sesion** y despues redirige a donde
    diga ``?next=``.

    Un ``next`` sin comprobar es un redirector abierto, y aqui de los peores:
    el enlace se manda con una excusa creible --"registrate aqui"--, la
    victima se registra de verdad, y acaba en un sitio ajeno recien
    autenticada, con la ``Referer`` de esta plataforma detras. El propio
    proyecto ya tiene el patron correcto en ``assets/views.py::_safe_next``.
    """

    def setUp(self):
        super().setUp()
        self.daily_code('CODIGODELDIA')

    def register_with_next(self, target):
        url = self.wizard_url(next=target)

        return self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA', url=url,
        )

    def test_an_external_next_is_not_followed(self):
        response = self.register_with_next('https://sitio-ajeno.example/')

        self.assertNotIn('sitio-ajeno.example', response.get('Location', ''))

    def test_a_protocol_relative_next_is_not_followed(self):
        """
        `//sitio-ajeno.example` no lleva esquema y parece una ruta local, pero
        el navegador la resuelve como otro dominio. Es la forma que se escapa
        de una comprobacion hecha a ojo.
        """
        response = self.register_with_next('//sitio-ajeno.example/')

        self.assertNotIn('sitio-ajeno.example', response.get('Location', ''))

    def test_a_local_next_is_still_honoured(self):
        """
        La otra mitad: la funcionalidad tiene que seguir. Un `next` propio es
        util y no se toca.
        """
        response = self.register_with_next('/buyer/')

        self.assertEqual(response.get('Location', ''), '/buyer/')

    def test_without_next_it_goes_to_the_holder_dashboard(self):
        response = self.register(
            user_type=UserModel.UserTypeChoices.HOLDER,
            code='CODIGODELDIA',
        )

        self.assertEqual(
            response.get('Location', ''), reverse('assets:holder_index'))
