# apps/project/specific/assets_management/assets/tests.py
"""
Alta de un activo y vuelta a donde se venia.

El alta acepta un ``next`` para que quien llega desde otro formulario -- el de
un resumen AEGIS -- regrese alli con el activo ya seleccionado. Un ``next`` es
justo el sitio por donde se cuela una redireccion abierta, asi que la mitad de
estas pruebas van a eso.

    manage.py test apps.project.specific.assets_management.assets \\
        --settings=app_core.settings_test
"""

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

from .models import AssetCategoryModel, AssetModel, AssetsNamesModel

PASSWORD = 'pw-for-tests-123'


class AssetCreationReturnTests(TestCase):
    """Ida y vuelta entre el alta de activos y el alta de un resumen."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = UserModel.objects.create_user(
            username='asset_staff', email='asset@example.com',
            password=PASSWORD, user_type=UserModel.UserTypeChoices.BUYER,
            is_staff=True,
        )
        cls.category = AssetCategoryModel.objects.create(
            es_name='Bonos', en_name='Bonds'
        )

    def setUp(self):
        self.assertTrue(
            self.client.login(username=self.staff.username, password=PASSWORD)
        )
        self.assets_url = reverse('assets:create')
        self.summary_url = reverse('code_gen:summary_create')

    def payload(self, name='Microlingotes de Oro', **extra):
        data = {
            'es_name': name,
            'en_name': 'Gold Micro-ingots',
            'category': str(self.category.pk),
            'quantity_type': 'UNIT',
            'total_quantity': '10',
            'es_description': 'x', 'en_description': 'x',
            'es_observations': 'x', 'en_observations': 'x',
        }
        data.update(extra)
        return data

    def create_asset(self, **extra):
        before = set(AssetModel.objects.values_list('pk', flat=True))
        response = self.client.post(self.assets_url, self.payload(**extra))
        created = AssetModel.objects.exclude(pk__in=before).first()
        return response, created

    # ---------------- El camino bueno ----------------

    def test_the_box_form_links_to_the_real_screen_not_the_admin(self):
        """El alta de activos tiene pantalla propia; nadie va al admin."""
        html = self.client.get(self.summary_url).content.decode()

        self.assertIn(self.assets_url, html)
        self.assertNotIn('/admin/assets/assetsnamesmodel/add', html)

    def test_saving_returns_to_the_box_form_with_the_asset(self):
        response, created = self.create_asset(next=self.summary_url)

        self.assertIsNotNone(created)
        self.assertRedirects(
            response,
            f'{self.summary_url}?asset={created.pk}',
            fetch_redirect_response=False,
        )

    def test_the_box_form_preselects_the_returning_asset(self):
        _, created = self.create_asset(next=self.summary_url)

        response = self.client.get(self.summary_url, {'asset': str(created.pk)})
        initial = response.context['form'].initial

        self.assertEqual(str(initial.get('asset')), str(created.pk))
        # La etiqueta se propone sola; sigue siendo editable.
        self.assertTrue(initial.get('asset_label'))

    def test_without_next_the_old_destination_is_kept(self):
        """Quien entra por su cuenta acaba donde acababa antes."""
        response, created = self.create_asset()

        self.assertIsNotNone(created)
        self.assertRedirects(
            response,
            reverse('buyers:buyer_index'),
            fetch_redirect_response=False,
        )

    # ---------------- Lo que no puede pasar ----------------

    def test_next_cannot_send_the_user_off_site(self):
        """Sin esto, el alta seria un trampolin hacia cualquier dominio."""
        hostile = (
            'https://evil.example.com/phish',
            '//evil.example.com/phish',
            'http://evil.example.com',
        )

        for index, target in enumerate(hostile):
            with self.subTest(next=target):
                response, created = self.create_asset(
                    name=f'Activo hostil {index}', next=target
                )

                self.assertIsNotNone(created)
                self.assertNotIn(
                    'evil.example.com', response.headers.get('Location', '')
                )

    def test_a_bogus_asset_id_does_not_break_the_box_form(self):
        for bogus in ('00000000-0000-0000-0000-000000000000',
                      'no-es-un-uuid', ''):
            with self.subTest(asset=bogus):
                response = self.client.get(self.summary_url, {'asset': bogus})

                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context['form'].initial.get('asset'))


class AssetNameInlineTests(TestCase):
    """El activo no existe sin su nombre: se crean juntos o no se crea nada."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = UserModel.objects.create_user(
            username='inline_staff', email='inline@example.com',
            password=PASSWORD, user_type=UserModel.UserTypeChoices.BUYER,
            is_staff=True,
        )
        cls.category = AssetCategoryModel.objects.create(
            es_name='Bonos', en_name='Bonds'
        )

    def setUp(self):
        self.client.login(username=self.staff.username, password=PASSWORD)

    def test_one_post_creates_both(self):
        self.client.post(reverse('assets:create'), {
            'es_name': 'Billetes de Alta Denominación',
            'en_name': 'High Denomination Notes',
            'category': str(self.category.pk),
            'quantity_type': 'UNIT',
            'total_quantity': '5',
            'es_description': 'x', 'en_description': 'x',
            'es_observations': 'x', 'en_observations': 'x',
        })

        name = AssetsNamesModel.objects.filter(
            en_name__iexact='High Denomination Notes'
        ).first()

        self.assertIsNotNone(name)
        self.assertTrue(AssetModel.objects.filter(asset_name=name).exists())
