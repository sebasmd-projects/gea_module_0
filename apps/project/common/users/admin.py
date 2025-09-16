from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import (AddressModel, CityModel, CountryModel, StateModel,
                     UserModel, UserPersonalInformationModel)


@admin.register(UserModel)
class UserModelAdmin(UserAdmin, GeneralAdminModel):

    def get_queryset(self, request):
        """
        Muestra solo al usuario autenticado su propio registro si no es superusuario.
        """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(id=request.user.id)

    def has_change_permission(self, request, obj=None):
        """
        Permite al usuario cambiar solo su propio registro.
        """
        if obj is None:  # Para las vistas generales de la lista
            return True
        return obj == request.user or request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        """
        Permite al usuario ver solo su propio registro.
        """
        if obj is None:  # Para las vistas generales de la lista
            return True
        return obj == request.user or request.user.is_superuser

    search_fields = (
        'id',
        'username',
        'email',
        'first_name',
        'last_name',
    )

    list_display = (
        'get_full_name',
        'username',
        'email',
        'full_code_and_phonenumber',
        'is_staff',
        'is_active',
        'is_superuser',
        'is_verified_holder',
        "user_type",
        'get_groups',
    )

    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "is_verified_holder",
        "user_type"
    )

    list_display_links = (
        'get_full_name',
        'username',
        'email',
    )

    ordering = (
        'default_order',
        'created',
        'last_name',
        'first_name',
        'email',
        'username',
    )

    readonly_fields = (
        'created',
        'updated',
        'last_login'
    )

    fieldsets = (
        (
            _('User Information'), {
                'fields': (
                    'username',
                    'password',
                    'user_type',
                )
            }
        ),
        (
            _('Personal Information'), {
                'fields': (
                    'first_name',
                    'last_name',
                    
                )
            }
        ),
        ('Contact Information', {
            'fields': (
                'phone_number_code',
                'phone_number',
                'email',
            )
        }),
        (
            _('Permissions'), {
                'fields': (
                    'is_verified_holder',
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'groups',
                    'user_permissions',
                )
            }
        ),
        (
            _('Dates'), {
                'fields': (
                    'last_login',
                    'created',
                    'updated'
                ),
                'classes': (
                    'collapse',
                )
            }
        ),
        (
            _('Priority'), {
                'fields': (
                    'default_order',
                ),
                'classes': (
                    'collapse',
                )
            }
        )
    )

    def full_code_and_phonenumber(self, obj):
        return f"+{obj.phone_number_code.split('-')[0]}{obj.phone_number}"
    
    def get_fieldsets(self, request, obj=None):
        """
        Restringe los campos visibles en el formulario de edición según el usuario.
        """
        fieldsets = super().get_fieldsets(request, obj)
        if not request.user.is_superuser:
            # Elimina campos sensibles o irrelevantes para usuarios normales
            restricted_fieldsets = [
                (
                    name, {
                        'fields': [field for field in fields['fields'] if field != 'is_staff']
                    }
                )
                for name, fields in fieldsets
            ]
            return restricted_fieldsets
        return fieldsets

    def get_groups(self, obj):
        return ", ".join([group.name for group in obj.groups.all()])

    def get_full_name(self, obj):
        return obj.get_full_name()

    get_groups.short_description = _('Groups')

    get_full_name.short_description = _('Names')
    
    full_code_and_phonenumber.short_description = _('Phone Number')


@admin.register(CountryModel)
class CountryModelAdmin(GeneralAdminModel):
    search_fields = (
        'country_name',
        'country_code'
    )

    list_display = (
        'country_name',
        'country_code'
    )

    ordering = (
        'country_name',
    )

    list_filter = (
        'country_name',
    )

    readonly_fields = (
        'created',
        'updated',
    )


@admin.register(StateModel)
class StateModelAdmin(GeneralAdminModel):
    search_fields = (
        'state_name',
        'country__country_name'
    )

    list_display = (
        'state_name',
        'country'
    )

    ordering = (
        'state_name',
        'country'
    )

    list_filter = (
        'country',
    )

    readonly_fields = (
        'created',
        'updated',
    )


@admin.register(CityModel)
class CityModelAdmin(GeneralAdminModel):
    search_fields = (
        'city_name',
        'state__state_name',
        'state__country__country_name'
    )

    list_display = (
        'city_name',
        'state',
        'get_country'
    )

    ordering = (
        'city_name',
        'state__state_name'
    )

    list_filter = (
        'state',
        'state__country'
    )

    readonly_fields = (
        'created',
        'updated',
    )

    def get_country(self, obj):
        return obj.state.country.country_name

    get_country.short_description = 'Country'


@admin.register(AddressModel)
class AddressModelAdmin(GeneralAdminModel):
    search_fields = (
        'country__country_name',
        'state__state_name',
        'city__city_name',
        'address_line_1',
        'postal_code'
    )

    list_display = (
        'country',
        'state',
        'city',
        'address_line_1',
        'address_line_2',
        'postal_code'
    )

    ordering = (
        'country',
        'state',
        'city',
        'address_line_1'
    )

    list_filter = (
        'country',
        'is_active'
    )

    readonly_fields = (
        'created',
        'updated',
    )

    fieldsets = (
        (None, {
            'fields': (
                'country',
                'state',
                'city',
                'address_line_1',
                'address_line_2',
                'postal_code'
            )
        }),
    )


@admin.register(UserPersonalInformationModel)
class UserPersonalInformationModelAdmin(GeneralAdminModel):
    search_fields = (
        'id',
        'user__first_name',
        'user__last_name',
        'user__email',
        'passport_id',
        'citizenship_country',
    )

    list_display = (
        'user',
        'birth_date',
        'gender',
        'citizenship_country',
        'passport_id',
        'date_of_issue',
        'date_of_expiry'
    )

    ordering = (
        'user__first_name',
        'user__last_name',
        'birth_date'
    )

    list_filter = (
        'gender',
        'citizenship_country'
    )

    readonly_fields = (
        'user',
    )

    fieldsets = (
        (None, {
            'fields': (
                'user',
                'birth_date',
                'gender',
                'citizenship_country'
            )
        }),
        ('Passport Information', {
            'fields': (
                'passport_id',
                'date_of_issue',
                'issuing_authority',
                'date_of_expiry',
                'passport_image',
                'signature'
            )
        })
    )

    filter_horizontal = (
        'addresses',
    )
