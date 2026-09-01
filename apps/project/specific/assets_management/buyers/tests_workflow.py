# apps/project/specific/assets_management/buyers/tests_workflow.py
"""
El flujo de doce etapas de una orden de compra.

``tests.py`` cubre **quien** puede tocar una orden. Esto cubre **que** puede
pasarle: el estado derivado y las tres capas que protegen el orden de las
etapas.

Las tres capas son a proposito, y cada una tapa lo que la anterior no ve:

1. Los ``mark_*()``, que es por donde entra el wizard. Rechazan saltarse una
   etapa con un mensaje que se puede ensenar.
2. ``clean()`` y ``save()``, que ademas **arrastran**: quitar la aprobacion
   borra todo lo posterior, porque dejarlo seria una orden no aprobada con
   media liquidacion hecha.
3. Diez ``CheckConstraint`` en la base de datos. Son la unica capa que
   sobrevive a un ``QuerySet.update()``, a un script de migracion de datos o
   a alguien tocando la tabla a mano -- y ahi es donde se comprueban aqui,
   porque probarlas a traves del modelo solo comprueba la capa 1.

El invariante que lo sostiene todo: **el estado no se almacena**.
``status_code`` se calcula desde los sellos ``*_at`` cada vez que se pide. No
hay ningun campo ``status`` que pueda quedarse desincronizado, y por eso no
puede haber una orden que diga "pagada" sin los sellos que lo respalden.

    manage.py test apps.project.specific.assets_management.buyers.tests_workflow \\
        --settings=app_core.settings_test
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import OfferModel
from .tests import OfferFixtureMixin

Status = OfferModel.StatusChoices


class WorkflowMixin(OfferFixtureMixin):
    """Una orden y la forma de llevarla etapa a etapa."""

    def walk_to(self, offer, stage):
        """
        Lleva la orden hasta la etapa pedida, pasando por todas las
        anteriores. No hay atajo: cada ``mark_*`` exige la de antes.
        """
        steps = [
            ('approved', lambda: self.approve(offer)),
            ('so_sent', lambda: offer.mark_service_order_sent(self.staff)),
            ('pay_created',
             lambda: offer.mark_payment_order_created(self.staff)),
            ('pay_sent', lambda: offer.mark_payment_order_sent(self.staff)),
            ('possession',
             lambda: offer.mark_asset_in_possession(self.staff)),
            ('asset_sent', lambda: offer.mark_asset_sent(self.staff)),
            ('profit_created',
             lambda: offer.mark_profitability_created(self.staff)),
            ('subpayments', lambda: self.pay_all_three(offer)),
            ('profit_paid',
             lambda: offer.mark_profitability_paid(self.staff)),
        ]

        for name, action in steps:
            action()
            if name == stage:
                break

        offer.refresh_from_db()

        return offer

    def pay_all_three(self, offer):
        offer.mark_rrf_paid(self.staff)
        offer.mark_paymaster_paid(self.staff)
        offer.mark_prop_paid(self.staff)


class TestTheStateIsDerived(WorkflowMixin, TestCase):
    """
    Invariante 1. No hay campo ``status``: se calcula desde los sellos.

    Es lo que hace imposible una orden que *diga* estar pagada sin los sellos
    que lo respaldan -- el fallo clasico de guardar el estado por separado.
    """

    def test_a_fresh_order_is_pending(self):
        offer = self.make_offer()

        self.assertEqual(offer.status_code, Status.PENDING_APPROVAL)

    def test_reviewing_without_approving_is_not_approved(self):
        offer = self.make_offer()
        offer.reviewed = True
        offer.reviewed_by = self.staff
        offer.save()

        self.assertEqual(offer.status_code, Status.NOT_APPROVED)

    def test_the_status_follows_the_stamps_all_the_way(self):
        offer = self.make_offer()

        expected = [
            ('approved', Status.SO_CREATED),
            ('so_sent', Status.SO_SENT),
            ('pay_created', Status.PAY_CREATED),
            ('pay_sent', Status.PAY_SENT),
            ('possession', Status.POSSESSION),
            ('asset_sent', Status.ASSET_SENT),
            ('profit_created', Status.PROFIT_CREATED),
            ('profit_paid', Status.PROFIT_PAID),
        ]

        for stage, status in expected:
            with self.subTest(stage=stage):
                self.walk_to(offer, stage)
                self.assertEqual(offer.status_code, status)

    def test_approving_lands_on_service_order_created_not_approved(self):
        """
        Aprobar crea la orden de servicio en el propio ``save()``, asi que la
        orden nunca se queda en APPROVED: pasa directa a SO_CREATED. No es un
        fallo -- es el invariante 18 -- pero sorprende, y por eso se fija.
        """
        offer = self.approve(self.make_offer())

        self.assertEqual(offer.status_code, Status.SO_CREATED)

    def test_there_is_no_status_field_to_get_out_of_sync(self):
        field_names = {field.name for field in OfferModel._meta.get_fields()}

        self.assertNotIn('status', field_names)
        self.assertNotIn('status_code', field_names)

    def test_every_reachable_status_has_an_icon_and_a_colour(self):
        """
        ``status_icon`` y ``status_color`` indexan el diccionario sin
        ``get()``: un estado que falte no se pinta mal, revienta la pagina con
        un KeyError.
        """
        offer = self.make_offer()

        for stage in ('approved', 'so_sent', 'pay_created', 'pay_sent',
                      'possession', 'asset_sent', 'profit_created',
                      'profit_paid'):
            with self.subTest(stage=stage):
                self.walk_to(offer, stage)

                self.assertTrue(offer.status_icon)
                self.assertTrue(offer.status_color)
                self.assertTrue(offer.status_label)


class TestTheStagesCannotBeSkipped(WorkflowMixin, TestCase):
    """
    Capa 1: los ``mark_*``, que es por donde entra el wizard.

    Cada uno se prueba sobre una orden recien aprobada, o sea con la etapa
    anterior sin hacer.
    """

    def setUp(self):
        self.offer = self.approve(self.make_offer())

    def test_a_payment_order_needs_the_service_order_sent(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_payment_order_created(self.staff)

    def test_sending_a_payment_order_needs_it_created(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_payment_order_sent(self.staff)

    def test_possession_needs_the_payment_order_sent(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_asset_in_possession(self.staff)

    def test_sending_the_asset_needs_possession(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_asset_sent(self.staff)

    def test_profitability_needs_the_asset_sent(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_profitability_created(self.staff)

    def test_the_subpayments_need_profitability_created(self):
        for name in ('mark_rrf_paid', 'mark_paymaster_paid', 'mark_prop_paid'):
            with self.subTest(step=name):
                with self.assertRaises(ValidationError):
                    getattr(self.offer, name)(self.staff)

    def test_paying_profitability_needs_it_created(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_profitability_paid(self.staff)

    def test_an_unapproved_order_cannot_send_its_service_order(self):
        offer = self.make_offer()

        with self.assertRaises(ValidationError):
            offer.mark_service_order_sent(self.staff)


class TestTheThreeSubPayments(WorkflowMixin, TestCase):
    """
    Invariante 3: cerrar la rentabilidad exige los tres subpagos.

    Es la regla con dinero de por medio, y la unica del flujo que no es un
    simple "la etapa anterior primero".
    """

    def setUp(self):
        self.offer = self.walk_to(self.make_offer(), 'profit_created')

    def test_none_of_them_is_enough(self):
        with self.assertRaises(ValidationError):
            self.offer.mark_profitability_paid(self.staff)

    def test_two_of_them_are_not_enough(self):
        self.offer.mark_rrf_paid(self.staff)
        self.offer.mark_paymaster_paid(self.staff)

        with self.assertRaises(ValidationError):
            self.offer.mark_profitability_paid(self.staff)

    def test_the_three_of_them_are(self):
        self.pay_all_three(self.offer)
        self.offer.mark_profitability_paid(self.staff)
        self.offer.refresh_from_db()

        self.assertEqual(self.offer.status_code, Status.PROFIT_PAID)

    def test_taking_one_back_undoes_the_closing(self):
        """
        Si se pudiera desmarcar un subpago dejando la rentabilidad cerrada,
        la orden diria "pagada" con una de las tres partes sin pagar.
        """
        self.pay_all_three(self.offer)
        self.offer.mark_profitability_paid(self.staff)

        self.offer.mark_rrf_paid(self.staff, paid=False)
        self.offer.refresh_from_db()

        self.assertIsNone(self.offer.profitability_paid_at)
        self.assertNotEqual(self.offer.status_code, Status.PROFIT_PAID)

    def test_unmarking_clears_who_and_when(self):
        self.offer.mark_rrf_paid(self.staff)
        self.offer.mark_rrf_paid(self.staff, paid=False)
        self.offer.refresh_from_db()

        self.assertFalse(self.offer.recovery_repatriation_foundation_paid)
        self.assertIsNone(
            self.offer.recovery_repatriation_foundation_mark_by)
        self.assertIsNone(
            self.offer.recovery_repatriation_foundation_mark_at)


class TestTheDatabaseIsTheLastLine(WorkflowMixin, TestCase):
    """
    Capa 3: las ``CheckConstraint``.

    Se escriben con ``QuerySet.update()`` **a proposito**: no pasa por
    ``save()`` ni por ``clean()``, asi que es lo mas parecido a un script de
    migracion de datos o a alguien tocando la tabla. Si estas pruebas pasaran
    sin las restricciones, la base de datos aceptaria estados imposibles y el
    unico guardian seria el codigo Python de esta version del proyecto.
    """

    def update(self, offer, **fields):
        """Escribe saltandose el modelo entero."""
        with transaction.atomic():
            OfferModel.objects.filter(pk=offer.pk).update(**fields)

    def test_it_refuses_an_approval_without_a_review(self):
        offer = self.make_offer()

        with self.assertRaises(IntegrityError):
            self.update(offer, is_approved=True, reviewed=False)

    def test_it_refuses_a_service_order_sent_without_being_created(self):
        offer = self.approve(self.make_offer())

        with self.assertRaises(IntegrityError):
            self.update(
                offer,
                service_order_created_at=None,
                service_order_sent_at=timezone.now(),
            )

    def test_it_refuses_a_payment_order_before_the_service_order_is_sent(self):
        offer = self.approve(self.make_offer())

        with self.assertRaises(IntegrityError):
            self.update(offer, payment_order_created_at=timezone.now())

    def test_it_refuses_possession_before_the_payment_order_is_sent(self):
        offer = self.approve(self.make_offer())

        with self.assertRaises(IntegrityError):
            self.update(offer, asset_in_possession_at=timezone.now())

    def test_it_refuses_the_asset_sent_before_possession(self):
        offer = self.approve(self.make_offer())

        with self.assertRaises(IntegrityError):
            self.update(offer, asset_sent_at=timezone.now())

    def test_it_refuses_profitability_before_the_asset_is_sent(self):
        offer = self.approve(self.make_offer())

        with self.assertRaises(IntegrityError):
            self.update(offer, profitability_created_at=timezone.now())

    def test_it_refuses_closing_profitability_without_the_three_subpayments(self):
        """
        La restriccion ``profit_paid_requires_3_subpaids``, que es la que
        respalda el invariante 3 cuando nadie pasa por el modelo.
        """
        offer = self.walk_to(self.make_offer(), 'profit_created')

        with self.assertRaises(IntegrityError):
            self.update(
                offer,
                profitability_paid_at=timezone.now(),
                recovery_repatriation_foundation_paid=True,
                pay_master_service_paid=True,
                propensiones_paid=False,
            )

    def test_a_complete_order_is_accepted(self):
        """
        La otra mitad: las restricciones tienen que dejar pasar lo valido. Una
        que rechace el camino bueno se acaba quitando, y entonces no protege.
        """
        offer = self.walk_to(self.make_offer(), 'profit_paid')

        self.assertEqual(offer.status_code, Status.PROFIT_PAID)


class TestUndoingAnApprovalCascades(WorkflowMixin, TestCase):
    """
    Capa 2: ``save()`` arrastra.

    Quitar la aprobacion no puede dejar los sellos posteriores donde estaban:
    seria una orden sin aprobar con media liquidacion hecha, y el estado
    derivado la seguiria contando como avanzada.
    """

    def unapprove(self, offer):
        """
        Quitar la aprobacion exige quitar tambien al aprobador.

        No es un descuido: ``clean()`` lo pide expresamente ("If there is an
        approver, the offer must be marked as approved"). Un sello sin su
        persona --o al reves-- es justo la incoherencia que estas reglas
        existen para impedir, y aprobar ya mando la orden de servicio a
        terceros: desaprobar tiene que ser un acto deliberado, no el efecto de
        desmarcar una casilla.
        """
        offer.is_approved = False
        offer.approved_by = None
        offer.save()
        offer.refresh_from_db()

        return offer

    def test_unapproving_while_keeping_the_approver_is_refused(self):
        offer = self.approve(self.make_offer())

        offer.is_approved = False

        with self.assertRaises(ValidationError):
            offer.save()

    def test_unapproving_clears_everything_downstream(self):
        offer = self.walk_to(self.make_offer(), 'profit_created')

        self.unapprove(offer)

        for field in ('service_order_created_at', 'service_order_sent_at',
                      'payment_order_created_at', 'payment_order_sent_at',
                      'asset_in_possession_at', 'asset_sent_at',
                      'profitability_created_at', 'profitability_paid_at'):
            with self.subTest(field=field):
                self.assertIsNone(getattr(offer, field))

    def test_unapproving_clears_the_subpayments_too(self):
        offer = self.walk_to(self.make_offer(), 'profit_created')
        self.pay_all_three(offer)

        self.unapprove(offer)

        self.assertFalse(offer.recovery_repatriation_foundation_paid)
        self.assertFalse(offer.pay_master_service_paid)
        self.assertFalse(offer.propensiones_paid)

    def test_unreviewing_also_removes_the_approval(self):
        """No se puede estar aprobado sin estar revisado."""
        offer = self.approve(self.make_offer())

        offer.reviewed = False
        offer.save()
        offer.refresh_from_db()

        self.assertFalse(offer.is_approved)
        self.assertIsNone(offer.approved_by)

    def test_removing_a_middle_stamp_clears_the_ones_after_it(self):
        """
        Si se pudiera borrar una etapa intermedia dejando las posteriores, la
        orden quedaria con un hueco en medio y el estado derivado seguiria
        leyendo el sello mas avanzado.
        """
        offer = self.walk_to(self.make_offer(), 'asset_sent')

        offer.payment_order_sent_by = None
        offer.payment_order_sent_at = None
        offer.save()
        offer.refresh_from_db()

        self.assertIsNone(offer.asset_in_possession_at)
        self.assertIsNone(offer.asset_sent_at)
        self.assertEqual(offer.status_code, Status.PAY_CREATED)


class TestMarkingIsIdempotent(WorkflowMixin, TestCase):
    """
    Pulsar dos veces el mismo boton no puede reescribir la fecha.

    El sello dice cuando ocurrio la etapa. Si cada clic lo moviera, la traza
    de una orden diria la hora del ultimo clic y no la del hecho.
    """

    def test_the_stamp_does_not_move_on_a_second_call(self):
        offer = self.walk_to(self.make_offer(), 'so_sent')
        first = offer.service_order_sent_at

        offer.mark_service_order_sent(self.staff)
        offer.refresh_from_db()

        self.assertEqual(offer.service_order_sent_at, first)

    def test_the_approval_stamp_survives_an_unrelated_save(self):
        offer = self.approve(self.make_offer())
        first = offer.approved_by_timestamp

        offer.en_observation = 'una nota cualquiera'
        offer.save()
        offer.refresh_from_db()

        self.assertEqual(offer.approved_by_timestamp, first)


class TestApprovalNeedsItsPeople(WorkflowMixin, TestCase):
    """
    ``clean()``: un sello sin persona detras no vale.

    Una orden aprobada es un documento que sale a terceros; tiene que constar
    quien la aprobo.
    """

    def test_approving_without_an_approver_is_rejected(self):
        offer = self.make_offer()
        offer.reviewed = True
        offer.reviewed_by = self.staff
        offer.save()

        offer.is_approved = True
        offer.approved_by = None

        with self.assertRaises(ValidationError):
            offer.save()

    def test_reviewing_without_a_reviewer_is_rejected(self):
        offer = self.make_offer()
        offer.reviewed = True
        offer.reviewed_by = None

        with self.assertRaises(ValidationError):
            offer.save()
