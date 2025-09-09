from django.urls import path

from .views import (AssetLocationDeleteView, AssetLocationCreateView,
                    AssetUpdateView, LocationCreateView,
                    LocationReferenceDeleteView, LocationUpdateView)

app_name = 'assets_location'

urlpatterns = [
    path(
        'holder/asset/add/location/',
        LocationCreateView.as_view(),
        name='add_location'
    ),
    path(
        'holder/asset/delete/location/<uuid:pk>/',
        LocationReferenceDeleteView.as_view(),
        name='delete_location'
    ),
    path(
        'holder/asset/update/location/<uuid:pk>/',
        LocationUpdateView.as_view(),
        name='update_location'
    ),

    path(
        'holder/asset/add/',
        AssetLocationCreateView.as_view(),
        name='add_asset_location'
    ),
    path(
        'holder/asset/delete/<uuid:pk>/',
        AssetLocationDeleteView.as_view(),
        name='delete_asset_location'
    ),
    path(
        'holder/asset/update/<uuid:pk>/',
        AssetUpdateView.as_view(),
        name='update_asset_location'
    ),
]
