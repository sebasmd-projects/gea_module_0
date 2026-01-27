# apps/project/specific/documents/video_masonry/views.py
from __future__ import annotations

from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, View
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator

from apps.project.specific.assets_management.buyers.views import BuyerRequiredMixin

from .models import MediaAsset, MediaAssetInteraction, MediaAssetUserStats

PAGE_SIZE = 15


class MediaGalleryView(BuyerRequiredMixin, TemplateView):
    template_name = "video_masonry/gallery.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        qs = MediaAsset.objects.all().only("id", "media_type", "file", "caption", "created")

        # paginación clásica
        try:
            page = int(self.request.GET.get("page", "1"))
        except ValueError:
            page = 1
        if page < 1:
            page = 1

        total = qs.count()
        start = (page - 1) * PAGE_SIZE
        end = start + PAGE_SIZE

        items = list(qs[start:end])
        has_prev = page > 1
        has_next = end < total

        ctx.update(
            items=items,
            page=page,
            page_size=PAGE_SIZE,
            total_items=total,
            has_prev=has_prev,
            has_next=has_next,
            prev_page=page - 1,
            next_page=page + 1,
        )
        return ctx


class MediaAssetDownloadView(BuyerRequiredMixin, View):
    """
    Descarga como attachment + contabiliza:
    - log (MediaAssetInteraction)
    - contador por usuario (MediaAssetUserStats)
    """

    def get(self, request, pk: int, *args, **kwargs):
        asset = get_object_or_404(MediaAsset, pk=pk)

        # tracking
        MediaAssetInteraction.objects.create(
            user=request.user,
            asset=asset,
            action=MediaAssetInteraction.Action.DOWNLOAD,
        )
        MediaAssetUserStats.inc_download(user=request.user, asset=asset)

        # descarga
        if not asset.file:
            raise Http404("file no disponible")

        # FileResponse maneja streaming
        resp = FileResponse(asset.file.open("rb"), as_attachment=True, filename=asset.file.name.rsplit("/", 1)[-1])
        return resp


@method_decorator(require_POST, name="dispatch")
class MediaAssetTrackView(BuyerRequiredMixin, View):
    """
    Endpoint para contabilizar visualización.
    Se invoca desde JS cuando el usuario abre el modal (acción explícita).
    """

    def post(self, request, *args, **kwargs):
        try:
            asset_id = int(request.POST.get("asset_id", "0"))
        except ValueError:
            return JsonResponse({"ok": False, "error": "asset_id inválido"}, status=400)

        asset = get_object_or_404(MediaAsset, pk=asset_id)

        MediaAssetInteraction.objects.create(
            user=request.user,
            asset=asset,
            action=MediaAssetInteraction.Action.VIEW,
        )
        MediaAssetUserStats.inc_view(user=request.user, asset=asset)

        return JsonResponse({"ok": True})
