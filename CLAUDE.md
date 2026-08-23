# CLAUDE.md — Contexto del proyecto GEA para asistentes de IA

Ficha técnica del repositorio `gea_module_0`. Léela antes de tocar código.
Documentos complementarios:

- [`docs/ROUTES_MAP.md`](docs/ROUTES_MAP.md) — todas las URLs, namespaces, vistas y permisos.
- [`docs/FEATURES_MAP.md`](docs/FEATURES_MAP.md) — funcionalidades por dominio, modelos y reglas de negocio.

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
| PDF | ReportLab (código de barras Code128) |
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
templates/                   # plantillas globales (dashboard, account, two_factor, email)
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
7. **La `ADMIN_URL` es secreta** y viene de entorno. No la fijes a `/admin/` ni la escribas en el código.

---

## 7. Trampas conocidas

| Trampa | Detalle |
|---|---|
| **Regex catch-all antes que rutas reales** | `apps/common/utils/attack_patterns.py` registra un `re_path` que matchea cualquier término de `COMMON_ATTACK_TERMS` en cualquier posición del path, y `utils` va en la 4.ª posición del URLconf — **antes** de `assets`, `assets_location`, `buyers` y `account`. Un término mal elegido secuestra rutas legítimas y bloquea la IP del usuario. |
| **`CACHES` no está definido** | Django cae en `LocMemCache`, que es **por proceso**. Los límites de OTP (`certificates/mixins.py`) y el código de registro de compradores viven en cache: con varios workers, los contadores no se comparten y los límites son efectivamente por worker. Si se despliega multi-proceso hay que configurar Redis/Memcached. |
| **`ERROR_TEMPLATE` no está definido** | Varios módulos hacen `settings.ERROR_TEMPLATE` dentro de `try/except` y caen a `'errors_template.html'`. Funciona, pero el `getattr` es engañoso. |
| **`request.user.is_superadmin` no existe** | Se usa en `templates/dashboard/partials/sidenav/dashboard_sidenav.html` (líneas 77 y 175). Django resuelve el atributo inexistente a cadena vacía (falsy), así que ese `or` **nunca aporta nada**: los superusuarios ven el bloque solo si además son `is_buyer`. Probable bug de visibilidad. |
| **`settings.py` explota si falta una variable** | Muchos `os.getenv(...)` se pasan directamente a `int()` o `.split(',')` sin valor por defecto (`DB_PORT`, `DJANGO_EMAIL_PORT`, `IP_BLOCKED_TIME_IN_MINUTES`, `CORS_ALLOWED_ORIGINS`, `COMMON_ATTACK_TERMS`, `GEA_DAILY_CODE_*`). Sin `.env` completo, el proyecto no arranca. |
| **`OPTIONS` de la BD se sobrescribe** | En `DATABASES` se define un `OPTIONS` con `charset`/`init_command` y, si `DB_ENGINE` es MySQL, el bloque siguiente **reemplaza el dict entero** (se pierde el `charset` y el `COLLATE utf8mb4_bin`). |
| **Allowlist de usuarios hardcodeada** | `OnlySpecificUserMixin.allowed_user_username = ['jose.henry', 'kalichemorales']` en `buyers/views.py` controla el acceso a Orion. |
| **Llamadas a OpenAI en señales `pre_save`** | La traducción automática de activos y ofertas ocurre **de forma síncrona dentro del guardado** (timeout 20 s). Un fallo o lentitud de la API se traduce en peticiones lentas. No hay cola de tareas. |
| **`ffmpeg` como dependencia del sistema** | `video_masonry` invoca `ffmpeg` por `subprocess` para quitar el audio de los vídeos. Si no está en el `PATH`, la subida falla. |
| **Descarga de logo por HTTP al enviar emails** | `SO_NOTIFY` hace `requests.get()` al logo en producción para incrustarlo. Depende de que el sitio esté accesible desde el propio servidor. |
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
CORS_ALLOWED_ORIGINS          # lista separada por comas
COMMON_ATTACK_TERMS           # lista separada por comas → regex catch-all
IP_BLOCKED_TIME_IN_MINUTES
MIDDLEWARE_NOT_INCLUDE

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

**Cambiar textos visibles**: edita el código con `_()`, luego `makemessages -l es` / `compilemessages`, o usa Rosetta desde el admin.

**Depurar un bloqueo de IP**: revisa `IPBlockedModel` (tabla `apps_common_utils_ipblocked`); `session_info` guarda los paths intentados. Añade la IP a `WhiteListedIPModel` o ajusta `blocked_until`.

---

## 11. Estado del repositorio

- Rama principal: `master`.
- Los ficheros `tests.py` existen en todas las apps pero **están vacíos**. No hay suite de pruebas, ni CI, ni linters configurados. La única carpeta `tests` con contenido es `buyers/functions/tests/dummy_offer.py` (fixture para probar la generación de PDFs a mano).
- Los mensajes de commit son informales y en español/inglés mezclado.
- El historial reciente muestra la plataforma pasando por un ciclo de desactivación ("standby mode") y reactivación.
