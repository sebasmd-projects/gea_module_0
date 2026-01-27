# apps/project/specific/documents/video_masonry/urls.py
from django.urls import path

from .views import MediaGalleryView, MediaAssetDownloadView, MediaAssetTrackView

app_name = "video_masonry"

urlpatterns = [
    path("gallery/masonry/", MediaGalleryView.as_view(), name="gallery"),
    path("gallery/masonry/download/<int:pk>/", MediaAssetDownloadView.as_view(), name="download"),
    path("gallery/masonry/track/", MediaAssetTrackView.as_view(), name="track"),
]
