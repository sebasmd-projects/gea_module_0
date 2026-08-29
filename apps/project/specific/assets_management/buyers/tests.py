# apps/project/specific/assets_management/buyers/tests.py
"""
Control de acceso del flujo de ordenes de compra.

Cada prueba de ``ClosedHolesTests`` reproduce un agujero que **estaba abierto**
y que ahora debe estar cerrado; ``LegitimateWorkflowTests`` comprueba lo
contrario, que el trabajo normal del equipo sigue pasando. Las dos mitades
importan por igual: un control de acceso que ademas impide trabajar se acaba
quitando, y entonces no protege nada.

    manage.py test apps.project.specific.assets_management.buyers
"""

from django.contrib.auth.models import Permission
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import (
    AssetCategoryModel, AssetModel, AssetsNamesModel)
from apps.project.specific.assets_management.assets_location.models import \
    AssetCountryModel

from .models import OfferModel, ServiceOrderRecipient

PASSWORD = 'pw-for-tests-123'


class OfferFixtureMixin:
    """Lo minimo para tener una orden de compra valida."""

    @classmethod
    def setUpTestData(cls):
        types = UserModel.UserTypeChoices

        cls.buyer = cls._user('buyer_one', types.BUYER)
        cls.mate = cls._user('buyer_two', types.BUYER)
        cls.holder = cls._user('holder_one', types.HOLDER)
        cls.intermediary = cls._user('intermediary_one', types.INTERMEDIARY)
        cls.staff = cls._user('staff_one', types.BUYER, is_staff=True)

        cls.country = AssetCountryModel.objects.create(
            es_country_name='Colombia', en_country_name='Colombia'
        )
        cls.asset = AssetModel.objects.create(
            asset_name=AssetsNamesModel.objects.create(
                es_name='Bono', en_name='Bond'
            ),
            category=AssetCategoryModel.objects.create(
                es_name='Bonos', en_name='Bonds'
            ),
        )

    @classmethod
    def _user(cls, username, user_type, **extra):
        return UserModel.objects.create_user(
            username=username, email=f'{username}@example.com',
            password=PASSWORD, user_type=user_type, **extra
        )

    def make_offer(self, quantity=10):
        return OfferModel.objects.create(
            created_by=self.buyer,
            asset=self.asset,
            offer_type=OfferModel.OfferTypeChoices.values[0],
            quantity_type=OfferModel.QuantityTypeChoices.values[0],
            offer_quantity=quantity,
            buyer_country=self.country,
        )

    def approve(self, offer):
        """Aprobar crea la orden de servicio: la orden pasa a documento vivo."""
        offer.reviewed = True
        offer.reviewed_by = self.buyer
        offer.save()
        offer.is_approved = True
        offer.approved_by = self.buyer
        offer.save()
        offer.refresh_from_db()
        return offer

    def login(self, user):
        self.assertTrue(
            self.client.login(username=user.username, password=PASSWORD)
        )
        return self.client

    def post_edit(self, offer, quantity):
        return self.client.post(
            reverse('buyers:offer_update', kwargs={'pk': offer.pk}),
            {
                'quantity_type': offer.quantity_type,
                'offer_quantity': quantity,
                'buyer_country': self.country.pk,
                'en_observation': 'x', 'es_observation': 'x',
                'en_description': 'x', 'es_description': 'x',
            },
        )

    def grant(self, user, *codenames):
        user.user_permissions.add(
            *Permission.objects.filter(codename__in=codenames)
        )
        # Django cachea los permisos en la instancia; hay que releerla.
        return UserModel.objects.get(pk=user.pk)


class ClosedHolesTests(OfferFixtureMixin, TestCase):
    """Cada una de estas fallaba antes."""

    def test_outsiders_cannot_read_a_purchase_order(self):
        """El detalle llevaba solo LoginRequired: bastaba con tener el UUID."""
        offer = self.make_offer()
        url = reverse('buyers:offer_details', kwargs={'id': offer.id})

        for outsider in (self.holder, self.intermediary):
            with self.subTest(user=outsider.username):
                self.client.logout()
                response = self.login(outsider).get(url)
                self.assertNotEqual(
                    response.status_code, 200,
                    'un usuario ajeno al flujo no puede ver la orden'
                )

    def test_approved_offer_cannot_be_edited_by_the_buyer_team(self):
        """Se cambiaba la cantidad de una orden aprobada y con PDF enviados."""
        offer = self.approve(self.make_offer(quantity=10))

        self.login(self.mate)
        self.post_edit(offer, 999999)

        offer.refresh_from_db()
        self.assertEqual(offer.offer_quantity, 10)

    def test_approved_offer_cannot_be_soft_deleted(self):
        """Se podia ocultar del listado una orden en curso."""
        offer = self.approve(self.make_offer())

        response = self.login(self.mate).post(
            reverse('buyers:offer_delete', kwargs={'id': offer.id})
        )

        offer.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertTrue(offer.display)

    def test_service_order_is_not_emailed_before_approval(self):
        """
        El correo salia primero y el estado se validaba al guardar despues, asi
        que la orden de servicio de una orden sin aprobar se enviaba igual -- y
        ademas el guardado limpiaba el sello, con lo que no quedaba ni rastro.
        """
        offer = self.make_offer()
        ServiceOrderRecipient.objects.create(
            offer=offer, user=self.buyer, added_by=self.buyer
        )
        self.grant(self.mate, 'can_see_wizard_page', 'can_send_service_order')

        mail.outbox = []
        response = self.login(self.mate).post(
            reverse('buyers:offer_wizard_action', kwargs={'id': offer.id}),
            {'step': 'SO_NOTIFY'},
        )

        offer.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNone(offer.service_order_sent_at)

    def test_each_stage_needs_its_own_permission(self):
        """Ver el wizard no es poder operarlo."""
        offer = self.make_offer()
        url = reverse('buyers:offer_wizard_action', kwargs={'id': offer.id})

        self.grant(self.mate, 'can_see_wizard_page')
        response = self.login(self.mate).post(url, {'step': 'REVIEW'})

        offer.refresh_from_db()
        self.assertEqual(response.status_code, 403)
        self.assertFalse(offer.reviewed)


class LegitimateWorkflowTests(OfferFixtureMixin, TestCase):
    """Y esto es lo que NO se puede haber roto al cerrar lo anterior."""

    def test_the_buyer_team_still_works_on_drafts(self):
        """Las ordenes son trabajo de equipo mientras son borrador."""
        offer = self.make_offer()

        self.login(self.mate)
        self.post_edit(offer, 42)

        offer.refresh_from_db()
        self.assertEqual(offer.offer_quantity, 42)

        response = self.client.get(
            reverse('buyers:offer_details', kwargs={'id': offer.id})
        )
        self.assertEqual(response.status_code, 200)

    def test_a_draft_can_still_be_hidden(self):
        offer = self.make_offer()

        response = self.login(self.mate).post(
            reverse('buyers:offer_delete', kwargs={'id': offer.id})
        )

        offer.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(offer.display)

    def test_internal_staff_can_still_fix_a_live_offer(self):
        """El cierre por etapa no ata las manos a quien tiene que arreglarlo."""
        offer = self.approve(self.make_offer(quantity=10))

        self.login(self.staff)
        self.post_edit(offer, 77)

        offer.refresh_from_db()
        self.assertEqual(offer.offer_quantity, 77)

    def test_an_approved_service_order_is_sent_and_recorded(self):
        offer = self.approve(self.make_offer())
        ServiceOrderRecipient.objects.create(
            offer=offer, user=self.buyer, added_by=self.buyer
        )
        self.grant(self.mate, 'can_see_wizard_page', 'can_send_service_order')

        mail.outbox = []
        response = self.login(self.mate).post(
            reverse('buyers:offer_wizard_action', kwargs={'id': offer.id}),
            {'step': 'SO_NOTIFY'},
        )

        offer.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIsNotNone(offer.service_order_sent_at)
        # Antes se guardaba el sello sin decir quien lo habia enviado.
        self.assertEqual(offer.service_order_sent_by_id, self.mate.pk)
