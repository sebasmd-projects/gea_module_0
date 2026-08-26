from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import (CodeRegistrationModel, CodeSequenceModel,
                     StampLayoutModel, StampPlacementModel)


@admin.register(CodeRegistrationModel)
class CodeRegistrationModelAdmin(GeneralAdminModel):
    list_display = (
        'reference',
        'initials',
        'sequence',
        'random_code',
        'custom_text_input',
        'code_information',
        'generated_barcode',
        'generated_qr',
        'created',
    )

    search_fields = (
        'reference',
        'custom_text_input',
        'code_information',
        'sequence',
        'random_code',
        'source_file_hash',
    )

    list_filter = (
        'is_active',
        'generated_barcode',
        'generated_qr',
    )

    readonly_fields = (
        'created',
        'updated'
    )

    ordering = (
        '-created',
    )

    fieldsets = (
        (
            _('Code information'),
            {
                'fields': (
                    'reference',
                    'description',
                    'custom_text_input',
                    'code_information',
                )
            }
        ),
        (
            _('Segments'),
            {
                'fields': (
                    'initials',
                    'sequence',
                    'random_code',
                    'source_file_hash',
                    'hash_fragment',
                )
            }
        ),
        (
            _('Symbols'),
            {
                'fields': (
                    'generated_barcode',
                    'generated_qr',
                    'qr_payload',
                )
            }
        ),
        (
            _('Status'),
            {
                'fields': (
                    'is_active',
                )
            }
        ),
        (
            _('System Information'),
            {
                'fields': (
                    'created',
                    'updated',
                ),
                'classes': ('collapse',)
            }
        )
    )


class StampPlacementInline(admin.TabularInline):
    model = StampPlacementModel
    extra = 0
    fields = (
        'kind',
        'page_selector',
        'page_numbers',
        'anchor',
        'offset_x',
        'offset_y',
        'width',
        'height',
        'opacity',
        'is_active',
    )


@admin.register(StampLayoutModel)
class StampLayoutModelAdmin(GeneralAdminModel):
    inlines = [StampPlacementInline]

    list_display = ('name', 'is_default', 'is_active', 'placement_count')
    list_filter = ('is_default', 'is_active')
    search_fields = ('name', 'description')

    @admin.display(description=_('Placements'))
    def placement_count(self, obj):
        return obj.placements.count()


@admin.register(CodeSequenceModel)
class CodeSequenceModelAdmin(GeneralAdminModel):
    list_display = ('name', 'counter', 'updated')
    readonly_fields = ('counter', 'created', 'updated')
    search_fields = ('name',)
