from django.urls import path

from apps.project.specific.assets_management.buyers.views import (
    BuyerCreateView, OfferDetailView, OfferSoftDeleteView, OfferUpdateView)

app_name = "buyers"

urlpatterns = [
    path(
        'offers/<uuid:id>/detail/',
        OfferDetailView.as_view(),
        name='offer_details'
    ),
    path(
        'offers/<uuid:pk>/update/',
        OfferUpdateView.as_view(),
        name='offer_update'
    ),
    path(
        'offers/<uuid:id>/delete/',
        OfferSoftDeleteView.as_view(),
        name='offer_delete'
    ),
    path(
        'asset/buyer/',
        BuyerCreateView.as_view(),
        name='buyer_index'
    ),
]
