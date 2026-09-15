# CLAUDE.md — Contexto del proyecto GEA para asistentes de IA

Ficha técnica del repositorio `gea_module_0`. Léela antes de tocar código.
Documentos complementarios:

- [`docs/ROUTES_MAP.md`](docs/ROUTES_MAP.md) — todas las URLs, namespaces, vistas y permisos.
- [`docs/FEATURES_MAP.md`](docs/FEATURES_MAP.md) — funcionalidades por dominio, modelos y reglas de negocio.
- [`docs/NORMATIVA.md`](docs/NORMATIVA.md) — qué exigen los reguladores a la certificación, por qué no se adopta W3C VC y qué falta en su lugar.
- [`docs/DJANGO_5_2.md`](docs/DJANGO_5_2.md) — la subida de Django 4.2 a 5.2: el checklist de
  cambios rompedores comprobado uno a uno contra este codigo, lo que hubo que cambiar, y **lo
  unico que puede impedir que el servidor arranque** (la version de la base de datos).
- [`docs/SEGURIDAD.md`](docs/SEGURIDAD.md) — checklist de despliegue en dos minutos, y la auditoría con lo que se encontró y por qué importa.
- [`docs/ANCLAJE.md`](docs/ANCLAJE.md) — el anclaje temporal explicado de punta a punta: los dos tiempos, quién madura las pruebas, dónde se mira el estado y qué significa cada uno.
- [`docs/verificar-certificado.html`](docs/verificar-certificado.html) y [`docs/verify-certificate.html`](docs/verify-certificate.html) — **para enseñar fuera**, no para desarrollar: el recorrido público de verificación paso a paso, con capturas anotadas, qué se entrega y qué se puede compartir. Es el mismo recorrido que describen los otros documentos, contado para un titular o un auditor. **Son la misma guía en español y en inglés**, generadas del mismo guion: el texto vive en tablas por idioma con las mismas claves, así que una frase añadida en uno y olvidada en el otro falla al generar y no en la página. Los recuadros de las capturas salen de medir la caja real de cada elemento en el navegador, no de estimarla. Si cambian esas pantallas, las capturas se quedan viejas y hay que rehacerlas.

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
| Framework | **Django 5.2 LTS** (`>=5.2,<6.0`) |
| Gestor de paquetes | **uv** (`uv.lock`, `pyproject.toml`); `requirements.txt` se exporta desde uv |
| Base de datos | MySQL o PostgreSQL — se elige por la variable `DB_ENGINE`; charset `utf8mb4` |
| Frontend | Plantillas Django + **Bootstrap 5.2.3** (CDN), AJAX con HTML renderizado en servidor. Sin SPA, sin build de JS |
| Estáticos | `django-compressor`, `public/staticfiles/` (~45 MB), imágenes en WebP |
| PDF | ReportLab (capa de estampado), **pypdf** (fusión, lectura y marca de agua), `python-barcode` (Code128), `qrcode` |
| IA | OpenAI (`gpt-4o-mini` para traducción es↔en, `gpt-4o-transcribe` para audio) |

**Terceros clave**: `django-two-factor-auth` + `django-otp` (2FA), `django-axes` (fuerza bruta),
`django-auditlog` (auditoría), `django-encrypted-model-fields` (PII cifrada), `django-import-export`,
`django-crontab`, `django-select2`, `django-formtools` (wizards), `rosetta`, `impersonate`,
`argon2-cffi`.

`django-filter`, `django-parler` y `django-countries` **ya no estan**: estaban
en `INSTALLED_APPS` sin un solo import, campo ni migracion, y en la subida a
Django 5.2 obligaban a comprobar la compatibilidad de tres paquetes que no
hacen nada. Ver [`docs/DJANGO_5_2.md`](docs/DJANGO_5_2.md) §5.

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
uv run python manage.py check_security
```

Nueve secciones: las seis propias de este proyecto (vistas sin guardia,
formularios sin freno, shell, SQL por cadenas, carpetas de subidas, ajustes) y
tres de herramientas de fuera.

**El reparto de los escáneres de dependencias no es redundancia:**

| | Dónde corre | Credencial |
|---|---|---|
| **pip-audit** | servidor **y** local | ninguna |
| **safety** | sólo local (`DEBUG=True`) | `SAFETY_API_KEY` |

- **`pip-audit` es la de producción, y lo es porque no lleva credencial.** Un
  chequeo que depende de un secreto deja de funcionar el día que el secreto
  caduca, y eso no se nota hasta el despliegue siguiente. Mira el **entorno
  instalado**, no `requirements.txt`: la versión que se ejecuta es la que puede
  tener el fallo.
- **`safety` ni se intenta en el servidor.** Safety CLI 3 siempre se autentica y
  sin credencial se queda esperando en el terminal — por cron o desde la
  consola, eso es un cuelgue. Saltársela en producción **no cuenta como hueco**
  (`ScanResult.by_design`): un aviso que sale en cada despliegue por algo que
  está bien acaba ignorándose junto con los que no lo están. Y la clave va **por
  el entorno, nunca como `--key=…`**: un argumento lo ve quien liste procesos y
  acaba escrito en `CommandRunModel` con el resto de la salida.
- Los tres son **opcionales** (`uv add --dev bandit pip-audit safety`) y lo que
  falte *sin estar previsto* se cuenta **aparte de los hallazgos**, al final: no
  haberlo ejecutado no es una vulnerabilidad, pero un «sin hallazgos» que se
  saltó una sección entera es una media verdad.
- Lo que bandit da por bueno está en `apps/common/utils/scanners.py`
  (`BANDIT_ACCEPTED`), con **la razón escrita al lado**, igual que
  `INTENTIONALLY_PUBLIC` o `NEVER_EXPOSED`. La clave es `(regla, fichero)`: una
  regla nueva, o la misma en un fichero nuevo, aflora; una segunda ocurrencia en
  un fichero ya aceptado, no.

```bash
uv run python manage.py test --settings=app_core.settings_test
```

La misma suite, guardando lo que normalmente se tira —qué prueba, de qué app,
cuánto tardó, cómo acabó— y midiendo la cobertura:

```bash
uv run python manage.py test_report
```

El resultado se lee en el panel, en «Resumen de pruebas» (§4-bis.F). Dos cosas
que hay que saber antes de tocarlo:

- **`coverage` es opcional.** No está en `requirements.txt` a propósito: es
  herramienta de desarrollo y el servidor no la necesita. Sin ella el comando
  hace el informe de resultados y lo dice, en vez de fallar. Para tenerla,
  `uv add coverage` **y** el `uv export` de siempre, o `check_requirements` la
  echará en falta.
- **La cobertura descuenta las pruebas y las migraciones.** Un fichero de
  pruebas se ejecuta entero por definición, así que contarlo sube el
  porcentaje por escribir más pruebas de lo mismo: con ellas dentro este
  proyecto daba un 76 %, sin ellas da el 67 % de verdad. Un número que se
  infla solo se usa para decidir dónde no hace falta mirar, que es justo
  donde hay que mirar.

Volcado UTF-8 completo de la base de datos:

```bash
python -Xutf8 manage.py dumpdata --natural-foreign --natural-primary --exclude auth.permission --exclude contenttypes --indent 2 --output db_data.json
```

Añadir dependencias y reexportar:

```bash
uv add <paquete>
```

```bash
uv export --no-dev --format=requirements-txt > requirements.txt
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
| **Detector de enumeración (ráfagas de 404)** | `apps/common/utils/scanning.py` |
| **De qué red viene una IP (cloud/ASN/país)** | `apps/common/utils/netintel.py` |
| **Duración de un bloqueo y columnas de la fila** | `apps/common/utils/blocking.py` |
| **Cifrado de los respaldos** | `apps/common/utils/backup_crypto.py` + `management/commands/db_backup.py` |
| Tareas programadas | `apps/common/utils/cron.py` |
| Filtros y tags de plantilla | `apps/common/utils/templatetags/custom_filters.py` |
| Landing pública y `health/` | `apps/common/core/views.py` |
| **Documentos legales: texto, aprobación y aceptación** | `apps/common/core/models.py` + `legal.py` (constancia) + `legal_html.py` (saneado) + `legal_pdf.py` |
| Usuario, PII cifrada, geografía | `apps/project/common/users/models.py` |
| Registro por wizard, recuperar contraseña | `apps/project/common/account/views.py` + `forms/` |
| **Entrar con código al correo** | `account/login_view.py` (los pasos) + `account/otp_login.py` (el código) + `account/emails.py` |
| **El correo con el código, para los dos sitios** | `apps/common/utils/otp_email.py` + `templates/email/otp_email.html` |
| **Contador de intentos fallidos (las tres puertas)** | `apps/common/utils/login_attempts.py` |
| Catálogo de activos y traducción automática | `assets/models.py`, `assets/signals.py` |
| Ubicaciones e inventario por ubicación | `assets_location/models.py`, `views.py` |
| **Flujo de 12 etapas de una orden** | `buyers/models.py` (`status_code`, `mark_*`, `CheckConstraint`) |
| **Quién puede ver/editar una orden** | `buyers/access.py` — no está repartido por las vistas |
| **Quién ve qué en el histórico de códigos** | `code_gen/access.py` — operador frente a titular; el filtro va en el queryset |
| Wizard de aprobación (UI + acciones) | `buyers/views.py` (`OfferApprovalWizard*`) + `templates/dashboard/pages/buyers/wizard/` |
| PDFs de orden de compra / de servicio | `buyers/functions/generate_*.py` |
| Verificación pública, OTP, entrega de PDF | `certificates/views.py`, `mixins.py`, `files.py` |
| Cotejo de un archivo subido | `certificates/verification.py` |
| Modelos de certificación y resúmenes AEGIS | `certificates/models.py` |
| **Algoritmos de certificación** | `internal/code_gen/services/` (ver §4-bis.E) |
| Generador de códigos, disposiciones, resúmenes | `code_gen/views.py`, `forms.py`, `api.py`, `preview.py` |
| **Historial de códigos agrupado por resumen** | `code_gen/history.py` — lo que se pagina son ramas, no filas |
| **Si un resumen se puede llevar en un USB** | `code_gen/services/usb_readiness.py` — las cinco condiciones y qué hacer con cada una |
| **La hora que acredita un bloque de Bitcoin** | `code_gen/services/bitcoin_time.py` — dos exploradores, y solo si coinciden |
| **Descargar la prueba de un anclaje (.ots / .tsr)** | `certificates/views.py::summary_anchor_proof` |
| **Lo que se graba en ese USB** | `code_gen/services/usb_bundle.py` + `code_gen/usb_kit/` (los tres guiones) |
| Consola de operaciones | `internal/ops/registry.py`, `runner.py`, `admin.py` |
| Galería multimedia | `documents/video_masonry/` |

### D. Los cuatro flujos, de punta a punta

**1. Alta y acceso**
`two_factor:login` → `GeaUserRegisterWizardView` (`account/views.py`, `formtools`) → `UserModel`
(`user_type` I/R/H/B) + `UserPersonalInformationModel` (PII cifrada). El registro de comprador exige el
código diario (`GeaDailyUniqueCode`, emitido por cron a las 19:00). `email_hash` se recalcula en
`UserModel.save()` y lo consume el flujo de recuperación de contraseña — y también la búsqueda del
código de acceso, porque el correo va cifrado con Fernet y `filter(email=...)` devuelve cero siempre.

`two_factor:login` lo sirve **`GeaLoginView`** (`account/login_view.py`), que es el asistente de
`django-two-factor-auth` con un paso más:

```
auth    usuario y contraseña             ← siempre presente
otp     usuario/correo **y** el código   ← solo en modo código
token   el segundo factor, si lo hay
backup  el código de respaldo
```

Los seis recorridos posibles, que están probados de punta a punta en `tests_login_paths.py`:

| Se entra con… | Sin 2FA | Con 2FA |
|---|---|---|
| Contraseña correcta | dentro | pantalla del 2FA → dentro |
| Tres contraseñas falladas → código | dentro | pantalla del 2FA → dentro |
| Código pedido a propósito | dentro | pantalla del 2FA → dentro |

Y en cualquiera de ellos, un fallo suma al **mismo** contador hasta `AXES_FAILURE_LIMIT` → bloqueo.

Cuatro cosas que hay que entender antes de tocarlo:

- **El código sustituye a la contraseña, no al segundo factor.** Por eso vive dentro del asistente:
  deja el usuario autenticado en el primer paso y el TOTP se sigue pidiendo después. Una vista aparte
  que llamara a `login()` convertiría el acceso al correo de alguien en una forma de saltarse su 2FA.
- **El código es una sola pantalla**, con el identificador y las seis cifras a la vez, un botón que
  manda el correo (`send_code`, atendido en `post()` antes de validar nada) y otro que entra. Pedir el
  código no puede exigir un código que aún no existe, de ahí que el envío no pase por el formulario.
- **El paso `auth` no sale nunca de la lista**, ni siquiera al ofrecer el código. Si saliera, un envío
  de contraseña posterior no llegaría a validarse, `django-axes` no contaría ese fallo y su bloqueo
  --seis intentos-- no se alcanzaría jamás desde el navegador: la comodidad habría apagado el freno.
  La oferta se hace **una sola vez** por intento (`OFFERED_KEY`) por el mismo motivo.
- **Preguntar por un usuario no dice si existe.** La pantalla contesta lo mismo para una cuenta real
  y para una inventada, y el correo solo sale si hay a quién mandárselo. Por eso el aviso «te hemos
  enviado un código» se decide con `requested` y no con `code_hash`: con el hash, el aviso
  desaparecería justo para los identificadores que no existen.

El código se guarda hasheado (HMAC-SHA256 sobre `SECRET_KEY`) en la sesión, que va en base de datos:
sigue en pie aunque Redis se caiga. El envío pasa por dos cupos de `RateLimit` que **fallan cerrados**,
uno por destinatario y otro por origen.

**Los tres caminos cuentan en el mismo contador.** Contraseña, código y segundo factor apuntan sus
fallos con `apps/common/utils/login_attempts.py::note_failure()` y consultan el bloqueo con
`is_locked_out()` **antes** de comparar nada. Antes solo contaba la contraseña, así que el camino más
barato para quien atacaba --seis cifras, quince minutos de vida-- era justo el que no dejaba rastro.

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

resumen AEGIS: master.seal_summary() (payload JCS verbatim)
             → anchoring.anchor_with_tsa() (instantáneo) y anchor_with_ots() (madura por cron)
             El compositor ofrece «sellar y enviar» y «solo sellar»: sellar es una
             escritura nuestra e instantánea, enviar sale a la red. El envío NUNCA
             propaga su fallo (con ATOMIC_REQUESTS desharía el sellado); se degrada a
             aviso y queda disponible en code_gen:summary_anchor. No se manda dos
             veces el mismo master hash.
             → summary.certify_summary() emite el PDF del resumen (code_gen:summary_issue).
             Es un DocumentVerificationModel más, con sus tres archivos. NO espera al
             anclaje y no debe: el QR estampado lleva la URL de la página de anclaje,
             no la prueba, así que se emite un solo papel y no hay que reestamparlo
             cuando llegue el bloque. Ver docs/ANCLAJE.md §5-bis.

consulta pública: certificates:input_document_verification_aegis → OTP por correo
   → OTPSessionMixin → detail → certificates:document_file (única vía de descarga)
                              → certificates:certification_record (JSON del registro)

entrega en USB: code_gen:summary_usb_export, desde el histórico agrupado
   └─ usb_readiness.export_state()   las cinco condiciones. Sin las cinco en
                                     verde no se genera nada (invariante 30)
   └─ usb_bundle.build_bundle()      arma el ZIP en memoria: copia pública,
                                     registro, clave pública, master payload
                                     verbatim, pruebas .ots/.tsr, las dos
                                     guías, el manifiesto y los tres guiones
                                     de `usb_kit/`. Nunca el `source_file`.
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
| `master.py` | Master hash de un resumen AEGIS sobre sus miembros |
| `summary.py` | Emisión del resumen AEGIS-6 (lleva códigos de otros documentos) |
| `anchoring.py` | Fachada de anclaje temporal; el QR lleva la URL, no la prueba |
| `tsa.py` / `ots.py` | RFC 3161 (instantáneo) / OpenTimestamps sobre Bitcoin (madura por cron) |
| `bitcoin_time.py` | La **hora** de un bloque: la prueba acredita una altura, no una fecha. Dos exploradores que tengan que coincidir, y solo desde el cron |
| `usb_readiness.py` | Si un resumen se puede exportar, y si no, por qué no |
| `usb_bundle.py` | El dossier del USB: se arma en memoria y no se guarda |
| `samples.py`, `preview.py` | Símbolos y contenedor de la vista previa de estampado |

La vista previa se dibuja en el navegador: `public/staticfiles/js/stamp_preview.js` **replica** la
geometría de `pdf_stamp.py`. Si cambias el posicionamiento en Python, actualiza también el JS.

### F. Consola de operaciones (`internal.ops`)

App sin rutas propias: `urls.py` está vacío a propósito y las páginas cuelgan del admin
(`admin:ops_console`, `admin:ops_command`, en `ops/admin.py::get_urls`, plantillas en `templates/admin/ops/`).
Se llega desde el índice del panel y desde el listado de ejecuciones; la entrada del índice la
inyecta `GeaAdminSite.get_app_list()`, porque la consola no es un modelo y el admin sólo lista
lo registrado. Sólo se le muestra a quien puede usarla: un enlace que lleva a un 404 no es una
pista útil, es una pista de que hay algo ahí.

Es una superficie de ejecución remota y por eso está acotada en cuatro puntos:
`registry.py` (lista blanca de comandos y de sus opciones), `runner.py` (ejecución **en subproceso**,
nunca dentro de la petición, por `ATOMIC_REQUESTS`), `models.py::CommandRunModel` (traza de quién
ejecutó qué) y el guardia de `admin.py`. Sólo superusuarios; aborta con 404, no con 403.
Al colgar del admin hereda además su puerta: hace falta segundo factor verificado (§6.7).

**Los comandos se separan por entorno.** Cada entrada declara `availability`:
`AVAILABILITY_ALWAYS` o `AVAILABILITY_DEBUG_ONLY`. Lo segundo es para lo que tiene
sentido en un portátil y ninguno en un servidor —`start_app`, `makemigrations`,
`makemessages`, `inspectdb`, `sqlsequencereset`, `test`—, todo lo cual escribe en el
repositorio: lo que se cree ahí no está en git y el siguiente `git pull` lo borra o
choca con él. **El filtro vive en `get_command()`, no en la plantilla**: esconder una
tarjeta no es un control, porque basta con teclear la URL. Al filtrar en el registro,
el runner recibe `None`, levanta `CommandNotAllowed` y la página responde 404.

⚠️ La separación por entorno **no** es donde se apoya la seguridad. `DEBUG` sale de una
variable de entorno y una variable se puede equivocar; por eso nada marcado `DANGEROUS`
puede ser `DEBUG_ONLY` (hay una prueba que lo impide). Lo peligroso no está en ningún
nivel: está fuera de la lista.

**Los tres cajones, y el inventario completo.** Todo comando instalado está en uno:

| Cajón | Qué es | Ejemplos |
|---|---|---|
| `COMMANDS` | Expuesto, con su nivel de entorno | `migrate`, `git_pull`, `start_app` (dev) |
| `NEVER_EXPOSED` | Prohibido siempre, con su razón | `auditlogflush`, `shell`, `diffsettings` |
| `NOT_USEFUL_HERE` | No es peligroso, no aporta nada | `startapp`, `createcachetable` |

Una prueba comprueba que **no queda ninguno sin decidir**: actualizar una dependencia
que traiga comandos nuevos falla el test, para que sea una decisión de alguien y no un
descuido. Si falla, la respuesta no es añadir el comando: es leer qué hace y meterlo en
el cajón que le toque, con su razón escrita.

Lo excluido por **cumplimiento regulatorio** va aparte y merece leerse: `auditlogflush`,
`axes_reset_logs` y `axes_reset_failure_logs` destruyen el rastro de quién hizo qué, en
el que se apoya la certificación ([`docs/NORMATIVA.md`](docs/NORMATIVA.md)) — y dejarían
su propia huella en `CommandRunModel`, contando que alguien borró la auditoría. Si algún
día hace falta purgar por retención, eso es un procedimiento escrito, no un clic.

Cuatro cosas más al añadir un comando:

- **La lista blanca es de programas, no de nombres de entrada.** `name` identifica la tarjeta
  (va en la URL y en la auditoría) y `program` dice qué se ejecuta de verdad, que no siempre
  coincide: `crontab_add` y `crontab_remove` son dos entradas del mismo `crontab` porque no
  tienen el mismo riesgo ni la misma explicación.
- **`fixed_args` es donde vive la seguridad de una entrada.** `--ff-only` en `git pull`,
  `--check --dry-run` en `makemigrations`. Si fueran opciones se podrían desmarcar.
- **Sólo hay dos ejecutables** (`EXEC_MANAGE`, `EXEC_GIT`) y están cerrados. Una ruta libre
  haría que la lista blanca no acotara nada: bastaría con declarar `bash`.
- **Todo texto lleva `pattern`.** Sin él, `runner.py` se niega a ejecutar: un campo de texto
  sin patrón es una cadena libre en la línea de comandos.

El docstring de `registry.py` enumera además lo que **no** está y por qué —`flush`, `dumpdata`,
`shell`, `diffsettings`, `generate_certification_key`, `auditlogflush`…—; léelo antes de añadir
nada, porque más de uno parece inofensivo hasta que se piensa dónde acaba su salida (en
`CommandRunModel`, escrita en una tabla).

**El resumen de pruebas** (`admin:ops_test_summary`, plantilla
`templates/admin/ops/test_summary.html`, datos en `ops/summary.py`) es la otra
página que cuelga del admin. Lee el último informe de
`MEDIA_ROOT/test_reports/latest.json` —lo escribe `manage.py test_report`— y lo
pinta: la cifra de cabecera, cómo acabó la suite, cuántas pruebas tiene cada
app, la cobertura por app y las diez más lentas.

Cuatro decisiones que no son de gusto:

- **Está cerrada en producción, con 404, igual que el comando.** Allí no hay ni
  puede haber un informe recién hecho, porque la suite se ejecuta con
  `settings_test`. Lo que se vería sería el de un portátil, con la fecha en
  letra pequeña y la cifra grande, leída como el estado del servidor.
- **El color nunca va solo.** En la paleta de estado el verde de «pasa» y el
  rojo de «falla» se separan un ΔE de 4 bajo deuteranopia: para bastante gente
  son el mismo color. Cada uno lleva su icono, su etiqueta y su número escrito.
- **Cada gráfica tiene su tabla**, detrás de un botón. Una barra que sólo se lee
  pasando el ratón no se lee con el teclado, ni se copia, ni se imprime.
- **No hay biblioteca de gráficas.** Las barras son cajas con un ancho en tanto
  por ciento que calcula `summary.py`; traer una por CDN sería un script de
  fuera más —con su `integrity`, y aquí no hay build que lo genere— para pintar
  lo que hacen cuatro reglas de CSS.

El informe se guarda bajo `MEDIA_ROOT` con su `.htaccess`: lleva nombres de
módulos, rutas del proyecto y la primera línea de cada traza, o sea un mapa del
código, y colgando de ahí sin eso se serviría solo (invariante 13).

### G. Puntos de entrada que no son el navegador

| Entrada | Dónde |
|---|---|
| Crons (`django-crontab`) | `settings.CRONJOBS`: `upgrade_ots_anchors` cada 15 min (sin pendientes no sale a la red), código diario 19:00, warm-up cada 3 min, `rotate_logs` cada hora (sin llegar al tope es un `stat`) |
| Comandos propios | `apps/common/utils/management/commands/` y `code_gen/management/commands/`, `certificates/management/commands/check_certifications.py` |
| Acciones del admin | «Certify» de `certificates/admin.py`; sellado y anclaje de resúmenes |
| Endpoints JSON internos | `code_gen/api.py` (disposiciones, miembros del resumen, símbolos de vista previa) |
| Señales | `assets/signals.py`, `buyers/signals.py` (traducción por OpenAI), `video_masonry/signals.py` |

Los directorios `api/` sueltos (`utils/api/`, `account/api/`) están vacíos: **no hay DRF**.

### H. Frontend

Sin build ni SPA. Plantillas Django + Bootstrap 5 por CDN; `templates/raw.html` →
`templates/dashboard/dashboard_layout_base.html` → página. Las plantillas globales viven en
`templates/` (no dentro de cada app, salvo `core/index.html`). JS a mano en `public/staticfiles/js/`:
`stamp_preview.js` y `layout_workspace.js` (editor de disposiciones), `summary_composer.js` (resúmenes),
`searchable_select.js`, `busy_buttons.js`, `toasts.js`, `simple-datatable.js`.

---

## 5. Convenciones del código

### Cómo se llaman las cosas
- **Un AEGIS es un *resumen*, no una *caja*.** No es un contenedor que guarda
  documentos: es un documento propio —con sus tres archivos y su certificación—
  cuyo contenido es llevar estampados los códigos de otros. Llamarlo «caja»
  sugiere que los documentos están dentro, y no lo están: lo que hay dentro son
  sus códigos. En inglés, *summary*; nunca *box*. La palabra «caja» solo vale
  para el rectángulo que se arrastra en la vista previa de estampado y para la
  `mediabox` del PDF.
- Los documentos que un resumen agrupa son sus **miembros**
  (`AegisSummaryDocumentModel`), y cada uno lleva su **código** en él
  (`AEGIS-1`, `AEGIS-2`…).

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
- **Los comentarios van en `{% comment %}…{% endcomment %}`, nunca en `{# … #}`.**
  Lo comprueba `apps/common/utils/tests_scripts.py`. Dos trampas al aplicarlo:
  `{% comment %}` **es una etiqueta**, así que no puede ir antes de
  `{% extends %}` —que tiene que ser la primera—; y dentro de un bloque
  `{% comment %}` ya existente no se anida otro, porque el `{% endcomment %}`
  interior lo cierra antes de tiempo y revive el código comentado.
- **Un script que ya carga `raw.html` no se vuelve a cargar en una página.**
  Cargar `busy_buttons.js` dos veces registraba dos escuchadores de `submit`, y
  el segundo tomaba por doble clic el envío que el primero acababa de marcar:
  el formulario no se enviaba, el botón se quedaba en «Procesando…» y no había
  ni petición en la red ni nada en el log. También lo comprueba esa prueba.

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
13. **Los archivos de certificación no se enlazan nunca por `MEDIA_URL`.** La única vía es `certificates:document_file`, que comprueba permisos: `source` y `certified` solo para `is_staff`/`is_superuser`; `public` para sesión OTP válida o autenticado. En el servidor hace falta además el `.htaccess` de `deploy/` — sin él el servidor web sigue sirviendo los PDF por su cuenta y estas reglas no pintan nada. **Y eso vale para toda carpeta de subidas con datos personales, no solo la de certificación**: `pqrs/` se cayó de esa lista al crear la app, y ahí un formulario público deposita cédulas. Al añadir un `FileField`, decide si su carpeta va bloqueada en `deploy/media.htaccess` o declarada en `PUBLICLY_SERVABLE_MEDIA` con su razón; `manage.py check_security` §5 no deja ninguna sin decidir.
15. **El master hash de un resumen nunca cubre al propio resumen.** Se sella sobre los miembros, luego se emite el resumen llevando ese hash, y solo después se registra su huella. Es la misma circularidad del código de barras y el hash del original, y no tiene otra solución.
16. **El QR del anclaje lleva una URL, no la prueba.** La página de `certificates:summary_anchor` se actualiza sola según maduran los anclajes; si el bloque de Bitcoin fuera impreso habría que reestampar el PDF cada vez. De ahí que **el documento del resumen se emita en cuanto el resumen está sellado**, con o sin anclaje, y que sea uno solo: dos papeles —«sin blockchain» y «con»— serían dos huellas distintas para el mismo resumen y habría que decidir cuál hace fe.
17. **El payload maestro se guarda verbatim.** No se reconstruye para verificar: se compara contra los bytes exactos que se hashearon. Cambiar `services/jcs.py` invalidaría todos los master hash ya anclados.
18. **Una orden aprobada ya no se edita ni se oculta desde las vistas de listado.** Aprobar crea la orden de servicio automáticamente (`OfferModel.save`, bloque B), así que a partir de ahí la orden es un documento vivo con PDF ya enviados a terceros: cambiarle la cantidad o ponerle `display = False` dejaría la base de datos contradiciendo lo repartido. Las reglas de quién puede hacer qué sobre una orden viven en `buyers/access.py`, no repartidas por las vistas. Y todo lo que tenga efecto hacia fuera —mandar la orden de servicio por correo— comprueba el estado **antes** de producir el efecto, no al guardar después.
14. **La trampa anti-escaneo empareja segmentos completos, no subcadenas** —pero el segmento puede llevar extensión (`/xmlrpc.php`) o empezar por punto (`/.env`), porque los términos se escriben sin ella y lo que llega siempre la trae. Antes `env` convertía `/envio/` en trampa y bloqueaba la IP del usuario; después, exigir barra o fin justo tras el término dejó pasar todo lo que de verdad se escanea y la trampa dejó de registrar nada. Los dos extremos están cubiertos en `tests_attack_patterns.py`. Al tocar `COMMON_ATTACK_TERMS`, ejecuta `manage.py check_attack_terms`: comprueba colisiones **respetando el orden del URLconf**, que es lo único que determina si una ruta queda secuestrada de verdad.
19. **La duración de un bloqueo por IP se calcula en un solo sitio.** `blocking.block_duration()` duplica en cada intento (15 min → 30 → 1 h → … → tope de 24 h en `MAX_BLOCK`), y la usan tanto la vista trampa como el middleware. Había dos políticas —una multiplicaba, la otra sumaba un intervalo fijo— así que el castigo dependía de por dónde hubiera entrado la petición. La duración sale del contador de intentos, no de lo que quedara del bloqueo anterior, y nunca se acorta uno en curso.
20. **Una IP bloqueada recibe un 404, y sólo eso.** Es byte a byte la misma página que cualquier ruta que no existe: sin mencionar el bloqueo, sin `attempt_count` y sin `blocked_until`. Un 403 que se anuncia le confirma al escáner que hay bloqueo por IP, que su sonda dio en la trampa y cuándo volver — la misma razón por la que el admin responde 404 (invariante 7). Todo lo que sirve para diagnosticar está en el log del servidor y en `IPBlockedModel`.
21. **Ningún contador de intentos se lleva leyendo la caché a mano.** Todos pasan por `RateLimit` (`apps/common/utils/throttling.py`), y por una razón concreta: con `IGNORE_EXCEPTIONS` puesto, `django-redis` **devuelve `None` en vez de lanzar**, así que `cache.get(k) or 0` da `0` y cualquier comparación contra un límite pasa. Eso apagaba los seis contadores durante cualquier avería de Redis, sin excepción, sin log y sin síntoma. `RateLimit` detecta la caída por lo que devuelve `incr` y **falla cerrado por defecto**; `fail_open=True` exige una `reason` escrita —el constructor lanza `ValueError` si falta— porque la decisión depende de qué impide el límite, no del límite. Y el cupo de un destinatario va por `scope`, nunca con la IP dentro de la llave: quien manda elige su IP, quien recibe no. Ver `docs/SEGURIDAD.md` §3.
22. **El código por correo entra en el asistente de acceso, no lo rodea.** Dos consecuencias que no se pueden romper. Una: el paso `otp` deja el usuario autenticado igual que el de contraseña, y el segundo factor se sigue pidiendo después — sacar esto a una vista propia que llamara a `login()` haría que el acceso al correo de alguien bastara para saltarse su 2FA. Y dos: el paso `auth` **no sale nunca** de la lista de pasos. Quitarlo al ofrecer el código haría que los envíos de contraseña posteriores no llegaran a validarse, `django-axes` no contaría esos fallos y su bloqueo de seis intentos no se alcanzaría desde el navegador; la oferta llegaría antes que el freno y de paso lo apagaría. Por lo mismo la oferta se hace una sola vez por intento. Lo cubren `account/tests_login_otp.py` y `account/tests_login_paths.py`.
23. **Las tres puertas del acceso cuentan sus fallos en el mismo sitio.** Contraseña, código al correo y segundo factor pasan todos por `apps/common/utils/login_attempts.py`: `note_failure()` dispara `user_login_failed` --que es la interfaz de `django-axes`, no se escribe en sus tablas a mano-- y `is_locked_out()` se consulta **antes** de comparar el código o el token. Apuntar sin consultar deja el bloqueo escrito en una tabla y a quien ataca dentro. Dos detalles que parecen menores y no lo son: el contador va por lo **tecleado** al identificarse (guardado en `ATTEMPT_KEY`), no por `get_user().get_username()` --que devuelve el correo, porque `USERNAME_FIELD` es el correo-- o serían dos cuentas atrás para el mismo intruso; y el tope de cinco intentos por código no sustituye a nada, porque se esquiva pidiendo otro código. Lo cubre `account/tests_login_lockout.py`.

24. **La capa inicial tiene tres señales, y sólo una depende de acertar el nombre de la ruta.** La trampa de `attack_patterns` empareja términos de `COMMON_ATTACK_TERMS` --precisa, y por eso puede bloquear al primer intento, pero ciega ante lo que nadie anticipó--; `scanning.py` mira el **patrón** (muchos 404 sobre rutas mayormente distintas, en una ventana) y no el nombre; y `block_bots.py` mira la firma de herramientas que se anuncian solas. Dos cosas no se pueden romper. Una: las tres acaban en el **mismo** `IPBlockedModel` con la misma curva de `blocking.block_duration()` — tener dos políticas es lo que hacía que el castigo dependiera de por dónde entrara la petición. Y dos: `scanning.py` **falla abierto**, al contrario que `throttling.py`, porque aquí el límite decide un *bloqueo* y no un *permiso*: fallar cerrado con la caché caída sería bloquear a cualquiera que reciba un 404 por una avería que no es suya. Ampliar `COMMON_ATTACK_TERMS` no es la respuesta a una detección insuficiente: cada término es una ruta legítima menos, y ya hubo un autobloqueo por meter `env`.
25. **El estado de un bloqueo se calcula, no se guarda.** `is_active` es el interruptor manual; `IPBlockedModel.is_currently_blocked` lo combina con el reloj y se evalúa al leerlo, así que el admin enseña siempre el estado real sin cron ni columna que mantener. Guardarlo obligaría a una tarea periódica que lo corrigiera, y mientras tanto la tabla mostraría como activos bloqueos caducados hace meses — que es exactamente lo que pasaba. Lo mismo vale para el origen de la IP (`netintel.py`): se resuelve **sin salir a la red**, con una tabla de prefijos que viaja en el repositorio, porque una consulta a un servicio de reputación metería una llamada de red en el camino crítico de cada petición, con `ATOMIC_REQUESTS` puesto, y le contaría a un tercero quién visita el sitio. La etiqueta de datacenter es un dato para leer la fila, **nunca** un motivo de bloqueo por sí sola: una VPN comercial sale por los mismos rangos.

26. **Un respaldo no puede deshacer el cifrado de campo.** `dumpdata` serializa el **valor de Python**, y en los campos de `django-encrypted-model-fields` ese valor es el ya descifrado: los volcados de usuarios salían con el correo, el teléfono y el pasaporte en claro. `FIELD_ENCRYPTION_KEY` protege la base de datos contra un volcado robado; el volcado de al lado, sin llave y legible por cualquiera de la máquina, era ese volcado robado ya servido. Hoy `db_backup` cifra lo que lleva PII (`GEA_BACKUP_PASSPHRASE`), escribe todo con permisos 600 —abriendo el fichero ya con ellos, no con un `chmod` posterior, porque entre una cosa y otra hay una ventana— y **sin contraseña no escribe la PII**: hay que pedirlo con `--allow-plaintext`. `GENERAL_APPS` no puede contener ninguna app de `APPS_WITH_PII`; el comando se niega en vez de escribirla. Lo cubre `utils/tests/test_backup.py`, cuya primera prueba **reproduce el fallo** para avisar el día que la biblioteca deje de comportarse así.
28. **La constancia de una autorizacion es la huella, no el texto.** Los cuatro documentos legales ya no son plantillas: son `LegalDocumentVersionModel`, y cada aceptacion (`LegalAcceptanceModel`) guarda **quien, cuando, que y como** — el «que» es el `content_hash` copiado, no una referencia a secas. El articulo 9 de la Ley 1581 no pide saber que el titular acepto, pide poder demostrarlo, y con el texto en una plantilla eso era imposible: se desplegaba encima y lo anterior desaparecia. De ahi tres reglas que no se pueden romper. Una: **una version aprobada no se edita**, se aprueba otra — lo impiden `clean()` y una `CheckConstraint`, porque editar el texto que alguien acepto deja la constancia apuntando a algo que ya no existe. Dos: **el estado vive solo en `status`**; antes estaba en la plantilla *y* en `settings.LEGAL_DOCUMENT_VERSIONS`, dos marcas que nada obligaba a mantener de acuerdo. Y tres: **entrar no acepta lo que no se ha avisado** — `accept_on_login()` se niega a registrar una version sin `notified_at`, porque consentimiento por conducta sin aviso previo es darlo por hecho; el aviso (`notify_legal_changes`, por cron) va primero. Lo cubre `core/tests/test_legal.py`.
29. **Lo que se redacta en el admin y se publica sin autenticar va saneado.** El cuerpo de un documento legal es HTML de un editor con boton de codigo fuente, y sus paginas las ve cualquiera. `core/legal_html.sanitize_legal_html()` deja pasar solo su lista blanca de etiquetas, atributos y esquemas de enlace, y **conserva el texto** de lo que descarta: a un documento legal no se le puede caer una clausula por una etiqueta rara. Esa lista es la misma que ofrece el editor (`CKEDITOR_5_CONFIGS['legal']`) y la misma que pinta `legal_pdf.py`; si divergen, algo que se escribe no se ve o algo que se ve no llega al papel. `mark_safe` sobre lo que salga del admin sin pasar por ahi seria un `<script>` en la cara de cada visitante, y esa es la razon escrita en `BANDIT_ACCEPTED`.

30. **Un dossier no sale a un USB si el resumen no está en verde en las cinco.** Un soporte se entrega y ya no vuelve: no se actualiza, no avisa y no se puede retirar, así que lo que se grabe es lo que alguien le enseñará a un banco o a un notario dentro de dos años. Exportar un resumen a medias —sellado pero sin bloque, o con un anclaje que ya no cubre el master hash de ahora— reparte un dossier que **parece** prueba y no lo es, y quien lo recibe no tiene forma de notarlo. Las cinco condiciones viven en `code_gen/services/usb_readiness.py` (activo · sellado y cuadrando · con papel emitido · confirmado en OpenTimestamps · sin errores) y la puerta está en `build_bundle()`, **no en la plantilla**: esconder el botón no es un control, porque basta con teclear la URL. Tres cosas que se deducen y no se pueden romper. Una: un OTS **pendiente** no cuenta —hay compromiso, no hay bloque— y una TSA sola tampoco es «blockchain». Dos: las cinco se devuelven siempre, cumplidas y no cumplidas, porque arreglar una y descubrir la siguiente de una en una es la peor forma de enterarse; por eso cuando no se puede exportar la pantalla enseña la lista y **no un botón apagado**. Y tres: el dossier se arma **en memoria** y no se guarda, que es lo que evita tener que decidir su carpeta en `deploy/media.htaccess` (invariante 13) y regenerarlo cada vez que cambie algo. Dentro va la copia pública, nunca el `source_file`: perder el USB tiene que ser perder una copia, no un incidente. Lo cubre `code_gen/tests/test_usb_bundle.py`.

32. **Un anclaje que no se puede comprobar sin nosotros no es un anclaje.** «Confirmado en el bloque 964899» escrito en una página nuestra es *esta plataforma diciéndolo*, que es exactamente lo que un anclaje existe para no ser. Lo que acredita es el **fichero de la prueba** —el camino desde el master hash hasta la transacción que lo metió en la cadena—, así que se descarga sin autenticar desde la página de anclaje y desde la del resumen (`certificates:summary_anchor_proof`), con las instrucciones al lado: sin ellas es un fichero que nadie sabe para qué sirve. Es público a propósito y no se puede cerrar: son hashes y un camino de Merkle, el master hash ya sale impreso encima, y cerrarlo no protegería nada mientras rompe lo único que hace útil al anclaje. Dos reglas más. Una: **la fecha de un anclaje de OpenTimestamps no está en la prueba** — la prueba acredita una **altura de bloque** y la hora vive en la cabecera de ese bloque, así que se resuelve aparte (`services/bitcoin_time.py`), **solo desde el cron** y nunca al pintar una página, porque con `ATOMIC_REQUESTS` eso sería una transacción abierta esperando a un tercero. Y dos: esa hora se acepta **solo si dos exploradores independientes coinciden**; si no coinciden no se escribe nada y queda en el log, porque una fecha sacada de una sola fuente vuelve a ser esta plataforma diciéndolo, con un intermediario. Que falle no impide confirmar el anclaje: `anchoring.anchors_without_block_time()` existe para volver a por ella, o un corte de red de un minuto dejaría la columna vacía para siempre. Lo cubre `code_gen/tests/test_anchor_proof.py`.

33. **El histórico de códigos tiene dos lecturas, y la del titular no es «la misma con menos botones».** `DocumentVerificationModel.holder` dice para quién se emitió un certificado — el campo no existía, así que «este certificado es de este usuario» no se podía escribir en ninguna parte. Con él, **el operador** (personal interno) ve todo el histórico, compone resúmenes, exporta a un USB y emite; **el titular** ve *sus* certificados y solo eso. Cuatro cosas que no se pueden romper. Una: **el recorte vive en el queryset** (`access.visible_registrations()`), aplicado **antes** de buscar y antes de agrupar, y el detalle de un código ajeno responde **404** — un 403 confirmaría que ese código existe (invariantes 7 y 20), y contar resultados de una búsqueda ya es media respuesta. Dos: al titular no se le enseñan **las tres piezas con las que se monta un certificado** —el original sin códigos, los símbolos sueltos en PNG y las coordenadas donde se estamparon—, y las tres salen de la misma pregunta (`can_see_internals`) a propósito: separadas, un día se contesta distinto a una por descuido. Y no se esconden, **no se producen**: renderizar un QR para no enseñarlo lo deja a una línea de plantilla de distancia de salir. Tres: `on_delete=SET_NULL` en `holder` porque de los tres comportamientos es el único que **nunca ensancha el acceso** — sin titular no encaja nadie. Y cuatro: el papel **no depende de `user_type`** sino de ser titular de algo; atarlo al tipo de cuenta dejaría fuera a un tipo nuevo sin que nadie lo notara. Dos consecuencias que ya desconcertaron una vez. **Impersonar enseña lo que ve esa persona**, y eso incluye el recorte: `impersonate` va el último del middleware y sustituye `request.user`, así que impersonar a un titular enseña lo suyo — pero impersonar a alguien **de personal interno enseña todo**, porque es lo que esa cuenta ve por su cuenta. No es un fallo del filtro, y perseguirlo como si lo fuera cuesta una tarde. Y **el enlace tiene que estar donde la vista**: abrir el historial al titular y dejar su entrada dentro del bloque de `is_staff` lo dejaba sin forma de llegar a lo suyo que no fuera saberse la URL. Lo cubre `code_gen/tests/test_holder_history.py`.

31. **Subir el documento comprueba su integridad; teclear el código público no.** Son los dos caminos de la misma pantalla, se parecen y no prueban lo mismo: el código busca una ficha y la enseña —un PDF alterado daría exactamente la misma página—, y solo la comparación byte a byte dice si el archivo que alguien tiene en la mano es el que se certificó. Quien no lo sabe se lleva una pantalla que dice «certificado» y cree que su copia acaba de quedar comprobada. Así que se escribe, entero y con las dos mitades juntas, en los tres sitios por los que se llega: la página pública (`certificate_input.html`), el `LEEME.txt` del dossier y la salida de los tres guiones. Y va con el límite del invariante 11 al lado, porque es la otra confusión de esa misma pantalla.

27. **Nada de fuera se ejecuta sin `integrity`.** Un `<script src="https://cdn…">` sin él es una promesa de que el CDN servirá siempre lo mismo, y la pantalla de acceso —donde se teclean la contraseña y el código— cargaba varios. Estaba además del revés: el **CSS** de Bootstrap lo llevaba y el **JS** no, o sea firmado justo lo que no ejecuta nada. Y `bootstrap-icons` se cargaba **sin versión** en 28 plantillas, siguiendo a la última publicación del paquete. Las dos únicas excepciones —el kit de Font Awesome y los formularios embebidos de JotForm— son URL mutables por diseño y están declaradas **con su motivo** en `utils/tests/test_sri.py`, que falla si aparece un tercero nuevo sin firmar.

---

## 7. Trampas conocidas

| Trampa | Detalle |
|---|---|
| **Regex catch-all antes que rutas reales** | `apps/common/utils/attack_patterns.py` registra un `re_path` que matchea cualquier término de `COMMON_ATTACK_TERMS` en cualquier posición del path, y `utils` va en la 4.ª posición del URLconf — **antes** de `assets`, `assets_location`, `buyers` y `account`. Un término mal elegido secuestra rutas legítimas y bloquea la IP del usuario. |
| **Un 403 confirma; un 404 no** | Vale también para el `User-Agent`, y ahí estaba mezclado. A un rastreador declarado (GPTBot, AhrefsBot) el 403 es lo correcto: es una decisión de política y necesita entenderla para dejar de volver. A una herramienta de ataque que se anuncia (sqlmap, nikto) el 403 le dice que hay filtro por agente, y cambiar la cadena cuesta un parámetro: ésas se llevan el mismo 404 silencioso que el resto de la capa, más su bloqueo. Y los nombres se emparejan como **token**, no como subcadena: `nmap` dentro de `Enmapador` es el mismo error que hizo que `env` bloqueara `/envio/`. |
| **`CACHES` sale de `REDIS_URL`** | Con la variable puesta se usa `django-redis` con `IGNORE_EXCEPTIONS`: un Redis caído degrada a «sin cache» en vez de tumbar el login. Cuidado con lo que significa eso exactamente: **no lanza la excepción, devuelve `None`**, así que un `try/except` alrededor de una operación de caché no se entera de nada y `cache.get(k) or 0` da `0`. Eso apagaba los seis contadores de intentos en silencio; hoy todos pasan por `apps/common/utils/throttling.py`, que detecta la avería por lo que devuelve `incr` y **falla cerrado salvo donde hay una razón escrita para lo contrario**. Sin la variable, Django cae en `LocMemCache`, que es **por proceso**: los límites son entonces por worker. Montaje del Redis: [`deploy/REDIS.md`](deploy/REDIS.md). |
| **`ERROR_TEMPLATE` no está definido** | Varios módulos hacen `settings.ERROR_TEMPLATE` dentro de `try/except` y caen a `'errors_template.html'`. Funciona, pero el `getattr` es engañoso. |
| **`settings.py` no arranca sin el `.env` completo, pero ya dice qué falta** | Muchos `os.getenv(...)` se pasan directos a `int()` o `.split(',')` sin valor por defecto (`DB_PORT`, `DJANGO_EMAIL_PORT`, `IP_BLOCKED_TIME_IN_MINUTES`, `CORS_ALLOWED_ORIGINS`, `COMMON_ATTACK_TERMS`, `GEA_DAILY_CODE_*`), y el error que salía era `int() argument must be a string … not 'NoneType'`: no nombraba la variable, y como el arranque muere en la primera, había que repetirlo una vez por cada una que faltara. Hoy `app_core/env.py::check_environment()` corre **antes de que `settings.py` lea nada** y levanta un `ImproperlyConfigured` con **todas** las que faltan, cada una con para qué sirve y con `cp docs/env.example .env` al pie. Tres cosas al tocarlo: una variable **vacía cuenta como ausente** salvo en `ALLOWED_EMPTY` (vacío significa algo en `CORS_ALLOWED_ORIGINS`, `COMMON_ATTACK_TERMS` y las contraseñas); `DJANGO_ALLOWED_HOSTS` va en `REQUIRED_IN_PRODUCTION` porque sólo la lee la rama de `DEBUG=False`, y exigirla siempre rompería un `.env` de portátil que hoy funciona; y lo que se lee sin defecto y aun así puede faltar va en `OPTIONAL_WITHOUT_DEFAULT` **con su motivo escrito**, que `app_core/tests/test_env.py` comprueba recorriendo `settings.py` — una lectura nueva sin declarar falla la prueba. Sólo cubre lo que impide arrancar: lo que falta y sólo degrada (`REDIS_URL`, `CERTIFICATION_SIGNING_KEY`, `GEA_BACKUP_PASSPHRASE`, `PQRS_NOTIFICATION_RECIPIENTS`) no sale ahí a propósito. |
| **Un ajuste que sólo se lee con `getattr(settings, …)` no se configura por entorno** | `SCAN_404_THRESHOLD`, `SCAN_404_WINDOW_SECONDS` y `GEOIP_PATH` estaban documentados como variables de entorno y no lo eran: `scanning.py` y `netintel.py` los leen del objeto `settings` con su propio defecto, y `settings.py` no los definía. Ponerlos en el `.env` no hacía nada — que es peor que no poder configurarlos, porque parece que sí. Ya se leen en `settings.py`. Al añadir un ajuste que quieras poder cambiar por entorno, defínelo ahí aunque el módulo que lo usa tenga un defecto. |
| **Los UUID de MariaDB: el motor es propio y no se puede quitar** | `settings.py` no instala `django.db.backends.mysql` sino `app_core/db/mysql`, que es ese mismo con `has_native_uuid_field = False`. Django 5.0 empezó a usar el tipo nativo `uuid` de MariaDB 10.7+, y con él `UUIDField.get_db_prep_value` manda el UUID **con guiones** en vez del hex de 32 — contra columnas que Django 4.2 creó como `char(32)` con el hex. No falla: la fila se lee y `filter(username=…)` la encuentra; sólo deja de funcionar lo que busca **por clave primaria**, así que la contraseña se acepta y acto seguido el asistente no puede recargar al usuario. Migrar sería convertir diez columnas `UUIDField` y todas las claves ajenas que apuntan a ellas, en producción y sin vuelta atrás a mitad; el tipo nativo no aporta nada que este proyecto use. La decisión vive en `app_core/db/engine_for()` para poder probarla, y la fija `app_core/tests/test_db_backend.py`. Ver [`docs/DJANGO_5_2.md`](docs/DJANGO_5_2.md) §4.4. |
| **Las opciones de conexion son de cada motor** | `DATABASES['default']['OPTIONS']` va **vacio** y cada motor pone las suyas en su propio bloque. Antes el diccionario base traia el `charset`/`init_command` de MySQL para todos: con MySQL no hacia nada --el bloque de abajo lo reemplazaba entero, perdiendo de paso el `COLLATE utf8mb4_bin`-- y con cualquier otro motor **rompia la conexion** (`TypeError: 'charset' is an invalid keyword argument for Connection()`), asi que levantar el proyecto contra PostgreSQL o SQLite en local era imposible sin editar `settings.py`. Inutil donde se usaba, impeditivo donde no. Al anadir una opcion de conexion, ponla en el bloque de su motor. |
| **Allowlist de usuarios hardcodeada** | `OnlySpecificUserMixin.allowed_user_username = ['jose.henry', 'kalichemorales']` en `buyers/views.py` controla el acceso a Orion. |
| **`django.contrib.sites` NO está instalado** | `get_current_site(request)` cae en `RequestSite` y devuelve la cabecera `Host`, que la pone el cliente. Cualquier URL construida así es envenenable. Por eso el enlace de recuperación de contraseña sale de `PUBLIC_BASE_URL` (invariante 12). Si añades otro correo con enlaces, hazlo igual. |
| **`axes` no ve el usuario del login** | El login es un wizard de `formtools`: su campo es `auth-username`, no `username`. Sin `AXES_USERNAME_CALLABLE` (`utils/axes_hooks.py`) todos los intentos se guardan con usuario vacío y **cualquier bloqueo por pareja (IP, usuario) degrada en silencio a bloqueo por IP**. Si algún día cambia el prefijo del paso, actualiza `USERNAME_FIELDS`. |
| **Un paso nuevo del login se toma por sesión caducada** | El asistente da por hecho que solo el **primer** paso está antes de identificarse: `step_requires_authentication()` devuelve `step != FIRST_STEP`. Como `expired` mira `authentication_time`, que todavía no existe, cualquier otro paso previo a la identificación sale caducado: al enviar el código el asistente reiniciaba el almacén y volvía a pedir el correo **sin validar y sin error en pantalla** — parecía que el botón no hacía nada. `GeaLoginView` lo corrige devolviendo `False` para `otp_id` y `otp_code`. |
| **El prefijo del asistente sale del nombre de la clase** | `formtools` lo deriva con `normalize_name(cls.__name__)`, así que heredar de `LoginView` con otro nombre renombra el campo oculto que envía la página (`login_view-current_step`) y la clave del almacén en la sesión. `GeaLoginView.get_prefix()` lo fija a `login_view` para que ni la plantilla ni un acceso a medias se rompan en el despliegue. |
| **`totp()` devuelve un entero, no una cadena** | Uno de cada diez códigos TOTP sale con un dígito menos --`071536` se convierte en `71536`-- y el formulario lo rechaza. Una prueba que genere el token así falla una vez de cada diez sin que nada esté roto, que es la clase de prueba que acaba ignorándose. En `tests_login_paths.py` se rellena con `f'{value:06d}'`. |
| **`default_device()` busca el nombre literal `default`** | `two_factor.utils.default_device()` recorre los dispositivos y devuelve el que se llama exactamente `default`, que es el que pone el asistente de alta. Un `TOTPDevice` creado a mano con otro nombre **no cuenta como segundo factor**: en una prueba, eso la deja pasando sin comprobar nada. |
| **El almacén del asistente devuelve `False`, no `None`, cuando no hay usuario** | `two_factor.views.utils.LoginStorage._get_authenticated_user()` contesta **`False`** si le faltan `user_pk`/`user_backend` en el almacén, o si el backend ya no puede cargar esa cuenta. Ese `False` llegaba tal cual a `django.contrib.auth.login()`, que le busca un atributo `backend`, no lo encuentra, y con los tres backends de este proyecto termina en `ValueError: You have multiple authentication backends configured…` — o sea, **un 500 en la pantalla de acceso**, visto en un portátil tras la subida a 5.2. No se reproduce con ningún recorrido normal (los seis de `test_login_paths.py` pasan, y tampoco lo provocan las 98 combinaciones de dos y tres acciones que se probaron): hace falta que el almacén pierda al usuario **entre dos peticiones** — sesión caída, sesión a medias de una versión anterior, o cuenta desactivada entre identificarse y terminar. `GeaLoginView.done()` lo corta antes: sin usuario no se llama a `login()`, se vacía el asistente, se vuelve a la pantalla con un aviso y se registra el estado (paso, pasos, modo) para poder identificar el disparador si vuelve. Lo fija `account/tests_login_lost_session.py`, que reproduce el `ValueError` si se quita la guarda. |
| **`AxesStandaloneBackend` va primero y exige `request`** | Ese orden es lo que impide que una contraseña correcta se salte el bloqueo, pero hace que `authenticate()` **sin** `request` lance excepción. `client.login()` de Django no la pasa: por eso `settings_test` apaga axes y solo lo encienden sus propias pruebas. |
| **Los PDF ya no descargan sus logotipos** | Los dos generadores de `buyers/functions/` traían sus cuatro imágenes de una URL absoluta de producción escrita a mano, y los correos de orden hacían lo mismo con `requests.get()`. O sea: una llamada de red **dentro de la petición**, con `ATOMIC_REQUESTS` puesto, para traer un fichero que ya está en el disco de ese servidor — y un PDF que no se podía generar sin salida a Internet. `reportlab` 5 lo destapó al dejar de poder abrir esas URLs, pero el problema no lo trajo la actualización. Hoy se resuelven por los buscadores de estáticos (`generate_pdf_helper.brand_image` / `attach_inline_logo`), y si una imagen falta el documento sale igual y el motivo queda en el log. |
| **Llamadas a OpenAI en señales `pre_save`** | La traducción automática de activos y ofertas ocurre **de forma síncrona dentro del guardado** (timeout 20 s). Un fallo o lentitud de la API se traduce en peticiones lentas. No hay cola de tareas. Sin `CHAT_GPT_API_KEY` **no falla**: `ChatGPTAPI` se queda sin cliente y `translate()` devuelve el texto original — antes el constructor lanzaba `ValueError` y, como las señales lo instancian a nivel de módulo y `models.py` las importa, una integración opcional sin configurar impedía arrancar el proyecto entero. En `DEBUG` tampoco sale a la red y devuelve el original (devolvía `src`, o sea la cadena `"es"`, y así se guardaba). |
| **`ffmpeg` como dependencia del sistema** | `video_masonry` invoca `ffmpeg` por `subprocess` para quitar el audio de los vídeos. Si no está en el `PATH`, la subida falla. |
| **La derivación de `MediaAsset` vive sólo en `save()`** | No hay `signals.py` en `video_masonry` y no debe volver a haberlo. Había uno que duplicaba lo que hace `save()` y de paso escribía dos campos que la migración 0003 borró: guardar **cualquier** media reventaba con `AttributeError: … no attribute 'categories'`, y la galería llevaba sin admitir una subida desde entonces. Tener la misma derivación en dos sitios es lo que dejó que una se quedara atrás sin que nadie lo notara. |
| **`ATOMIC_REQUESTS = True`** | Cada petición es una transacción. Cuidado con operaciones largas (PDF, OpenAI, email) dentro de vistas. |
| **Rotar el log exige `WatchedFileHandler`** | Rotar es renombrar, y en Linux renombrar no toca a quien ya tiene el fichero abierto: el descriptor sigue apuntando al mismo inodo. Con varios workers y un `FileHandler` normal, tras rotar **todos siguen escribiendo en `stderr_old_N.log`**, el `stderr.log` nuevo no llega a crearse y el «viejo» es el que crece — sin error y sin aviso. `WatchedFileHandler` reabre cuando detecta el renombrado; es lo que sostiene `rotate_logs`. Tampoco vale `RotatingFileHandler`: rota el proceso que escribe, y aquí hay varios. Ver `apps/common/utils/logs.py`. **Y todo esto es de POSIX**: Windows no deja renombrar un fichero abierto (`WinError 32`), así que el mecanismo no es que funcione peor allí, es que no existe — la propia documentación de Python lo dice de `WatchedFileHandler`. Las dos pruebas que lo fijan van con `posix_rename_only`; `rotate_logs` lo explica en vez de escupir el error del sistema. |
| **Ajustes definidos y nunca leídos** | `MIDDLEWARE_NOT_INCLUDE`, `ADMIN_DELETE_PERMISSION` y `ADMIN_ADD_PERMISSION` se declaran en `settings.py` pero no los consume nadie. No asumas que hacen algo. (`UTILS_DATA_PATH` sí se usa, solo en `delete_migrations`.) |
| **`{% blocktrans count %}` con una variable que falte es un 500, no un hueco** | El contador **tiene que ser un número**, y una variable que no está en el contexto se resuelve a la **cadena vacía**: `TemplateSyntaxError: 'counter' argument to 'blocktrans' tag must be a number`, o sea la página entera caída. Tumbó el historial de códigos en producción, y el motivo no era de lógica sino **de despliegue**: el cargador de plantillas cacheado (que Django activa solo con `DEBUG=False`) se llena **por plantilla y en el primer render de cada proceso**, así que un worker arrancado antes de un `git pull` ejecuta en memoria la vista vieja y, la primera vez que alguien abre esa página, lee del disco la plantilla **nueva** — contexto viejo con plantilla nueva. Reiniciar la aplicación lo arregla, pero no puede ser lo único que lo arregle: durante esa ventana la página tiene que verse. Todo contador lleva `|default:0`, que convierte la cadena vacía en cero — una cifra equivocada hasta el reinicio en vez de un 500. Lo fija `code_gen/tests/test_history_tree.py::StaleContextTestCase`, que renderiza la plantilla a mano con el contexto de la vista anterior, porque por la vista es imposible llegar ahí. |
| **Un payload «verbatim» no sobrevive a copiar y pegar** | El master hash se calcula sobre los bytes **exactos** del payload canónico, sin salto de línea al final. Casi todos los editores añaden uno al guardar, así que quien copia el JSON de la pantalla en vez de descargarlo obtiene otro hash y concluye que el sello no cuadra: comprobado, `a90d46ed…` pasa a ser `31513814…` por un solo byte. `certificates:summary_master_payload` sirve el campo tal cual (`HttpResponse(summary.canonical_payload)`) y por eso `sha256sum` sobre el fichero descargado sí da la cifra. El aviso va escrito en la página, al lado del comando, no como nota al pie. |
| **Comprobar una URL en el HTML con `assertIn(reverse(...))` da falsos positivos** | Las rutas de este proyecto se anidan (`/generate/code/` es **prefijo** de `/generate/code/history/`), así que `assertNotIn(reverse('code_gen:code_generate'), html)` falla en cuanto el menú lleva el historial — por el prefijo, no por el permiso. Ya ha mordido dos veces, en `test_holder_history.py` y en `test_entry_point.py`. Se comprueba con las comillas del atributo: `assertNotIn('href="%s"' % reverse(...), html)`. Es el mismo error de fondo que hizo que el término `env` bloqueara `/envio/` (invariante 14): emparejar un fragmento donde hay que emparejar una cosa entera. |
| **Un `_()` dentro de una f-string no llega al catálogo** | `xgettext` no entra en las expresiones de una f-string, así que `f'{code}: {_("not certified")}'` se traduce en tiempo de ejecución —contra un catálogo que no tiene esa cadena— y sale en inglés. No falla, no avisa y `makemessages` no la extrae: la única señal es que la frase no aparece en el `.po`. Se escribe con `%` o con `.format()` sobre la cadena ya traducida. Pasó en `usb_readiness.py` con las tres frases de los miembros que faltan. |
| **Una entrada `fuzzy` en un `.po` no se usa, y casi nunca dice lo que parece** | gettext **ignora** lo marcado `fuzzy`: la pantalla sale en inglés aunque el `.po` tenga una traducción al lado, así que un catálogo «completo» a ojo puede no estarlo. Y lo que hay escrito ahí no es una traducción aproximada: lo pegó `msgmerge` por parecido de la cadena original, y se equivoca de lleno — `'Operations console'` tenía `'Observaciones'`, `'App'` tenía `'Aprobar'`, `'Test summary'` tenía `'Nuevo resumen'`. Quitar el marcador sin leer publica eso. Al revisar un catálogo cuenta las tres cifras (`polib`: traducidas, sin traducir y **fuzzy**), no sólo las vacías. |

---

## 8. Variables de entorno

Se cargan con `python-dotenv` desde `.env` en la raíz (ignorado por git). La
plantilla comentada es [`docs/env.example`](docs/env.example), y cuál de ellas
es obligatoria lo decide `app_core/env.py`, que además es lo que produce el
error cuando falta alguna: la lista completa, por su nombre, antes de arrancar.

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
GEA_BACKUP_PASSPHRASE         # con la que se cifran los respaldos que llevan PII.
                              # Sin ella `db_backup` NO los escribe: `dumpdata`
                              # serializa el valor descifrado, así que el volcado
                              # deshacía el cifrado de campo
CERTIFICATION_SIGNING_KEY     # Ed25519 base64; firma el registro de certificación
                              # (manage.py generate_certification_key). Sin ella
                              # el registro se sella con HMAC y solo la propia
                              # plataforma puede verificarlo
PUBLIC_BASE_URL               # base canónica para el QR y el registro; NUNCA se
                              # deriva del host de la petición
BITCOIN_BLOCK_EXPLORERS       # con qué se resuelve la HORA de un bloque, porque
                              # una prueba .ots acredita una ALTURA y no una
                              # fecha. Van dos, de operadores distintos, y
                              # tienen que COINCIDIR para que se guarde: de una
                              # sola fuente la fecha vuelve a ser esta
                              # plataforma diciéndolo. Solo desde el cron
BITCOIN_BLOCK_EXPLORER_URL    # a dónde lleva el enlace del bloque en la página.
                              # Solo es un enlace; la fecha no sale de ahí
CORS_ALLOWED_ORIGINS          # lista separada por comas
COMMON_ATTACK_TERMS           # lista separada por comas → regex catch-all
SAFETY_API_KEY                # credencial de Safety CLI, SOLO en local y solo
                              # para `check_security` §9. En el servidor esa
                              # sección ni se intenta (allí la de dependencias
                              # es pip-audit, que no lleva clave). NUNCA se pasa
                              # como --key: la línea de comandos acaba escrita
                              # en CommandRunModel
IP_BLOCKED_TIME_IN_MINUTES
MIDDLEWARE_NOT_INCLUDE
SCAN_404_THRESHOLD            # por defecto 20; cuántos 404 en la ventana
SCAN_404_WINDOW_SECONDS       # por defecto 300; la ventana del detector
GEOIP_PATH                    # opcional; sin ella el país de un bloqueo se
                              # queda vacío y todo lo demás sigue igual
AXES_FAILURE_LIMIT            # por defecto 6, bloqueo por pareja (IP, usuario)
AXES_COOLOFF_MINUTES          # por defecto 30; nunca dejarlo sin espera
LOGIN_OTP_TTL_MINUTES         # por defecto 15; cuánto dura el código de acceso
OTP_TTL_MINUTES               # por defecto 15; el de la verificación documental
OTP_CONTACT_EMAIL             # por defecto info@propensionesabogados.com; el
                              # «ponte en contacto con nosotros» de los DOS
                              # correos. Una sola variable a propósito: dos
                              # ajustes para la misma dirección divergen

# Cache — ver deploy/REDIS.md
REDIS_URL                     # rediss://usuario:clave@host:6380/0?ssl_cert_reqs=
                              # required&ssl_ca_certs=/ruta/ca.crt
                              # Sin ella, LocMemCache: los límites son por worker
REDIS_KEY_PREFIX              # por defecto 'gea'
CELERY_BROKER_URL             # vacía mientras no haya cola de tareas. NO es
                              # REDIS_URL: el broker lleva su propio usuario y
                              # su propia base (deploy/REDIS.md §9), porque el
                              # de la cache está acotado a ~gea:* y responde
                              # NOPERM a las cinco operaciones de un broker
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
DocumentVerificationModel  ─FK──  UserModel (holder)      (para quién se emitió; decide
                                                           qué ve en el histórico)
StampLayoutModel           ─1:N─ StampPlacementModel
CodeSequenceModel                (contador de la secuencia autónoma)
CodeRegistrationModel            (traza de cada código emitido)

MediaAsset ─1:N─ MediaAssetInteraction
MediaAsset ─1:N─ MediaAssetUserStats  (unique por usuario+activo)

LegalDocumentModel ─1:N─ LegalDocumentVersionModel ─1:N─ LegalAcceptanceModel
   (documento)            (texto es/en, estado, hash,        (quién, cuándo,
                           aprobador, vigencia)               qué hash, cómo)

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

**Cambiar un documento legal** (términos, datos, privacidad, cookies): en el admin, `Legal document versions` → **crear una versión nueva** (nunca editar la aprobada), redactar en los dos idiomas con el editor, escribir **qué cambió** —ese texto es el que reciben los usuarios— y pulsar **«Aprobar y publicar»**, el botón que hay arriba y abajo del propio formulario. El estado y el aprobador **no son campos que se escriban**: salen en gris porque los fija ese botón, con tu nombre y la fecha. (La acción del listado sigue ahí para aprobar varias de una vez.) El aviso sale solo en la siguiente pasada del cron, o desde la consola de operaciones con «Anunciar un cambio». Sólo después de ese aviso empieza a contar el uso continuado como aceptación.

**Depurar un bloqueo de IP**: revisa `IPBlockedModel` (tabla `apps_common_utils_ipblocked`); `session_info` guarda los paths intentados. Añade la IP a `WhiteListedIPModel` o ajusta `blocked_until`. Ojo: desde fuera un bloqueo se ve como un 404 normal y corriente, así que el síntoma que reporta el usuario es «la página no existe», no «me han bloqueado». La confirmación está en la tabla y en el log (`Blocked IP … attempted access to …`).

---

## 11. Estado del repositorio

- Rama principal: `master`.
- **Las pruebas viven en `apps/<app>/tests/`**, un paquete por app, con ficheros `test_*.py`. Estaban sueltas al lado del código (`tests_login.py`, `tests_workflow.py`…) y en `utils/` llegaron a ser diecinueve ficheros mezclados con los módulos, lo que hacía que abrir la carpeta no dijera nada. El descubrimiento de `unittest` recorre paquetes, así que sigue encontrándolas sin configurar nada; lo único que hace falta es el `__init__.py` y que el nombre empiece por `test`. Un módulo de prueba que importe del suyo usa `..` (`from ..models import …`), y de un hermano, `.` (`from .test_buyers import …`).
  `app_core/tests/` sigue la misma regla: era el último `tests_*.py` suelto, y se veía en el resumen
  de pruebas, que lo agrupaba como una app llamada `app_core.tests_admin`.
- **La suite corre también en Windows.** Lo que la rompía no era lógica: `os.getuid` no existe allí y
  reventaba `check_workers` entero, y `open()` sin `encoding` usa cp1252, donde cualquier tilde en un
  log corta la prueba con un `UnicodeEncodeError` que no tiene que ver con lo que se probaba. Se
  encontró ejecutando con `PYTHONWARNDEFAULTENCODING=1`, no adivinando. Lo que de verdad es de POSIX
  —los permisos `rw-------`, que Windows no tiene— se marca con `posix_only`
  (`apps/common/utils/testing.py`) en vez de borrarse: saltarlo dice la verdad, quitarlo diría que a
  nadie le importa, y en el servidor, que es Linux, importa.
  La segunda tanda salió al ejecutarla de verdad en un portátil: **Windows no deja renombrar un
  fichero abierto**, y la rotación del log es exactamente eso, así que las dos pruebas que rotan con
  un handler abierto van con `posix_rename_only`. Los marcadores llevan **su propio motivo**
  (`posix_only_because`): un `skip` que explica mal manda a quien lo lee a buscar en la dirección
  equivocada — «permisos de Unix» no tenía nada que ver con un `WinError 32`.
- **Una condición de asistente que cambia a mitad de petición rompe la caché de `formtools`.**
  Desde la 2.6, `get_form_list()` resuelve las condiciones una vez y se queda con el resultado; su
  firma mira la *identidad* del `condition_dict`, no lo que devuelven sus condiciones. El login entra
  y sale del modo código dentro de la misma petición (`KeyError: 'otp'`) y PQRS sustituye el
  formulario del paso de titular (la rama de persona jurídica recibía el de persona natural y la
  solicitud no se guardaba). Los dos invalidan con
  `apps/common/utils/wizards.py::forget_resolved_steps()`. Si añades un asistente cuyos pasos
  dependan de algo que cambia dentro de la petición, llámalo también.
- **Ojo con `os.environ` dentro de una prueba.** El corredor del informe
  (`apps/common/utils/test_runner.py`) lee su destino **al construirse** justo por esto: una prueba
  que quitaba `GEA_TEST_REPORT` y no lo devolvía dejaba la suite entera en verde y sin informe, y el
  fallo no se veía ejecutando ese fichero solo. Si tocas el entorno en una prueba, devuélvelo como
  estaba.
- No hay CI ni linters configurados, pero **todas las apps con lógica tienen pruebas** (778). Las que más peso llevan: `buyers/` (control de acceso del flujo **y** las tres capas del flujo de 12 etapas, con las `CheckConstraint` probadas por `QuerySet.update()` para saltarse `save()` y `clean()`), `users/` (el correo cifrado no se puede consultar: por eso existe `email_hash`), `account/` (login por HTTP y wizard de registro), `common/utils/` (bloqueos, trampa anti-escaneo, rotación del log, `safe_next`), e `internal/ops/`. Las únicas sin contenido son `notifications/` (app vacía a propósito) y los `tests.py` de apps sin lógica propia. Se ejecutan con `--settings=app_core.settings_test` (SQLite en memoria), porque el usuario de MySQL en cPanel no puede crear la base `test_*`. La otra carpeta `tests` con contenido es `buyers/functions/tests/dummy_offer.py` (fixture para probar la generación de PDFs a mano).
- Los mensajes de commit son informales y en español/inglés mezclado.
- El historial reciente muestra la plataforma pasando por un ciclo de desactivación ("standby mode") y reactivación.
