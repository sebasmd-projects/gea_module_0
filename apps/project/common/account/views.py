from django.contrib.auth import authenticate, login, logout
from django.db import IntegrityError
from django.http import HttpResponseRedirect
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.generic import View
from django.views.generic.edit import FormView

from apps.project.common.users.models import UserModel

from .forms import GeaUserRegisterForm


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
