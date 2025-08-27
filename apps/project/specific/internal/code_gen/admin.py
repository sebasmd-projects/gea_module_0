from django.contrib import admin

from apps.common.utils.admin import GeneralAdminModel

from .models import CodeRegistrationModel


@admin.register(CodeRegistrationModel)
class CodeRegistrationModelAdmin(GeneralAdminModel):
    list_display = (
        'reference',
        'custom_text_input',
        'code_information',
        'created',
        'updated'
    )

    search_fields = (
        'reference',
        'custom_text_input',
        'code_information'
    )

    list_filter = (
        'is_active',
    )

    readonly_fields = (
        'created',
        'updated'
    )

    ordering = (
        '-default_order',
    )

    fieldsets = (
        (
            'Barcode Information',
            {
                'fields': (
                    'reference',
                    'custom_text_input',
                    'code_information',
                )
            }
        ),
        (
            'Status',
            {
                'fields': (
                    'is_active',
                )
            }
        ),
        (
            'System Information',
            {
                'fields': (
                    'created',
                    'updated',
                )
            }
        )
    )
