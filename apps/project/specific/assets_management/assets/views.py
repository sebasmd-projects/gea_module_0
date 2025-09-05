from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import TemplateView, CreateView

from apps.project.specific.assets_management.assets_location.models import (
    AssetLocationModel, LocationModel)
from apps.project.specific.assets_management.assets_location.views import \
    HolderRequiredMixin
from apps.project.specific.assets_management.buyers.models import OfferModel
from apps.project.specific.assets_management.buyers.views import BuyerRequiredMixin

from .forms import AssetAddNewCategoryForm, AssetInlineForm, AssetNameInlineForm
from .models import AssetModel, AssetsNamesModel, AssetCategoryModel


class HolderTemplateview(HolderRequiredMixin, TemplateView):
    template_name = 'dashboard/pages/assets_management/assets/holders/holder_dashboard.html'

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
        )

        context['assets'] = assets
        context['locations'] = locations
        context['offers'] = offers
        context['total_offers'] = offers.count()

        return context


class AssetNameWithInlineAssetCreateView(BuyerRequiredMixin, View):
    """
    Crea un AssetsNamesModel dependiendo del idioma y, en el mismo submit,
    registra su AssetModel (1–1) con categoría (Select2) + datos.
    """

    template_name = "dashboard/pages/assets_management/assets/assetname_inline_create.html"

    def get(self, request, *args, **kwargs):
        name_form = AssetNameInlineForm(request=request)
        asset_form = AssetInlineForm()
        context = {
            "name_form": name_form,
            "asset_form": asset_form,
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
            return redirect(reverse("buyers:buyer_index"))
        else:
            messages.error(request, _("Please fix the errors below."))

        context = {
            "name_form": name_form,
            "asset_form": asset_form,
        }
        return render(request, self.template_name, context)


class AssetAddNewCategory(BuyerRequiredMixin, CreateView):
    """Create a new asset category."""

    model = AssetCategoryModel
    template_name = "dashboard/pages/assets_management/assets/asset_category_add.html"
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
