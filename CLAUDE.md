# CLAUDE.md — Contexto del proyecto GEA para asistentes de IA

Ficha técnica del repositorio `gea_module_0`. Léela antes de tocar código.
Documentos complementarios:

- [`docs/ROUTES_MAP.md`](docs/ROUTES_MAP.md) — todas las URLs, namespaces, vistas y permisos.
- [`docs/FEATURES_MAP.md`](docs/FEATURES_MAP.md) — funcionalidades por dominio, modelos y reglas de negocio.
- [`docs/NORMATIVA.md`](docs/NORMATIVA.md) — qué exigen los reguladores a la certificación, por qué no se adopta W3C VC y qué falta en su lugar.
- [`docs/ANCLAJE.md`](docs/ANCLAJE.md) — el anclaje temporal explicado de punta a punta: los dos tiempos, quién madura las pruebas, dónde se mira el estado y qué significa cada uno.

Si lo que necesitas es orientarte —qué módulo llama a cuál y por dónde entra una petición—
empieza por [§4-bis, Mapa de arquitectura](#4-bis-mapa-de-arquitectura-codebase-map).

---

## 1. Qué es este proyecto

**GEA** es la plataforma web de **Propensiones Abogados** para la gestión de *activos históricos*
(bonos alemanes, oro, billetes de alta denominación y similares).

Cubre cuatro procesos de negocio:

1. **Tenedores** registran activos y sus ubicaciones físicas.
2. **Compradores** crean órdenes de compra sobre esos activos.
3. Un **flujo de aprobación de 12 etapas** lleva la orden desde la revisión hasta la liquidación de rentabilidad, con permisos granulares por etapa y generación de PDFs.
4. Un **portal público de verificación de certificados** (personas y documentos) con QR, código de barras y protección OTP.

Producción: `https://geausa.propensionesabogados.com`
Idiomas: español (contenido primario) e inglés.

---

## 2. Stack

| Capa | Tecnología |
|---|---|
| Runtime | Python **3.11** |
| Framework | **Django 4.2 LTS** (`>=4.2,<5.0`) |
| Gestor de paquetes | **uv** (`uv.lock`, `pyproject.toml`); `requirements.txt` se exporta desde uv |
| Base de datos | MySQL o PostgreSQL — se elige por la variable `DB_ENGINE`; charset `utf8mb4` |
| Frontend | Plantillas Django + **Bootstrap 5.2.3** (CDN), AJAX con HTML renderizado en servidor. Sin SPA, sin build de JS |
| Estáticos | `django-compressor`, `public/staticfiles/` (~45 MB), imágenes en WebP |
| PDF | ReportLab (capa de estampado), **pypdf** (fusión, lectura y marca de agua), `python-barcode` (Code128), `qrcode` |
| IA | OpenAI (`gpt-4o-mini` para traducción es↔en, `gpt-4o-transcribe` para audio) |

**Terceros clave**: `django-two-factor-auth` + `django-otp` (2FA), `django-axes` (fuerza bruta),
`django-auditlog` (auditoría), `django-encrypted-model-fields` (PII cifrada), `django-import-export`,
`django-crontab`, `django-select2`, `django-formtools` (wizards), `rosetta`, `impersonate`,
`django-parler` (instalado, apenas usado), `argon2-cffi`.

**No hay Django REST Framework.** Los directorios `api/` existen pero están vacíos. No asumas endpoints REST.

---

## 3. Comandos

Entorno con `uv` (hay un `.venv` en la raíz del repo principal):

```bash
uv sync
```

```bash
uv run python manage.py runserver
```

`runserver` está sobrescrito: sirve en `0.0.0.0:8000` e imprime la IPv4 de LAN.

```bash
uv run python manage.py migrate
```

```bash
uv run python manage.py db_backup -o backups/
```

```bash
uv run python manage.py generate_gea_code
```

```bash
uv run python manage.py clear_cache
```

```bash
uv run python manage.py check_attack_terms
```

```bash
uv run python manage.py test --settings=app_core.settings_test
```

Volcado UTF-8 completo de la base de datos:

```bash
python -Xutf8 manage.py dumpdata --natural-foreign --natural-primary --exclude auth.permission --exclude contenttypes --indent 2 --output db_data.json
```

Añadir dependencias y reexportar:

```bash
uv add <paquete>
```

```bash
uv export --format=requirements-txt > requirements.txt
```

⚠️ **Ese `export` no es opcional, y olvidarlo ya rompió producción.** Hay dos
ficheros de dependencias y cada uno manda en un sitio distinto:

| Fichero | Quién lo usa | Con qué |
|---|---|---|
| `pyproject.toml` + `uv.lock` | Solo **local** | `uv` |
| `requirements.txt` | **Producción** (cPanel) | `pip` — ahí no hay uv |

El puente entre los dos es ese `uv export`, que es manual. `uv add` **no**
actualiza `requirements.txt`: si no lo exportas y commiteas, la dependencia
nunca llega al servidor y el fallo aparece en tiempo de ejecución, lejos de la
causa. Pasó con `opentimestamps`, declarada el 29 de agosto y exportada el 30:
en medio, el anclaje en la cadena de bloques fallaba en producción.

Para no repetirlo, antes de desplegar:

```bash
uv run python manage.py check_requirements
```

También está en la consola de operaciones como «Dependencias».

⚠️ **No ejecutes `delete_migrations` ni `rename_migrations`** salvo petición explícita: borran o renombran ficheros de migración de todo el proyecto (`skip_apps.txt` está vacío, así que no protegen nada).

---

## 4. Estructura de directorios

```
app_core/                    # settings, urls, wsgi/asgi, signature, locale
apps/
  common/
    core/                    # landing pública, health check, TyC
    utils/                   # TimeStampedModel, middleware, cron, comandos, helpers
  project/
    common/
      account/               # registro (wizard), login/logout, contraseñas
      notifications/         # vacía (reservada)
      users/                 # UserModel + geografía + PII
    specific/
      assets_management/
        assets/              # catálogo de activos
        assets_location/     # ubicaciones e inventario
        buyers/              # órdenes de compra + flujo + PDFs
      documents/
        certificates/        # verificación pública de certificados
        video_masonry/       # galería multimedia
      internal/
        code_gen/            # generador de códigos + motor de certificación de PDF
        ops/                 # consola de operaciones (comandos en lista blanca, dentro del admin)
templates/                   # plantillas globales (dashboard, account, two_factor, email, admin/ops)
public/staticfiles/          # css, js, imágenes WebP, vídeo
docs/                        # mapas de rutas y funcionalidades
```

Las apps se declaran en `settings.py` agrupadas (`COMMON_APPS`, `PROJECT_COMMON_APPS`,
`PROJECT_ASSETS_MANAGEMENT_APPS`, `PROJECT_DOCUMENTS_APPS`, `PROJECT_INTERNAL_APPS`)
y se concatenan en `ALL_CUSTOM_APPS`. **Ese orden determina el orden del URLconf y de `LOCALE_PATHS`.**

Para crear una app nueva usa el comando propio, que ya fija el `name` con ruta completa, crea `urls.py` y `locale/`:

```bash
uv run python manage.py start_app apps/project/specific/<grupo>/<nombre>
```

Después hay que **añadirla a mano** al grupo correspondiente en `settings.py`.

---

## 4-bis. Mapa de arquitectura (codebase map)

La estructura de carpetas dice dónde están los ficheros; esta sección dice **quién llama a quién**.
Úsala para localizar el punto de entrada correcto antes de abrir nada.

### A. Recorrido de una petición

```
navegador
  │
  ├─ MIDDLEWARE (settings.py, en orden)
  │    security → session → locale → cors → common → csrf → auth
  │    → auditlog → otp → messages → clickjacking
  │    → RedirectWWWMiddleware              (apps/common/utils/middleware/)
  │    → RedirectAuthenticatedUserMiddleware   idem
  │    → BlockBadBotsMiddleware                idem
  │    → DetectSuspiciousRequestMiddleware  ← consulta IPBlockedModel / WhiteListedIPModel
  │    → axes → impersonate
  │
  ├─ URLconf raíz (app_core/urls.py)
  │    1. two_factor.urls        2. admin en ADMIN_URL
  │    3. apps propias en el orden de ALL_CUSTOM_APPS  ← incluye la regex catch-all de `utils`
  │    4. rosetta / ckeditor5 / select2 / impersonate
  │    `include_if_present()` omite (y loguea) una app cuyo urls.py no importe; en DEBUG re-lanza.
  │
  ├─ CBV + mixin de acceso   (nunca decoradores; ver §5)
  │    BuyerRequiredMixin · HolderRequiredMixin · OnlySpecificUserMixin
  │    InternalToolAccessMixin · OTPSessionMixin / OTPProtectedDocumentMixin
  │    OfferMutationMixin  (buyers/access.py, autorización por objeto + etapa)
  │
  ├─ modelo (reglas de negocio en el propio modelo) o servicio (code_gen/services/)
  │    ATOMIC_REQUESTS = True → toda la vista va dentro de una transacción
  │
  └─ respuesta: plantilla Django, o JsonResponse con HTML pre-renderizado (AJAX)
```

### B. Grafo de dependencias entre apps

Las flechas van de quien importa a quien es importado.

```
                       apps.common.utils            (base: TimeStampedModel,
                        ▲   ▲   ▲   ▲   ▲            GeneralAdminModel, sha256_hex,
                        │   │   │   │   │            IPBlocked, middleware, cron)
      ┌─────────────────┘   │   │   │   └──────────────────┐
      │                     │   │   └────────┐             │
   users ◄──── account   assets ◄─ assets_location      video_masonry
      ▲  ▲                  ▲   ▲       ▲                   │
      │  │                  │   └───┬───┘                   │
      │  └──────────────── buyers ──┘                       │
      │                     ▲ (BuyerRequiredMixin) ─────────┘
      │                     │
  certificates ◄══════════► code_gen ────► assets (import diferido, sólo lectura)
      ▲                                 └─► certificates (imports dentro de función)
      │
     ops ──► users (sólo en tests) · utils
```

Reglas que se deducen del grafo — respétalas al añadir código:

- **`apps.common.utils` no importa nunca hacia arriba.** Es la base de todo (excepto en `utils/tests.py`,
  que sí toca `users`). Si necesitas algo de negocio dentro de `utils`, va en el sitio equivocado.
- **`users` es hoja de dominio**: lo importa medio proyecto y él sólo importa `utils`.
- **`assets` importa desde `assets_location` y `buyers`** (mixins y modelos, en `assets/views.py`).
  Es acoplamiento cruzado real y no accidental: mover un mixin rompe la otra app.
- **`certificates` ↔ `code_gen` es bidireccional a propósito.** `certificates` **posee los modelos**
  (`DocumentVerificationModel`, `AegisSummaryModel`) y `code_gen` **posee los algoritmos**
  (`services/`). Para evitar el import circular, cada lado importa al otro **dentro de la función**,
  nunca en el encabezado del módulo. Mantén ese patrón.
- **`ops` es terminal**: nadie lo importa; su superficie es el admin.
- **`notifications` está vacía** (modelos, vistas y `urls.py` sin contenido). No la uses como ejemplo.

### C. Índice: quiero tocar X → abre Y

| Si buscas… | Fichero |
|---|---|
| Orden del URLconf, handlers de error | `app_core/urls.py` |
| Apps instaladas, middleware, crons, i18n | `app_core/settings.py` (`ALL_CUSTOM_APPS`, `CRONJOBS`) |
| Pruebas sobre SQLite en memoria | `app_core/settings_test.py` |
| Modelo base, códigos diarios, bloqueo de IP | `apps/common/utils/models.py` |
| Trampa anti-escaneo y su comprobador | `apps/common/utils/attack_patterns.py` + `management/commands/check_attack_terms.py` |
| Tareas programadas | `apps/common/utils/cron.py` |
| Filtros y tags de plantilla | `apps/common/utils/templatetags/custom_filters.py` |
| Landing pública y `health/` | `apps/common/core/views.py` |
| Usuario, PII cifrada, geografía | `apps/project/common/users/models.py` |
| Registro por wizard, recuperar contraseña | `apps/project/common/account/views.py` + `forms/` |
| Catálogo de activos y traducción automática | `assets/models.py`, `assets/signals.py` |
| Ubicaciones e inventario por ubicación | `assets_location/models.py`, `views.py` |
| **Flujo de 12 etapas de una orden** | `buyers/models.py` (`status_code`, `mark_*`, `CheckConstraint`) |
| **Quién puede ver/editar una orden** | `buyers/access.py` — no está repartido por las vistas |
| Wizard de aprobación (UI + acciones) | `buyers/views.py` (`OfferApprovalWizard*`) + `templates/dashboard/pages/buyers/wizard/` |
| PDFs de orden de compra / de servicio | `buyers/functions/generate_*.py` |
| Verificación pública, OTP, entrega de PDF | `certificates/views.py`, `mixins.py`, `files.py` |
| Cotejo de un archivo subido | `certificates/verification.py` |
| Modelos de certificación y cajas AEGIS | `certificates/models.py` |
| **Algoritmos de certificación** | `internal/code_gen/services/` (ver §4-bis.E) |
| Generador de códigos, disposiciones, cajas | `code_gen/views.py`, `forms.py`, `api.py`, `preview.py` |
| Consola de operaciones | `internal/ops/registry.py`, `runner.py`, `admin.py` |
| Galería multimedia | `documents/video_masonry/` |

### D. Los cuatro flujos, de punta a punta

**1. Alta y acceso**
`two_factor:login` → `GeaUserRegisterWizardView` (`account/views.py`, `formtools`) → `UserModel`
(`user_type` I/R/H/B) + `UserPersonalInformationModel` (PII cifrada). El registro de comprador exige el
código diario (`GeaDailyUniqueCode`, emitido por cron a las 19:00). `email_hash` se recalcula en
`UserModel.save()` y lo consume el flujo de recuperación de contraseña.

**2. Activo → ubicación → inventario**
`AssetsNamesModel` 1:1 `AssetModel` (FK a `AssetCategoryModel`) → señal `pre_save` que traduce es↔en
llamando a OpenAI **de forma síncrona** → `AssetLocationModel` cruza activo, `LocationModel` y cantidad.
Vistas del tenedor en `assets_location/views.py` bajo `HolderRequiredMixin`.

**3. Orden de compra**
`PurchaseOrderCreateView` → `OfferModel` → `OfferApprovalWizardPageView` pinta el timeline,
`OfferApprovalWizardActionView._apply_step()` ejecuta la etapa: comprueba el permiso `buyers.can_*`,
llama al `mark_*()` correspondiente, la BD valida con sus `CheckConstraint` y `status_code` se **recalcula**
desde los sellos `*_at`. Aprobar dispara la creación de la orden de servicio en `OfferModel.save()`
(bloque B) y el envío por correo a `ServiceOrderRecipient`, con los PDF de `buyers/functions/`.

**4. Certificación y verificación pública**
```
subir PDF (admin «Certify» | code_gen:code_generate)
   └─ services/certification.certify_document()
        ├─ codes.build_code_payload()      código y payload del barcode (sin URLs)
        ├─ render.render_{barcode,qr}_png()
        ├─ pdf_stamp.stamp_pdf()           overlay ReportLab + fusión pypdf, según StampLayout/Placement
        ├─ hashing.file_fingerprints()     huella exacta + huella canónica (ignora la marca de agua)
        ├─ watermark.embed_watermark()     copia distribuible
        └─ record.build_certification_record() + seal_record()   (Ed25519, o HMAC si falta la clave)
   → DocumentVerificationModel: source_file / document_file / public_copy_file

caja AEGIS: master.seal_summary() (payload JCS verbatim)
             → anchoring.anchor_with_tsa() (instantáneo) y anchor_with_ots() (madura por cron)
             El compositor ofrece «sellar y enviar» y «solo sellar»: sellar es una
             escritura nuestra e instantánea, enviar sale a la red. El envío NUNCA
             propaga su fallo (con ATOMIC_REQUESTS desharía el sellado); se degrada a
             aviso y queda disponible en code_gen:summary_anchor. No se manda dos
             veces el mismo master hash.
             → summary.certify_summary() emite el PDF de la caja (code_gen:summary_issue).
             Es un DocumentVerificationModel más, con sus tres archivos. NO espera al
             anclaje y no debe: el QR estampado lleva la URL de la página de anclaje,
             no la prueba, así que se emite un solo papel y no hay que reestamparlo
             cuando llegue el bloque. Ver docs/ANCLAJE.md §5-bis.

consulta pública: certificates:input_document_verification_aegis → OTP por correo
   → OTPSessionMixin → detail → certificates:document_file (única vía de descarga)
                              → certificates:certification_record (JSON del registro)
```

### E. `code_gen/services/` — el subsistema más denso

Cada módulo tiene un docstring largo que explica *por qué* existe. Léelo antes de modificarlo.

| Módulo | Responsabilidad |
|---|---|
| `certification.py` | Orquestador. Resuelve la circularidad hash ↔ código estampado |
| `codes.py` | Composición y validación del payload; rechaza URLs en el barcode |
| `hashing.py` | Huella exacta (`raw`) y canónica (`canonical_pdf_hash`, ignora la marca de agua) |
| `pdf_stamp.py` | Overlay ReportLab + fusión pypdf; no reconstruye el PDF original |
| `render.py` | Code128 y QR a bytes PNG |
| `watermark.py` | Marca oculta en dos canales, verificable |
| `record.py` | Registro de certificación: separa contenido jurídico de prueba técnica |
| `jcs.py` | Canonicalización JSON RFC 8785 — tocarlo invalida todos los master hash |
| `master.py` | Master hash de una caja AEGIS sobre sus miembros |
| `summary.py` | Emisión del resumen AEGIS-6 (lleva códigos de otros documentos) |
| `anchoring.py` | Fachada de anclaje temporal; el QR lleva la URL, no la prueba |
| `tsa.py` / `ots.py` | RFC 3161 (instantáneo) / OpenTimestamps sobre Bitcoin (madura por cron) |
| `samples.py`, `preview.py` | Símbolos y contenedor de la vista previa de estampado |

La vista previa se dibuja en el navegador: `public/staticfiles/js/stamp_preview.js` **replica** la
geometría de `pdf_stamp.py`. Si cambias el posicionamiento en Python, actualiza también el JS.

### F. Consola de operaciones (`internal.ops`)

App sin rutas propias: `urls.py` está vacío a propósito y las páginas cuelgan del admin
(`admin:ops_console`, `admin:ops_command`, en `ops/admin.py::get_urls`, plantillas en `templates/admin/ops/`).
Es una superficie de ejecución remota y por eso está acotada en tres puntos:
`registry.py` (lista blanca de comandos y de sus opciones), `runner.py` (ejecución **en subproceso**,
nunca dentro de la petición, por `ATOMIC_REQUESTS`) y `models.py::CommandRunModel` (traza de quién
ejecutó qué). Sólo superusuarios; el guardia aborta con 404, no con 403.
Al colgar del admin hereda además su puerta: hace falta segundo factor verificado (§6.7).

### G. Puntos de entrada que no son el navegador

| Entrada | Dónde |
|---|---|
| Crons (`django-crontab`) | `settings.CRONJOBS`: `upgrade_ots_anchors` cada 15 min (sin pendientes no sale a la red), código diario 19:00, warm-up cada 3 min |
| Comandos propios | `apps/common/utils/management/commands/` y `code_gen/management/commands/`, `certificates/management/commands/check_certifications.py` |
| Acciones del admin | «Certify» de `certificates/admin.py`; sellado y anclaje de cajas |
| Endpoints JSON internos | `code_gen/api.py` (disposiciones, miembros de caja, símbolos de vista previa) |
| Señales | `assets/signals.py`, `buyers/signals.py` (traducción por OpenAI), `video_masonry/signals.py` |

Los directorios `api/` sueltos (`utils/api/`, `account/api/`) están vacíos: **no hay DRF**.

### H. Frontend

Sin build ni SPA. Plantillas Django + Bootstrap 5 por CDN; `templates/raw.html` →
`templates/dashboard/dashboard_layout_base.html` → página. Las plantillas globales viven en
`templates/` (no dentro de cada app, salvo `core/index.html`). JS a mano en `public/staticfiles/js/`:
`stamp_preview.js` y `layout_workspace.js` (editor de disposiciones), `summary_composer.js` (cajas),
`searchable_select.js`, `busy_buttons.js`, `toasts.js`, `simple-datatable.js`.

---

## 5. Convenciones del código

### Modelos
- Casi todos heredan de `apps.common.utils.models.TimeStampedModel`, que aporta
  `history` (auditlog), `language`, `created`, `updated`, `is_active`, `default_order`
  y `ordering = ['default_order']`.
- Sufijo `Model` en el nombre de clase (`AssetModel`, `OfferModel`, `UserVerificationModel`).
  Excepciones históricas: `ServiceOrderRecipient`, `MediaAsset`, `MediaAssetInteraction`, `MediaAssetUserStats`.
- **`db_table` explícito** en `Meta` para todos los modelos (`apps_buyers_offer`, `apps_users_user`, …). Respétalo al crear modelos nuevos.
- PK **UUID** en las entidades de negocio (`AssetModel`, `OfferModel`, `LocationModel`, certificados…); `BigAutoField` en el resto.
- **Bilingüismo por campos duplicados** `es_*` / `en_*` (no `parler`). Ojo con la inconsistencia de orden: `assets` usa `es_name`/`en_name` pero `assets_location` usa `description_es`/`observations_es`. Sigue el patrón del fichero que estés tocando.
- **Borrado lógico** con `is_active = False`, no `DELETE`.

### Vistas
- Todo son **CBVs**. El control de acceso se hace con mixins, no con decoradores:
  `BuyerRequiredMixin` (en `buyers/views.py`), `HolderRequiredMixin` (en `assets_location/views.py`),
  `OnlySpecificUserMixin`, `OTPSessionMixin` / `OTPProtectedDocumentMixin` (en `certificates/mixins.py`).
- `assets/views.py` **importa los mixins desde `buyers` y `assets_location`** — hay acoplamiento cruzado entre apps; tenlo en cuenta antes de mover código.
- Los mixins de rol dejan pasar siempre a `is_superuser` e `is_staff`.
- Las acciones AJAX devuelven `JsonResponse` con **HTML pre-renderizado** (`render_to_string`), no JSON de datos.

### Textos
- Todo texto visible va envuelto en `gettext_lazy as _`. Los `.po`/`.mo` viven en `locale/es/LC_MESSAGES/` dentro de cada app.
- Comentarios y docstrings están mezclados en español e inglés. Escribe en el idioma dominante del fichero.

### Plantillas
- Jerarquía: `templates/raw.html` → `templates/dashboard/dashboard_layout_base.html` → página.
- Filtros y tags propios en `apps/common/utils/templatetags/custom_filters.py`
  (`add_class`, `add_attrs`, `currency`, `active_class`, `is_active`, `collapse_open_class`, `aria_expanded`, `split`, `trim`).

---

## 6. Invariantes que NO se pueden romper

1. **El estado de una orden es derivado, no almacenado.** `OfferModel.status_code` se calcula desde los sellos `*_at`. Nunca añadas un campo `status` ni escribas estado directamente.
2. **El flujo de la orden está protegido en tres capas**: métodos `mark_*()` atómicos, `clean()`/`save()`, y **10 `CheckConstraint` en la base de datos**. Cualquier cambio en el flujo obliga a actualizar las tres, más la migración correspondiente.
3. **`profitability_paid_at` exige los tres subpagos** (`recovery_repatriation_foundation_paid`, `pay_master_service_paid`, `propensiones_paid`). Lo garantiza la restricción `profit_paid_requires_3_subpaids`.
4. **Los números de documento de certificados nunca se almacenan en claro**: solo su HMAC (`get_hmac`). Los OTP también se guardan hasheados con HMAC-SHA256 sobre `SECRET_KEY` y se comparan con `constant_time_compare`.
5. **`email_hash`** (SHA-256 del email normalizado) se recalcula en `UserModel.save()`; los flujos de recuperación de contraseña dependen de él.
6. **Cada etapa del wizard exige su permiso Django concreto** (`buyers.can_*`). Los permisos están declarados en `OfferModel.Meta.permissions`; añadir una etapa implica migración.
7. **El admin se protege con la sesión, no con la URL.** `app_core/admin.py::GeaAdminSite` (instalado vía `AdminConfig.default_site`, así que `admin.site` sigue siendo el mismo objeto y ningún `@admin.register` cambia) exige personal activo **con segundo factor verificado**, y a quien no cumple le responde **404**, nunca 403 ni el formulario de login del admin: un 403 confirmaría la ruta. La excepción es el personal interno sin OTP verificado, al que se redirige a `two_factor:setup`. La `ADMIN_URL` sigue viniendo de entorno y no se escribe en el código, pero ya no es el control de acceso. El panel se alcanza desde el enlace del sidenav.
8. **Un documento certificado son tres archivos**: `source_file` (original sin códigos), `document_file` (con QR y barcode, el que hace fe) y `public_copy_file` (copia distribuible con marca de agua oculta). De cada uno se guardan dos huellas: la exacta (`*_hash`) y la de contenido (`*_content_hash`). No sustituyas ninguno de los tres a mano: usa la acción "Certify" del admin o `services.certification.certify_document()`, que recalcula todo el conjunto.
9. **El código de barras nunca lleva URLs.** `services.codes.validate_barcode_payload()` rechaza `://`, `:` y los caracteres de URL. Todo lo que no encaje va al QR.
10. **La huella de contenido ignora deliberadamente la marca de agua**, de modo que el certificado y su copia distribuible comparten `*_content_hash` y se distinguen solo por la marca. Si tocas `canonical_pdf_hash()` invalidas todas las huellas ya emitidas.
11. **La certificación acredita integridad, no veracidad.** El registro de certificación lo dice expresamente en `scope.does_not_attest`: la plataforma prueba que el archivo no ha cambiado desde que se registró, no que sea cierto lo que el documento afirma. No redactes textos que sugieran lo contrario.
12. **Las URLs de los artefactos permanentes salen de `PUBLIC_BASE_URL`**, nunca de `request.build_absolute_uri()`: el QR vive dentro del PDF y no puede apuntar al host desde el que se certificó.
13. **Los archivos de certificación no se enlazan nunca por `MEDIA_URL`.** La única vía es `certificates:document_file`, que comprueba permisos: `source` y `certified` solo para `is_staff`/`is_superuser`; `public` para sesión OTP válida o autenticado. En el servidor hace falta además el `.htaccess` de `deploy/` — sin él el servidor web sigue sirviendo los PDF por su cuenta y estas reglas no pintan nada.
15. **El master hash de una caja nunca cubre al propio resumen.** Se sella sobre los miembros, luego se emite el resumen llevando ese hash, y solo después se registra su huella. Es la misma circularidad del código de barras y el hash del original, y no tiene otra solución.
16. **El QR del anclaje lleva una URL, no la prueba.** La página de `certificates:summary_anchor` se actualiza sola según maduran los anclajes; si el bloque de Bitcoin fuera impreso habría que reestampar el PDF cada vez. De ahí que **el documento del resumen se emita en cuanto la caja está sellada**, con o sin anclaje, y que sea uno solo: dos papeles —«sin blockchain» y «con»— serían dos huellas distintas para la misma caja y habría que decidir cuál hace fe.
17. **El payload maestro se guarda verbatim.** No se reconstruye para verificar: se compara contra los bytes exactos que se hashearon. Cambiar `services/jcs.py` invalidaría todos los master hash ya anclados.
18. **Una orden aprobada ya no se edita ni se oculta desde las vistas de listado.** Aprobar crea la orden de servicio automáticamente (`OfferModel.save`, bloque B), así que a partir de ahí la orden es un documento vivo con PDF ya enviados a terceros: cambiarle la cantidad o ponerle `display = False` dejaría la base de datos contradiciendo lo repartido. Las reglas de quién puede hacer qué sobre una orden viven en `buyers/access.py`, no repartidas por las vistas. Y todo lo que tenga efecto hacia fuera —mandar la orden de servicio por correo— comprueba el estado **antes** de producir el efecto, no al guardar después.
14. **La trampa anti-escaneo empareja segmentos completos, no subcadenas.** Antes `env` convertía `/envio/` en trampa y bloqueaba la IP del usuario. Al tocar `COMMON_ATTACK_TERMS`, ejecuta `manage.py check_attack_terms`: comprueba colisiones **respetando el orden del URLconf**, que es lo único que determina si una ruta queda secuestrada de verdad.

---

## 7. Trampas conocidas

| Trampa | Detalle |
|---|---|
| **Regex catch-all antes que rutas reales** | `apps/common/utils/attack_patterns.py` registra un `re_path` que matchea cualquier término de `COMMON_ATTACK_TERMS` en cualquier posición del path, y `utils` va en la 4.ª posición del URLconf — **antes** de `assets`, `assets_location`, `buyers` y `account`. Un término mal elegido secuestra rutas legítimas y bloquea la IP del usuario. |
| **`CACHES` sale de `REDIS_URL`** | Con la variable puesta se usa `django-redis` con `IGNORE_EXCEPTIONS`: un Redis caído degrada a «sin cache» en vez de tumbar el login. Sin la variable, Django cae en `LocMemCache`, que es **por proceso**: los límites de OTP, del código de registro y del cupo de recuperación de contraseña son entonces por worker. Montaje del Redis: [`deploy/REDIS.md`](deploy/REDIS.md). |
| **`ERROR_TEMPLATE` no está definido** | Varios módulos hacen `settings.ERROR_TEMPLATE` dentro de `try/except` y caen a `'errors_template.html'`. Funciona, pero el `getattr` es engañoso. |
| **`settings.py` explota si falta una variable** | Muchos `os.getenv(...)` se pasan directamente a `int()` o `.split(',')` sin valor por defecto (`DB_PORT`, `DJANGO_EMAIL_PORT`, `IP_BLOCKED_TIME_IN_MINUTES`, `CORS_ALLOWED_ORIGINS`, `COMMON_ATTACK_TERMS`, `GEA_DAILY_CODE_*`). Sin `.env` completo, el proyecto no arranca. |
| **`OPTIONS` de la BD se sobrescribe** | En `DATABASES` se define un `OPTIONS` con `charset`/`init_command` y, si `DB_ENGINE` es MySQL, el bloque siguiente **reemplaza el dict entero** (se pierde el `charset` y el `COLLATE utf8mb4_bin`). |
| **Allowlist de usuarios hardcodeada** | `OnlySpecificUserMixin.allowed_user_username = ['jose.henry', 'kalichemorales']` en `buyers/views.py` controla el acceso a Orion. |
| **`django.contrib.sites` NO está instalado** | `get_current_site(request)` cae en `RequestSite` y devuelve la cabecera `Host`, que la pone el cliente. Cualquier URL construida así es envenenable. Por eso el enlace de recuperación de contraseña sale de `PUBLIC_BASE_URL` (invariante 12). Si añades otro correo con enlaces, hazlo igual. |
| **`axes` no ve el usuario del login** | El login es un wizard de `formtools`: su campo es `auth-username`, no `username`. Sin `AXES_USERNAME_CALLABLE` (`utils/axes_hooks.py`) todos los intentos se guardan con usuario vacío y **cualquier bloqueo por pareja (IP, usuario) degrada en silencio a bloqueo por IP**. Si algún día cambia el prefijo del paso, actualiza `USERNAME_FIELDS`. |
| **`AxesStandaloneBackend` va primero y exige `request`** | Ese orden es lo que impide que una contraseña correcta se salte el bloqueo, pero hace que `authenticate()` **sin** `request` lance excepción. `client.login()` de Django no la pasa: por eso `settings_test` apaga axes y solo lo encienden sus propias pruebas. |
| **Llamadas a OpenAI en señales `pre_save`** | La traducción automática de activos y ofertas ocurre **de forma síncrona dentro del guardado** (timeout 20 s). Un fallo o lentitud de la API se traduce en peticiones lentas. No hay cola de tareas. |
| **`ffmpeg` como dependencia del sistema** | `video_masonry` invoca `ffmpeg` por `subprocess` para quitar el audio de los vídeos. Si no está en el `PATH`, la subida falla. |
| **`ATOMIC_REQUESTS = True`** | Cada petición es una transacción. Cuidado con operaciones largas (PDF, OpenAI, email) dentro de vistas. |
| **`logging.basicConfig` a `stderr.log`** | Configurado en `settings.py`, sin rotación. |
| **Ajustes definidos y nunca leídos** | `MIDDLEWARE_NOT_INCLUDE`, `ADMIN_DELETE_PERMISSION` y `ADMIN_ADD_PERMISSION` se declaran en `settings.py` pero no los consume nadie. No asumas que hacen algo. (`UTILS_DATA_PATH` sí se usa, solo en `delete_migrations`.) |

---

## 8. Variables de entorno

Se cargan con `python-dotenv` desde `.env` en la raíz (ignorado por git).

```
# Django
DJANGO_SECRET_KEY, DJANGO_DEBUG, DJANGO_ALLOWED_HOSTS, DJANGO_ADMIN_URL
DJANGO_STATIC_URL, DJANGO_STATIC_ROOT, DJANGO_MEDIA_URL, DJANGO_MEDIA_ROOT

# Base de datos
DB_ENGINE, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
DB_CONN_MAX_AGE, DB_CHARSET, DB_SSLMODE

# Email
DJANGO_EMAIL_BACKEND, DJANGO_EMAIL_HOST, DJANGO_EMAIL_PORT, DJANGO_EMAIL_USE_SSL
DJANGO_EMAIL_HOST_USER, DJANGO_EMAIL_HOST_PASSWORD, DJANGO_EMAIL_DEFAULT_FROM_EMAIL

# Seguridad
FIELD_ENCRYPTION_KEY          # cifrado de PII — perderla inutiliza los datos cifrados
CERTIFICATION_SIGNING_KEY     # Ed25519 base64; firma el registro de certificación
                              # (manage.py generate_certification_key). Sin ella
                              # el registro se sella con HMAC y solo la propia
                              # plataforma puede verificarlo
PUBLIC_BASE_URL               # base canónica para el QR y el registro; NUNCA se
                              # deriva del host de la petición
CORS_ALLOWED_ORIGINS          # lista separada por comas
COMMON_ATTACK_TERMS           # lista separada por comas → regex catch-all
IP_BLOCKED_TIME_IN_MINUTES
MIDDLEWARE_NOT_INCLUDE
AXES_FAILURE_LIMIT            # por defecto 6, bloqueo por pareja (IP, usuario)
AXES_COOLOFF_MINUTES          # por defecto 30; nunca dejarlo sin espera

# Cache — ver deploy/REDIS.md
REDIS_URL                     # rediss://usuario:clave@host:6380/0?ssl_cert_reqs=
                              # required&ssl_ca_certs=/ruta/ca.crt
                              # Sin ella, LocMemCache: los límites son por worker
REDIS_KEY_PREFIX              # por defecto 'gea'
REDIS_CONNECT_TIMEOUT, REDIS_TIMEOUT   # segundos, por defecto 3

# Negocio / integraciones
GEA_DAILY_CODE_GENERAL_RECIPIENTS   # lista separada por comas
GEA_DAILY_CODE_BUYER_RECIPIENTS     # lista separada por comas
GEA_WARMUP_URL                      # por defecto https://geausa.propensionesabogados.com/health/
CHAT_GPT_API_KEY
OA_AUDIO_MODEL, OA_TEXT_MODEL       # solo para el script de transcripción
```

---

## 9. Modelo de datos en una página

```
UserModel (UUID, user_type I/R/H/B)
 ├─1:1─ UserPersonalInformationModel   [PII cifrada, pasaporte, firma]
 │        └─M:N─ AddressModel ── CityModel ── StateModel ── CountryModel
 ├──── referred (self FK)
 ├──── LocationModel        (created_by)  ── AssetCountryModel
 ├──── AssetLocationModel   (created_by)  ── AssetModel + LocationModel + cantidad
 └──── OfferModel           (created_by, y 12 pares *_by de flujo)

AssetsNamesModel ─1:1─ AssetModel ─FK─ AssetCategoryModel
AssetModel ─1:N─ AssetLocationModel        (inventario por ubicación)
AssetModel ─1:N─ OfferModel                (órdenes de compra)

OfferModel ─1:N─ ServiceOrderRecipient     (destinatarios por usuario o por tipo)

UserVerificationModel      ─1:N─ CertificateViewLogModel
DocumentVerificationModel  ─1:N─ CertificateViewLogModel
DocumentVerificationModel  ─FK──  StampLayoutModel        (dónde se estampan los códigos)
StampLayoutModel           ─1:N─ StampPlacementModel
CodeSequenceModel                (contador de la secuencia autónoma)
CodeRegistrationModel            (traza de cada código emitido)

MediaAsset ─1:N─ MediaAssetInteraction
MediaAsset ─1:N─ MediaAssetUserStats  (unique por usuario+activo)

GeaDailyUniqueCode   (código diario, kind GENERAL/BUYER, único por fecha+kind)
IPBlockedModel / WhiteListedIPModel
```

---

## 10. Cómo abordar tareas frecuentes

**Añadir una ruta**: crea la vista en `<app>/views.py` con el mixin de acceso adecuado, regístrala en `<app>/urls.py` (que ya tiene `app_name`) y comprueba que el path **no contenga ningún término de `COMMON_ATTACK_TERMS`**.

**Añadir una etapa al flujo de órdenes**: campos `*_by`/`*_at` en `OfferModel` → método `mark_*()` atómico → rama en `status_code` (respetando el orden de más avanzado a más básico) → entradas en `status_icon`/`status_color` → permiso en `Meta.permissions` → `CheckConstraint` → rama en `_apply_step()` de `OfferApprovalWizardActionView` → partial de timeline en `templates/dashboard/pages/buyers/partials/timeline/` → migración.

**Añadir un modelo bilingüe**: hereda de `TimeStampedModel`, define `es_*`/`en_*`, fija `db_table`, y si quieres traducción automática engancha una señal `pre_save` al estilo de `assets/signals.py`.

**Certificar un documento**: en el admin, `Document Verification` → subir el PDF original en `source_file`, elegir `stamp_layout` (o dejarlo vacío para el layout por defecto), guardar, y ejecutar la acción *Certify*. También desde el dashboard en `code_gen:code_generate` marcando "Certify this document". Re-certificar rehace el estampado, las huellas y la copia, conservando `public_code` y secuencia.

**Mover un código dentro del PDF**: edita el `StampPlacementModel` correspondiente (coordenadas en puntos PostScript, medidas desde el anclaje hacia el interior) y vuelve a certificar.

**Cambiar textos visibles**: edita el código con `_()`, luego `makemessages -l es` / `compilemessages`, o usa Rosetta desde el admin.

**Depurar un bloqueo de IP**: revisa `IPBlockedModel` (tabla `apps_common_utils_ipblocked`); `session_info` guarda los paths intentados. Añade la IP a `WhiteListedIPModel` o ajusta `blocked_until`.

---

## 11. Estado del repositorio

- Rama principal: `master`.
- No hay CI ni linters configurados. Sólo cuatro `tests.py` tienen contenido: `buyers/tests.py` (control de acceso del flujo de órdenes: una mitad reproduce agujeros ya cerrados, la otra comprueba que el trabajo legítimo del equipo sigue pasando), `assets/tests.py`, `common/utils/tests.py` e `internal/ops/tests.py` (lista blanca y trazabilidad de la consola). Los demás siguen vacíos. Se ejecutan con `--settings=app_core.settings_test` (SQLite en memoria), porque el usuario de MySQL en cPanel no puede crear la base `test_*`. La otra carpeta `tests` con contenido es `buyers/functions/tests/dummy_offer.py` (fixture para probar la generación de PDFs a mano).
- Los mensajes de commit son informales y en español/inglés mezclado.
- El historial reciente muestra la plataforma pasando por un ciclo de desactivación ("standby mode") y reactivación.
