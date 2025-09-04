from django.urls import path

from .views import (
    AssetAddNewCategory,
    AssetNameWithInlineAssetCreateView,
    HolderTemplateview,
)

app_name = 'assets'

urlpatterns = [
    path(
        'asset/holder/',
        HolderTemplateview.as_view(),
        name='holder_index'
    ),
    path(
        "asset/create/",
        AssetNameWithInlineAssetCreateView.as_view(),
        name="create"
    ),
    path(
        "asset/add/category/",
        AssetAddNewCategory.as_view(),
        name="add_category"
    ),
]
