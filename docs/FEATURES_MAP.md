# Mapa de Funcionalidades — GEA (gea_module_0)

Plataforma Django de **Propensiones Abogados** para la gestión de activos históricos
(bonos alemanes, oro, billetes de alta denominación, etc.): registro de tenedores,
catálogo y localización de activos, órdenes de compra con flujo de aprobación
multi-etapa, verificación pública de certificados y galería de material audiovisual.

---

## Índice de dominios funcionales

| # | Dominio | App | Usuarios |
|---|---|---|---|
| 1 | Identidad, roles y 2FA | `common.users`, `common.account` | Todos |
| 2 | Catálogo de activos | `assets_management.assets` | Compradores / staff |
| 3 | Inventario y ubicaciones | `assets_management.assets_location` | Tenedores |
| 4 | Órdenes de compra y flujo comercial | `assets_management.buyers` | Compradores / aprobadores |
| 5 | Rentabilidad y liquidación | `assets_management.buyers` | Roles con permiso |
| 6 | Certificados y verificación documental | `documents.certificates` | Público |
| 7 | Galería multimedia | `documents.video_masonry` | Compradores |
| 8 | Seguridad perimetral y anti-abuso | `common.utils` | Infraestructura |
| 9 | i18n y traducción automática | transversal | Todos |
| 10 | Auditoría y trazabilidad | transversal | Staff |
| 11 | Operación: cron, comandos, salud | `common.utils`, `common.core` | DevOps |

---

## 1. Identidad, roles y autenticación

### Modelo de usuario — `apps_users_user` (`UserModel`)
Extiende `AbstractUser` + `TimeStampedModel`. PK **UUID**.

**Tipos de usuario** (`UserTypeChoices`):

| Código | Tipo | Rol funcional |
|---|---|---|
| `I` | Intermediary | Facilitador / intermediario |
| `R` | Representative | Representante |
| `H` | Holder | Tenedor del activo |
| `B` | Buyer | Comprador |

- `is_asset_holder` → cualquier tipo **excepto** `BUYER` (`NOT_INCLUDE_USER_TYPE_CHOICES = {BUYER}`).
- `is_buyer` → `user_type == 'B'`.
- `is_verified_holder`: los compradores se marcan verificados automáticamente en `save()`.
- `email_hash`: SHA-256 del email en minúsculas, usado para búsquedas sin exponer el email (p. ej. "olvidé mi contraseña").
- Normalización en `save()`: nombre/apellido a *Title Case*, username a minúsculas, email a minúsculas.
- `clean()` prohíbe `@` en el username.
- `referred` / `is_referred`: cadena de referidos entre usuarios.
- `phone_number_code`: catálogo exhaustivo de códigos país (`PhoneCodeChoices`, formato `57-CO`).

### Datos personales — `apps_users_userpersonalpnformation`
`UserPersonalInformationModel` (OneToOne con el usuario). Campos sensibles **cifrados en base de datos** vía `django-encrypted-model-fields`, más `passport_image` y `signature` (imágenes), género, autoridad emisora, fechas de emisión/expiración y M2M de direcciones.

### Geografía de usuarios
`CountryModel` → `StateModel` → `CityModel` → `AddressModel` (jerarquía propia, separada del catálogo geográfico de activos).

### Autenticación
- Backend propio `EmailOrUsernameModelBackend`: login con **email o username**.
- `django-axes` para bloqueo por intentos fallidos.
- **2FA obligatorio disponible** con `django-two-factor-auth` + `django-otp` (TOTP y tokens estáticos de respaldo).
- Hash de contraseñas: **Argon2** (primero en `PASSWORD_HASHERS`).
- Sesión: 7200 s (2 h), no expira al cerrar navegador.
- Validadores de contraseña: similitud con atributos del usuario (0.7), mínimo 8 caracteres, contraseñas comunes, solo-numérica.
- `django-impersonate` para suplantación por soporte.

### Registro (`account:register`)
`GeaUserRegisterWizardView` — `SessionWizardView` de 4 pasos con ramificación:

```
user (datos + user_type) → security → contact → code
                                ↑
              BuyerContactForm si user_type == BUYER
              SupplierContactForm en cualquier otro caso
```

- El paso `contact` se resuelve leyendo `user_type` **del storage crudo** del wizard (no de `cleaned_data`) para evitar recursión con `get_form_list()`.
- Paso `code`: valida el **código diario GEA**.
  - **Compradores**: código enviado por email al propio solicitante, TTL 10 min, máx. 3 envíos por ventana de 5 min.
  - **Resto de perfiles**: código diario general entregado por un asesor.

### Recuperación y cambio de contraseña
- `account:forgot_password` — flujo de 2 pasos (`ForgotPasswordStep1Form` / `Step2Form`) con token de Django y email HTML (`templates/account/password_reset_email.html`). Localiza al usuario por `email_hash`.
- `account:change_password` — `ChangePasswordForm` con `update_session_auth_hash`.

---

## 2. Catálogo de activos

| Modelo | Tabla | Contenido |
|---|---|---|
| `AssetCategoryModel` | `apps_assets_assetcategory` | Categoría bilingüe (`es_name`/`en_name`, descripciones) |
| `AssetsNamesModel` | `apps_assets_assetsnames` | Nombre canónico bilingüe del activo |
| `AssetModel` | `apps_assets_asset` | Activo: imagen, categoría, descripciones y observaciones bilingües; PK UUID |

- `AssetModel.asset_name` es **OneToOne** con `AssetsNamesModel` (un nombre ↔ un activo).
- `asset_total_quantity_by_type()` agrega existencias desde `AssetLocationModel` por tipo de cantidad (unidades / resúmenes).
- Alta rápida desde el dashboard: `assets:create` crea **nombre + activo en línea** en una sola pantalla; `assets:add_category` añade categorías.
- Import/export CSV, HTML, JSON, TSV, XLS, XLSX en el admin (`django-import-export`).
- Señales: borrado del archivo de imagen al eliminar o reemplazar el activo.

---

## 3. Inventario y ubicaciones (perfil Tenedor)

| Modelo | Tabla | Contenido |
|---|---|---|
| `AssetCountryModel` | `apps_assets_location_country` | País con continente (`ContinentChoices`), nombres bilingües |
| `LocationModel` | `apps_assets_location_location` | Ubicación con `reference`, descripciones bilingües, país, `created_by` |
| `AssetLocationModel` | `apps_assets_location_assetlocation` | Registro activo↔ubicación: `quantity_type` (U/B), `amount`, observaciones bilingües |

Dashboard del tenedor (`assets:holder_index`): sus registros de activos, sus ubicaciones y las **órdenes aprobadas aún sin orden de pago creada** (oportunidades abiertas).

CRUD completo de ubicaciones y de registros activo-ubicación, todo restringido por `HolderRequiredMixin` (y filtrado por `created_by` para que un tenedor solo vea lo suyo).

---

## 4. Órdenes de compra y flujo comercial

### `OfferModel` — `apps_buyers_offer` (el corazón del sistema, ~1.000 líneas)

Una "Purchase order" (orden de compra) sobre un activo, con país de comprador, cantidad, tipo de cantidad, imagen, y descripciones/observaciones bilingües.

### Máquina de estados

El estado **no se almacena**: se deriva en la propiedad `status_code` a partir de los sellos de tiempo, del más avanzado al más básico.

```
UNDER_REVIEW
   → PENDING_APPROVAL        (activa, sin revisar, sin aprobar)
   → NOT_APPROVED            (revisada y rechazada)
   → APPROVED                (revisada + aprobada)
      → SO_CREATED           Service Order creada
      → SO_SENT              Service Order enviada
      → PAY_CREATED          Payment Order creada
      → PAY_SENT             Payment Order enviada
      → POSSESSION           Activo en posesión
      → ASSET_SENT           Activo enviado
      → PROFIT_CREATED       Rentabilidad creada
      → PROFIT_PAID          Rentabilidad pagada (exige los 3 subpagos)
      → COMPLETED
```

Cada etapa guarda **quién** (`*_by`) y **cuándo** (`*_at`). `status_label`, `status_icon` y `status_color` derivan del mismo `status_code` para pintar la línea de tiempo en la UI.

### Triple garantía de integridad del flujo

1. **Métodos de transición** (`mark_service_order_sent`, `mark_payment_order_created`, …) — `@transaction.atomic`, lanzan `ValidationError` si se salta un paso.
2. **`clean()` / `save()`** — coherencia y sellado automático de `*_at` cuando se asigna `*_by`.
3. **`CheckConstraint` en base de datos** — 10 restricciones que impiden estados imposibles incluso escribiendo directo en la BD:
   `approved_requires_reviewed`, `so_created_requires_approved`, `so_sent_requires_so_created`,
   `pay_created_requires_so_sent`, `pay_sent_requires_pay_created`, `possession_requires_pay_sent`,
   `asset_sent_requires_possession`, `profit_created_requires_asset_sent`,
   `profit_paid_requires_profit_created`, `profit_paid_requires_3_subpaids`.

### Wizard de aprobación (`buyers:offer_wizard_*`)

Interfaz AJAX que ejecuta las transiciones. Cada paso exige un **permiso Django específico** (ver tabla completa en [ROUTES_MAP.md §10](ROUTES_MAP.md)); `is_superuser`/`is_staff` los saltan todos. Respuesta JSON con el HTML re-renderizado del wizard y de la línea de tiempo.

### Destinatarios de orden de servicio — `ServiceOrderRecipient`
Tabla `apps_buyers_service_order_recipient`. Permite añadir destinatarios **por usuario concreto o por tipo de usuario**; `_resolve_so_emails()` resuelve la unión en una lista de emails deduplicada.

### Generación de PDF (ReportLab)
- `generate_purchase_order_pdf(offer, user)` — orden de compra en A4 con **código de barras Code128** y la imagen del activo.
- `generate_service_order_pdf(offer, user)` — orden de servicio, mismo formato.
- `build_offer_image_story()` — helper compartido para incrustar la imagen escalada.

### Notificaciones por email
- Alta de orden de compra → email al equipo (`email/purchase_order_email_template.html`).
- `SO_NOTIFY` → email **BCC** a los destinatarios con el PDF adjunto y el logo GEA incrustado como imagen inline (`Content-ID`), plantilla `email/service_order_email_template.html`.

### Optimización de imágenes
Señal `pre_save` sobre `offer_img`: redimensiona a máx. 1600×1600, calidad 85 y **convierte a WebP**; borra el archivo anterior al reemplazar o eliminar la oferta.

### Borrado lógico
`OfferSoftDeleteView` marca `is_active = False`; no se borra la fila.

---

## 5. Rentabilidad y liquidación

Vista `buyers:profitability_view` (`ProfitabilityTemplateView`):

- Listado de órdenes con `profitability_created_at` establecido.
- Contadores **en curso** vs **pagadas** (una orden se considera pagada cuando los tres subpagos están marcados).
- **Gráfico de 12 meses**: órdenes creadas por mes (`TruncMonth` sobre `created`) frente a órdenes cerradas por mes (sobre `profitability_paid_at`).
- **Tabla de activos** con totales por resúmenes/unidades, nombres localizados según el idioma activo y *tokens* de filtrado en cliente (`img:yes|no`, `qty:U`, `qty:B`, `zero:yes|no`). Se omiten activos con stock cero en ambos tipos.

Los tres subpagos que componen la liquidación:

| Subpago | Campo | Permiso |
|---|---|---|
| Recovery Repatriation Foundation | `recovery_repatriation_foundation_paid` | `recovery_repatriation_foundation_paid` |
| PAY MASTER Service | `pay_master_service_paid` | `pay_master_service_paid` |
| Propensiones | `propensiones_paid` | `propensiones_paid` |

`profitability_all_paid` exige los tres; solo entonces `mark_profitability_paid()` (permiso `can_approve_pay_profitability`) puede cerrar la orden — y la restricción `profit_paid_requires_3_subpaids` lo garantiza también a nivel de BD.

Vista complementaria: `buyers:inventory_view` (inventario consolidado para compradores).

### Módulos satélite
- **Hermes** (`buyers:hermes_form`) — formulario de crédito sobre activos, **JotForm embebido** (con firma manuscrita jSignature) + pantalla de éxito.
- **Orion** (`buyers:orion_scheduler`) — agendador restringido a una **allowlist de usernames** (`jose.henry`, `kalichemorales`) además de staff/superuser.

---

## 6. Certificados y verificación documental (público)

### `UserVerificationModel` — `apps_certificates_user_verification`
Certificados de personas (p. ej. empleado IPCON, idoneidad).

- Identificadores múltiples: `public_uuid` (36 chars), `uuid_prefix` (8), `public_code` (4).
- **Los números de documento no se almacenan**: se guarda solo su HMAC (`document_number_cc_hash`, `document_number_pa_hash`). Las propiedades `cc_masked`/`pa_masked` muestran versiones enmascaradas.
- Ciclo de vida: `approved` / `approved_by` / `approval_date`, `issued_at`, `expires_at`, `revoked_at` + `revocation_reason`.
- Propiedades derivadas: `is_revoked`, `is_expired`, `is_passport_expired`, `total_views`, `unique_views`.

**Flujo de consulta** (`certificates:input_employee_verification_ipcon`): el visitante elige tipo de documento (CC / PA / código único) e introduce el valor; el sistema calcula el HMAC o filtra por longitud del código (4 → `public_code`, 8 → `uuid_prefix`, 36 → `public_uuid`) y redirige al detalle.

La página de detalle genera **QR con el favicon GEA incrustado** y **código de barras**, ambos apuntando a la URL absoluta del certificado.

### `DocumentVerificationModel` — `apps_certificates_document_verification`
Certificados de documentos (línea "Aegis"): archivo, `document_hash` (huella del fichero), método de entrega, fechas de emisión/expiración, códigos públicos.

**Protegido por OTP de email** (`OTPSessionMixin` / `OTPProtectedDocumentMixin`):

| Control | Valor |
|---|---|
| TTL del código | 10 min |
| Cooldown de reenvío | 1 min |
| Máx. intentos de verificación | 5 → bloqueo 10 min |
| Máx. envíos por ventana | 3 / 10 min (clave `ip+email`) |
| Máx. verificaciones por ventana | 10 / 10 min (clave `ip+sesión`) |

El OTP se guarda **hasheado con HMAC-SHA256** usando `SECRET_KEY`; la comparación es en tiempo constante (`constant_time_compare`). Hay detección de emails temporales/desechables y de dominios IPCON.

### `CertificateViewLogModel` — `apps_certificates_view_log`
Bitácora de cada consulta: certificado (de usuario o de documento), usuario autenticado o email anónimo, IP, user-agent y timestamp. Alimenta `total_views` / `unique_views`.

---

## 6-bis. Motor de certificación documental (`internal.code_gen`)

### Qué hace

Convierte un PDF sin marcas en un documento certificado y verificable
públicamente. De cada documento certificado quedan **tres archivos**:

| Archivo | Campo | Contenido |
|---|---|---|
| Original | `source_file` | El PDF tal cual se recibió, sin códigos. |
| Certificado | `document_file` | El original con el QR y el código de barras ya incrustados. Es el que hace fe. |
| Copia distribuible | `public_copy_file` | Idéntico a la vista al anterior, con una marca de agua oculta y verificable. Es el que se entrega. |

### El código emitido

Orden canónico de los segmentos (los no seleccionados se omiten):

```
NIT   texto libre   INICIALES_SECUENCIA   HASH_B64   DDMMYYYY   ALEATORIO(12)
901.409.813-7 AEGIS_04829173 xgXuB9Dj7EXz9mhV 25082026 90685R83CCJU
```

- **Secuencia autónoma**: permutación multiplicativa modular sobre un contador
  interno (`CodeSequenceModel`), `seq = (n * A) mod 10^8` con `gcd(A, 10^8) = 1`.
  Es biyectiva: no se repite dentro del ciclo y nunca es consecutiva.
- **Código aleatorio**: 12 caracteres por defecto, alfabeto sin `I O 0 1`. Es
  también el `public_code` con el que se verifica el documento.
- **Hash**: base64 urlsafe sin relleno del SHA-256 del **archivo original**,
  truncado a 16 caracteres por legibilidad del simbolo.

### La dependencia circular hash / código

El hash del archivo estampado no existe hasta estampar, pero el código
estampado debería llevar un hash. La regla adoptada: **el código certifica el
contenido que se certificó**, es decir el hash del original. Los hashes del
certificado y de la copia se calculan después del estampado y se almacenan.

### Restricciones del código de barras

Code128 solo se emite con `[A-Za-z0-9 ._-]`. Se rechazan URLs (`://`, `:`),
`? & # % = + < > " ' \ | / @` y demás. Todo eso va en el QR. Por encima de 48
caracteres se avisa (no se bloquea); el límite duro son 80.

### Marca de agua imperceptible

Dos canales redundantes en la copia distribuible:

1. un **XObject de imagen incrustado en los recursos de cada página pero nunca
   referenciado desde el flujo de contenido**: está en el archivo, no se dibuja
   ni se imprime, y la plataforma puede extraerlo y mostrarlo;
2. una clave privada en los metadatos `/Info`.

Ambos llevan el mismo token `GEAWM1|<uuid>|<hmac-sha256(SECRET_KEY, uuid)[:16]>`.
El HMAC impide fabricar copias con marca válida sin la `SECRET_KEY`.

### Estampado

`StampLayoutModel` + `StampPlacementModel` definen dónde va cada símbolo:
tipo (QR/barcode), páginas (primera / última / todas / concretas), anclaje a
una esquina, desplazamientos y tamaño en puntos PostScript. Un layout marcado
`is_default` se aplica a los documentos que no tengan uno asignado. El overlay
se genera con ReportLab y se fusiona con pypdf: **el contenido original no se
reconstruye**.

### Vista previa del estampado

`public/staticfiles/js/stamp_preview.js` dibuja una página a escala y coloca
un resumen por posición. **Replica exactamente
`services/pdf_stamp.py::_resolve_position`**, y ambas implementaciones se
contrastan con casos aleatorios sobre los seis anclajes: si se toca una, hay
que tocar la otra.

Se usa en cinco sitios, con el mismo componente:

| Dónde | Modo |
|---|---|
| Admin, `StampLayoutModel` | Editable, enlazado al formset inline |
| Dashboard, editor de disposición | Editable, enlazado al formset |
| Dashboard, **generador de códigos** | Editable, sobre el PDF real, con tabla y guardado por API |
| Dashboard, listado de disposiciones | Solo lectura, desde `preview_data` |
| Dashboard, detalle del código | Solo lectura |

En modo editable se puede **arrastrar un resumen**: el JS convierte el
desplazamiento a puntos y escribe de vuelta `offset_x`/`offset_y` respetando el
anclaje (con anclaje derecho, mover a la izquierda *aumenta* el offset). Una
posición que se sale de la página se pinta en rojo discontinuo.

⚠️ **Durante el arrastre no se repinta la vista completa**, solo se recoloca la
caja que se mueve. Un `render()` por cada `pointermove` destruye el propio
elemento arrastrado, se pierde la captura del puntero y el arrastre se queda
clavado tras el primer pixel. El repintado completo va en `pointerup`.

### El PDF de fondo

Con `data-pdf-input`, el componente pinta la página real del PDF elegido,
renderizada con **pdf.js** en el navegador: el archivo se lee del propio input,
**no se sube para esto**. De ahí salen el tamaño real de página (que manda
sobre el selector de tamaños) y el número de páginas, y con eso los resúmenes se
muestran **solo en las páginas donde de verdad caen** (`appliesToPage`, espejo
de `resolved_pages`).

⚠️ pdf.js no admite dos `render()` simultáneos sobre el mismo lienzo: hay que
cancelar la tarea anterior antes de lanzar la siguiente. Las resúmenes se recolocan
en cuanto se conoce la geometría, sin esperar a que el lienzo termine, para que
un fallo del render no deje la vista a medias. Si pdf.js no carga, se sigue
trabajando sobre la página en blanco y se avisa.

### Guardado desde el generador

`api.py` expone las disposiciones en JSON, sin DRF:

| Verbo | Ruta | Qué hace |
|---|---|---|
| GET | `layouts/<pk>/placements/` | Lee las posiciones |
| PATCH | `layouts/<pk>/placements/` | **Reemplaza** el conjunto completo |
| POST | `layouts/save/` | Crea una disposición (nombre obligatorio + descripción) |

El PATCH sustituye todas las posiciones de una vez dentro de una transacción:
es lo que envía el editor, y evita casar identificadores en el cliente. Toda
entrada se valida contra las choices del modelo antes de tocar nada.

### Historial de códigos emitidos

`code_generate` ya no devuelve el resultado en el propio POST: **redirige a
`code_detail`**, una URL permanente. Con eso se arregla de paso que recargar la
página de resultados volvía a emitir un código —y a certificar de nuevo el
documento—, y el operador puede cerrar la pestaña y volver más tarde sin pasar
por el admin.

`CodeRegistrationModel.document` (FK opcional) enlaza el código con el
documento que se certificó, de modo que el detalle muestra también los tres
archivos, las huellas y el registro de certificación. Los símbolos no se
almacenan: se vuelven a renderizar desde el payload, así que nunca pueden
divergir del código registrado.

### Verificación por archivo

Tres canales, del más estricto al más tolerante:

1. **Huella exacta** (SHA-256 de los bytes). Reconoce cualquiera de los tres
   archivos byte a byte.
2. **Huella de contenido** (`canonical_pdf_hash`): SHA-256 sobre caja de página,
   rotación, flujos de contenido y XObjects, **ignorando** `/Info`, `/ID`, la
   estructura física del archivo y el recurso de la marca de agua. Sobrevive a
   los cambios de metadatos del transporte por correo. Como certificado y copia
   comparten esta huella, se distinguen por la presencia de la marca.
3. **Marca de agua**: si el contenido ya no coincide pero la marca sigue válida,
   el archivo salió de la plataforma **pero fue modificado** → se rechaza
   diciéndolo.

Sin ningún cotejo, el archivo no corresponde a un documento certificado.

### Registro de certificación (auditoría)

Un certificado tiene dos mitades, y conviene no confundirlas:

| | Qué es | De dónde sale |
|---|---|---|
| **Contenido jurídico** | Lo que la firma declara sobre el activo | El documento y la firma del representante legal. La plataforma lo registra, **no lo avala** |
| **Integridad digital** | La prueba de que el archivo no fue alterado | Las huellas, el QR, el código de barras y la marca de agua |

El **registro de certificación** acredita solo la segunda. Es un JSON
determinista y sellado, descargable desde el detalle público
(`certificates:certification_record`), pensado para adjuntarse a un expediente:

```json
{
  "schema": "gea.certification-record/1",
  "status": "VALID",
  "algorithm": "SHA-256",
  "certificate": { "id": "...", "public_code": "...", "code": "NIT INICIALES_SEC HASH FECHA ALEATORIO" },
  "issuer": { "name": "PROPENSIONES ABOGADOS INTERNACIONAL S.A.S.", "nit": "901.409.813-7" },
  "files": {
    "original":    { "sha256": "H0", "content_sha256": "..." },
    "certified":   { "sha256": "H1", "content_sha256": "..." },
    "public_copy": { "sha256": "H2", "content_sha256": "..." }
  },
  "dates": { "issued_at": "...", "certified_at": "...", "expires_at": "...", "record_generated_at": "..." },
  "verification_url": "https://...",
  "scope": { "attests": "...", "does_not_attest": "..." },
  "how_to_verify": [ "..." ],
  "seal": { "algorithm": "Ed25519", "key_id": "...", "public_key": "...", "signature": "..." }
}
```

Van las **tres** huellas, no solo dos: el auditor puede tener en la mano
cualquiera de los tres archivos y el registro le dice cuál es.

**Sello.** Con `CERTIFICATION_SIGNING_KEY` configurada (Ed25519, generada con
`manage.py generate_certification_key`), el sello es una firma asimétrica que
**cualquiera** verifica en local con la clave pública publicada en
`certificates:certification_public_key`. Sin esa clave el registro se sella con
un HMAC simétrico que solo la propia plataforma puede comprobar, y el registro
lo dice de forma explícita en `seal.warning`. La firma cubre todos los campos
salvo `seal`, serializados como JSON compacto con claves ordenadas en UTF-8.

**Lo que el registro no congela**: el vencimiento y la revocación. `status` es
el del momento en que se generó; para el estado vivo hay que abrir
`verification_url`.

### URLs permanentes

`public_base_url()` devuelve siempre `PUBLIC_BASE_URL` y **nunca** deriva del
host de la petición: el QR queda estampado dentro de un PDF que circulará
durante años, y certificar desde `runserver` en la LAN grabaría un
`http://192.168.x.x:8000` dentro del documento para siempre.

### Formatos

Certificación y verificación por archivo: **PDF únicamente**. El archivo subido
para verificar no se almacena: se calcula su huella en memoria y se descarta.

---

## 7. Galería multimedia (`video_masonry`)

| Modelo | Contenido |
|---|---|
| `MediaAsset` | Archivo (imagen o vídeo), `media_type` inferido, caption, `remove_audio`, `size_bytes` |
| `MediaAssetInteraction` | Log por evento: `VIEW` / `DOWNLOAD`, usuario, activo |
| `MediaAssetUserStats` | Agregado por (usuario, activo): contadores y últimas fechas |

- Layout *masonry* paginado de 15 elementos, solo para compradores.
- **Eliminación de pista de audio** en vídeos vía `ffmpeg` (`strip_audio_ffmpeg`, `-c:v copy -an`) cuando `remove_audio` está activo — requiere `ffmpeg` en el `PATH` del servidor.
- Descarga en *streaming* (`FileResponse`) contabilizada; visualización contabilizada mediante POST a `video_masonry:track` desde JavaScript al abrir el modal.
- `MediaAssetUserStats.inc_view()` / `inc_download()` como métodos de clase idempotentes.

---

## 8. Seguridad perimetral y anti-abuso

### Middleware propio (`apps/common/utils/middleware/`)

| Middleware | Función |
|---|---|
| `RedirectWWWMiddleware` | Normaliza `www.` → dominio canónico |
| `RedirectAuthenticatedUserMiddleware` | Usuario logueado en `two_factor:login` → `core:index` |
| `BlockBadBotsMiddleware` | Bloquea user-agents de bots indeseados |
| `DetectSuspiciousRequestMiddleware` | Bloqueo temporal de IP con backoff |

`DetectSuspiciousRequestMiddleware`:
1. Si `is_safe_path(path)` (assets, UUIDs, extensiones conocidas) → pasa sin tocar la BD.
2. Si la IP está en `IPBlockedModel` y sigue bloqueada → responde **403** con la plantilla de error, incrementa `attempt_count` y **extiende el bloqueo** `IP_BLOCKED_TIME_IN_MINUTES` más en cada intento.
3. Registra en `session_info` (JSON) los paths intentados, user-agent, referer y timestamp.

### Modelos de control de IP
- `IPBlockedModel` (`apps_common_utils_ipblocked`) — IP, razón (`ReasonsChoices`), `blocked_until`, `session_info`.
- `WhiteListedIPModel` (`apps_utils_whitelistedip`) — excepciones.

### Ruta trampa
`HttpRequestAttackView` captura cualquier path que contenga un término de `COMMON_ATTACK_TERMS` (regex generada en `attack_patterns.py`) y dispara el bloqueo. **Cuidado con el orden del URLconf**: se registra antes que `assets`, `buyers` y `account` (ver [ROUTES_MAP.md §7](ROUTES_MAP.md)).

### `robots.txt`
`Disallow: /` para todo, con entradas explícitas para GPTBot, Google-Extended, ClaudeBot, Claude-User, Claude-SearchBot, PerplexityBot, Perplexity-User, Meta-ExternalAgent y Applebot.

### Endurecimiento en producción (`DEBUG=False`)
HSTS 1 año con preload y subdominios, `SECURE_SSL_REDIRECT`, cookies `Secure`, `CSRF_COOKIE_SAMESITE='Strict'`, `X_FRAME_OPTIONS='DENY'`, nosniff, XSS filter. `ALLOWED_HOSTS` desde entorno. Admin en URL secreta. `ATOMIC_REQUESTS = True` en la conexión por defecto.

### Cifrado de datos
`FIELD_ENCRYPTION_KEY` + `django-encrypted-model-fields` para PII (documentos, fechas y emails sensibles en `UserPersonalInformationModel`).

---

## 9. Internacionalización y traducción automática

- Idiomas: **español** (por defecto de contenido) e **inglés**; `LANGUAGE_CODE = 'en'`, `TIME_ZONE = 'UTC'`.
- `LOCALE_PATHS` se genera dinámicamente: un directorio `locale/` por cada app de `ALL_CUSTOM_APPS`, más `app_core/locale` y `templates/locale`.
- **Patrón bilingüe por campos duplicados**: la mayoría de modelos llevan pares `es_*` / `en_*` en vez de usar `django-parler` (que está instalado y configurado, pero apenas se usa).
- Cambio de idioma en caliente vía `utils:set_language`.
- **Traducción automática con OpenAI**: `ChatGPTAPI` (`gpt-4o-mini`, timeout 20 s) rellena el campo vacío del par es/en mediante señales `pre_save` en `AssetCategoryModel`, `AssetsNamesModel`, `AssetModel` y `OfferModel`. El *system prompt* incluye el contexto del dominio (bonos alemanes, oro, billetes de alta denominación).
- `rosetta` permite editar los `.po` desde el panel de administración.
- Utilidad aparte: `apps/common/utils/management/transcribe.py` — transcripción bilingüe de audio/vídeo con la Audio API de OpenAI (`gpt-4o-transcribe` + traducción con `gpt-4o`).

---

## 10. Auditoría y trazabilidad

- **`django-auditlog`**: `TimeStampedModel` incluye `AuditlogHistoryField`, y los modelos se registran con `auditlog.register(...)`. `AuditlogMiddleware` asocia cada cambio al usuario que lo hizo.
- **Sellos de actor** en el flujo de órdenes: 12 pares `*_by` / `*_at` en `OfferModel`.
- **`CertificateViewLogModel`** para consultas públicas de certificados.
- **`MediaAssetInteraction`** para la galería.
- **`IPBlockedModel.session_info`** para intentos sospechosos.
- **`django-axes`** para intentos de login.
- Campos base heredados de `TimeStampedModel`: `created`, `updated`, `is_active`, `language`, `default_order` (`ordering = ['default_order']` por defecto).

---

## 11. Operación

### Cron (`django-crontab`)

| Expresión | Tarea | Función |
|---|---|---|
| `0 19 * * *` | Código diario GEA | `apps.common.utils.cron.generate_and_send_gea_code` |
| `*/3 * * * *` | Warm-up de la app | `apps.common.utils.cron.warm_gea_app` (GET a `/health/`) |

### Código diario GEA — `GeaDailyUniqueCode` (`utils_gea_daily_unique_code`)
Dos variantes (`KindChoices`): `GENERAL` (facilitador, representante, tenedor) y `BUYER` (compra).
`get_or_create_for_today()` es atómico y garantiza unicidad por `(fecha, kind)`.
`send_today()` envía el código por email a `GEA_DAILY_CODE_*_RECIPIENTS` y registra `sent_to`, `sent_at` y `last_email_message_id`.

### Comandos de gestión (`apps/common/utils/management/commands/`)

| Comando | Función |
|---|---|
| `generate_gea_code` | Genera y envía los códigos diarios GENERAL y BUYER |
| `db_backup [-o DIR]` | 4 volcados JSON (con/sin usuarios × indentado/compacto), excluyendo tablas de sistema y logs |
| `clear_cache` | Vacía el backend de cache por defecto |
| `start_app` | `startapp` extendido: fija el `name` completo en `apps.py` y crea `urls.py` |
| `runserver` | Sobrescribe el de Django: `0.0.0.0:8000` e imprime la IPv4 LAN clicable |
| `delete_migrations` | ⚠️ Borra todos los ficheros de migración salvo `__init__.py`, respetando la lista de `apps/common/utils/data/skip_apps.txt` (hoy vacío) |
| `rename_migrations` | Renombra `0001_initial.py` añadiendo un sufijo aleatorio de 4 caracteres |

### Health check
`GET /health/` → JSON con `database`, `cache` y `email`. `200` si todo OK, `503` si algo falla.

---

## 12. Capa de presentación

- **Bootstrap 5.2.3** por CDN, iconos Bootstrap Icons + Feather Icons + Font Awesome (kit).
- Jerarquía de plantillas: `templates/raw.html` (base HTML, manifest PWA, favicons, canonical) → `dashboard/dashboard_layout_base.html` (sidenav + nav + footer) → páginas.
- Sidenav con **navegación por rol**: bloque comprador (`is_buyer`), bloque tenedor (`is_asset_holder` + `is_verified_holder`), selector de idioma, 2FA y cambio de contraseña.
- Interactividad AJAX sin framework SPA: el wizard de órdenes intercambia HTML renderizado en servidor vía JSON.
- Estáticos propios en `public/staticfiles/` (~45 MB de imágenes/vídeo), servidos con `django-compressor`; imágenes en **WebP**, vídeo hero MP4 con variante móvil.
- Página de error única `templates/errors_template.html` para 400/401/403/404/500/503/504, con mensaje ampliado para staff.

---

## 12-bis. Resumen AEGIS, master hash y anclaje temporal

### El resumen

`AegisSummaryModel` agrupa N certificados bajo un único **master hash**, y
`AegisSummaryDocumentModel` les asigna su código dentro del resumen (AEGIS-1…).
Solo entran documentos **certificados**: uno sin certificar no tiene huella.

### El master hash

Payload canónico **JCS/RFC 8785** (`services/jcs.py`), que ordena las claves
por unidades de código UTF-16 y **rechaza flotantes** — reproducir el algoritmo
de números de ECMAScript es la parte frágil de JCS, y es preferible fallar
ruidosamente a emitir un hash irreproducible.

De cada miembro entra `sha256` = **`document_hash`** (el archivo certificado,
el que hace fe) y `content_sha256` como campo aparte. El vínculo con el activo
es por **UUID**; la etiqueta es solo para leerlo.

⚠️ **La circularidad**: el master hash cubre a los miembros y **nunca al propio
resumen**. El orden es sellar → emitir el resumen llevando ese hash → registrar
la huella del resumen. Si el resumen entrara en su propio hash no habría forma
de calcularlo.

El payload se guarda **verbatim**: `sha256sum` sobre los bytes descargados en
`certificates:summary_master_payload` da la cifra anclada.
`verify_master_hash()` distingue dos fallos: registro corrupto (el hash no
corresponde a los bytes) y resumen modificado tras sellarse (los bytes ya no
describen a los miembros).

### El documento resumen

Es el único que lleva **códigos de otros**. Dos tipos de posición nuevos:
`MEMBER_BARCODE` (con `member_code` diciendo de qué documento es) y
`ANCHOR_QR`. Los códigos de los miembros **se re-renderizan desde su payload
almacenado**, nunca se copia la imagen, para que no puedan desincronizarse del
código realmente emitido.

Se guarda como un `DocumentVerificationModel` más, así que hereda gratis los
tres archivos, la marca de agua, la verificación por archivo y el registro de
certificación.

### Anclaje temporal

| | RFC 3161 (TSA) | OpenTimestamps (Bitcoin) |
|---|---|---|
| Confianza | En la TSA | En nadie |
| Nace | Confirmado | **Pendiente**, madura en 1-6 h |
| Caduca | Sí, el certificado de la TSA | No |
| Coste | Céntimos | 0 |
| Módulo | `services/tsa.py` (asn1crypto) | `services/ots.py` |

Se anclan juntos porque cubren el fallo del otro. Lo que sale de la plataforma
es **solo el master hash**: 78 bytes en la petición TSA, nunca el documento ni
el payload.

⚠️ Una TSA **gratuita es técnicamente idéntica pero no tiene peso legal**. Sin
`CERTIFICATION_TSA_URL` no se sella — no hay fallback silencioso.

### La URL estable del anclaje

El QR estampado **no contiene la prueba**, sino la URL de
`certificates:summary_anchor` — pública y sin OTP a propósito, porque es lo que
abre quien escanea el papel, y solo muestra hashes y fechas. La página se
actualiza sola según maduran los anclajes, así que **el PDF no se reemite
nunca**. Un OTS pendiente no cuenta como fecha acreditada: hay compromiso, no
bloque.

`manage.py upgrade_ots_anchors` (cron horario) madura las pruebas.

### El compositor

`code_gen:summary_compose`: elige los miembros, «trae los códigos de barras» —
crea una posición por miembro, ya enlazada a su código— y se arrastran sobre la
vista previa del PDF real. Cambiar los miembros **invalida el sello** y lo
limpia, para que nadie lo confunda con vigente.

---

## 13. Funcionalidad presente pero inactiva

| Elemento | Estado |
|---|---|
| `apps.project.common.notifications` | App instalada, sin modelos, vistas ni rutas |
| `apps.common.utils.api`, `apps.project.common.account.api` | Andamiaje de API (serializers/views/urls vacíos); **DRF no está instalado** |
| `PortfolioTemplateView` | Vista definida, sin ruta ni plantilla |
| `django-parler` | Configurado (`PARLER_LANGUAGES`), pero el bilingüismo se resuelve con campos `es_*`/`en_*` |
| `custom_processors` | Context processor registrado que devuelve un dict vacío |
| Plantillas `employee_propensiones/`, `idoneity/` | Existen en `templates/`, sin rutas propias (se sirven vía tipo de certificado) |
