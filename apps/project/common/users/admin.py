from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _
from django.utils.text import capfirst

from apps.common.utils.admin import GeneralAdminModel

from .models import (AddressModel, CityModel, CountryModel, StateModel,
                     UserModel, UserPersonalInformationModel)

admin.site.unregister(Group)

def _normalize_perm_text(name: str) -> str:
    """
    Normaliza el texto 'humano' del Permission.name:
    - Colapsa espacios.
    - Lo deja en estilo oración (primera letra en mayúscula).
    """
    if not name:
        return ""
    lowered = name.strip()
    lowered = " ".join(lowered.split())
    return capfirst(lowered.lower())


@admin.register(UserModel)
class UserModelAdmin(UserAdmin, GeneralAdminModel):

    @staticmethod
    def _can_view_all(request):
        u = request.user
        return u.is_superuser or u.has_perm('users.can_view_all_users')

    @staticmethod
    def _can_view_buyers(request):
        return request.user.has_perm('users.can_view_buyers')

    @staticmethod
    def _can_view_holders(request):
        return request.user.has_perm('users.can_view_holders')

    def get_queryset(self, request):

        qs = super().get_queryset(request)

        if self._can_view_all(request):
            return qs

        if self._can_view_buyers(request):
            return qs.filter(user_type=UserModel.UserTypeChoices.BUYER)

        if self._can_view_holders(request):
            return qs.filter(user_type__in=UserModel.asset_holder_values())

        return qs.filter(id=request.user.id)

    def _can_access_obj(self, request, obj):
        if obj is None:
            return True
        if self._can_view_all(request):
            return True
        if obj == request.user:
            return True
        if self._can_view_buyers(request):
            return obj.user_type == UserModel.UserTypeChoices.BUYER
        if self._can_view_holders(request):
            return obj.user_type in UserModel.asset_holder_values()
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and self._can_access_obj(request, obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._can_access_obj(request, obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._can_access_obj(request, obj)

    def get_readonly_fields(self, request, obj=None):
        """
        Lock down specific fields based on custom perms.
        """
        ro_fields = set(super().get_readonly_fields(request, obj))

        # Passwords
        if not (
            request.user.is_superuser or
            request.user.has_perm('users.can_change_all_passwords') or
            (obj == request.user and request.user.has_perm(
                'users.can_change_password'))
        ):
            ro_fields |= {'password'}

        # Personal info
        if not request.user.has_perm('users.can_change_users_personal_info'):
            ro_fields |= {'first_name', 'last_name'}

        # Contact info
        if not request.user.has_perm('users.can_change_users_contact_info'):
            ro_fields |= {'phone_number_code', 'phone_number', 'email'}

        # Referred
        if not request.user.has_perm('users.can_change_users_referred'):
            ro_fields |= {'referred'}

        # Verify holders
        if not request.user.has_perm('users.can_verify_holders'):
            ro_fields |= {'is_verified_holder'}

        # Deactivate
        if not request.user.has_perm('users.can_deactivate_users'):
            ro_fields |= {'is_active'}

        return tuple(ro_fields)

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
        'referred',
        'is_referred',
        "user_type",
        'get_groups',
    )

    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "is_verified_holder",
        'is_referred',
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
        (
            _('Contact Information'), {
                'fields': (
                    'phone_number_code',
                    'phone_number',
                    'email',
                    'referred',
                )
            }
        ),
        (
            _('Permissions'), {
                'fields': (
                    'is_verified_holder',
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'is_referred',
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


@admin.register(Group)
class GroupAdmin(GeneralAdminModel):
    list_display = ("name", "perms_labels", "perms_human")

    list_filter = ("permissions__content_type__app_label",)

    search_fields = (
        "name",
        "permissions__codename",
        "permissions__name",
        "permissions__content_type__app_label",
    )

    filter_horizontal = ("permissions",)

    def get_queryset(self, request):
        # Optimiza N+1: precarga permisos y su content_type
        qs = super().get_queryset(request)
        return qs.prefetch_related("permissions__content_type")

    @admin.display(description="Permisos (app.perm)", ordering=None)
    def perms_labels(self, obj: Group):
        """
        Muestra permisos como app_label.codename en <ul>.
        """
        perms = obj.permissions.all()
        if not perms:
            return "—"
        # Ordena por app_label y codename
        items = sorted(
            (f"{p.content_type.app_label}.{p.codename}" for p in perms),
            key=lambda s: (s.split(".", 1)[0], s.split(".", 1)[1]),
        )
        return format_html(
            "<ul style='margin:0;padding-left:1.25rem'>{}</ul>",
            format_html_join("", "<li>{}</li>", ((it,) for it in items)),
        )
        
    @admin.display(description="Permisos", ordering=None)
    def perms_human(self, obj: Group):
        """
        Muestra permisos con su nombre 'humano' normalizado en <ul>.
        """
        perms = obj.permissions.all()
        if not perms:
            return "—"
        items = sorted((_normalize_perm_text(p.name) for p in perms))
        return format_html(
            "<ul style='margin:0;padding-left:1.25rem'>{}</ul>",
            format_html_join("", "<li>{}</li>", ((it,) for it in items)),
        )
