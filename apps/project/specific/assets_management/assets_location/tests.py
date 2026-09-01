# apps/project/specific/assets_management/assets_location/tests.py
"""
Ubicaciones e inventario del tenedor: quien entra y que puede tocar.

Esta app no tenia ninguna prueba, y es donde vive ``HolderRequiredMixin`` --
el control de acceso de todo el lado del tenedor, que ademas importa la app
``assets``. Son dos preguntas distintas y las dos hacen falta:

* **Quien entra.** El mixin deja pasar a tenedor, representante e
  intermediario, y ademas a ``is_staff`` e ``is_superuser``. Al comprador lo
  manda a la portada.
* **Que ve el que entra.** Esto es lo que de verdad separa a un tenedor de
  otro, y no esta en el ``dispatch`` sino en ``get_queryset()``, que acota
  todo a ``created_by=request.user``. Sin esa segunda mitad, cualquier
  tenedor podria editar el inventario de otro con solo cambiar el UUID de la
  URL: pasaria el control de acceso, porque tambien es tenedor.

El borrado es logico (``is_active = False``), asi que hay que comprobar dos
cosas por separado: que la fila sigue ahi y que deja de listarse.

    manage.py test apps.project.specific.assets_management.assets_location \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import (
    AssetCategoryModel, AssetModel, AssetsNamesModel)

from .models import AssetCountryModel, AssetLocationModel, LocationModel

PASSWORD = 'pw-for-tests-123'


class LocationFixtureMixin:
    """Dos tenedores distintos, cada uno con lo suyo."""

    @classmethod
    def setUpTestData(cls):
        types = UserModel.UserTypeChoices

        cls.holder = cls._user('holder_one', types.HOLDER)
        cls.other_holder = cls._user('holder_two', types.HOLDER)
        cls.representative = cls._user('rep_one', types.REPRESENTATIVE)
        cls.intermediary = cls._user('inter_one', types.INTERMEDIARY)
        cls.buyer = cls._user('buyer_one', types.BUYER)
        cls.staff = cls._user('staff_one', types.BUYER, is_staff=True)

        cls.country = AssetCountryModel.objects.create(
            es_country_name='Colombia', en_country_name='Colombia'
        )
        cls.asset = AssetModel.objects.create(
            asset_name=AssetsNamesModel.objects.create(
                es_name='Bono', en_name='Bond'),
            category=AssetCategoryModel.objects.create(
                es_name='Bonos', en_name='Bonds'),
        )

    @classmethod
    def _user(cls, username, user_type, **extra):
        return UserModel.objects.create_user(
            username=username, email=f'{username}@example.com',
            password=PASSWORD, user_type=user_type, **extra
        )

    def login(self, user):
        self.assertTrue(
            self.client.login(username=user.username, password=PASSWORD))

    def make_location(self, owner, reference='bodega norte'):
        return LocationModel.objects.create(
            created_by=owner, reference=reference, country=self.country)

    def make_inventory(self, owner, amount=10):
        return AssetLocationModel.objects.create(
            created_by=owner, asset=self.asset,
            location=self.make_location(owner, f'bodega de {owner.username}'),
            amount=amount,
        )


class TestWhoCanReachTheHolderArea(LocationFixtureMixin, TestCase):
    """El ``dispatch`` del mixin: la primera mitad del control."""

    def setUp(self):
        self.url = reverse('assets_location:add_location')

    def test_a_holder_gets_in(self):
        self.login(self.holder)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_a_representative_gets_in(self):
        self.login(self.representative)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_an_intermediary_gets_in(self):
        self.login(self.intermediary)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_a_buyer_is_sent_to_the_front_page(self):
        """
        Un comprador no tiene activos que ubicar. No se le da un 403: se le
        manda a donde si tiene algo que hacer.
        """
        self.login(self.buyer)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('core:index'))

    def test_staff_gets_in_even_being_a_buyer(self):
        """
        Los mixins de rol de este proyecto dejan pasar siempre a `is_staff` e
        `is_superuser`: el equipo interno tiene que poder arreglar cosas.
        """
        self.login(self.staff)

        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_anonymous_is_sent_to_the_login(self):
        """
        Y con el `next` puesto: quien llega sin sesion a una pagina concreta
        tiene que acabar en esa pagina despues de entrar, no en la portada.
        """
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        self.assertIn(f'next={self.url}', response.url)


class TestOneHolderCannotTouchAnothers(LocationFixtureMixin, TestCase):
    """
    La segunda mitad, y la que de verdad separa a un tenedor de otro.

    El ``dispatch`` deja pasar a los dos: los dos son tenedores. Lo unico que
    impide que uno edite el inventario del otro es que ``get_queryset()``
    acota por ``created_by``, y por eso el objeto ajeno no es un 403 sino un
    404 -- para quien pregunta, sencillamente no existe.
    """

    def setUp(self):
        self.mine = self.make_inventory(self.holder)
        self.theirs = self.make_inventory(self.other_holder)
        self.their_location = self.theirs.location

        self.login(self.holder)

    def test_i_can_open_my_own_inventory(self):
        response = self.client.get(reverse(
            'assets_location:update_asset_location',
            kwargs={'pk': self.mine.pk}))

        self.assertEqual(response.status_code, 200)

    def test_i_cannot_open_someone_elses_inventory(self):
        response = self.client.get(reverse(
            'assets_location:update_asset_location',
            kwargs={'pk': self.theirs.pk}))

        self.assertEqual(response.status_code, 404)

    def test_i_cannot_open_someone_elses_location(self):
        response = self.client.get(reverse(
            'assets_location:update_location',
            kwargs={'pk': self.their_location.pk}))

        self.assertEqual(response.status_code, 404)

    def test_i_cannot_delete_someone_elses_inventory(self):
        self.client.post(reverse(
            'assets_location:delete_asset_location',
            kwargs={'pk': self.theirs.pk}))

        self.theirs.refresh_from_db()

        self.assertTrue(self.theirs.is_active)

    def test_i_cannot_delete_someone_elses_location(self):
        response = self.client.post(reverse(
            'assets_location:delete_location',
            kwargs={'pk': self.their_location.pk}))

        self.their_location.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertTrue(self.their_location.is_active)

    def test_the_dashboard_only_lists_what_is_mine(self):
        response = self.client.get(reverse('assets:holder_index'))

        self.assertIn(self.mine, response.context['assets'])
        self.assertNotIn(self.theirs, response.context['assets'])


class TestDeletingIsLogical(LocationFixtureMixin, TestCase):
    """
    Invariante del proyecto: se marca ``is_active = False``, no se borra.

    Son dos comprobaciones distintas y las dos hacen falta: que la fila siga
    en la tabla --si no, la auditoria pierde el rastro-- y que deje de
    listarse, porque un borrado que no desaparece de la pantalla no es un
    borrado para quien lo pulsa.
    """

    def setUp(self):
        self.inventory = self.make_inventory(self.holder)
        self.location = self.make_location(self.holder, 'bodega sur')

        self.login(self.holder)

    def test_the_inventory_row_survives(self):
        self.client.post(reverse(
            'assets_location:delete_asset_location',
            kwargs={'pk': self.inventory.pk}))

        self.inventory.refresh_from_db()

        self.assertFalse(self.inventory.is_active)
        self.assertTrue(
            AssetLocationModel.objects.filter(pk=self.inventory.pk).exists())

    def test_it_stops_being_listed(self):
        self.client.post(reverse(
            'assets_location:delete_asset_location',
            kwargs={'pk': self.inventory.pk}))

        response = self.client.get(reverse('assets:holder_index'))

        self.assertNotIn(self.inventory, response.context['assets'])

    def test_the_location_row_survives_too(self):
        self.client.post(reverse(
            'assets_location:delete_location',
            kwargs={'pk': self.location.pk}))

        self.location.refresh_from_db()

        self.assertFalse(self.location.is_active)
        self.assertTrue(
            LocationModel.objects.filter(pk=self.location.pk).exists())


class TestTheLocationReference(LocationFixtureMixin, TestCase):
    """
    La referencia es como se nombra una bodega en el dia a dia.

    Se guarda en mayusculas para que "Bodega Norte" y "bodega norte" sean la
    misma, y se inventa una cuando no se escribe ninguna: una ubicacion sin
    nombre no se puede elegir en un desplegable.
    """

    def test_it_is_stored_uppercased_and_trimmed(self):
        location = self.make_location(self.holder, '  bodega norte  ')

        self.assertEqual(location.reference, 'BODEGA NORTE')

    def test_an_empty_reference_gets_one_generated(self):
        location = LocationModel.objects.create(
            created_by=self.holder, country=self.country)

        self.assertTrue(location.reference)
        self.assertIn('COLOMBIA', location.reference)

    def test_two_generated_references_do_not_collide(self):
        first = LocationModel.objects.create(
            created_by=self.holder, country=self.country)
        second = LocationModel.objects.create(
            created_by=self.holder, country=self.country)

        self.assertNotEqual(first.reference, second.reference)


class TestTheCountry(LocationFixtureMixin, TestCase):

    def test_names_are_normalized(self):
        country = AssetCountryModel.objects.create(
            es_country_name='  perú  ', en_country_name=' peru ')

        self.assertEqual(country.es_country_name, 'Perú')
        self.assertEqual(country.en_country_name, 'Peru')

    def test_the_spanish_name_is_the_one_used(self):
        country = AssetCountryModel.objects.create(
            es_country_name='Brasil', en_country_name='Brazil')

        self.assertEqual(country.country_name(), 'Brasil')


class TestCreatingRecordsTheOwner(LocationFixtureMixin, TestCase):
    """
    ``created_by`` no viene del formulario, lo pone la vista.

    Si viniera del formulario, bastaria con cambiarlo en el navegador para
    crear inventario a nombre de otro.
    """

    def test_a_new_location_belongs_to_whoever_created_it(self):
        self.login(self.holder)

        self.client.post(reverse('assets_location:add_location'), {
            'reference': 'bodega nueva',
            'country': self.country.pk,
            'description_es': 'x',
            'description_en': 'x',
        })

        location = LocationModel.objects.filter(
            reference='BODEGA NUEVA').first()

        self.assertIsNotNone(location)
        self.assertEqual(location.created_by, self.holder)

    def test_the_owner_cannot_be_forced_from_the_form(self):
        self.login(self.holder)

        self.client.post(reverse('assets_location:add_location'), {
            'reference': 'bodega ajena',
            'country': self.country.pk,
            'description_es': 'x',
            'description_en': 'x',
            # Lo que mandaria quien quisiera crearla a nombre de otro.
            'created_by': str(self.other_holder.pk),
        })

        location = LocationModel.objects.filter(
            reference='BODEGA AJENA').first()

        self.assertIsNotNone(location)
        self.assertEqual(location.created_by, self.holder)
