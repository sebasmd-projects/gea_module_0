from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import IPBlockedModel
from apps.common.utils.forms import KeyForm


class LoginGroupRequiredMixin(UserPassesTestMixin, LoginRequiredMixin):
    group_required = None
    redirect_url = None

    def test_func(self):
        if self.group_required is None:
            raise ValueError(_("group_required attribute not set"))
        user = self.request.user
        return user.is_superuser or user.groups.filter(name=self.group_required).exists()

    def handle_no_permission(self):
        if self.redirect_url:
            return redirect(self.redirect_url)
        raise PermissionDenied(
            _("You do not have permission to view this page"))


class EncryptedPermissionsMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        if user.is_superuser or user.groups.filter(name=settings.KEY_BYPASS_GROUP).exists():
            return True
        return False

    def handle_no_permission(self):
        if self.request.method == 'POST':
            key_form = KeyForm(self.request.POST)
            if key_form.is_valid():
                key = key_form.cleaned_data['key']
                if key == settings.SECRET_KEY[:6]:
                    self.request.session['has_key_access'] = True
                    self.request.session['key_attempts'] = 0
                else:
                    attempts = self.request.session.get('key_attempts', 0) + 1
                    self.request.session['key_attempts'] = attempts
                    if attempts > 6:
                        IPBlockedModel.objects.create(
                            current_ip=self.request.META['REMOTE_ADDR'],
                            reason=IPBlockedModel.ReasonsChoices.SECURITY_KEY_ATTEMPTS
                        )
            else:
                self.request.session['has_key_access'] = False

        key_form = KeyForm()
        return render(self.request, 'key_form.html', {'key_form': key_form})
