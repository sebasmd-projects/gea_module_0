# apps/project/specific/documents/video_masonry/views.py
from __future__ import annotations

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.views.generic import TemplateView, View

from .models import MediaAsset

PAGE_SIZE = 24


class MediaGalleryView(TemplateView):
    template_name = "video_masonry/gallery.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = MediaAsset.objects.all().only("id", "media_type", "file", "caption", "created_at")

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(1)

        ctx.update(
            items=page_obj.object_list,
            has_more=page_obj.has_next(),
            next_page=2 if page_obj.has_next() else None,
            total_items=paginator.count,
            page_size=PAGE_SIZE,
        )
        return ctx


class MediaGalleryFragmentView(View):
    template_name = "video_masonry/_media_grid.html"

    def get(self, request, *args, **kwargs):
        try:
            page = int(request.GET.get("page", "1"))
        except ValueError:
            raise Http404("page inválida")

        if page < 1:
            raise Http404("page inválida")

        qs = MediaAsset.objects.all().only("id", "media_type", "file", "caption", "created_at")
        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(page)

        return render(
            request,
            self.template_name,
            {
                "items": page_obj.object_list,
                "has_more": page_obj.has_next(),
                "next_page": (page + 1) if page_obj.has_next() else None,
            },
        )
