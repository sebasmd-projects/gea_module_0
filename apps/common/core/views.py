from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView


class IndexTemplateView(TemplateView):
    template_name = "core/index/index.html"
