# apps/project/common/account/views.py

from collections import OrderedDict

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sites.shortcuts import get_current_site
from django.core.mail import send_mail
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.edit import FormView
from django.core.cache import cache
from django.contrib import messages
from django.utils.crypto import get_random_string

from formtools.wizard.views import SessionWizardView

from apps.common.utils.models import GeaDailyUniqueCode
from apps.project.common.users.models import UserModel


from .forms import (
    SupplierContactForm,
    BuyerContactForm,
    ForgotPasswordStep1Form,
    ForgotPasswordStep2Form,
    ChangePasswordForm,
    UserInformationForm,
    SecurityInformationForm,
    UniqueCodeForm
)

STEP_USER = "user"
STEP_SECURITY = "security"
STEP_CONTACT = "contact"
STEP_CODE = "code"


class GeaUserRegisterWizardView(SessionWizardView):
    """
    Wizard de registro con ramificación por tipo:
    - Compra (BUYER): email restringido + envío de código por email
    - Otros: email libre + código diario entregado por asesor
    """
    template_name = "account/gea_register.html"

    # IMPORTANTE: no vacío (formtools lo evalúa en import-time)
    form_list = [
        (STEP_USER, UserInformationForm),
        (STEP_SECURITY, SecurityInformationForm),
        (STEP_CONTACT, SupplierContactForm),  # default
        (STEP_CODE, UniqueCodeForm),
    ]

    # --- Buyer email code settings ---
    BUYER_CODE_TTL_SECONDS = 10 * 60          # 10 min
    BUYER_SEND_RATE_TTL_SECONDS = 5 * 60      # 5 min window
    BUYER_MAX_SENDS_IN_WINDOW = 3

    # -------------------------
    # Lifecycle
    # -------------------------
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("core:index")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, form, **kwargs):
        ctx = super().get_context_data(form=form, **kwargs)
        ctx["title"] = _("Register")
        ctx["step_key"] = self.steps.current
        ctx["step_index"] = self.steps.step1
        # no llames get_form_list() custom (no existe) ni uses cleaned aquí
        ctx["step_count"] = len(super().get_form_list())
        return ctx

    # -------------------------
    # Step routing (NO recursion)
    # -------------------------
    def _get_user_type_from_storage(self):
        """
        Lee user_type del step USER sin usar get_cleaned_data_for_step()
        para evitar recursión con get_form_list().
        """
        step_data = self.storage.get_step_data(STEP_USER) or {}
        key = f"{STEP_USER}-user_type"  # típico: 'user-user_type'

        if hasattr(step_data, "get"):
            v = step_data.get(key)
            # QueryDict puede devolver lista si múltiples; normalizamos
            if isinstance(v, (list, tuple)):
                v = v[0] if v else None
            return v
        return None

    def _set_contact_form(self, cls):
        fl = OrderedDict(super().get_form_list())
        fl[STEP_CONTACT] = cls
        self.form_list = fl

    def get_form(self, step=None, data=None, files=None):
        """
        Cambia el form del step 'contact' según el user_type del step 'user'
        usando storage raw (no cleaned) para evitar recursión.
        """
        step = step or self.steps.current

        if step == STEP_CONTACT:
            user_type = self._get_user_type_from_storage()
            if user_type == UserModel.UserTypeChoices.BUYER:
                self._set_contact_form(BuyerContactForm)
            else:
                self._set_contact_form(SupplierContactForm)

        return super().get_form(step=step, data=data, files=files)

    # -------------------------
    # Buyer code generation/sending
    # -------------------------
    def _buyer_cache_key(self, email: str) -> str:
        return f"gea:buyer_reg_code:{email}"

    def _buyer_rate_key(self, ip: str, email: str) -> str:
        return f"gea:buyer_reg_rate:{ip}:{email}"

    def _send_buyer_code(self, *, email: str) -> None:
        """
        Envía un código único al email (Compra), con rate-limiting.
        Usa cache como storage de verificación (TTL).
        """
        email = (email or "").strip().lower()
        if not email:
            raise ValueError(_("Invalid email."))

        ip = self.request.META.get("REMOTE_ADDR", "0.0.0.0")
        rate_key = self._buyer_rate_key(ip, email)
        bucket = cache.get(rate_key) or {"count": 0}

        if bucket["count"] >= self.BUYER_MAX_SENDS_IN_WINDOW:
            raise ValueError(
                _("Too many code requests. Please try again later."))

        code = get_random_string(
            length=10,
            allowed_chars="ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        )
        cache.set(self._buyer_cache_key(email), code,
                  timeout=self.BUYER_CODE_TTL_SECONDS)

        bucket["count"] += 1
        cache.set(rate_key, bucket, timeout=self.BUYER_SEND_RATE_TTL_SECONDS)

        subject = _("Your GEA registration code")
        message = _(
            "Your registration code is:\n\n"
            "%(code)s\n\n"
            "This code expires in %(minutes)s minutes."
        ) % {"code": code, "minutes": int(self.BUYER_CODE_TTL_SECONDS / 60)}

        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=[email],
            fail_silently=False,
        )

    def process_step(self, form):
        """
        Cuando se completa CONTACT y el user_type es BUYER, envía el código al email.
        """
        res = super().process_step(form)

        # current == step que se acaba de procesar
        if self.steps.current == STEP_CONTACT:
            user_type = self._get_user_type_from_storage()

            if user_type == UserModel.UserTypeChoices.BUYER:
                email = (form.cleaned_data.get("email") or "").strip().lower()
                try:
                    self._send_buyer_code(email=email)
                    messages.success(self.request, _(
                        "We sent a verification code to your email."))
                except ValueError as e:
                    messages.error(self.request, str(e))

        return res

    # -------------------------
    # Final validation + user creation
    # -------------------------
    def _validate_unique_code(self, *, user_type: str, email: str, code: str) -> bool:
        candidate = (code or "").strip()
        if not candidate:
            return False

        if user_type == UserModel.UserTypeChoices.BUYER:
            expected = cache.get(self._buyer_cache_key(
                (email or "").strip().lower()))
            return bool(expected and expected == candidate)

        # Proveedores: código del día (GENERAL)
        return GeaDailyUniqueCode.objects.verify_code(
            candidate,
            kind=GeaDailyUniqueCode.KindChoices.GENERAL
        )

    def done(self, form_list, **kwargs):
        step_data = {
            STEP_USER: self.get_cleaned_data_for_step(STEP_USER) or {},
            STEP_SECURITY: self.get_cleaned_data_for_step(STEP_SECURITY) or {},
            STEP_CONTACT: self.get_cleaned_data_for_step(STEP_CONTACT) or {},
            STEP_CODE: self.get_cleaned_data_for_step(STEP_CODE) or {},
        }

        user_type = step_data[STEP_USER].get("user_type")
        email = (step_data[STEP_CONTACT].get("email") or "").strip().lower()
        unique_code = step_data[STEP_CODE].get("unique_code")

        if not self._validate_unique_code(user_type=user_type, email=email, code=unique_code):
            form = self.get_form(
                step=STEP_CODE, data=self.storage.get_step_data(STEP_CODE))
            form.add_error("unique_code", _("Invalid or expired code."))
            return self.render(form)

        referred = step_data[STEP_USER].get("referred", "")

        if user_type == UserModel.UserTypeChoices.BUYER:
            referred = None

        try:
            user = UserModel.objects.create_user(
                username=step_data[STEP_USER]["username"],
                email=email,
                first_name=step_data[STEP_USER]["first_name"],
                last_name=step_data[STEP_USER]["last_name"],
                password=step_data[STEP_SECURITY]["password"],
                user_type=user_type,
                phone_number_code=step_data[STEP_CONTACT]["phone_number_code"],
                phone_number=step_data[STEP_CONTACT]["phone_number"],
                referred=referred,
            )
        except IntegrityError as e:
            if "email_hash" in str(e):
                form = self.get_form(
                    step=STEP_CONTACT, data=self.storage.get_step_data(STEP_CONTACT))
                form.add_error("email", _(
                    "A user with this email already exists."))
                return self.render(form)
            raise

        auth_user = authenticate(
            self.request,
            username=step_data[STEP_USER]["username"],
            password=step_data[STEP_SECURITY]["password"],
        )
        if auth_user is not None:
            login(self.request, auth_user)

        # invalidar código buyer para que no se reuse
        if user_type == UserModel.UserTypeChoices.BUYER:
            cache.delete(self._buyer_cache_key(email))

        # Redirects
        next_url = self.request.GET.get("next")
        if next_url:
            return redirect(next_url)

        if getattr(user, "is_asset_holder", False):
            return redirect("assets:holder_index")

        if getattr(user, "is_buyer", False):
            return redirect("buyers:buyer_index")

        return redirect("core:index")


class ForgotPasswordFormView(View):
    """Two-step forgot password process in one URL"""
    template_name = "account/forgot_password.html"
    token_generator = default_token_generator

    def get(self, request, *args, **kwargs):
        """Handle both steps based on URL parameters"""
        uidb64 = request.GET.get('uidb64')
        token = request.GET.get('token')

        # Step 2: If token and uid provided, show password reset form
        if uidb64 and token:
            return self._handle_step2_get(request, uidb64, token)

        # Step 1: Show email/username form
        return self._handle_step1_get(request)

    def post(self, request, *args, **kwargs):
        """Handle form submissions for both steps"""
        uidb64 = request.GET.get('uidb64')
        token = request.GET.get('token')

        # Step 2: Password reset form submission
        if uidb64 and token:
            return self._handle_step2_post(request, uidb64, token)

        # Step 1: Email/username form submission
        return self._handle_step1_post(request)

    def _handle_step1_get(self, request):
        """Display step 1 form"""
        form = ForgotPasswordStep1Form()
        return render(request, self.template_name, {
            'form': form,
            'step': 1,
            'title': _('Reset Your Password'),
        })

    def _handle_step1_post(self, request):
        form = ForgotPasswordStep1Form(request.POST)
        if form.is_valid():
            user = form.get_user()
            if user:
                self._send_password_reset_email(request, user)

            messages.success(request, _(
                "If an account exists with the provided email/username, "
                "you will receive password reset instructions shortly."
            ))

            return render(request, self.template_name, {
                'step': 'success',
                'title': _('Check Your Email'),
                'message': _(
                    "We've sent password reset instructions to your email. "
                    "Please check your inbox and follow the link to reset your password."
                ),
            })

        # solo caerá aquí si el campo viene vacío u otro error real
        return render(request, self.template_name, {
            'form': form,
            'step': 1,
            'title': _('Reset Your Password'),
        })

    def _handle_step2_get(self, request, uidb64, token):
        """Display step 2 form if token is valid"""
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = UserModel.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            user = None

        if user is not None and self.token_generator.check_token(user, token):
            form = ForgotPasswordStep2Form(user)
            return render(request, self.template_name, {
                'form': form,
                'step': 2,
                'uidb64': uidb64,
                'token': token,
                'title': _('Set New Password'),
            })
        else:
            # Invalid token
            messages.error(request, _(
                "The password reset link is invalid or has expired. "
                "Please request a new password reset."
            ))
            return redirect('account:forgot_password')

    def _handle_step2_post(self, request, uidb64, token):
        """Process step 2 form"""
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = UserModel.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            user = None

        if user is None or not self.token_generator.check_token(user, token):
            messages.error(request, _(
                "The password reset link is invalid or has expired. "
                "Please request a new password reset."
            ))
            return redirect('account:forgot_password')

        form = ForgotPasswordStep2Form(user, request.POST)
        if form.is_valid():
            form.save()

            # Update session if the user who changed password is logged in
            if request.user.is_authenticated and request.user.pk == user.pk:
                update_session_auth_hash(request, user)

            messages.success(request, _(
                "Your password has been reset successfully. "
                "You can now log in with your new password."
            ))

            # Redirect to login page
            return redirect('two_factor:login')

        # Form invalid, show errors
        return render(request, self.template_name, {
            'form': form,
            'step': 2,
            'uidb64': uidb64,
            'token': token,
            'title': _('Set New Password'),
        })

    def _send_password_reset_email(self, request, user):
        """Send password reset email to user"""
        current_site = get_current_site(request)
        site_name = current_site.name
        domain = current_site.domain

        # Use HTTPS if request is secure
        protocol = 'https' if request.is_secure() else 'http'

        # Generate token and uid
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = self.token_generator.make_token(user)

        # Build reset URL
        reset_url = reverse('account:forgot_password') + \
            f'?uidb64={uid}&token={token}'
        reset_url = f"{protocol}://{domain}{reset_url}"

        # Email context
        context = {
            'email': user.email,
            'domain': domain,
            'site_name': site_name,
            'uid': uid,
            'user': user,
            'token': token,
            'protocol': protocol,
            'reset_url': reset_url,
        }

        # Render email content
        subject = _("Password Reset Request for %(site)s") % {
            "site": site_name}
        subject = "".join(subject.splitlines())

        # Remove newlines from subject
        subject = ''.join(subject.splitlines())

        message = render_to_string(
            'account/password_reset_email.html', context)

        # Send email
        send_mail(
            subject=subject,
            message=message,
            from_email=None,  # Use DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
            html_message=message,
            fail_silently=False,
        )


class ChangePasswordFormView(FormView):
    """Change password view for logged-in users"""
    template_name = "account/change_password.html"
    form_class = ChangePasswordForm

    def dispatch(self, request, *args, **kwargs):
        # Ensure user is logged in
        if not request.user.is_authenticated:
            messages.error(request, _(
                "You must be logged in to change your password."))
            return redirect('two_factor:login')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """Pass the current user to the form"""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        # Save the new password
        user = form.save()

        # Update session to prevent logout
        update_session_auth_hash(self.request, user)

        messages.success(self.request, _(
            "Your password has been changed successfully!"))

        # Redirect based on user type
        if getattr(user, "is_asset_holder", False):
            return redirect('assets:holder_index')

        if getattr(user, "is_buyer", False):
            return redirect('buyers:buyer_index')

        return redirect('core:index')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _('Change Password')
        return context


class UserLogoutView(View):
    def get(self, request, *args, **kwargs):
        logout(request)
        return HttpResponseRedirect(
            reverse(
                'two_factor:login'
            )
        )
