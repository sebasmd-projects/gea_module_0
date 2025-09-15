from django.urls import path

from .views import (AssetAddNewCategory, AssetNameWithInlineAssetCreateView,
                    HolderTemplateview, WhatsAppRedirectView)

app_name = 'assets'

urlpatterns = [
    path(
        'holder/assets/',
        HolderTemplateview.as_view(),
        name='holder_index'
    ),
    path(
        "buyer/asset/add/",
        AssetNameWithInlineAssetCreateView.as_view(),
        name="create"
    ),
    path(
        "buyer/asset/add/category/",
        AssetAddNewCategory.as_view(),
        name="add_category"
    ),
    path(
        "client/help/GEA/",
        WhatsAppRedirectView.as_view(),
        name="help_gea"
    )
]
