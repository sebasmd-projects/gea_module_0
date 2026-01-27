# apps/project/specific/documents/video_masonry/urls.py

from django.urls import path
from .views import MediaGalleryView, MediaGalleryFragmentView

app_name = "video_masonry"

urlpatterns = [
    path(
        "gallery/masonry/",
        MediaGalleryView.as_view(),
        name="gallery"
    ),
    path(
        "fragment/",
        MediaGalleryFragmentView.as_view(),
        name="gallery_fragment"
    ),
]
