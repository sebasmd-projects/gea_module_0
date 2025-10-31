from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import TemplateView


class IndexTemplateView(TemplateView):
    template_name = "core/index.html"


class PrivacyTemplateView(TemplateView):
    template_name = "core/privacy.html"


class TermsTemplateView(TemplateView):
    template_name = "core/terms.html"


class PortfolioTemplateView(TemplateView):
    template_name = "core/portfolio.html"
