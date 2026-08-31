# apps/project/common/users/tests.py
"""
El usuario: PII cifrada, ``email_hash`` y quien es quien.

Esta app no tenia ninguna prueba, y sostiene dos invariantes del proyecto (el
4 y el 5). El que hay que entender antes de tocar nada es este:

    **El correo esta cifrado, asi que no se puede buscar por el.**

``EncryptedEmailField`` cifra con Fernet, que lleva un vector de
inicializacion aleatorio: el mismo correo guardado dos veces produce dos
ciphertexts distintos. De ahi se siguen tres cosas que no son evidentes
leyendo el modelo:

1. ``UserModel.objects.filter(email=...)`` **siempre devuelve cero**. No falla
   ni avisa: no encuentra.
2. El ``unique=True`` del campo ``email`` no impide duplicados. Quien impide
   de verdad dos cuentas con el mismo correo es el ``unique`` de
   ``email_hash``.
3. ``USERNAME_FIELD = 'email'`` no basta para entrar: el
   ``get_by_natural_key`` de Django hace justo esa consulta que nunca
   encuentra. Lo que hace funcionar el login es
   ``EmailOrUsernameModelBackend``, que busca por ``email_hash``.

Por eso ``email_hash`` no es un indice de conveniencia: es la unica forma de
encontrar a alguien por su correo. Si deja de recalcularse en ``save()``, el
login por correo y la recuperacion de contrasena dejan de funcionar a la vez,
y sin ningun error que lo diga.

    manage.py test apps.project.common.users \\
        --settings=app_core.settings_test
"""

from datetime import timedelta

from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.utils import IntegrityError
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.common.utils.functions import sha256_hex

from .models import (AddressModel, CityModel, CountryModel, StateModel,
                     UserModel, UserPersonalInformationModel)

PASSWORD = 'una-clave-larga-de-prueba-123'


def make_user(**kwargs):
    data = {
        'username': 'juan',
        'email': 'juan@example.com',
        'password': PASSWORD,
        'first_name': 'juan',
        'last_name': 'perez',
    }
    data.update(kwargs)

    return UserModel.objects.create_user(**data)


class TestTheEmailIsEncryptedAtRest(TestCase):
    """
    Lo primero que hay que saber de este modelo.

    No es una comprobacion de la libreria: es la razon de que exista
    ``email_hash``, y quien no la conozca escribira un
    ``filter(email=...)`` que no falla, simplemente no encuentra.
    """

    def test_the_stored_value_is_not_the_email(self):
        user = make_user()

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT email FROM apps_users_user WHERE id = %s',
                [user.id.hex],
            )
            stored = cursor.fetchone()[0]

        self.assertNotIn('juan@example.com', stored)
        self.assertTrue(stored.startswith('gAAAA'), stored[:20])

    def test_it_still_reads_back_as_the_email(self):
        make_user()

        self.assertEqual(UserModel.objects.first().email, 'juan@example.com')

    def test_searching_by_email_finds_nothing(self):
        """
        El comportamiento que sorprende. No lanza excepcion: devuelve vacio,
        que es mucho peor porque parece un usuario que no existe.
        """
        make_user()

        self.assertEqual(UserModel.objects.filter(
            email='juan@example.com').count(), 0)

    def test_searching_by_hash_does_find_it(self):
        user = make_user()

        self.assertEqual(
            UserModel.objects.filter(email_hash=user.email_hash).count(), 1
        )

    def test_the_natural_key_lookup_cannot_work(self):
        """
        ``USERNAME_FIELD = 'email'`` mas cifrado no determinista.

        Se fija a proposito: si algun dia el correo dejara de cifrarse, esto
        empezaria a pasar y seria la senal de que ``email_hash`` ya no es
        imprescindible. Mientras siga fallando, quitar el backend propio deja
        a todo el mundo fuera.
        """
        make_user()

        with self.assertRaises(UserModel.DoesNotExist):
            UserModel.objects.get_by_natural_key('juan@example.com')


class TestTheEmailHash(TestCase):
    """La unica forma de encontrar a alguien por su correo."""

    def test_it_is_the_sha256_of_the_normalized_email(self):
        user = make_user(email='juan@example.com')

        self.assertEqual(user.email_hash, sha256_hex('juan@example.com'))

    def test_case_does_not_change_it(self):
        """
        Nadie escribe su correo siempre igual. Si el hash dependiera de las
        mayusculas, entrar dependeria de como se tecleo el dia del registro.
        """
        user = make_user(email='JUAN@Example.COM')

        self.assertEqual(user.email, 'juan@example.com')
        self.assertEqual(user.email_hash, sha256_hex('juan@example.com'))

    def test_surrounding_blanks_do_not_change_it(self):
        user = make_user(email='  juan@example.com  ')

        self.assertEqual(user.email_hash, sha256_hex('juan@example.com'))

    def test_it_is_recalculated_when_the_email_changes(self):
        """
        El invariante 5. Si el hash se quedara con el correo viejo, el login
        y la recuperacion de contrasena apuntarian a una direccion que ya no
        es la del usuario -- y sin dar ningun error.
        """
        user = make_user()
        old = user.email_hash

        user.email = 'otro@example.com'
        user.save()

        self.assertNotEqual(user.email_hash, old)
        self.assertEqual(user.email_hash, sha256_hex('otro@example.com'))

    def test_two_accounts_cannot_share_an_email(self):
        """
        Lo impide el unique de `email_hash`, no el del campo `email`: dos
        cifrados del mismo correo son bytes distintos y la base de datos no
        los ve iguales.
        """
        make_user()

        with self.assertRaises(IntegrityError):
            make_user(username='otro')

    def test_the_same_email_in_another_case_is_still_the_same_account(self):
        """
        Sin normalizar, `Juan@…` y `juan@…` serian dos cuentas para la misma
        persona, y entrar dependeria de cual de las dos se acertara.
        """
        make_user(email='juan@example.com')

        with self.assertRaises(IntegrityError):
            make_user(username='otro', email='JUAN@EXAMPLE.COM')


class TestLoggingIn(TestCase):
    """
    El backend propio, que es lo que hace utilizable un correo cifrado.

    Se prueba a traves de ``authenticate()`` y no llamando al backend a mano:
    lo que importa es que la cadena entera funcione, incluido el orden de
    ``AUTHENTICATION_BACKENDS``.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.user = make_user()

    def login(self, username, password=PASSWORD):
        # `request` es obligatorio: `AxesStandaloneBackend` va primero y lo
        # exige. Sin el, `authenticate()` lanza excepcion.
        request = self.factory.post('/')

        return authenticate(request, username=username, password=password)

    def test_by_email(self):
        self.assertEqual(self.login('juan@example.com'), self.user)

    def test_by_email_in_any_case(self):
        self.assertEqual(self.login('JUAN@Example.COM'), self.user)

    def test_by_username(self):
        self.assertEqual(self.login('juan'), self.user)

    def test_with_the_wrong_password(self):
        self.assertIsNone(self.login('juan@example.com', 'no-es-la-clave'))

    def test_an_unknown_email(self):
        self.assertIsNone(self.login('nadie@example.com'))

    def test_an_inactive_user_cannot_get_in(self):
        """
        Desactivar es como se da de baja a alguien en esta plataforma: el
        borrado es logico. Si `is_active` no cortara el login, dar de baja no
        serviria de nada.
        """
        self.user.is_active = False
        self.user.save()

        self.assertIsNone(self.login('juan@example.com'))


class TestWhoIsWho(TestCase):
    """Los dos lados del producto: quien tiene activos y quien compra."""

    def test_a_buyer_is_a_buyer(self):
        user = make_user(user_type=UserModel.UserTypeChoices.BUYER)

        self.assertTrue(user.is_buyer)
        self.assertFalse(user.is_asset_holder)

    def test_every_other_type_holds_assets(self):
        for code in ('I', 'R', 'H'):
            with self.subTest(user_type=code):
                user = make_user(
                    username=f'u{code}', email=f'{code}@example.com',
                    user_type=code,
                )

                self.assertTrue(user.is_asset_holder)
                self.assertFalse(user.is_buyer)

    def test_a_buyer_is_marked_verified_on_save(self):
        """
        `is_verified_holder` no significa nada para un comprador -- no tiene
        activos que verificar -- y se le pone a True para que no aparezca
        como pendiente en las pantallas de verificacion.
        """
        user = make_user(user_type=UserModel.UserTypeChoices.BUYER)

        self.assertTrue(user.is_verified_holder)

    def test_a_holder_is_not_verified_by_default(self):
        """El que si tiene activos empieza sin verificar, que es el punto."""
        user = make_user(user_type=UserModel.UserTypeChoices.HOLDER)

        self.assertFalse(user.is_verified_holder)


class TestNormalization(TestCase):

    def test_names_are_stored_in_title_case(self):
        user = make_user(first_name='  juan carlos ', last_name=' PEREZ ')

        self.assertEqual(user.first_name, 'Juan Carlos')
        self.assertEqual(user.last_name, 'Perez')

    def test_the_username_is_lowercased(self):
        user = make_user(username='  JuanP  ')

        self.assertEqual(user.username, 'juanp')

    def test_an_at_sign_in_the_username_is_rejected(self):
        """
        El backend decide por el '@' si busca por correo o por usuario. Un
        nombre de usuario con '@' se buscaria como correo y no se encontraria
        nunca.
        """
        user = UserModel(
            username='juan@casa', email='x@example.com',
            first_name='a', last_name='b',
        )

        with self.assertRaises(ValidationError):
            user.clean()


class TestPersonalInformationIsEncrypted(TestCase):
    """
    Invariante 4 por el lado de la PII: pasaporte, fecha de nacimiento y
    nacionalidad no se guardan en claro.
    """

    def setUp(self):
        self.user = make_user()

    def make_information(self, **kwargs):
        data = {
            'user': self.user,
            'citizenship_country': 'Colombia',
            'passport_id': 'AB1234567',
            'issuing_authority': 'cancilleria',
        }
        data.update(kwargs)

        return UserPersonalInformationModel.objects.create(**data)

    def test_the_passport_is_not_stored_in_the_clear(self):
        information = self.make_information()

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT passport_id, citizenship_country '
                'FROM apps_users_userpersonalpnformation WHERE id = %s',
                [information.id.hex],
            )
            passport, citizenship = cursor.fetchone()

        self.assertNotIn('AB1234567', passport)
        self.assertNotIn('Colombia', citizenship)

    def test_it_reads_back_correctly(self):
        self.make_information()

        stored = UserPersonalInformationModel.objects.first()

        self.assertEqual(stored.passport_id, 'AB1234567')
        self.assertEqual(stored.citizenship_country, 'Colombia')

    def test_the_issuing_authority_is_normalized(self):
        information = self.make_information(issuing_authority='cancilleria')

        self.assertEqual(information.issuing_authority, 'Cancilleria')

    def test_one_person_has_one_record(self):
        self.make_information()

        with self.assertRaises(IntegrityError):
            self.make_information()


class TestTheBirthDateRule(TestCase):
    """
    Menores de edad no, y fechas del futuro tampoco.

    La comparacion de la edad estaba **al reves**: rechazaba a todo el que
    pasara de dieciocho anos --con el mensaje de que hay que ser mayor de
    edad-- y aceptaba a un recien nacido. Una fecha mas antigua significa mas
    edad, y el ``<`` decia lo contrario.

    Paso desapercibido porque el valor por defecto del campo caia justo en la
    frontera, el unico punto que pasaba en las dos versiones. Por eso aqui se
    prueban las dos orillas y el propio defecto.
    """

    def validate(self, value):
        UserPersonalInformationModel.validate_birth_date(value)

    def years_ago(self, years):
        today = timezone.now().date()

        try:
            return today.replace(year=today.year - years)
        except ValueError:
            return today.replace(year=today.year - years, day=28)

    def test_a_future_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.validate(timezone.now().date() + timedelta(days=1))

    def test_a_newborn_is_rejected(self):
        """Lo que se aceptaba antes."""
        with self.assertRaises(ValidationError):
            self.validate(timezone.now().date())

    def test_a_minor_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.validate(self.years_ago(17))

    def test_someone_a_day_short_of_eighteen_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.validate(self.years_ago(18) + timedelta(days=1))

    def test_someone_exactly_eighteen_today_is_accepted(self):
        """
        El borde. Con `timedelta(days=18*365)` se perdian cuatro o cinco dias
        bisiestos, y quien cumplia dieciocho ayer seguia constando como menor
        casi una semana.
        """
        self.validate(self.years_ago(18))

    def test_an_adult_is_accepted(self):
        """Lo que se rechazaba antes, que era todo el mundo."""
        self.validate(self.years_ago(30))

    def test_the_default_value_passes_its_own_validator(self):
        """
        Es el unico punto que pasaba con la comparacion invertida, y por eso
        el fallo no se noto: el registro se creaba bien hasta que alguien
        escribia su fecha de verdad.
        """
        self.validate(UserPersonalInformationModel.default_birth_date())


class TestGeography(TestCase):
    """La cadena pais -> departamento -> ciudad -> direccion."""

    def setUp(self):
        self.country = CountryModel.objects.create(
            country_name='colombia', country_code='CO')
        self.state = StateModel.objects.create(
            state_name='antioquia', country=self.country)
        self.city = CityModel.objects.create(
            city_name='medellin', state=self.state)

    def test_names_are_normalized_at_every_level(self):
        self.assertEqual(self.country.country_name, 'Colombia')
        self.assertEqual(self.state.state_name, 'Antioquia')
        self.assertEqual(self.city.city_name, 'Medellin')

    def test_a_country_code_is_unique(self):
        with self.assertRaises(IntegrityError):
            CountryModel.objects.create(
                country_name='otra cosa', country_code='CO')

    def test_the_same_state_cannot_repeat_within_a_country(self):
        with self.assertRaises(IntegrityError):
            StateModel.objects.create(
                state_name='antioquia', country=self.country)

    def test_the_same_state_name_in_another_country_is_fine(self):
        other = CountryModel.objects.create(
            country_name='peru', country_code='PE')

        StateModel.objects.create(state_name='antioquia', country=other)

    def test_the_street_address_is_encrypted(self):
        address = AddressModel.objects.create(
            country=self.country, state=self.state, city=self.city,
            address_line_1='Calle 10 # 20-30', postal_code='050001',
        )

        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT address_line_1 FROM apps_users_address WHERE id = %s',
                [address.id],
            )
            stored = cursor.fetchone()[0]

        self.assertNotIn('Calle 10', stored)


class TestReferrals(TestCase):

    def test_someone_can_refer_someone_else(self):
        sponsor = make_user()
        invited = make_user(
            username='ana', email='ana@example.com',
            referred=sponsor, is_referred=True,
        )

        self.assertEqual(invited.referred, sponsor)
        self.assertIn(invited, sponsor.referrals.all())

    def test_deleting_the_sponsor_does_not_delete_the_invited(self):
        """
        `SET_NULL` y no `CASCADE`: quien entro por una invitacion tiene sus
        propios activos y sus propias ordenes. Que se vaya quien le invito no
        puede llevarselo por delante.
        """
        sponsor = make_user()
        invited = make_user(
            username='ana', email='ana@example.com', referred=sponsor)

        sponsor.delete()
        invited.refresh_from_db()

        self.assertIsNone(invited.referred)
        self.assertTrue(UserModel.objects.filter(pk=invited.pk).exists())
