# apps/project/common/account/views.py

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
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode, url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.edit import FormView
from django.contrib import messages

from apps.project.common.users.models import UserModel

from .forms import GeaUserRegisterForm, ForgotPasswordStep1Form, ForgotPasswordStep2Form, ChangePasswordForm


class UserLogoutView(View):
    def get(self, request, *args, **kwargs):
        logout(request)
        return HttpResponseRedirect(
            reverse(
                'two_factor:login'
            )
        )


class GeaUserRegisterView(FormView):
    template_name = "account/gea_register.html"
    form_class = GeaUserRegisterForm

    def dispatch(self, request, *args, **kwargs):
        if self.request.user.is_authenticated:
            return redirect('core:index')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            user = UserModel.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
                password=form.cleaned_data['password'],
                user_type=form.cleaned_data['user_type'],
                phone_number_code=form.cleaned_data['phone_number_code'],
                phone_number=form.cleaned_data['phone_number'],
                referred=form.cleaned_data['referred'],
            )
        except IntegrityError as e:
            if "email_hash" in str(e):
                form.add_error("email", _(
                    "A user with this email already exists."))
                return self.form_invalid(form)
            raise

        # Autenticación e inicio de sesión inmediato
        auth_user = authenticate(
            self.request,
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password'],
        )
        if auth_user is not None:
            login(self.request, auth_user)

        # 1) Priorizar next_url si viene en GET
        next_url = self.request.GET.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure()
        ):
            return redirect(next_url)

        # 2) Si no hay next, redirigir según rol
        if getattr(user, "is_asset_holder", False):
            return redirect('assets:holder_index')

        if getattr(user, "is_buyer", False):
            return redirect('buyers:buyer_index')

        # 3) Fallback
        return redirect('core:index')

    def form_invalid(self, form):
        return super().form_invalid(form)

    def get_success_url(self):
        # No se usará porque hacemos redirect en form_valid,
        # pero lo dejamos por compatibilidad
        return reverse('core:index')


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
        subject = _("Password Reset Request for %(site)s") % {"site": site_name}
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
