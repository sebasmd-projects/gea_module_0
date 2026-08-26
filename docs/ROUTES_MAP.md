# Mapa de Rutas — GEA (gea_module_0)

> Generado a partir de `app_core/urls.py` y los `urls.py` de cada app.
> Dominio de producción: `https://geausa.propensionesabogados.com`

## 1. Cómo se arma el URLconf raíz

`app_core/urls.py` construye `urlpatterns` en **orden explícito** y con carga tolerante a fallos:

```python
urlpatterns = [
    *two_factor_urls,   # 1. django-two-factor-auth
    *admin_urls,        # 2. admin en settings.ADMIN_URL (env DJANGO_ADMIN_URL)
    *apps_urls,         # 3. apps propias, en el orden de settings.ALL_CUSTOM_APPS
    *third_party_urls,  # 4. rosetta / ckeditor5 / select2 / impersonate
]
```

- `include_if_present(dotted_path)` importa `<app>.urls` y, si falla, **loguea y omite la app** en producción (en `DEBUG=True` re-lanza la excepción). Esto permite despliegues parciales sin romper el arranque.
- El orden de las apps lo fija `settings.ALL_CUSTOM_APPS`:
  1. `documents.certificates`
  2. `documents.video_masonry`
  3. `common.core`
  4. `common.utils`  ← **incluye una regex catch-all** (ver §7)
  5. `assets_management.assets`
  6. `assets_management.assets_location`
  7. `assets_management.buyers`
  8. `common.account`
  9. `common.notifications` (vacío)
  10. `common.users` (vacío)
- Handlers de error exportados: `handler400/401/403/404/500/503/504` → `apps.common.utils.views`.
- En `DEBUG=True` se sirven `STATIC_URL` y `MEDIA_URL` desde el propio Django.

---

## 2. Autenticación y 2FA (namespace `two_factor`)

Provisto por `django-two-factor-auth` (`two_factor.urls`).

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `account/login/` | `two_factor:login` | `LoginView` | Público (`settings.LOGIN_URL`) |
| `account/two_factor/setup/` | `two_factor:setup` | `SetupView` | Autenticado |
| `account/two_factor/qrcode/` | `two_factor:qr` | `QRGeneratorView` | Autenticado |
| `account/two_factor/setup/complete/` | `two_factor:setup_complete` | `SetupCompleteView` | Autenticado |
| `account/two_factor/backup/tokens/` | `two_factor:backup_tokens` | `BackupTokensView` | Autenticado |
| `account/two_factor/` | `two_factor:profile` | `ProfileView` | Autenticado |
| `account/two_factor/disable/` | `two_factor:disable` | `DisableView` | Autenticado |

Plantillas sobreescritas en `templates/two_factor/`.
`RedirectAuthenticatedUserMiddleware` redirige a `core:index` si un usuario ya autenticado visita `two_factor:login`.

---

## 3. Administración

| Ruta | Nombre | Notas |
|---|---|---|
| `<DJANGO_ADMIN_URL>` | `admin:*` | Prefijo configurable por variable de entorno (no es `/admin/` fijo) |
| `rosetta/` | `rosetta:*` | Traducción de `.po` desde el panel (`ROSETTA_SHOW_AT_ADMIN_PANEL = True`) |
| `ckeditor5/` | — | Uploads del editor CKEditor 5 |
| `select2/` | — | Endpoints AJAX de `django-select2` |
| `impersonate/` | `impersonate:*` | Suplantación de usuario para soporte |

---

## 4. Sitio público — `apps.common.core` (`app_name = 'core'`)

| Ruta | Nombre | Vista | Plantilla | Acceso |
|---|---|---|---|---|
| `/` | `core:index` | `IndexTemplateView` | `core/index.html` | Público |
| `health/` | `core:health_check` | `HealthCheckView` | JSON | Público |
| `privacy/` | `core:privacy` | `PrivacyTemplateView` | `core/tyc/privacy.html` | Público |
| `terms/` | `core:terms` | `TermsTemplateView` | `core/tyc/terms.html` | Público |

`core:index` es también `settings.LOGIN_REDIRECT_URL`.

`health/` devuelve JSON con chequeos de **base de datos**, **cache** y **backend de email**; responde `200` si todo OK, `503` si algo falla, `500` ante excepción no controlada. Es el endpoint que golpea el cron de *warm-up* cada 3 minutos.

> Existe `PortfolioTemplateView` (`core/portfolio.html`) definida en `views.py` pero **no enrutada** y sin plantilla en el repo.

---

## 5. Utilidades — `apps.common.utils` (`app_name = 'utils'`)

| Ruta | Nombre | Vista | Notas |
|---|---|---|---|
| `robots.txt` | — | función `robots_txt` | `Disallow: /` para todos, incluidos GPTBot, ClaudeBot, PerplexityBot, Meta-ExternalAgent, Applebot |
| `set_language/` | `utils:set_language` | `set_language` | Cambio de idioma es/en |
| regex catch-all | `attack_path` | `HttpRequestAttackView` | Ver §7 |

Solo con `DEBUG=True` se añaden rutas de prueba de páginas de error:
`__test__/400/`, `__test__/401/`, `__test__/403/`, `__test__/404/`, `__test__/500/`, `__test__/503/`, `__test__/504/`.

---

## 6. Certificados y verificación documental — `documents.certificates` (`app_name = 'certificates'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `certificates/` | `certificates:certificates_landing` | `CertificatesLandingTemplateView` | Público |
| `verify/ipcon/` | `certificates:input_employee_verification_ipcon` | `InputEmployeeIPCONFormView` | Público |
| `verify/ipcon/<uuid:pk>/` | `certificates:detail_employee_verification_ipcon` | `EmployeeIPCONDetailView` | Público (registra la visita) |
| `verify/aegis/asset/certification/` | `certificates:input_document_verification_aegis` | `InputDocumentVerificationFormView` | Público **+ OTP por email** |
| `verify/aegis/asset/certification/<uuid:pk>/` | `certificates:detail_document_verification_aegis` | `DocumentVerificationDetailView` | Requiere sesión OTP válida |
| `verify/aegis/asset/certification/<uuid:pk>/record/` | `certificates:certification_record` | `CertificationRecordView` | Requiere sesión OTP válida |
| `verify/aegis/certification/key/` | `certificates:certification_public_key` | `certification_public_key` | Público |

Las rutas `aegis` están protegidas por `OTPSessionMixin` / `OTPProtectedDocumentMixin` (código de un solo uso enviado por email, TTL 10 min, límites de reenvío y de intentos).

La vista de entrada `input_document_verification_aegis` acepta **dos formas de
verificar**, ambas por POST a la misma URL:

- por identificador (`identifier` + `certificate_type`): código público de 12
  caracteres, prefijo del UUID (8), UUID completo o la propia URL del QR;
- por archivo (`verify_by_file=1` + `document_file`, `multipart/form-data`):
  solo se ofrece una vez superado el OTP. El archivo no se almacena.


---

## 7. Ruta trampa anti-escaneo (⚠️ el orden importa)

`apps/common/utils/attack_patterns.py` registra:

```python
pattern = r'^.*(?:' + '|'.join(settings.COMMON_ATTACK_TERMS) + r').*$'
re_path(pattern, HttpRequestAttackView.as_view(), name='attack_path')
```

- `COMMON_ATTACK_TERMS` viene de la variable de entorno del mismo nombre (lista separada por comas).
- Es un **catch-all** que matchea el término en *cualquier* posición del path.
- **Está registrado en la posición 4 del URLconf** (dentro de `utils`), es decir **antes** de `assets`, `assets_location`, `buyers` y `account`.
- Consecuencia: si algún término de ataque aparece como subcadena de una ruta legítima de esas apps, la petición se desvía a `HttpRequestAttackView` y la IP puede terminar bloqueada. Al añadir términos nuevos hay que contrastarlos contra las rutas de §8–§11.

---

## 8. Activos — `assets_management.assets` (`app_name = 'assets'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `holder/assets/` | `assets:holder_index` | `HolderTemplateview` | `HolderRequiredMixin` |
| `buyer/asset/add/` | `assets:create` | `AssetNameWithInlineAssetCreateView` | `BuyerRequiredMixin` |
| `buyer/asset/add/category/` | `assets:add_category` | `AssetAddNewCategory` | `BuyerRequiredMixin` |
| `client/help/GEA/` | `assets:help_gea` | `WhatsAppRedirectView` | Autenticado (usa `request.user.username`) |

`assets:help_gea` redirige a `https://wa.me/573012283818` con mensaje prellenado.

---

## 9. Ubicaciones de activos — `assets_management.assets_location` (`app_name = 'assets_location'`)

Todas requieren `HolderRequiredMixin` (definido en `assets_location/views.py`).

| Ruta | Nombre | Vista |
|---|---|---|
| `holder/asset/add/location/` | `assets_location:add_location` | `LocationCreateView` |
| `holder/asset/update/location/<uuid:pk>/` | `assets_location:update_location` | `LocationUpdateView` |
| `holder/asset/delete/location/<uuid:pk>/` | `assets_location:delete_location` | `LocationReferenceDeleteView` |
| `holder/asset/add/` | `assets_location:add_asset_location` | `AssetLocationCreateView` |
| `holder/asset/update/<uuid:pk>/` | `assets_location:update_asset_location` | `AssetUpdateView` |
| `holder/asset/delete/<uuid:pk>/` | `assets_location:delete_asset_location` | `AssetLocationDeleteView` |

---

## 10. Órdenes de compra y flujo comercial — `assets_management.buyers` (`app_name = 'buyers'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `buyer/asset/purchase-orders/` | `buyers:buyer_index` | `PurchaseOrdersView` | `BuyerRequiredMixin` |
| `buyer/asset/purchase-order/add/` | `buyers:buyer_create` | `PurchaseOrderCreateView` | `BuyerRequiredMixin` |
| `buyer/asset/purchase-order/<uuid:id>/detail/` | `buyers:offer_details` | `OfferDetailView` | `LoginRequiredMixin` |
| `buyer/asset/purchase-order/<uuid:pk>/update/` | `buyers:offer_update` | `OfferUpdateView` | `BuyerRequiredMixin` |
| `buyer/asset/purchase-order/<uuid:id>/delete/` | `buyers:offer_delete` | `OfferSoftDeleteView` | `BuyerRequiredMixin` (borrado lógico) |
| `po/<uuid:id>/wizard/` | `buyers:offer_wizard_page` | `OfferApprovalWizardPageView` | Permiso `buyers.can_see_wizard_page` |
| `po/<uuid:id>/wizard/partial/` | `buyers:offer_wizard_partial` | `OfferApprovalWizardPartialView` | Permiso `buyers.can_see_wizard_page` |
| `po/<uuid:id>/wizard/action/` | `buyers:offer_wizard_action` | `OfferApprovalWizardActionView` | **POST only** + permiso por paso |
| `profitability/` | `buyers:profitability_view` | `ProfitabilityTemplateView` | `BuyerRequiredMixin` |
| `buyer/inventory/` | `buyers:inventory_view` | `InventoryTemplateView` | `BuyerRequiredMixin` |
| `buyer/hermes/form/` | `buyers:hermes_form` | `AssetCreditFormTemplateView` | `BuyerRequiredMixin` (formulario JotForm embebido) |
| `buyer/hermes/form/success/` | `buyers:hermes_form_success` | `AssetCreditFormSuccessTemplateView` | `BuyerRequiredMixin` |
| `buyer/orion/scheduler/` | `buyers:orion_scheduler` | `OrionSchedulerView` | `OnlySpecificUserMixin` (**allowlist de usernames**: `jose.henry`, `kalichemorales`, + staff/superuser) |

### `po/<uuid:id>/wizard/action/` — sub-acciones por campo `step` (POST)

Devuelve JSON `{ok, html, timeline_html}` o `{ok: false, errors: [...]}`.

| `step` | Permiso requerido | Efecto |
|---|---|---|
| `REVIEW` | `can_review_offer` | Marca revisada + `reviewed_by` |
| `APPROVE` | `can_approve_offer` | Marca aprobada + `approved_by` |
| `SO_ADD_RECIPIENTS` | `can_send_service_order` | Añade destinatarios de orden de servicio |
| `SO_REMOVE_RECIPIENTS` | `can_send_service_order` | Elimina destinatarios |
| `SO_NOTIFY` | `can_send_service_order` | Envía email BCC con **PDF de orden de servicio** + logo inline; sella `service_order_sent_at` |
| `SO_SEND` | `can_send_service_order` | `mark_service_order_sent()` |
| `PAY_CREATE` | `can_create_payment_order` | `mark_payment_order_created()` |
| `PAY_SEND` | `can_send_payment_order` | `mark_payment_order_sent()` |
| `POSSESSION` | `can_set_asset_possession` | `mark_asset_in_possession()` |
| `ASSET_SEND` | `can_send_asset` | `mark_asset_sent()` |
| `PROFIT_CREATE` | `can_set_profitability` | `mark_profitability_created()` |
| `RRF_PAY` | `recovery_repatriation_foundation_paid` | Marca pago Recovery Repatriation Foundation |
| `AMPRO_PAY` | `pay_master_service_paid` | Marca pago PAY MASTER |
| `PROP_PAY` | `propensiones_paid` | Marca pago Propensiones |
| `PROFIT_PAY` | `can_approve_pay_profitability` | `mark_profitability_paid()` (exige los 3 subpagos) |

`_require_perm()` deja pasar siempre a `is_superuser` e `is_staff`.

---

## 11. Cuentas — `common.account` (`app_name = 'account'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `account/register/` | `account:register` | `GeaUserRegisterWizardView` (`SessionWizardView`) | Solo anónimos |
| `account/logout/` | `account:logout` | `UserLogoutView` | Autenticado |
| `account/change/password/` | `account:change_password` | `ChangePasswordFormView` | Autenticado |
| `account/forgot/password/` | `account:forgot_password` | `ForgotPasswordFormView` | Público (2 pasos) |

Pasos del wizard de registro: `user` → `security` → `contact` → `code`.
El paso `contact` cambia de formulario según `user_type` (`BuyerContactForm` vs `SupplierContactForm`) y el paso `code` valida el **código diario GEA** (`GeaDailyUniqueCode`).

---

## 12. Galería multimedia — `documents.video_masonry` (`app_name = 'video_masonry'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `gallery/masonry/` | `video_masonry:gallery` | `MediaGalleryView` | `BuyerRequiredMixin` (paginación de 15) |
| `gallery/masonry/download/<int:pk>/` | `video_masonry:download` | `MediaAssetDownloadView` | `BuyerRequiredMixin`, cuenta descarga |
| `gallery/masonry/track/` | `video_masonry:track` | `MediaAssetTrackView` | `BuyerRequiredMixin`, **POST only**, cuenta visualización |

---

## 12-bis. Generador de códigos y certificación — `internal.code_gen` (`app_name = 'code_gen'`)

| Ruta | Nombre | Vista | Acceso |
|---|---|---|---|
| `generate/code/` | `code_gen:code_generate` | `CodeGeneratorView` | `is_staff` o `is_superuser` |

- La app va **la última** en `ALL_CUSTOM_APPS`, por lo que sus rutas quedan
  *después* del catch-all anti-escaneo de §7: cualquier ruta nueva de esta app
  debe evitar los términos de `COMMON_ATTACK_TERMS`.
- La antigua ruta `code_gen:dynamic_qr` (`qr/generate/<path:text>/`) se eliminó:
  generaba un QR con texto arbitrario tomado del path, sin autenticación, y su
  comodín `<path:text>` chocaba con el catch-all.

---

## 13. Apps sin rutas

`apps.project.common.notifications` y `apps.project.common.users` exponen `urlpatterns = []`.
`apps.common.utils.api` y `apps.project.common.account.api` también están vacíos (andamiaje para una futura API).

---

## 14. Resumen de nombres de URL por namespace

```
two_factor:  login, setup, qr, setup_complete, backup_tokens, profile, disable
core:        index, health_check, privacy, terms
utils:       set_language, attack_path
code_gen:    code_generate
certificates: certificates_landing,
              input_employee_verification_ipcon, detail_employee_verification_ipcon,
              input_document_verification_aegis, detail_document_verification_aegis
assets:      holder_index, create, add_category, help_gea
assets_location: add_location, update_location, delete_location,
                 add_asset_location, update_asset_location, delete_asset_location
buyers:      buyer_index, buyer_create, offer_details, offer_update, offer_delete,
             offer_wizard_page, offer_wizard_partial, offer_wizard_action,
             profitability_view, inventory_view,
             hermes_form, hermes_form_success, orion_scheduler
account:     register, logout, change_password, forgot_password
video_masonry: gallery, download, track
```
