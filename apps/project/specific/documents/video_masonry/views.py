# apps/project/specific/documents/video_masonry/views.py
from __future__ import annotations

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import render
from django.views.generic import TemplateView, View

from .models import MediaAsset

PAGE_SIZE = 24


def _get_all_categories() -> list[str]:
    """
    Extrae categorías únicas desde la columna CSV (100-500 registros ok).
    Si esto crece, conviene una tabla Category o un cache.
    """
    cats: list[str] = []
    seen = set()
    qs = MediaAsset.objects.exclude(categories__isnull=True).exclude(categories__exact="").values_list("categories", flat=True)
    for raw in qs:
        for c in (raw or "").split(","):
            c = c.strip()
            if not c:
                continue
            key = c.lower()
            if key in seen:
                continue
            seen.add(key)
            cats.append(c)
    cats.sort(key=lambda x: x.lower())
    return cats


def _apply_category_filter(qs, category: str | None):
    if not category:
        return qs
    cat = category.strip().lower()
    if not cat:
        return qs
    # filtro robusto por delimitadores
    return qs.filter(categories_key__icontains=f"|{cat}|")


class MediaGalleryView(TemplateView):
    template_name = "video_masonry/gallery.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        category = self.request.GET.get("cat")
        qs = MediaAsset.objects.all().only(
            "id", "media_type", "file", "caption", "categories", "categories_key", "created_at"
        )
        qs = _apply_category_filter(qs, category)

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(1)

        ctx.update(
            items=page_obj.object_list,
            has_more=page_obj.has_next(),
            next_page=2 if page_obj.has_next() else None,
            total_items=paginator.count,
            page_size=PAGE_SIZE,
            categories=_get_all_categories(),
            current_cat=(category or "").strip(),
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

        category = request.GET.get("cat")
        qs = MediaAsset.objects.all().only(
            "id", "media_type", "file", "caption", "categories", "categories_key", "created_at"
        )
        qs = _apply_category_filter(qs, category)

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
