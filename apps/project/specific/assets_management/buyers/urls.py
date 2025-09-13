from django.urls import path

from apps.project.specific.assets_management.buyers.views import (
    OfferDetailView,
    OfferSoftDeleteView,
    OfferUpdateView,
    PurchaseOrderCreateView,
    PurchaseOrdersView,
    OfferApprovalWizardPageView,
    OfferApprovalWizardPartialView,
    OfferApprovalWizardActionView,
    ProfitabilityTemplateView
)

app_name = "buyers"

urlpatterns = [
    path(
        'buyer/asset/purchase-order/<uuid:id>/detail/',
        OfferDetailView.as_view(),
        name='offer_details'
    ),
    path(
        'buyer/asset/purchase-order/<uuid:pk>/update/',
        OfferUpdateView.as_view(),
        name='offer_update'
    ),
    path(
        'buyer/asset/purchase-order/<uuid:id>/delete/',
        OfferSoftDeleteView.as_view(),
        name='offer_delete'
    ),
    path(
        'buyer/asset/purchase-orders/',
        PurchaseOrdersView.as_view(),
        name='buyer_index'
    ),
    path(
        'buyer/asset/purchase-order/add/',
        PurchaseOrderCreateView.as_view(),
        name='buyer_create'
    ),
    path(
        "po/<uuid:id>/wizard/",
        OfferApprovalWizardPageView.as_view(),
        name="offer_wizard_page"
    ),
    path(
        "po/<uuid:id>/wizard/partial/",
        OfferApprovalWizardPartialView.as_view(),
        name="offer_wizard_partial"
    ),
    path(
        "po/<uuid:id>/wizard/action/",
        OfferApprovalWizardActionView.as_view(),
        name="offer_wizard_action"
    ),
    path(
        "profitability/",
        ProfitabilityTemplateView.as_view(),
        name="profitability_view"
    )
]
