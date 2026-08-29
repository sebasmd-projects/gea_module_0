from urllib.parse import urlencode, urlparse, urlunparse

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, TemplateView

from apps.project.specific.assets_management.assets_location.models import (
    AssetLocationModel, LocationModel)
from apps.project.specific.assets_management.assets_location.views import \
    HolderRequiredMixin
from apps.project.specific.assets_management.buyers.models import OfferModel
from apps.project.specific.assets_management.buyers.views import \
    BuyerRequiredMixin

from .forms import (AssetAddNewCategoryForm, AssetInlineForm,
                    AssetNameInlineForm)
from .models import AssetCategoryModel, AssetModel, AssetsNamesModel


class HolderTemplateview(HolderRequiredMixin, TemplateView):
    template_name = 'dashboard/pages/holders/holder_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        assets = AssetLocationModel.objects.filter(
            asset__is_active=True,
            is_active=True,
            created_by=self.request.user
        )

        locations = LocationModel.objects.filter(
            is_active=True,
            created_by=self.request.user
        )

        offers = OfferModel.objects.filter(
            is_active=True,
            is_approved=True,
            payment_order_created_at__isnull=True,
        )

        context['assets'] = assets
        context['locations'] = locations
        context['offers'] = offers
        context['total_offers'] = offers.count()

        return context


def _safe_next(request) -> str:
    """
    Devuelve el ``next`` de la peticion solo si apunta a este mismo sitio.

    Sin esta comprobacion cualquiera podria mandar a un usuario autenticado a
    ``/buyer/asset/add/?next=https://otro-sitio/`` y usarnos de trampolin. Se
    aceptan unicamente rutas de este host.
    """
    candidate = request.POST.get('next') or request.GET.get('next') or ''

    if not candidate:
        return ''

    allowed = url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )

    return candidate if allowed else ''


def _with_query(url: str, **params) -> str:
    """Anade parametros a una URL respetando los que ya lleve."""
    parts = urlparse(url)
    query = parts.query

    extra = urlencode({k: v for k, v in params.items() if v})

    if extra:
        query = f'{query}&{extra}' if query else extra

    return urlunparse(parts._replace(query=query))


class AssetNameWithInlineAssetCreateView(BuyerRequiredMixin, View):
    """
    Alta de un activo con su nombre, en una sola pantalla.

    Acepta un ``next``: quien llega desde otro formulario -- el alta de una
    caja AEGIS, por ejemplo -- vuelve alli con el activo recien creado ya
    seleccionado, en vez de tener que buscarlo a mano.
    """

    template_name = "dashboard/pages/buyers/assetname_inline_create.html"

    def get(self, request, *args, **kwargs):
        name_form = AssetNameInlineForm(request=request)
        asset_form = AssetInlineForm()
        assets = (
            AssetModel.objects
            .select_related("asset_name", "category")
            .only(
                "asset_img",
                "es_description", "en_description",
                "es_observations", "en_observations",
                "asset_name__es_name", "asset_name__en_name",
                "category__es_name", "category__en_name",
                "created",
            )
            .order_by("-created")
        )
        context = {
            "name_form": name_form,
            "asset_form": asset_form,
            "assets": assets,
            "next_url": _safe_next(request),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        name_form = AssetNameInlineForm(request.POST, request=request)
        asset_form = AssetInlineForm(request.POST, request.FILES)

        if name_form.is_valid() and asset_form.is_valid():
            with transaction.atomic():
                # 1) Crear el nombre
                assets_name: AssetsNamesModel = name_form.save()

                # 2) Crear el asset enlazado (asset_name es OneToOne)
                asset: AssetModel = asset_form.save(commit=False)
                asset.asset_name = assets_name
                asset.save()
            messages.success(request, _(
                "Asset and Asset Name created successfully."))

            # Si se venia de otro formulario, se vuelve alli con el activo ya
            # elegido; si no, al listado de siempre.
            destination = _safe_next(request)

            if destination:
                return redirect(_with_query(destination, asset=str(asset.pk)))

            return redirect(reverse("buyers:buyer_index"))
        else:
            messages.error(request, _("Please fix the errors below."))

        assets = (
            AssetModel.objects
            .select_related("asset_name", "category")
            .order_by("-created")
        )

        context = {
            "name_form": name_form,
            "asset_form": asset_form,
            "assets": assets,
            "next_url": _safe_next(request),
        }
        return render(request, self.template_name, context)


class AssetAddNewCategory(BuyerRequiredMixin, CreateView):
    """Create a new asset category."""

    model = AssetCategoryModel
    template_name = "dashboard/pages/buyers/asset_category_add.html"
    form_class = AssetAddNewCategoryForm

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        messages.success(
            self.request,
            _("New category created successfully.")
        )
        return response

    def get_success_url(self):
        return reverse("buyers:buyer_index")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = AssetCategoryModel.objects.all()
        return ctx

class WhatsAppRedirectView(View):
    """
    Redirect to WhatsApp with a pre-filled message.
    https://wa.me/573012283818?text=I need help with GEA, my user: request.user.username
    """

    def get(self, request, *args, **kwargs):
        phone_number = "573012283818"
        message = f"{_('I need help with GEA, my user is')}: {request.user.username}"
        whatsapp_url = f"https://wa.me/{phone_number}?text={message}"
        return redirect(whatsapp_url)