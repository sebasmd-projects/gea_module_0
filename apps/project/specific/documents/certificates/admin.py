# apps/project/specific/documents/certificates/admin.py

from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.db.models import F, Value, CharField
from django.db.models.functions import Coalesce, Cast, Concat

from apps.common.utils.admin import GeneralAdminModel

from apps.project.specific.internal.code_gen.services.certification import (
    CertificationError, certify_document)

from .models import (
    AegisSummaryDocumentModel,
    AegisSummaryModel,
    CertificateViewLogModel,
    CertificationStatusChoices,
    DocumentCertificateTypeChoices,
    DocumentVerificationModel,
    UserCertificateTypeChoices,
    UserVerificationModel,
)


@admin.action(description=_('Certify: stamp codes, hash and issue the copy'))
def action_certify_documents(modeladmin, request, queryset):
    """
    Ejecuta el flujo completo de certificacion sobre los documentos elegidos.

    Cada documento se procesa por separado para que un PDF ilegible no tumbe
    el lote entero.
    """
    certified = 0

    for document in queryset:
        try:
            outcome = certify_document(document, request=request)
        except CertificationError as error:
            messages.error(
                request,
                _('%(title)s: %(error)s') % {
                    'title': document.document_title,
                    'error': error,
                }
            )
            continue
        except Exception as error:
            messages.error(
                request,
                _('%(title)s: unexpected error (%(error)s)') % {
                    'title': document.document_title,
                    'error': error,
                }
            )
            continue

        certified += 1

        if outcome.skipped:
            messages.warning(
                request,
                _('%(title)s: some placements did not match any page (%(items)s).')
                % {
                    'title': document.document_title,
                    'items': ', '.join(outcome.skipped),
                }
            )

    if certified:
        messages.success(
            request,
            _('%(count)s document(s) certified.') % {'count': certified}
        )


@admin.action(description=_('Re-certify: rebuild codes, files and hashes'))
def action_recertify_documents(modeladmin, request, queryset):
    """
    Vuelve a certificar desde el original.

    Reutiliza el codigo publico y la secuencia ya asignados, de modo que la
    identidad del documento no cambia; lo que se rehace es el estampado, las
    huellas y la copia distribuible.
    """
    with transaction.atomic():
        queryset.update(certification_status=CertificationStatusChoices.DRAFT)

    action_certify_documents(modeladmin, request, queryset)


def set_certificate_type_action(*, certificate_value: str, label: str, name: str):
    """
    Factory para acciones seguras y reutilizables.
    name: identificador único (se usa para __name__)
    """
    def _action(modeladmin, request, queryset):
        with transaction.atomic():
            updated = queryset.update(certificate_type=certificate_value)
        messages.success(request, _(f"{updated} records updated to {label}."))

    _action.__name__ = name
    _action.short_description = _(f"Asignar tipo de certificado: {label}")
    return _action


action_set_idoneity = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.IDONEITY,
    label="IDONEITY",
    name="action_set_idoneity",
)

action_set_em_ipcon = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.EM_IPCON,
    label="EM_IPCON",
    name="action_set_em_ipcon",
)

action_set_em_propensiones = set_certificate_type_action(
    certificate_value=UserCertificateTypeChoices.EM_PROPENSIONES,
    label="EM_PROPENSIONES",
    name="action_set_em_propensiones",
)

action_set_aegis = set_certificate_type_action(
    certificate_value=DocumentCertificateTypeChoices.AEGIS,
    label="ASSET_AEGIS",
    name="action_set_aegis",
)

action_set_generic = set_certificate_type_action(
    certificate_value=DocumentCertificateTypeChoices.GENERIC,
    label="GENERIC",
    name="action_set_generic",
)


@admin.register(UserVerificationModel)
class UserVerificationModelAdmin(GeneralAdminModel):
    actions = [action_set_idoneity,
               action_set_em_ipcon, action_set_em_propensiones]

    list_per_page = 50
    empty_value_display = "-"

    list_display = (
        "uuid_prefix",
        "full_name",
        "certificate_type",
        "approved_badge",
        "expired_badge",
        "revoked_badge",
        "expires_at",
        "views_total",
        "views_unique",
        "cc_masked_admin",
        "pa_masked_admin",
        "detail_link",
    )
    list_display_links = ("uuid_prefix", "full_name")
    list_editable = ("expires_at",)  # UX: ajustes rápidos (si te conviene)

    list_filter = (
        "certificate_type",
        "approved",
        ("expires_at", admin.DateFieldListFilter),
        ("revoked_at", admin.DateFieldListFilter),
        ("created", admin.DateFieldListFilter),
    )
    date_hierarchy = "created"
    ordering = ("-created",)

    search_fields = (
        "public_uuid",
        "uuid_prefix",
        "public_code",
        "name",
        "last_name",
        "document_number_cc_hash",
        "document_number_pa_hash",
        "user__email",
    )

    autocomplete_fields = ("user", "approved_by")
    list_select_related = ("user", "approved_by")

    readonly_fields = (
        "id",
        "public_uuid",
        "uuid_prefix",
        "public_code",
        "document_number_cc_hash",
        "document_number_pa_hash",
        "created",
        "updated",
        "expired_badge",
        "revoked_badge",
        # UX/seguridad: mostrar solo máscara en admin
        "cc_masked_admin",
        "pa_masked_admin",
        "employee_photo_preview",
        # métricas anotadas (no properties)
        "views_total",
        "views_unique",
    )

    fieldsets = (
        (_("Identificación"), {
            "fields": ("public_uuid", "uuid_prefix", "public_code", "certificate_type"),
        }),
        (_("Titular"), {
            "fields": ("user", "name", "last_name", "employee_photo", "employee_photo_preview"),
        }),
        (_("Documentos (sensibles)"), {
            "fields": (
                "document_number_cc",
                "cc_masked_admin",
                "document_number_pa",
                "pa_masked_admin",
                "passport_expiration_date",
            ),
        }),
        (_("Estado legal"), {
            "fields": ("approved", "approved_by", "approval_date", "revoked_at", "revocation_reason"),
        }),
        (_("Vigencia"), {
            "fields": ("issued_at", "expires_at", "expired_badge", "revoked_badge"),
        }),
        (_("Métricas"), {
            "fields": ("views_total", "views_unique"),
            "classes": ("collapse",),
        }),
        (_("Auditoría"), {
            "fields": ("created", "updated"),
            "classes": ("collapse",),
        }),
    )

    class Media:
        # La accion "Certificar" estampa, hashea y marca al agua un PDF que
        # puede pesar decenas de MB: sin senal visual el operador la relanza.
        css = {'all': ('css/busy_buttons.css',)}
        js = ('js/busy_buttons.js',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        viewer_key = Concat(
            Coalesce(Cast(F("view_logs__user_id"),
                     output_field=CharField()), Value("")),
            Value("|"),
            Coalesce(F("view_logs__anonymous_email"), Value("")),
            output_field=CharField(),
        )

        return qs.annotate(
            _views_total=Count("view_logs"),
            _views_unique=Count(viewer_key, distinct=True),
        )

    @admin.display(description=_("Full name"))
    def full_name(self, obj):
        return f"{obj.name or ''} {obj.last_name or ''}".strip() or "-"

    @admin.display(description=_("Approved"), boolean=True)
    def approved_badge(self, obj):
        return bool(obj.approved)

    @admin.display(description=_("Expired"), boolean=True)
    def expired_badge(self, obj):
        return bool(obj.is_expired)

    @admin.display(description=_("Revoked"), boolean=True)
    def revoked_badge(self, obj):
        return bool(obj.is_revoked)

    @admin.display(description=_("Views"))
    def views_total(self, obj):
        return getattr(obj, "_views_total", 0)

    @admin.display(description=_("Unique"))
    def views_unique(self, obj):
        return getattr(obj, "_views_unique", 0)

    @admin.display(description=_("CC (masked)"))
    def cc_masked_admin(self, obj):
        return obj.cc_masked or "-"

    @admin.display(description=_("Passport (masked)"))
    def pa_masked_admin(self, obj):
        return obj.pa_masked or "-"

    @admin.display(description=_("Photo"))
    def employee_photo_preview(self, obj):
        if not getattr(obj, "employee_photo", None):
            return "-"
        return format_html(
            '<img src="{}" style="height:55px;width:55px;object-fit:cover;border-radius:8px;" />',
            reverse('certificates:employee_photo', args=[obj.pk]),
        )

    @admin.display(description=_("Detail"))
    def detail_link(self, obj):
        url = reverse(
            "certificates:detail_employee_verification_ipcon", args=[obj.pk])
        return format_html('<a href="{}">Ver</a>', url)

@admin.register(DocumentVerificationModel)
class DocumentVerificationModelAdmin(GeneralAdminModel):
    actions = [
        action_certify_documents,
        action_recertify_documents,
        action_set_aegis,
        action_set_generic,
    ]

    list_per_page = 50
    empty_value_display = "-"

    list_display = (
        "uuid_prefix",
        "document_title",
        "certificate_type",
        "status_badge",
        "public_code",
        "delivery_method",
        "expired_badge",
        "expires_at",
        "views_total",
        "views_unique",
        "files_column",
        "hash_short",
    )
    list_display_links = ("uuid_prefix", "document_title")
    list_editable = ("delivery_method", "expires_at")

    list_filter = (
        "certificate_type",
        "certification_status",
        "delivery_method",
        ("expires_at", admin.DateFieldListFilter),
        ("created", admin.DateFieldListFilter),
    )
    date_hierarchy = "created"
    ordering = ("-created",)

    search_fields = (
        "public_code",
        "uuid_prefix",
        "document_title",
        "document_hash",
        "source_hash",
        "public_copy_hash",
        "code_sequence",
        "code_payload",
    )

    autocomplete_fields = ()

    readonly_fields = (
        "id",
        "uuid_prefix",
        "public_code",
        "certification_status",
        "certified_at",
        "source_hash",
        "source_content_hash",
        "document_hash",
        "certified_content_hash",
        "public_copy_hash",
        "public_copy_content_hash",
        "code_payload",
        "code_initials",
        "code_sequence",
        "code_hash_fragment",
        "qr_payload",
        "hash_short",
        "created",
        "updated",
        "expired_badge",
        "views_total",
        "views_unique",
        "files_column",
        "record_link",
        "certification_help",
    )

    fieldsets = (
        (_("Identificacion"), {
            "fields": (
                "uuid_prefix",
                "public_code",
                "certificate_type",
                "document_title",
            )
        }),
        (_("Certificacion"), {
            "fields": (
                "certification_help",
                "source_file",
                "stamp_layout",
                "certification_status",
                "certified_at",
                "files_column",
                "record_link",
            )
        }),
        (_("Archivos generados"), {
            "fields": (
                "document_file",
                "public_copy_file",
            ),
            "classes": ("collapse",),
        }),
        (_("Huellas"), {
            "fields": (
                "source_hash",
                "source_content_hash",
                "document_hash",
                "certified_content_hash",
                "public_copy_hash",
                "public_copy_content_hash",
            ),
            "classes": ("collapse",),
        }),
        (_("Codigo emitido"), {
            "fields": (
                "code_payload",
                "code_initials",
                "code_sequence",
                "code_hash_fragment",
                "qr_payload",
            ),
            "classes": ("collapse",),
        }),
        (_("Entrega"), {"fields": ("delivery_method", "sent_at")}),
        (_("Vigencia"), {"fields": ("issued_at", "expires_at", "expired_badge")}),
        (_("Metricas"), {
            "fields": ("views_total", "views_unique"),
            "classes": ("collapse",),
        }),
        (_("Auditoria"), {
            "fields": ("created", "updated"),
            "classes": ("collapse",),
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        viewer_key = Concat(
            Coalesce(Cast(F("view_logs__user_id"),
                     output_field=CharField()), Value("")),
            Value("|"),
            Coalesce(F("view_logs__anonymous_email"), Value("")),
            output_field=CharField(),
        )

        return qs.annotate(
            _views_total=Count("view_logs"),
            _views_unique=Count(viewer_key, distinct=True),
        )

    @admin.display(description=_("How it works"))
    def certification_help(self, obj):
        return format_html(
            "<div style=\"max-width:60em\">{}<br><br>{}</div>",
            _(
                "1) Upload the ORIGINAL PDF without codes. 2) Pick the stamp "
                "layout (or leave it empty for the default one). 3) Save. "
                "4) Run the action \u201cCertify\u201d from the list view."
            ),
            _(
                "Certifying produces the certified PDF with its QR and barcode, "
                "the distributable copy carrying a hidden watermark, and the "
                "fingerprints of all three files."
            ),
        )

    @admin.display(description=_("Status"))
    def status_badge(self, obj):
        colors = {
            CertificationStatusChoices.DRAFT: "#a17f1a",
            CertificationStatusChoices.CERTIFIED: "#1a7f37",
            CertificationStatusChoices.REVOKED: "#a11a1a",
        }
        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.certification_status, "#444"),
            obj.get_certification_status_display(),
        )

    @admin.display(description=_("Expired"), boolean=True)
    def expired_badge(self, obj):
        return bool(obj.is_expired)

    @admin.display(description=_("Views"))
    def views_total(self, obj):
        return getattr(obj, "_views_total", 0)

    @admin.display(description=_("Unique"))
    def views_unique(self, obj):
        return getattr(obj, "_views_unique", 0)

    @admin.display(description=_("Files"))
    def files_column(self, obj):
        links = []

        # Se enlaza la vista controlada, no MEDIA_URL: el enlace directo no
        # comprobaba permisos de ningun tipo.
        for field_name, kind, label in (
            ("source_file", "source", _("Original")),
            ("document_file", "certified", _("Certified")),
            ("public_copy_file", "public", _("Public copy")),
        ):
            file_field = getattr(obj, field_name, None)
            if file_field:
                links.append(
                    format_html(
                        '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                        reverse(
                            "certificates:document_file",
                            args=[obj.pk, kind],
                        ),
                        label,
                    )
                )

        if not links:
            return "-"

        return format_html(" · ".join("{}" for _link in links), *links)

    @admin.display(description=_("Certification record"))
    def record_link(self, obj):
        if not obj.is_certified:
            return "-"

        url = reverse("certificates:certification_record", args=[obj.pk])

        return format_html(
            '<a href="{}">{}</a>',
            url,
            _("Download the signed JSON record (for auditors)"),
        )

    @admin.display(description=_("Hash"))
    def hash_short(self, obj):
        h = obj.document_hash or ""
        return (h[:10] + "\u2026") if len(h) > 12 else (h or "-")


# -----------------------
# View Log
# -----------------------
@admin.register(CertificateViewLogModel)
class CertificateViewLogModelAdmin(GeneralAdminModel):
    list_per_page = 100
    empty_value_display = "-"

    list_display = (
        "viewed_at",
        "target_type",
        "target_admin_link",
        "viewer_display",
        "ip_address",
    )
    list_filter = (
        ("viewed_at", admin.DateFieldListFilter),
        "certificate_user__certificate_type",
        "document_verification__certificate_type",
    )
    date_hierarchy = "viewed_at"
    ordering = ("-viewed_at",)

    search_fields = (
        "ip_address",
        "anonymous_email",
        "user__email",
        "certificate_user__name",
        "certificate_user__last_name",
        "document_verification__document_title",
    )

    autocomplete_fields = ("certificate_user", "document_verification", "user")
    list_select_related = ("certificate_user", "document_verification", "user")

    readonly_fields = (
        "certificate_user",
        "document_verification",
        "user",
        "anonymous_email",
        "ip_address",
        "user_agent",
        "viewed_at",
        "created",
        "updated",
        "target_type",
        "target_admin_link",
        "viewer_display",
    )

    fieldsets = (
        (_("Target"), {"fields": ("certificate_user",
         "document_verification", "target_type", "target_admin_link")}),
        (_("Viewer"), {"fields": ("user", "anonymous_email",
         "viewer_display", "ip_address")}),
        (_("Technical"), {"fields": ("user_agent",),
         "classes": ("collapse",)}),
        (_("Audit"), {"fields": ("viewed_at", "created",
         "updated"), "classes": ("collapse",)}),
    )

    @admin.display(description=_("Type"))
    def target_type(self, obj):
        return _("User Certificate") if obj.certificate_user_id else _("Document Certificate")

    @admin.display(description=_("Target"))
    def target_admin_link(self, obj):
        if obj.certificate_user_id:
            url = reverse("admin:certificates_userverificationmodel_change", args=[
                          obj.certificate_user_id])
            label = f"{obj.certificate_user.name} {obj.certificate_user.last_name}".strip()
            return format_html('<a href="{}">{}</a>', url, label or "-")
        if obj.document_verification_id:
            url = reverse("admin:certificates_documentverificationmodel_change", args=[
                          obj.document_verification_id])
            return format_html('<a href="{}">{}</a>', url, obj.document_verification.document_title)
        return "-"

    @admin.display(description=_("Viewer"))
    def viewer_display(self, obj):
        return obj.user or obj.anonymous_email or "-"


class AegisSummaryDocumentInline(admin.TabularInline):
    model = AegisSummaryDocumentModel
    extra = 0
    fields = ('code', 'document', 'document_type_label', 'default_order')
    autocomplete_fields = ('document',)


@admin.action(description=_('Seal: compute the master hash of the box'))
def action_seal_summaries(modeladmin, request, queryset):
    from apps.project.specific.internal.code_gen.services.master import (
        MasterHashError, seal_summary)

    sealed = 0

    for summary in queryset:
        try:
            digest = seal_summary(summary)
        except MasterHashError as error:
            messages.error(
                request,
                _('%(title)s: %(error)s') % {
                    'title': summary.title, 'error': error,
                }
            )
            continue

        sealed += 1
        messages.info(
            request,
            _('%(title)s sealed: %(hash)s') % {
                'title': summary.title, 'hash': digest,
            }
        )

    if sealed:
        messages.success(
            request, _('%(count)s summary/summaries sealed.') % {'count': sealed}
        )


@admin.action(description=_('Anchor with the timestamp authority (RFC 3161)'))
def action_anchor_summaries(modeladmin, request, queryset):
    from apps.project.specific.internal.code_gen.services.anchoring import \
        anchor_with_tsa
    from apps.project.specific.internal.code_gen.services.tsa import TSAError

    anchored = 0

    for summary in queryset:
        try:
            anchor = anchor_with_tsa(summary)
        except TSAError as error:
            messages.error(
                request,
                _('%(title)s: %(error)s') % {
                    'title': summary.title, 'error': error,
                }
            )
            continue

        anchored += 1
        messages.info(
            request,
            _('%(title)s anchored at %(time)s') % {
                'title': summary.title, 'time': anchor.stamped_at,
            }
        )

    if anchored:
        messages.success(
            request, _('%(count)s summary/summaries anchored.') % {'count': anchored}
        )


@admin.action(description=_('Anchor in Bitcoin (OpenTimestamps, free)'))
def action_anchor_ots(modeladmin, request, queryset):
    from apps.project.specific.internal.code_gen.services.anchoring import         anchor_with_ots
    from apps.project.specific.internal.code_gen.services.ots import OTSError

    anchored = 0

    for summary in queryset:
        try:
            anchor_with_ots(summary)
        except OTSError as error:
            messages.error(
                request,
                _('%(title)s: %(error)s') % {
                    'title': summary.title, 'error': error,
                }
            )
            continue

        anchored += 1

    if anchored:
        messages.success(
            request,
            _('%(count)s summary/summaries submitted to Bitcoin. The proof '
              'takes a few hours to mature; the anchor page updates on its '
              'own (manage.py upgrade_ots_anchors).')
            % {'count': anchored}
        )


@admin.register(AegisSummaryModel)
class AegisSummaryModelAdmin(GeneralAdminModel):
    inlines = [AegisSummaryDocumentInline]

    # El desplegable de activos listaba el catalogo entero sin buscador.
    autocomplete_fields = ('asset',)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        """
        Manda el "anadir" del activo a donde de verdad se anade un activo.

        ``AssetModel`` no se crea suelto: ``AssetsNamesModelAdmin`` lo lleva
        como inline obligatorio, asi que el alta empieza siempre por el nombre.
        El "+" que Django pone junto al desplegable apuntaba al alta directa de
        ``AssetModel``, que deja un activo sin nombre. Se quita ese atajo y se
        indica el camino bueno.

        Tiene que ser ``formfield_for_dbfield`` y no ``formfield_for_foreignkey``:
        el ``RelatedFieldWidgetWrapper`` que pinta esos iconos lo anade Django
        **despues** de llamar a la segunda, con sus propios flags, asi que
        tocarlos alli no surte ningun efecto.
        """
        formfield = super().formfield_for_dbfield(db_field, request, **kwargs)

        if db_field.name == 'asset' and formfield is not None:
            widget = getattr(formfield, 'widget', None)

            if hasattr(widget, 'can_add_related'):
                widget.can_add_related = False
                widget.can_change_related = False
                widget.can_delete_related = False

            formfield.help_text = format_html(
                '{} <a href="{}" target="_blank" rel="noopener">{}</a>',
                _('The asset this box of certificates belongs to.'),
                reverse('admin:assets_assetsnamesmodel_add'),
                _('Add a new asset (starts with its name).'),
            )

        return formfield
    actions = [action_seal_summaries, action_anchor_summaries,
               action_anchor_ots]

    list_display = (
        'uuid_prefix', 'title', 'status', 'public_code',
        'member_count', 'master_hash_short', 'anchor_state',
    )
    list_display_links = ('uuid_prefix', 'title')
    list_filter = ('status',)
    search_fields = ('title', 'public_code', 'master_hash', 'asset_label')
    ordering = ('-created',)

    readonly_fields = (
        'id', 'uuid_prefix', 'public_code', 'status',
        'master_hash', 'canonical_payload', 'sealed_at',
        'summary_document', 'anchor_state', 'created', 'updated',
        'seal_help',
    )

    fieldsets = (
        (_('Identificacion'), {
            'fields': ('uuid_prefix', 'public_code', 'title',
                       'asset', 'asset_label', 'issued_at')
        }),
        (_('Sello'), {
            'fields': ('seal_help', 'status', 'master_hash',
                       'sealed_at', 'anchor_state', 'canonical_payload')
        }),
        (_('Documento resumen'), {
            'fields': ('summary_document',),
        }),
        (_('Auditoria'), {
            'fields': ('created', 'updated'), 'classes': ('collapse',)
        }),
    )

    @admin.display(description=_('How it works'))
    def seal_help(self, obj=None):
        return format_html(
            '<div style="max-width:60em">{}</div>',
            _('1) Add the member documents below (all must be certified). '
              '2) Run "Seal" to compute the master hash. 3) Issue the summary '
              'document, which carries that hash. 4) Run "Anchor" to have a '
              'timestamp authority attest the date. The master hash never '
              'covers the summary itself: it cannot, it does not exist yet '
              'when the hash is computed.')
        )

    @admin.display(description=_('Members'))
    def member_count(self, obj):
        return obj.members.count()

    @admin.display(description=_('Master hash'))
    def master_hash_short(self, obj):
        value = obj.master_hash or ''
        return (value[:12] + '…') if value else '-'

    @admin.display(description=_('Anchor'))
    def anchor_state(self, obj):
        total = obj.anchors.count()

        if not total:
            return _('Not anchored')

        confirmed = obj.anchors.filter(status='CONFIRMED').count()
        return f'{confirmed}/{total}'
