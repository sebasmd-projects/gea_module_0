# apps.project.specific.assets_management.buyers.views.py
from django.conf import settings
from django.db.models.functions import TruncMonth
from django.db.models import Count
from dateutil.relativedelta import relativedelta
from datetime import date
from email.mime.image import MIMEImage

import requests
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.html import escape
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override
from django.views.generic import (CreateView, DetailView, TemplateView,
                                  UpdateView, View)

from apps.project.common.users.models import UserModel
from apps.project.specific.assets_management.assets.models import (
    AssetCategoryModel, AssetModel)
from apps.project.specific.assets_management.assets_location.models import AssetLocationModel

from .form import OfferForm, OfferUpdateForm, ServiceOrderRecipientsForm
from .functions import generate_purchase_order_pdf, generate_service_order_pdf
from .models import OfferModel


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


def build_wizard_context(request, offer):
    # Aliases
    so_created = offer.service_order_created_at
    so_sent = offer.service_order_sent_at
    pay_created = offer.payment_order_created_at
    pay_sent = offer.payment_order_sent_at
    possess = offer.asset_in_possession_at
    asset_sent = offer.asset_sent_at
    prof_created = offer.profitability_created_at
    prof_paid = offer.profitability_paid_at

    # Step 1: revisión y aprobación
    if not offer.reviewed:
        current_step = 1
    elif not offer.is_approved:
        current_step = 1

    # Step 2: orden de servicio
    elif not so_created:
        current_step = 2
    elif not so_sent:
        current_step = 2

    # Step 3: orden de pago
    elif not pay_created:
        current_step = 3
    elif not pay_sent:
        current_step = 3

    # Step 4: posesión y envío del activo
    elif not possess:
        current_step = 4
    elif not asset_sent:
        current_step = 4

    # Step 5: rentabilidad
    elif not prof_created:
        current_step = 5
    elif not prof_paid:
        current_step = 5
    elif not offer.recovery_repatriation_foundation_paid:
        current_step = 5
    elif not offer.am_pro_service_paid:
        current_step = 5
    elif not offer.propensiones_paid:
        current_step = 5

    # Completado
    else:
        current_step = 6

    # Idioma
    lang = (request.LANGUAGE_CODE or get_language() or 'en')[:2]

    def get_i18n(obj, base_name, default=""):
        primary = f"{lang}_{base_name}"
        alt = f"{'en' if lang == 'es' else 'es'}_{base_name}"
        return getattr(obj, primary, None) or getattr(obj, alt, None) or default

    asset = offer.asset

    # País comprador
    buyer_country_name = ""
    if offer.buyer_country:
        attr_name = f"{lang}_country_name"
        buyer_country_name = getattr(offer.buyer_country, attr_name, None)
        if not buyer_country_name:
            with override(lang):
                buyer_country_name = str(offer.buyer_country)

    # Categoría
    category_name = ""
    if asset and asset.category:
        attr_name = f"{lang}_name"
        category_name = getattr(asset.category, attr_name, None)
        if not category_name:
            with override(lang):
                category_name = str(asset.category)

    ctx = {
        "offer": offer,
        "so_created": so_created,
        "so_sent": so_sent,
        "pay_created": pay_created,
        "pay_sent": pay_sent,
        "possess": possess,
        "asset_sent": asset_sent,
        "prof_created": prof_created,
        "prof_paid": prof_paid,
        "rrf_paid": offer.recovery_repatriation_foundation_paid,
        "rrf_paid_at": offer.recovery_repatriation_foundation_mark_at,
        "rrf_paid_by": offer.recovery_repatriation_foundation_mark_by,
        "ampro_paid": offer.am_pro_service_paid,
        "ampro_paid_at": offer.am_pro_service_mark_at,
        "ampro_paid_by": offer.am_pro_service_mark_by,
        "propensiones_paid": offer.propensiones_paid,
        "propensiones_paid_at": offer.propensiones_mark_at,
        "propensiones_paid_by": offer.propensiones_mark_by,
        "all_prof_subpaid": offer.profitability_all_paid,
        "current_step": current_step,
        "offer_observation": get_i18n(offer, 'observation', ""),
        "offer_description": get_i18n(offer, 'description', ""),
        "asset_description": get_i18n(asset, 'description', ""),
        "asset_observation": get_i18n(asset, 'observations', ""),
        "buyer_country_name": buyer_country_name,
        "category_name": category_name,
    }

    selected_user_ids = set(
        offer.so_recipients.filter(
            user__isnull=False).values_list('user_id', flat=True)
    )
    selected_types = set(
        offer.so_recipients.filter(
            user_type__isnull=False).values_list('user_type', flat=True)
    )

    users_qs = (UserModel.objects
                .filter(is_active=True, is_verified_holder=True)
                .exclude(id__in=selected_user_ids)
                .order_by("first_name", "last_name"))

    ctx.update({
        "users_queryset": users_qs,
        "user_type_choices": UserModel.UserTypeChoices.choices,
        "selected_types": selected_types,
    })
    return ctx


def _resolve_so_emails(offer):
    # Usuarios seleccionados explícitos
    user_ids = list(
        offer.so_recipients.filter(user__isnull=False)
        .values_list('user_id', flat=True)
    )
    # Tipos seleccionados
    type_codes = list(
        offer.so_recipients.filter(user_type__isnull=False)
             .values_list('user_type', flat=True)
    )

    qs_users = UserModel.objects.filter(is_active=True)
    emails = set()

    if user_ids:
        for email in qs_users.filter(id__in=user_ids).values_list('email', flat=True):
            if email:
                emails.add(email)

    if type_codes:
        for email in qs_users.filter(user_type__in=type_codes).values_list('email', flat=True):
            if email:
                emails.add(email)

    return sorted(set(emails))


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


class PurchaseOrdersView(BuyerRequiredMixin, TemplateView):
    template_name = 'dashboard/pages/buyers/purchase_orders.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        offers = OfferModel.objects.all()

        context['offers'] = offers

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
    template_name = 'dashboard/pages/buyers/create_purchase_orders.html'

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
        hide_recipient_email = [
            "ceo@globalallianceusa.com", "support@globalallianceusa.com"]
        recipient_email = [self.request.user.email]
        review_url = self.request.build_absolute_uri(
            reverse("buyers:offer_details", kwargs={"id": offer_instance.id})
        )

        safe_data = {
            "asset_es": escape(offer_instance.asset.asset_name.es_name or offer_instance.asset.asset_name.en_name or ""),
            "asset_en": escape(offer_instance.asset.asset_name.en_name or offer_instance.asset.asset_name.es_name or ""),
            "offer_type_en": escape(_choice_label(offer_instance, "offer_type", "en")),
            "offer_type_es": escape(_choice_label(offer_instance, "offer_type", "es")),
            "quantity_type_en": escape(_choice_label(offer_instance, "quantity_type", "en")),
            "quantity_type_es": escape(_choice_label(offer_instance, "quantity_type", "es")),
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
            "review_url": review_url,
            "logo_cid": "gea_logo",   # <-- añadido para el template
        }

        html_content = render_to_string(
            "email/purchase_order_email_template.html",
            safe_data
        )

        # Email con soporte para multipart/related
        email = EmailMultiAlternatives(
            subject=subject,
            body="Orden de compra adjunta",
            from_email="no-reply@globalallianceusa.com",
            to=recipient_email,
            bcc=hide_recipient_email,
        )
        email.attach_alternative(html_content, "text/html")

        # Adjuntar PDF
        pdf_bytes = generate_purchase_order_pdf(
            offer_instance, self.request.user
        )
        email.attach(
            f"purchase_order_{offer_instance.id}.pdf",
            pdf_bytes,
            "application/pdf"
        )

        # Adjuntar logo PNG inline
        email.mixed_subtype = "related"
        logo_url = "https://globalallianceusa.com/gea/public/static/assets/imgs/logos/gea_logo.png"
        resp = requests.get(logo_url, timeout=10)
        if resp.status_code == 200:
            mime_img = MIMEImage(resp.content, _subtype="png")
            mime_img.add_header("Content-ID", "<gea_logo>")
            mime_img.add_header("Content-Disposition",
                                "inline", filename="gea_logo.png")
            email.attach(mime_img)
        if not settings.DEBUG:
            email.send(fail_silently=False)


class OfferUpdateView(BuyerRequiredMixin, UpdateView):
    model = OfferModel
    form_class = OfferUpdateForm
    template_name = 'dashboard/pages/buyers/edit_offer.html'
    success_url = reverse_lazy('buyers:buyer_index')


class OfferSoftDeleteView(BuyerRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(OfferModel, pk=kwargs.get('id'))
        offer.display = False
        offer.save()
        return JsonResponse({'success': True, 'id': str(offer.pk)})


class OfferDetailView(LoginRequiredMixin, DetailView):
    model = OfferModel
    template_name = 'dashboard/pages/buyers/detail_offer.html'
    context_object_name = 'offer'

    def get_object(self, queryset=None):
        return get_object_or_404(OfferModel, id=self.kwargs.get('id'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        offer: OfferModel = context['offer']

        # Idioma activo ('es' o 'en')
        lang = (self.request.LANGUAGE_CODE or get_language() or 'en')[:2]

        # Helpers seguros para extraer campos según idioma
        def get_i18n(obj, base_name, default=""):
            """
            Lee obj.<lang>_<base_name> si existe, si no, intenta el alterno.
            """
            primary = f"{lang}_{base_name}"
            alt = f"{'en' if lang == 'es' else 'es'}_{base_name}"
            return getattr(obj, primary, None) or getattr(obj, alt, None) or default

        # Oferta (detalles en el idioma)
        context['offer_observation'] = get_i18n(offer, 'observation', "")
        context['offer_description'] = get_i18n(offer, 'description', "")

        # Activo (descripciones/observaciones en el idioma)
        asset = offer.asset
        context['asset_description'] = get_i18n(asset, 'description', "")
        # Nota: en el modelo del asset el campo es *_observations (plural)
        # ajustamos el base_name para coincidir:
        context['asset_observation'] = get_i18n(asset, 'observations', "")

        # País del comprador (string traducido)
        buyer_country_name = ""
        if offer.buyer_country:
            # prueba atributos tipo es_country_name/en_country_name; si no, usa __str__ bajo override
            attr_name = f"{lang}_country_name"
            buyer_country_name = getattr(offer.buyer_country, attr_name, None)
            if not buyer_country_name:
                with override(lang):
                    buyer_country_name = str(offer.buyer_country)
        context['buyer_country_name'] = buyer_country_name

        # Categoría (nombre traducido si existe es_name/en_name; fallback a __str__)
        category_name = ""
        if asset and asset.category:
            attr_name = f"{lang}_name"
            category_name = getattr(asset.category, attr_name, None)
            if not category_name:
                with override(lang):
                    category_name = str(asset.category)
        context['category_name'] = category_name

        return context


class OfferApprovalWizardPageView(LoginRequiredMixin, TemplateView):
    """
    Página contenedora: carga el shell y, vía JS, inyecta el parcial del wizard.
    """
    template_name = "dashboard/pages/buyers/wizard/offer_wizard_page.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        offer = get_object_or_404(OfferModel, id=self.kwargs.get("id"))
        ctx["offer"] = offer

        # Reutiliza tu helper para obtener los nombres localizados
        wizard_ctx = build_wizard_context(self.request, offer)
        ctx.update({
            "buyer_country_name": wizard_ctx["buyer_country_name"],
            "category_name": wizard_ctx["category_name"],
            "offer_observation": wizard_ctx["offer_observation"],
            "offer_description": wizard_ctx["offer_description"],
            "asset_description": wizard_ctx["asset_description"],
            "asset_observation": wizard_ctx["asset_observation"],
        })
        get_token(self.request)
        return ctx


class OfferApprovalWizardPartialView(LoginRequiredMixin, TemplateView):
    """
    Devuelve SOLO el HTML del wizard (parcial) para ser inyectado por fetch().
    """
    template_name = "dashboard/pages/buyers/wizard/partials/_offer_approval_wizard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        offer = get_object_or_404(OfferModel, id=self.kwargs.get("id"))
        return build_wizard_context(self.request, offer)


class OfferApprovalWizardActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(OfferModel, id=kwargs.get("id"))
        step = (request.POST.get("step") or "").strip().upper()

        # --- recipients: remove ---
        if step == "SO_REMOVE_RECIPIENTS":
            to_remove = request.POST.getlist("remove")
            from django.db.models import Q
            q = Q(pk__isnull=True)
            for token in to_remove:
                try:
                    kind, val = token.split(":", 1)
                except ValueError:
                    continue
                if kind == "user":
                    q |= Q(offer=offer, user_id=val)
                elif kind == "type":
                    q |= Q(offer=offer, user_type=val)
            if q:
                offer.so_recipients.filter(q).delete()

            ctx = build_wizard_context(request, offer)
            html = render_to_string(
                "dashboard/pages/buyers/wizard/partials/_offer_approval_wizard.html",
                ctx, request=request
            )
            return JsonResponse({"ok": True, "html": html})

        # --- recipients: add ---
        if step == "SO_ADD_RECIPIENTS":
            form = ServiceOrderRecipientsForm(request.POST)
            if form.is_valid():
                form.save(offer, request.user)
            else:
                return JsonResponse({"ok": False, "errors": sum(form.errors.values(), [])}, status=400)

            ctx = build_wizard_context(request, offer)
            html = render_to_string(
                "dashboard/pages/buyers/wizard/partials/_offer_approval_wizard.html",
                ctx, request=request
            )
            return JsonResponse({"ok": True, "html": html})

        # --- service order: notify (sends email + pdf) ---
        if step == "SO_NOTIFY":
            self._require_perm(request.user, "can_send_service_order")
            recipients = _resolve_so_emails(offer)
            if not recipients:
                return JsonResponse(
                    {"ok": False, "errors": [_("No recipients to notify.")]},
                    status=400
                )

            review_url = request.build_absolute_uri(
                reverse("buyers:offer_details", kwargs={"id": offer.id})
            )
            safe_data = {
                "po_short": str(offer.id)[:8],
                "asset_es": escape(getattr(offer.asset.asset_name, "es_name", "")),
                "tipo_cantidad_es": escape(offer.get_quantity_type_display()),
                "cantidad": offer.offer_quantity,
                "pais_comprador_es": escape(str(offer.buyer_country or "")),
                "obs_es": escape(offer.es_observation or ""),
                "desc_es": escape(offer.es_description or ""),
                "created_at": offer.service_order_created_at or offer.created,
                "sent_at": offer.service_order_sent_at,
                "review_url": review_url,
                "user_name": escape(request.user.get_full_name()),
                "user_email": escape(request.user.email),
                "logo_cid": "gea_logo",
            }

            subject = _("Service Order Notification for OC: %(po)s") % {
                "po": str(offer.id)}
            html_content = render_to_string(
                "email/service_order_email_template.html", safe_data)

            email = EmailMultiAlternatives(
                subject=subject,
                body="Orden de Servicio adjunta",
                from_email="no-reply@globalallianceusa.com",
                to=[],
                bcc=recipients,
            )
            email.attach_alternative(html_content, "text/html")

            # Adjuntar PDF
            pdf_bytes = generate_service_order_pdf(offer, request.user)
            email.attach(
                f"orden_servicio_{str(offer.id).upper()}.pdf", pdf_bytes, "application/pdf"
            )

            # Adjuntar logo PNG desde la URL
            email.mixed_subtype = "related"  # importante para HTML + inline
            logo_url = "https://globalallianceusa.com/gea/public/static/assets/imgs/logos/gea_logo.png"
            resp = requests.get(logo_url, timeout=10)
            if resp.status_code == 200:
                mime_img = MIMEImage(resp.content, _subtype="png")
                mime_img.add_header("Content-ID", "<gea_logo>")
                mime_img.add_header("Content-Disposition",
                                    "inline", filename="gea_logo.png")
                email.attach(mime_img)

            email.send(fail_silently=False)

            if not offer.service_order_sent_at:
                offer.service_order_sent_at = timezone.now()
                offer.save(update_fields=["service_order_sent_at"])

            ctx = build_wizard_context(request, offer)
            html = render_to_string(
                "dashboard/pages/buyers/wizard/partials/_offer_approval_wizard.html",
                ctx,
                request=request,
            )
            return JsonResponse({"ok": True, "html": html})

        # --- DEFAULT: apply model transition for all other steps (REVIEW, APPROVE, SO_SEND, PAY_CREATE, ...) ---
        try:
            self._apply_step(offer, request.user, step)
        except ValidationError as ve:
            return JsonResponse({"ok": False, "errors": [str(e) for e in ve.error_list]}, status=400)
        except PermissionError as pe:
            return JsonResponse({"ok": False, "errors": [str(pe)]}, status=403)
        except Exception as e:
            return JsonResponse({"ok": False, "errors": [str(e)]}, status=400)

        # Re-render: wizard + timeline
        ctx = build_wizard_context(request, offer)
        wizard_html = render_to_string(
            "dashboard/pages/buyers/wizard/partials/_offer_approval_wizard.html",
            ctx,
            request=request,
        )
        timeline_html = render_to_string(
            "dashboard/pages/buyers/partials/timeline/_timeline_wrapper.html",
            {"offer": offer},
            request=request,
        )
        return JsonResponse({"ok": True, "html": wizard_html, "timeline_html": timeline_html})

    # ---- Helpers de permisos y transición ----

    def _require_perm(self, user, codename: str):
        """
        Acepta superusers/staff, o el permiso/grupo custom que ya definiste en Meta.permissions.
        """
        if user.is_superuser or user.is_staff:
            return
        if not user.has_perm(f"buyers.{codename}"):
            raise PermissionError(
                _("You don't have permission to perform this action.")
            )

    def _apply_step(self, offer: OfferModel, user, step: str):
        """
        Mapea el 'step' pedido desde el front con la transición del modelo.
        """
        step = step.upper()

        if step == "REVIEW":
            self._require_perm(user, "can_review_offer")
            offer.reviewed = True
            offer.reviewed_by = user
            offer.save()

        elif step == "APPROVE":
            self._require_perm(user, "can_approve_offer")
            offer.is_approved = True
            offer.approved_by = user
            offer.save()

        elif step == "SO_SEND":
            self._require_perm(user, "can_send_service_order")
            offer.mark_service_order_sent(user)

        elif step == "PAY_CREATE":
            self._require_perm(user, "can_create_payment_order")
            offer.mark_payment_order_created(user)

        elif step == "PAY_SEND":
            self._require_perm(user, "can_send_payment_order")
            offer.mark_payment_order_sent(user)

        elif step == "POSSESSION":
            self._require_perm(user, "can_set_asset_possession")
            offer.mark_asset_in_possession(user)

        elif step == "ASSET_SEND":
            self._require_perm(user, "can_send_asset")
            offer.mark_asset_sent(user)

        elif step == "PROFIT_CREATE":
            self._require_perm(user, "can_set_profitability")
            offer.mark_profitability_created(user)

        elif step == "RRF_PAY":
            offer.mark_rrf_paid(user)

        elif step == "AMPRO_PAY":
            offer.mark_ampro_paid(user)

        elif step == "PROP_PAY":
            offer.mark_prop_paid(user)

        elif step == "PROFIT_PAY":
            self._require_perm(user, "can_pay_profitability")
            offer.mark_profitability_paid(user)

        else:
            raise ValidationError(_("Unknown step."))


class ProfitabilityTemplateView(BuyerRequiredMixin, TemplateView):
    template_name = 'dashboard/pages/buyers/profitability.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # === Lo que ya tienes ===
        ctx['offers'] = OfferModel.objects.filter(
            profitability_created_at__isnull=False
        ).order_by('-created')

        ctx['in_progress_value'] = OfferModel.objects.exclude(
            recovery_repatriation_foundation_paid=True,
            am_pro_service_paid=True,
            propensiones_paid=True
        ).count()

        ctx['paid_value'] = OfferModel.objects.filter(
            recovery_repatriation_foundation_paid=True,
            am_pro_service_paid=True,
            propensiones_paid=True
        ).count()

        # === NUEVO: barras por mes (últimos 12 meses, incluyendo el mes actual) ===
        tz_now = timezone.now()
        end_month = date(tz_now.year, tz_now.month, 1)
        start_month = (end_month - relativedelta(months=11))

        # Eje de meses normalizado
        months = []
        cursor = start_month
        while cursor <= end_month:
            months.append(cursor)
            cursor = (cursor + relativedelta(months=1))

        # Creadas por mes (por campo created)
        created_qs = (
            OfferModel.objects
            .filter(created__date__gte=start_month, created__date__lt=end_month + relativedelta(months=1))
            .annotate(m=TruncMonth('created'))
            .values('m')
            .annotate(c=Count('id'))
        )
        created_map = {row['m'].date(): row['c'] for row in created_qs}

        # Cerradas por mes (por campo profitability_paid_at)
        closed_qs = (
            OfferModel.objects
            .filter(
                profitability_paid_at__isnull=False,
                profitability_paid_at__date__gte=start_month,
                profitability_paid_at__date__lt=end_month +
                relativedelta(months=1),
            )
            .annotate(m=TruncMonth('profitability_paid_at'))
            .values('m')
            .annotate(c=Count('id'))
        )
        closed_map = {row['m'].date(): row['c'] for row in closed_qs}

        labels = [m.strftime('%b %Y') for m in months]
        created_counts = [created_map.get(m, 0) for m in months]
        closed_counts = [closed_map.get(m, 0) for m in months]

        ctx['po_month_labels'] = labels
        ctx['po_created_counts'] = created_counts
        ctx['po_closed_counts'] = closed_counts

        # === Tabla de Activos con totales y tokens de filtro ===
        lang = get_language()
        assets_qs = (
            AssetModel.objects
            .select_related('asset_name', 'category')
            .order_by('asset_name__es_name', 'asset_name__en_name')
        )

        asset_rows = []
        for a in assets_qs:
            # Localización de nombres
            if lang == 'es':
                asset_name = a.asset_name.es_name or a.asset_name.en_name or ''
                category_name = (getattr(a.category, 'es_name', None)
                                 or getattr(a.category, 'en_name', '') or '')
                observations = (getattr(a, 'es_observations', None)
                                or getattr(a, 'en_observations', '') or '')
                description = (getattr(a, 'es_description', None)
                               or getattr(a, 'en_description', '') or '')
            else:
                asset_name = a.asset_name.en_name or a.asset_name.es_name or ''
                category_name = (getattr(a.category, 'en_name', None)
                                 or getattr(a.category, 'es_name', '') or '')
                observations = (getattr(a, 'en_observations', None)
                                or getattr(a, 'es_observations', '') or '')
                description = (getattr(a, 'en_description', None)
                               or getattr(a, 'es_description', '') or '')

            # Totales por tipo (intenta con claves comunes: 'B'/'U' o 'boxes'/'units')
            qty_by_type = a.asset_total_quantity_by_type() or {}

            def pick(qmap, *keys, default=0):
                for k in keys:
                    if k in qmap and qmap[k] is not None:
                        return qmap[k]
                return default

            total_boxes = pick(qty_by_type, "Boxes", "Box",
                               "Cajas", "B", default=0)
            total_units = pick(qty_by_type, "Units", "Unit",
                               "Unidades", "U", default=0)

            if (int(total_boxes) if total_boxes else 0) == 0 and (int(total_units) if total_units else 0) == 0:
                continue

            # Tokens para filtros
            zero_yes = (int(total_boxes) + int(total_units) == 0)
            has_image = bool(getattr(a, 'asset_img', None))

            qty_tokens = []

            qty_tokens.append(
                'zero:yes') if zero_yes else qty_tokens.append('zero:no')

            if int(total_units) > 0:
                qty_tokens.append('qty:U')
            if int(total_boxes) > 0:
                qty_tokens.append('qty:B')

            # Si no hay stock en ningún tipo, deja sin qty:* (los filtros funcionarán por zero:yes)

            tokens = [
                f"img:{'yes' if has_image else 'no'}",
                *qty_tokens
            ]

            asset_rows.append({
                'name': asset_name,
                'category': category_name,
                'total_boxes': total_boxes,
                'total_units': total_units,
                'observations': observations,
                'description': description,
                'tokens': tokens,
            })

        ctx['asset_rows'] = asset_rows
        # Opciones del filtro de tipo (código y etiqueta traducible desde Choices)
        ctx['qty_choices'] = AssetLocationModel.QuantityTypeChoices.choices

        return ctx
