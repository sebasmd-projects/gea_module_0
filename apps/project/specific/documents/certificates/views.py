
from django.shortcuts import redirect
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, FormView
from django.urls import reverse


from .functions import generate_qr_with_favicon, generate_barcode

from .forms import IDNumberForm
from .models import CertificateTypesModel, CertificateUserModel


class InputEmployeeVerificationIPCONFormView(FormView):
    template_name = 'dashboard/pages/documents/certificates/idoneity/certificate_input.html'
    form_class = IDNumberForm

    def form_valid(self, form):
        document_type = form.cleaned_data['document_type']
        document_number = form.cleaned_data['document_number'].strip().upper()

        try:
            certificate = CertificateUserModel.objects.get(
                document_type=document_type,
                certificate_type=CertificateTypesModel.objects.get(
                    name=CertificateTypesModel.CertificateTypeChoices.IDONEITY
                )
            )
            return redirect('certificates:detail_employee_verification_ipcon', pk=certificate.id)

        except CertificateUserModel.DoesNotExist:
            form.add_error('document_number', _('ID Number not found.'))
            return self.form_invalid(form)


class InputEmployeeVerificationIPCONDetailView(DetailView):
    model = CertificateUserModel
    template_name = 'dashboard/pages/documents/certificates/idoneity/certificate_detail.html'
    context_object_name = 'certificate'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        relative_url = reverse(
            'certificates:detail_employee_verification_ipcon',
            kwargs={'pk': self.object.pk}
        )

        absolute_url = self.request.build_absolute_uri(relative_url)

        context['qr_code'] = mark_safe(
            generate_qr_with_favicon(absolute_url)
        )

        context['barcode'] = mark_safe(
            generate_barcode(absolute_url)
        )

        return context

