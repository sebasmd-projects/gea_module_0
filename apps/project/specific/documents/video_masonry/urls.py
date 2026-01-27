# apps/project/specific/documents/video_masonry/urls.py
from django.urls import path

from .views import MediaGalleryView, MediaAssetDownloadView, MediaAssetTrackView

app_name = "video_masonry"

urlpatterns = [
    path("", MediaGalleryView.as_view(), name="gallery"),
    path("download/<int:pk>/", MediaAssetDownloadView.as_view(), name="download"),
    path("track/", MediaAssetTrackView.as_view(), name="track"),
]
