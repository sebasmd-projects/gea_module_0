# apps/project/specific/assets_management/buyers/access.py
"""
Quien puede hacer que sobre una orden de compra.

La app autorizaba por **rol** (``BuyerRequiredMixin``) y, dentro del wizard, por
**permiso de etapa** (``_require_perm``). Las dos capas funcionan, pero ninguna
mira el objeto ni la etapa en la que ese objeto esta, y de ahi salian cuatro
agujeros comprobados:

* el detalle de cualquier orden lo abria cualquier usuario autenticado -- un
  tenedor o un intermediario incluidos -- con solo tener el UUID;
* cualquier comprador podia borrar (``display=False``) una orden ajena, incluida
  una ya aprobada y con la orden de pago enviada;
* cualquier comprador podia cambiar la cantidad de una orden ya aprobada, con lo
  que la base de datos decia una cosa y los PDF ya enviados por correo otra;
* ``SO_NOTIFY`` mandaba la orden de servicio y validaba el estado despues.

Las reglas viven aqui, y no repartidas por cada vista, porque el criterio de
acceso solo se puede auditar si se lee de una vez.

Dos ideas, y nada mas:

**Quien.** Las ordenes de compra son trabajo del equipo de compradores, no de un
cliente final: ``PurchaseOrdersView`` lista *todas* las ordenes a cualquier
comprador, asi que aqui no se restringe por propietario -- eso rompería el
trabajo diario. Lo que si se corta es el acceso de los roles que no pintan nada
en este flujo.

**Cuando.** Aprobar una orden le crea la orden de servicio automaticamente
(``OfferModel.save``, bloque B), o sea que la aprobacion es justo el punto en el
que la orden deja de ser un borrador y pasa a ser un documento vivo, con PDF
enviados por correo a terceros. A partir de ahi solo el personal interno la
toca, y por el wizard, que es quien deja rastro de cada etapa.
"""

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from apps.project.common.users.models import UserModel

from .models import OfferModel


def is_internal(user) -> bool:
    """Personal de la casa: se le deja pasar donde el equipo de compras no."""
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def is_buyer_team(user) -> bool:
    """Quien trabaja el flujo de ordenes de compra."""
    if not (user and user.is_authenticated and user.is_active):
        return False

    if is_internal(user):
        return True

    return getattr(user, 'user_type', None) == UserModel.UserTypeChoices.BUYER


def offer_lock_reason(offer: OfferModel):
    """
    Por que esta orden ya no se puede editar ni borrar.

    Returns:
        str | None: el motivo, o ``None`` si todavia es un borrador.
    """
    if offer.is_approved:
        return _(
            'This purchase order is already approved and its service order '
            'has been issued. Changing or deleting it now would contradict '
            'the documents already sent. Use the approval workflow instead.'
        )

    return None


def can_view_offer(user, offer: OfferModel) -> bool:
    """El detalle de una orden es del equipo de compras, de nadie mas."""
    return is_buyer_team(user)


def can_modify_offer(user, offer: OfferModel):
    """
    Decide si este usuario puede escribir sobre esta orden.

    Returns:
        tuple[bool, str | None]: permitido, y el motivo cuando no lo esta.
    """
    if not is_buyer_team(user):
        return False, _("You don't have permission to perform this action.")

    # El personal interno puede corregir una orden en curso; para eso esta.
    if is_internal(user):
        return True, None

    reason = offer_lock_reason(offer)

    if reason:
        return False, reason

    return True, None


class OfferMutationMixin:
    """
    Cierra la escritura sobre ordenes que ya son documentos vivos.

    Se pone *despues* del mixin de rol, para que este siga decidiendo quien
    entra y aqui solo se decida sobre que puede escribir.

    Attributes:
        offer_url_kwarg: nombre del parametro de la URL con el UUID.
        mutation_denied_json: responder JSON en vez de redirigir (vistas AJAX).
    """

    offer_url_kwarg = 'pk'
    mutation_denied_json = False

    def get_offer(self) -> OfferModel:
        return get_object_or_404(
            OfferModel, pk=self.kwargs.get(self.offer_url_kwarg)
        )

    def dispatch(self, request, *args, **kwargs):
        # Las lecturas ya las filtra el mixin de rol; aqui solo la escritura.
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return super().dispatch(request, *args, **kwargs)

        offer = self.get_offer()
        allowed, reason = can_modify_offer(request.user, offer)

        if allowed:
            return super().dispatch(request, *args, **kwargs)

        if self.mutation_denied_json:
            return JsonResponse(
                {'success': False, 'ok': False, 'errors': [str(reason)]},
                status=403
            )

        from django.contrib import messages

        messages.error(request, reason)

        return redirect(reverse('buyers:offer_details', kwargs={'id': offer.pk}))
