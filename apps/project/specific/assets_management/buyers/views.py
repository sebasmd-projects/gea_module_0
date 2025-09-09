from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from django.views.generic import (CreateView, DetailView, TemplateView,
                                  UpdateView, View)

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import (
    AssetCategoryModel, AssetModel)

from .form import OfferForm, OfferUpdateForm
from .functions import generate_purchase_order_pdf
from .models import OfferModel


class BuyerRequiredMixin(LoginRequiredMixin):
    """Mixin to check if the user has the 'buyer' category.

    Args:
        LoginRequiredMixin (_type_): _description_

    Returns:
        _type_: _description_
    """

    def dispatch(self, request, *args, **kwargs):
        """
        Mixin to check if the user has the 'buyer' category.
        """
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        allowed_user_types = [
            UserModel.UserTypeChoices.BUYER,
        ]

        if (
            not hasattr(request.user, 'user_type') or
            request.user.user_type not in allowed_user_types and
            not request.user.is_superuser and
            not request.user.is_staff
        ):
            return redirect(reverse('core:index'))

        return super().dispatch(request, *args, **kwargs)


def _choice_label(instance, field_name: str, lang: str) -> str:
    """
    Devuelve el display label de un campo de choices en el idioma indicado.
    """
    with override(lang):
        return getattr(instance, f"get_{field_name}_display")()


def _localized_str(value, lang: str) -> str:
    """
    Convierte a str un valor potencialmente traducible (e.g. país) en un idioma dado.
    """
    with override(lang):
        return str(value) if value is not None else ""


class PurchaseOrdersView(BuyerRequiredMixin, TemplateView):
    template_name = 'dashboard/pages/assets_management/assets/buyers/purchase_orders.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['offers'] = OfferModel.objects.filter(
            created_by=self.request.user)

        context['categories'] = AssetCategoryModel.objects.all().order_by('es_name')

        assets_qs = (
            AssetModel.objects
            .filter(
                is_active=True
            ).select_related(
                'asset_name', 'category'
            ).order_by(
                'asset_name__es_name'
            )
        )
        context['assets'] = assets_qs

        return context


class PurchaseOrderCreateView(BuyerRequiredMixin, CreateView):
    model = OfferModel
    form_class = OfferForm
    template_name = 'dashboard/pages/assets_management/assets/buyers/create_purchase_orders.html'

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        self.object = form.save()
        self.send_email_notification(form.cleaned_data, self.object)
        messages.success(self.request, _(
            "Your Purchase order has been sent for verification."
        ))
        return super().form_valid(form)

    def get_success_url(self):
        # Al crear, regresa al dashboard/listado
        return reverse('buyers:buyer_index')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user_language = self.request.LANGUAGE_CODE

        description_field = 'es_description' if user_language == 'es' else 'en_description'
        context['description_field'] = description_field
        context['description_field_instance'] = context['form'][description_field]

        observation_field = 'es_observation' if user_language == 'es' else 'en_observation'
        context['observation_field'] = observation_field
        context['observation_field_instance'] = context['form'][observation_field]

        return context

    def send_email_notification(self, cleaned_data, offer_instance):
        """Enviar correo con los datos de la orden de compra."""
        subject = _("New Purchase order Submitted for Verification")
        hide_recipient_email = ["ceo@globalallianceusa.com"]
        recipient_email = [self.request.user.email]

        safe_data = {
            "asset_es": escape(offer_instance.asset.asset_name.es_name or offer_instance.asset.asset_name.en_name or ""),
            "asset_en": escape(offer_instance.asset.asset_name.en_name or offer_instance.asset.asset_name.es_name or ""),
            "offer_type_en": escape(_choice_label(offer_instance, "offer_type", "en")),
            "offer_type_es": escape(_choice_label(offer_instance, "offer_type", "es")),
            "quantity_type_en": escape(_choice_label(offer_instance, "quantity_type", "en")),
            "quantity_type_es": escape(_choice_label(offer_instance, "quantity_type", "es")),
            "offer_amount": offer_instance.offer_amount,
            "offer_quantity": offer_instance.offer_quantity,
            "buyer_country_en": escape(_localized_str(offer_instance.buyer_country, "en")),
            "buyer_country_es": escape(_localized_str(offer_instance.buyer_country, "es")),
            "en_observation": escape(offer_instance.en_observation or ""),
            "es_observation": escape(offer_instance.es_observation or ""),
            "en_description": escape(offer_instance.en_description or ""),
            "es_description": escape(offer_instance.es_description or ""),
            "user_name": escape(self.request.user.get_full_name()),
            "user_email": escape(self.request.user.email),
            "user_username": escape(self.request.user.username),
        }

        html_content = render_to_string(
            "core/email/purchase_order_email_template.html",
            safe_data
        )

        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email="no-reply@globalallianceusa.com",
            to=recipient_email,
            bcc=hide_recipient_email
        )
        email.content_subtype = "html"
        pdf_bytes = generate_purchase_order_pdf(
            offer_instance, self.request.user)
        email.attach(
            f"purchase_order_{offer_instance.id}.pdf",
            pdf_bytes,
            "application/pdf"
        )
        email.send()


class OfferUpdateView(BuyerRequiredMixin, UpdateView):
    model = OfferModel
    form_class = OfferUpdateForm
    template_name = 'dashboard/pages/assets_management/assets/buyers/edit_offer.html'
    success_url = reverse_lazy('buyers:buyer_index')


class OfferSoftDeleteView(BuyerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(OfferModel, pk=kwargs.get('id'))
        offer.display = False
        offer.save()
        return JsonResponse({'success': True, 'id': str(offer.pk)})


class OfferDetailView(LoginRequiredMixin, DetailView):
    model = OfferModel
    template_name = 'dashboard/pages/assets_management/assets/buyers/detail_offer.html'
    context_object_name = 'offer'

    def get_object(self, queryset=None):
        """Fetch the OfferModel instance by the ID provided in the URL."""
        return get_object_or_404(OfferModel, id=self.kwargs.get('id'))
