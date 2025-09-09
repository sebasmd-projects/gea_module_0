from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DeleteView, UpdateView

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import AssetModel

from .forms import (AssetLocationModelForm, AssetUpdateLocationModelForm,
                    LocationModelForm)
from .models import AssetLocationModel, LocationModel

"""
# Mixins

Description

- HolderRequiredMixin: Mixin to check if the user has the 'holder' category.
    - dispatch: Check if the user has the 'holder' category.
    - get_queryset: Get the queryset of the model, verify the queryset.
"""


class HolderRequiredMixin(LoginRequiredMixin):
    """
    Mixin to check if the user has the 'HOLDER', 'REPRESENTATIVE' or 'INTERMEDIARY category.
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        allowed_user_types = [
            UserModel.UserTypeChoices.HOLDER,
            UserModel.UserTypeChoices.REPRESENTATIVE,
            UserModel.UserTypeChoices.INTERMEDIARY
        ]

        if (
            not hasattr(request.user, 'user_type') or
            request.user.user_type not in allowed_user_types and
            not request.user.is_superuser and
            not request.user.is_staff
        ):
            return redirect(reverse('core:index'))

        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        model = getattr(self, 'model', None)
        if model is not None and hasattr(model, 'created_by'):
            return model.objects.filter(created_by=self.request.user)
        return super().get_queryset()


"""
# Asset views

Description

- AssetLocationCreateView: Create a new asset location.
- AssetUpdateView: Update an existing asset location.
- AseetLocationDeleteView: Soft Delete an existing asset location.

"""


class AssetLocationMixin(HolderRequiredMixin):
    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        language_code = self.request.LANGUAGE_CODE

        context['assets'] = AssetModel.objects.select_related(
            'asset_name', 'category').all()

        for asset in context['assets']:
            asset.display_name = asset.asset_name.es_name if language_code == 'es' else asset.asset_name.en_name or asset.asset_name.es_name
            asset.display_category = asset.category.es_name if language_code == 'es' else asset.category.en_name or asset.category.es_name

        return context


class AssetLocationCreateView(AssetLocationMixin, CreateView):
    model = AssetLocationModel
    form_class = AssetLocationModelForm
    template_name = 'dashboard/pages/assets_management/asset_location/add_asset_location.html'
    success_url = reverse_lazy('assets:holder_index')

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except IntegrityError:
            # Agregar un error no relacionado a un campo
            form.add_error(None, _("A location with the same details already exists."))
            return self.form_invalid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Pasar el usuario para la validación
        kwargs['user'] = self.request.user
        return kwargs


class AssetUpdateView(AssetLocationMixin, UpdateView):
    model = AssetLocationModel
    form_class = AssetUpdateLocationModelForm
    template_name = 'dashboard/pages/assets_management/asset_location/edit_asset_location.html'
    success_url = reverse_lazy('assets:holder_index')


class AssetLocationDeleteView(HolderRequiredMixin, DeleteView):
    model = AssetLocationModel
    success_url = reverse_lazy('assets:holder_index')

    def form_valid(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save()
        return JsonResponse({'success': True})


"""
# Location views

Description

- LocationCreateView: Create a new location.
- LocationUpdateView: Update an existing location.
- LocationReferenceDeleteView: Delete an existing location.

"""


class LocationCreateView(HolderRequiredMixin, CreateView):
    model = LocationModel
    form_class = LocationModelForm
    template_name = 'dashboard/pages/assets_management/location/add_location.html'
    success_url = reverse_lazy('assets_location:add_asset_location')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        return super().form_valid(form)


class LocationUpdateView(HolderRequiredMixin, UpdateView):
    model = LocationModel
    form_class = LocationModelForm
    template_name = 'dashboard/pages/assets_management/location/edit_location.html'
    success_url = reverse_lazy('assets:holder_index')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs


class LocationReferenceDeleteView(HolderRequiredMixin, DeleteView):
    model = LocationModel
    success_url = reverse_lazy('assets:holder_index')

    def form_valid(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.is_active = False
        self.object.save()
        return JsonResponse({'success': True})
