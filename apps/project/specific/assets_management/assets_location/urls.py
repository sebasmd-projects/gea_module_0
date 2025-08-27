from django.urls import path

from .views import (AseetLocationDeleteView, AssetLocationCreateView,
                    AssetUpdateView, LocationCreateView,
                    LocationReferenceDeleteView, LocationUpdateView)

app_name = 'assets_location'

urlpatterns = [
    path(
        'asset/add/location/',
        LocationCreateView.as_view(),
        name='add_location'
    ),
    path(
        'asset/delete/location/<uuid:pk>/',
        LocationReferenceDeleteView.as_view(),
        name='delete_location'
    ),
    path(
        'asset/update/location/<uuid:pk>/',
        LocationUpdateView.as_view(),
        name='update_location'
    ),

    path(
        'asset/add/',
        AssetLocationCreateView.as_view(),
        name='add_asset_location'
    ),
    path(
        'asset/delete/<uuid:pk>/',
        AseetLocationDeleteView.as_view(),
        name='delete_asset_location'
    ),
    path(
        'asset/update/<uuid:pk>/',
        AssetUpdateView.as_view(),
        name='update_asset_location'
    ),
]
