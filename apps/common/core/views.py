import logging

from django.conf import settings
from django.core.mail import send_mail
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.generic.edit import FormView
from honeypot.decorators import check_honeypot

from .forms import ContactForm
from .models import ContactModel, ModalBannerModel

logger = logging.getLogger(__name__)


@method_decorator(check_honeypot, name='post')
class IndexTemplateView(FormView):
    template_name = "core/index/index.html"
    form_class = ContactForm
    success_url = reverse_lazy('core:index')

    def form_valid(self, form):
        unique_id = form.cleaned_data.get('unique_id')
        honeypot_field = form.cleaned_data.get('email_confirm')

        if ContactModel.objects.filter(unique_id=unique_id).exists():
            form.add_error(None, _("This form has already been sent."))
            return self.form_invalid(form)

        if honeypot_field:
            form.save()
            return render(self.request, self.template_name, {'form': None, 'success_message': True})

        contact = form.save()

        user_language = self.request.LANGUAGE_CODE

        html_message = render_to_string('core/email/contact_email_template.html', {
            'names': contact.name,
            'LANGUAGE_CODE': user_language,
        })

        subject = _('Message Received! | GEA')

        plain_message = _('Thank you %(name)s for contacting us.') % {
            'name': contact.name}

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                html_message=html_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[contact.email],
                fail_silently=False
            )
        except Exception as e:
            logger.error(f"An unexpected error occurred sending mail: {e}")
            return render(self.request, self.template_name, {'form': None, 'success_message': True})

        return render(self.request, self.template_name, {'form': None, 'success_message': True})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        banner = ModalBannerModel.objects.filter(is_active=True).first()
        context['modal_banner'] = banner
        return context
