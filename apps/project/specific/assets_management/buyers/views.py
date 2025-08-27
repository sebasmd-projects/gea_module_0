from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.html import escape
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, View, UpdateView

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import AssetModel

from .form import OfferForm, OfferUpdateForm
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


class BuyerCreateView(BuyerRequiredMixin, CreateView):
    model = OfferModel
    template_name = 'dashboard/pages/assets_management/assets/buyers/buyer_dashboard.html'
    context_object_name = 'offers'
    form_class = OfferForm

    def form_valid(self, form):
        form.instance.created_by = self.request.user

        self.send_email_notification(form.cleaned_data)

        messages.success(
            self.request, _("Your offer has been sent for verification.")
        )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        user_language = self.request.LANGUAGE_CODE

        description_field = 'es_description' if user_language == 'es' else 'en_description'
        context['description_field'] = description_field
        context['description_field_instance'] = context['form'][description_field]

        observation_field = 'es_observation' if user_language == 'es' else 'en_observation'
        context['observation_field'] = observation_field
        context['observation_field_instance'] = context['form'][observation_field]

        context['offers'] = OfferModel.objects.filter(
            created_by=self.request.user
        )
        
        assets_qs = (
            AssetModel.objects
            .filter(is_active=True)
            .select_related('asset_name', 'category')
            .order_by('asset_name__es_name')
        )
        context['assets'] = assets_qs

        return context

    def get_success_url(self):
        return self.request.path

    def send_email_notification(self, cleaned_data):
        """Enviar correo con los datos de la oferta."""
        subject = _("New Offer Submitted for Verification")
        recipient_email = "notificaciones@propensionesabogados.com"

        # Escapar datos para evitar inyecciones de scripts
        safe_data = {key: escape(value) for key, value in cleaned_data.items()}

        # Generar el cuerpo del correo con HTML
        html_content = f"""
        <html>
        <body>
            <h2>New Offer Submitted</h2>
            <p><strong>Asset:</strong> {safe_data.get('asset')}</p>
            <p><strong>Offer Type:</strong> {safe_data.get('offer_type')}</p>
            <p><strong>Quantity Type:</strong> {safe_data.get('quantity_type')}</p>
            <p><strong>Offer Amount:</strong> ${safe_data.get('offer_amount')}</p>
            <p><strong>Offer Quantity:</strong> {safe_data.get('offer_quantity')}</p>
            <p><strong>Country of Purchase:</strong> {safe_data.get('buyer_country')}</p>
            <p><strong>Observations (EN):</strong> {safe_data.get('en_observation')}</p>
            <p><strong>Observations (ES):</strong> {safe_data.get('es_observation')}</p>
            <p><strong>Description (EN):</strong> {safe_data.get('en_description')}</p>
            <p><strong>Description (ES):</strong> {safe_data.get('es_description')}</p>
            <br>
            <p>Sent by:</p>
            <p><strong>Name:</strong> {self.request.user.get_full_name()}</p>
            <p><strong>Email:</strong> {self.request.user.email}</p>
            <p><strong>Username:</strong> {self.request.user.username}</p>
        </body>
        </html>
        """

        # Crear y enviar el correo
        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email="no-reply@propensionesabogados.com",
            to=[recipient_email],
        )
        email.content_subtype = "html"  # Indicar que el contenido es HTML
        email.send()


class OfferUpdateView(BuyerRequiredMixin, UpdateView):
    model = OfferModel
    form_class = OfferUpdateForm
    template_name = 'dashboard/pages/assets_management/assets/buyers/edit_offer.html'
    success_url = reverse_lazy('buyers:buyer_index')

class OfferSoftDeleteView(BuyerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(OfferModel, pk=kwargs.get('pk'))
        offer.is_active = False
        offer.save()
        return JsonResponse({'success': True})


class OfferDetailView(DetailView):
    model = OfferModel
    template_name = 'dashboard/pages/assets_management/assets/buyers/detail_offer.html'
    context_object_name = 'offer'

    def get_object(self, queryset=None):
        """Fetch the OfferModel instance by the ID provided in the URL."""
        return get_object_or_404(OfferModel, id=self.kwargs.get('id'))

    def get_context_data(self, **kwargs):
        """Add custom context data to be used in the template."""
        context = super().get_context_data(**kwargs)
        offer = context['offer']

        # Obtener el idioma actual del usuario
        current_language = get_language()

        # Obtener el banner y el texto (procedimiento) de acuerdo con el idioma
        banner = offer.es_banner.url if current_language == 'es' and offer.es_banner else offer.en_banner.url if offer.en_banner else None
        procedure = offer.es_procedure if current_language == 'es' else offer.en_procedure

        # Si no hay banner, mostramos el procedimiento como texto
        context['banner'] = banner
        context['procedure'] = procedure

        return context
