from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView

from .forms import ProofOfLifeForm
from .models import ProofOfLifeModel


class ProofOfLifeCreateView(CreateView):
    """
    Vista basada en clases (CBV) que crea un registro de prueba de vida (POL).
    """
    model = ProofOfLifeModel
    form_class = ProofOfLifeForm
    template_name = "dashboard/pages/documents/pol/pol_form.html"
    success_url = reverse_lazy("pol:success")

    def form_valid(self, form):
        return super().form_valid(form)


class ProofOfLifeSuccessView(TemplateView):
    """
    Vista mostrada al completar exitosamente la prueba de vida.
    """
    template_name = "dashboard/pages/documents/pol/pol_success.html"
