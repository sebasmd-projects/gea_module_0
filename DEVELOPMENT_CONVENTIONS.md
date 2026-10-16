# DEVELOPMENT_CONVENTIONS.md — Cómo se desarrolla en este repositorio

Guía para que otra IA o un desarrollador escriba código coherente con el de este proyecto
(Python 3.11, Django 5.2) sin redescubrir las convenciones. No es una guía genérica de Django
ni una propuesta de reestructuración: describe lo que el usuario pide de forma explícita y lo
que el código ya hace, y separa una cosa de la otra.

Complementa a `CLAUDE.md` (ficha técnica e invariantes de negocio). Si este documento y
`CLAUDE.md` se contradicen, la sección 9 lo registra; ninguna discrepancia autoriza a renombrar
ni a reescribir código existente.

---

## 1. Propósito, alcance, fuentes y límites de la revisión

### 1.1 Etiquetas de cada regla

| Etiqueta | Significado | Cómo se aplica |
|---|---|---|
| **Explícita** | Preferencia declarada por el usuario, o afirmación vigente de `CLAUDE.md` | Obligatoria en código nuevo. Se indica si hay implementación localizada |
| **Observada** | Respaldada por implementaciones leídas; se dice si es de un solo módulo o repetida en varios | Seguirla en código nuevo salvo que el fichero que se toca haga otra cosa |
| **Pendiente** | Evidencia insuficiente o contradictoria | No inventar una regla: seguir el fichero vecino y no generalizar |
| **Propuesta** | Mejora sugerida, no vinculante | Nunca se aplica sin que el usuario la acepte |

Cada regla lleva alcance, ejemplo y fuente (ruta relativa al repositorio más un símbolo que existe).
Cuando el porqué no está escrito en el repositorio, se dice «sin motivo documentado»; no se reconstruye historia.

### 1.2 Fuentes

- Cuatro informes de investigación (nomenclatura, vistas/URLs/plantillas/i18n/admin, tipado y estilo,
  modelos/lógica/pruebas), con recorridos `ast` sobre `apps/` y `app_core/` **excluyendo**
  `migrations/`, `locale/`, `public/` y `.venv/`: 228 ficheros `.py` de producción (186 sin contar
  `__init__.py`) y 80 bajo carpetas `tests/`. Cada informe filtró de forma ligeramente distinta, así que
  los totales parciales de cada sección pueden diferir en unas pocas unidades; ninguna regla depende de ello.
- `CLAUDE.md`, tratado como fuente **Explícita** donde sigue siendo cierto; la sección 9 lista dónde
  ya no lo es.
- Lectura directa de ficheros concretos para verificar cada símbolo citado aquí.

### 1.3 Límites

- Es una **muestra analizada**, no una auditoría exhaustiva: no se revisó uno a uno el tipo de PK por
  modelo, el `verbose_name` de cada `Meta`, ni el contenido de `docs/FEATURES_MAP.md` y `docs/ROUTES_MAP.md`.
- Los recuentos de idioma de comentarios son heurísticos (palabras vacías); los del resto salen de `ast`/`grep`.
- El intérprete que ejecutó los análisis era 3.13; el proyecto declara 3.11 (`.python-version`, `requires-python >=3.11`).
- **No existe ninguna herramienta de estilo configurada**: ni `ruff`, `flake8`, `black`, `isort`, `mypy`,
  `pyright`, `.editorconfig` ni `pre-commit`. `pyproject.toml` solo tiene `[project]` y `[dependency-groups]`.
  Lo que sigue es el estilo **observado**, no uno impuesto por máquina.
- **No hay Django REST Framework** (sin serializers, viewsets, routers ni clases de permisos): las secciones
  correspondientes no existen en esta guía.
- **Graphify no está instalado** y no hay salida de grafo en el repositorio (solo `.graphifyignore`).
  **No se encontró ningún vault de Obsidian.** Nada de esto se usó como fuente.
- Longitud de línea: no hay límite configurado. Distribución observada en producción: p95 77, p99 80,
  máximo 148; solo 1,3 % de las líneas pasa de 79 columnas. El código nuevo respeta ≈79 (**Observada**).

### 1.4 Alias de rutas usados en el documento

Para no repetir rutas largas, un nombre de app seguido de `/` significa su carpeta:

| Alias | Carpeta |
|---|---|
| `core/`, `utils/` | `apps/common/core/`, `apps/common/utils/` |
| `account/`, `pqrs/`, `users/`, `notifications/` | `apps/project/common/<nombre>/` |
| `assets/`, `assets_location/`, `buyers/` | `apps/project/specific/assets_management/<nombre>/` |
| `certificates/`, `video_masonry/` | `apps/project/specific/documents/<nombre>/` |
| `code_gen/`, `ops/` | `apps/project/specific/internal/<nombre>/` |

Ejemplo: `buyers/models.py` = `apps/project/specific/assets_management/buyers/models.py`.
`app_core/`, `templates/`, `docs/`, `deploy/` y `public/` son rutas desde la raíz.

---

## 2. Reglas esenciales para una IA que vaya a implementar cambios

1. **Modelos.** Para un modelo nuevo, hereda de `TimeStampedModel` (`utils/models.py`), nómbralo
   `<Nombre>Model` sin duplicar «Model» si el nombre ya lo contiene, fija `db_table` y declara su
   propio `ordering` (el `Meta` del abstracto no se hereda). *Explícita* (nombre) y *Observada* (resto, 35 de 35 modelos heredan; 32 de 35 fijan `db_table`).
2. **Enumeraciones.** `models.TextChoices` con sufijo `Choices` (`DocumentTypeChoices`), miembros en MAYÚSCULAS, etiquetas con `_()`. *Explícita* (sufijo); *Observada* (solo `TextChoices`, 26 de 33 con sufijo).
3. **Admin.** Registra con `@admin.register(Modelo)` y hereda `GeneralAdminModel` (`utils/admin.py`). Nombra la subclase `<ClaseDelModelo>Admin`. *Explícita* solo el nombre `GeneralAdminModel` como ejemplo de tu nomenclatura de administración; *Observada* que los admins lo hereden (24 de 33) y el nombre de las subclases (28 de 33). El sufijo «AdminModel» **no** se generaliza a las subclases.
4. **Funciones.** `snake_case`, con anotaciones de parámetros y de retorno como en `block_duration(attempt_count: int, base: timedelta) -> timedelta` (`utils/blocking.py`). *Explícita*. La cobertura real es 36 % de retornos y 25 % de parámetros: el código nuevo debe superar esa media, no igualarla.
5. **Cron.** Para una función nueva registrada en `CRONJOBS` usa `<verbo>_..._cron() -> None`. *Explícita — preferencia explícita del usuario, sin implementación localizada*: las dos existentes se llaman `generate_and_send_gea_code` y `warm_gea_app`, sin sufijo ni anotación. No se renombran.
6. **Vistas.** CBV con nombre `Recurso + Acción + View`, donde el sufijo coincide con la clase base de Django (`OfferUpdateView` hereda de `UpdateView`). Acceso por mixin, no por decorador. *Explícita* (patrón) y *Observada* (60 CBV frente a 15 FBV enrutadas).
7. **Dónde va cada cosa.** Regla de negocio de una entidad en su modelo; algoritmos de certificación en `code_gen/services/`; quién puede ver qué en `access.py`; mixins de rol en el `views.py` de la app (donde ya viven). *Explícita* (`CLAUDE.md` §4-bis) y *Observada*.
8. **Texto visible.** `gettext_lazy as _`, msgid en **inglés**, traducción al español en `.po`. Nunca `_()` dentro de una f-string. *Explícita* (`CLAUDE.md` §5, §7).
9. **Comentarios y docstrings.** En español, explicando el porqué (decisión, incidente, alternativa descartada). Identificadores en inglés. *Observada* (135 de 139 módulos con texto en español).
10. **Plantillas.** Comentarios con `{% comment %}`, nunca `{# #}`; no recargar un script que `templates/raw.html` ya carga; todo recurso de CDN con versión exacta e `integrity`. *Explícita* (la hacen cumplir `utils/tests/test_scripts.py` y `utils/tests/test_sri.py`).
11. **Transacciones.** `ATOMIC_REQUESTS = True`: un efecto externo (correo, red, OpenAI) dentro de una petición no puede propagar su fallo si eso deshace una escritura propia. *Explícita* (`CLAUDE.md` §3, §7) y *Observada*.
12. **Respuestas a quien no debe ver.** En zonas sensibles, 404 y no 403. Es política *Explícita* pero **no uniforme** en el código (sección 9): ante la duda, 404 en lo nuevo que revele existencia de un objeto.
13. **Contadores de intentos.** Pasan siempre por `RateLimit` (`utils/throttling.py`), que falla cerrado salvo `fail_open=True` con `reason`. Nunca `cache.get(k) or 0`. *Explícita* (invariante 21).
14. **Logging.** `logger = logging.getLogger(__name__)`; en código nuevo, argumentos perezosos `%s`. *Observada* (49 módulos; 62 llamadas perezosas frente a 18 con f-string).
15. **Imports.** Relativos dentro de la app, absolutos entre apps, agrupados como isort por defecto (stdlib, terceros y Django mezclados alfabéticamente, `apps.*`, relativos). *Observada*.
16. **Ajustes nuevos.** Defínelos en `app_core/settings.py` como nombre de módulo aunque los consuma un diccionario; si son obligatorios, decláralos en `app_core/env.py`. Un `getattr(settings, 'X', d)` sin definición en `settings.py` no es configurable por entorno. *Explícita* (`CLAUDE.md` §7).
17. **Pruebas.** En `<app>/tests/test_*.py`, ejecutables con `--settings=app_core.settings_test`; fixtures por mixins propios, sin factorías; el docstring de clase cuenta qué fallo previene. *Explícita* (`CLAUDE.md` §11) y *Observada*.
18. **No convertir hallazgos en reglas.** Los defectos de la sección 9.3 (p. ej. `PermissionError` fuera del `try`) no son convenciones.
19. **No copiar datos sensibles** a documentación, ejemplos ni pruebas: claves, correos reales, teléfonos, usuarios de allowlists.
20. **No tocar** `delete_migrations` ni `rename_migrations` salvo petición explícita (`CLAUDE.md` §3).

---

## 3. Nomenclatura

Idioma: identificadores en inglés (excepciones aisladas en español, ver 3.2); comentarios y docstrings en español;
msgid visibles en inglés. Ninguna clase ni función del código analizado incumple `CamelCase`/`snake_case`.

### 3.1 Tablas por categoría

**Modelos y bases abstractas**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| `<Nombre>Model(TimeStampedModel)`, PascalCase descriptivo; «Model» no se duplica (0 coincidencias de `ModelModel`) | `LegalDocumentModel`, `IPBlockedModel`, `UserVerificationModel`, `OfferModel`, `StampLayoutModel`, `CommandRunModel` | 6 sin sufijo, todos hijos de `TimeStampedModel`: `GeaDailyUniqueCode` (`utils/models.py`), `MediaAsset`, `MediaAssetInteraction`, `MediaAssetUserStats` (`video_masonry/models.py`), `ServiceOrderRecipient` (`buyers/models.py`), `PQRSRequest` (`pqrs/models.py`) | `<app>/models.py` | **Explícita** (sufijo, preferencia del usuario; implementación localizada en 29 de 35 modelos concretos) |
| Base abstracta única `TimeStampedModel(models.Model)` con `Meta.abstract = True`; aporta `history`, `language`, `created`, `updated`, `is_active`, `default_order` | `TimeStampedModel` (`utils/models.py`); `UserModel(TimeStampedModel, AbstractUser)` | Ninguna otra base abstracta de modelos | `utils/models.py` | **Observada** (en todas las apps que tienen modelos) |
| Alias de módulo `UserModel = get_user_model()` (variable CamelCase, no clase) | `assets/models.py`, `assets_location/models.py`, `buyers/models.py` y otros ficheros (6 en total) | Otros estilos conviven: `settings.AUTH_USER_MODEL` (core, pqrs, video_masonry), import directo (certificates) | cabecera del módulo | **Pendiente** (tres estilos, sin motivo documentado) |

Un modelo nuevo no debe llevar sufijo `Model` repetido ni omitirlo: la excepción histórica no autoriza a omitirlo (`CLAUDE.md` §5 solo reconoce `ServiceOrderRecipient` y `MediaAsset*`; faltan `GeaDailyUniqueCode` y `PQRSRequest`).

**Enumeraciones**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| `models.TextChoices` con sufijo `Choices`; miembros MAYÚSCULAS con valor corto y etiqueta `_()` | `DocumentTypeChoices` (`certificates/models.py`), `CodeKindChoices` (`code_gen/models.py`), `IPBlockedModel.ReasonsChoices` | 7 sin sufijo: `LegalDocumentKind`, `LegalVersionStatus`, `AcceptanceMethod`, `DeliveryMethod`, `DocumentCopyKind`, `MediaType`, `Action`. 0 `IntegerChoices` y 0 `enum.Enum` | A nivel de módulo en `certificates`, `code_gen`, `core`; anidada en el modelo en `utils`, `users`, `buyers`, `assets_location`, `video_masonry`, `ops`; `pqrs` mezcla | **Explícita** (sufijo); **Observada** (solo `TextChoices`; ubicación por app) |
| Nombres repetidos entre modelos distintos | `StatusChoices` ×3 (anidadas, sin colisión), `QuantityTypeChoices` ×2 | — | anidadas | **Observada** |
| Dónde declarar una enumeración nueva | — | — | Seguir la app: módulo en `certificates`/`code_gen`/`core`, anidada en el resto | **Pendiente** (no hay criterio escrito de cuándo anidar) |

**Admin**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| Base `GeneralAdminModel(ImportExportActionModelAdmin, admin.ModelAdmin)`: `list_per_page=100`, `max_list_per_page=2000`, `format_thousands`, selector de `list_per_page` | `utils/admin.py` | El nombre de la base lleva «Model» aunque sea un admin; `OfferModelAdmin` y `ServiceOrderRecipientAdmin` repiten sus dos bases sin heredarla | `utils/admin.py` | **Explícita** el nombre (ejemplo del usuario); **Observada** su uso como base en 24 de 33 admins |
| Subclase: `<ClaseDelModelo>Admin`; si el modelo acaba en `Model`, resulta `...ModelAdmin` | `UserVerificationModelAdmin`, `IPBlockedModelAdmin`, `OfferModelAdmin`, `PQRSRequestAdmin`, `MediaAssetAdmin`, `ServiceOrderRecipientAdmin` | 5 quitan el `Model` del modelo: `LegalDocumentAdmin`, `LegalDocumentVersionAdmin`, `LegalAcceptanceAdmin`, `AssetCountryAdmin`, `AssetLocationAdmin`. Total: 21 acaban en `ModelAdmin`, 12 en `Admin` | `<app>/admin.py` o `<app>/admin/__init__.py` | **Observada** (28 de 33) |
| Nombre de una **nueva clase base** de admin | — | — | — | **Pendiente**: «AdminModel» no se generaliza a otros admins |
| Registro `@admin.register(Modelo)` (0 `admin.site.register`); inlines `<X>Inline`; recursos `<X>Resource(resources.ModelResource)`; filtros `<X>Filter` | `StampPlacementInline`, `AssetResource`, `OverdueFilter` | `admin.site.unregister(Group)` en `users/admin.py` | idem | **Observada** |
| Columnas calculadas `@admin.display(description=_())`; acciones `@admin.action(description=_())` | `certificates/admin.py::action_certify_documents` | Factoría `set_certificate_type_action`; acción por nombre de método en `LegalDocumentVersionAdmin` (`approve_versions`) | idem | **Observada** |
| Sitio y config con prefijo `Gea` | `GeaAdminSite` (`app_core/admin.py`), `GeaAdminConfig` (`app_core/apps.py`) | — | `app_core/` | **Observada** |

Admins que no usan la base (9): los tres de `core/admin.py`, `GeaDailyUniqueCodeAdmin`, los tres de `video_masonry/admin.py` y `OfferModelAdmin`/`ServiceOrderRecipientAdmin`. Tres admins de `assets/admin/__init__.py` añaden `ImportExportModelAdmin` antes de la base: es redundante, no un patrón.

**Vistas (CBV y FBV)**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| `Recurso + Acción + View`; el sufijo coincide con la base de Django | `PurchaseOrderCreateView`, `OfferUpdateView`, `OfferDetailView`, `AssetLocationDeleteView`, `LocationCreateView`, `CodeHistoryListView`, `StampLayoutListView`, `SummaryCreateView` | `AssetAddNewCategory` (sin `View`), `HolderTemplateview` (minúscula), `AssetUpdateView` (edita `AssetLocationModel`), `PurchaseOrdersView` (listado plural sobre `TemplateView`) | `<app>/views.py` (siempre módulo, nunca paquete) | **Explícita** (patrón conceptual «recurso + tipo de vista»); **Observada** el orden y el sufijo |
| `Recurso + TemplateView` / `+ FormView` cuando la base es genérica de plantilla o formulario | `IndexTemplateView`, `CertificatesLandingTemplateView`, `CodeGeneratorView`, `InputDocumentVerificationFormView` | `ForgotPasswordFormView` hereda de `View`, no de `FormView` | idem | **Observada** |
| Prefijo `Input` + recurso + `FormView` para la entrada de un flujo de verificación | `InputEmployeeIPCONFormView`, `InputDocumentVerificationFormView` | — | `certificates/views.py` | **Observada** (solo certificates) |
| Rol dentro de un recurso: `OfferApprovalWizard` + `PageView` / `PartialView` / `ActionView` | `OfferApprovalWizardActionView` | Únicos del repo con esos sufijos | `buyers/views.py` | **Observada** (solo buyers) |
| Wizard de `formtools`: `...WizardView` | `GeaUserRegisterWizardView`, `PQRSWizardView` | «Wizard» significa otra cosa en `OfferApprovalWizard*` (UI propia de aprobación) | `account/views.py`, `pqrs/views.py` | **Observada** |
| Prefijos de dominio: `Offer*` (buyers), `Summary*` (code_gen), `PQRS*`, `Gea*` (especializa una clase de librería) | `GeaLoginView` | El resumen AEGIS se llama `Summary*` en `code_gen` y `AegisSummary*` en `certificates` | idem | **Observada**; unificar prefijo: **Pendiente** |
| Borrado lógico por POST con respuesta JSON: nombre `...DeleteView` aunque herede de `View` | `OfferSoftDeleteView`, `LocationReferenceDeleteView` | Solo `AssetLocationDeleteView` hereda de `DeleteView` | idem | **Observada** |
| FBV: `snake_case` con nombre de acción; JSON | `layout_placements`, `summary_seal`, `preview_symbols` (`code_gen/api.py`); `issue_document`, `revoke_document` (`certificates/external.py`); `certification_public_key`, `summary_master_payload`, `summary_anchor_proof` (`certificates/views.py`); `set_language` | Manejadores `handler400..504` (`utils/views.py`) | `code_gen/api.py`, `certificates/external.py`, `utils/views.py` | **Observada** (15 FBV enrutadas, todas en esos módulos) |
| Vistas dentro de un `ModelAdmin`: método `<nombre>_view` | `CommandRunModelAdmin.console_view`, `test_summary_view`, `command_view` | — | `ops/admin.py` | **Observada** (solo ops) |

El orden es siempre recurso primero y acción después; no inventes variantes con la acción delante. Para un recurso nuevo con alta/edición/detalle/listado/borrado, usa los cinco sufijos de Django con el mismo recurso en todos (la excepción `AssetUpdateView` no es un modelo a seguir).

**Formularios, widgets, mixins, managers, validadores**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| Clases de formulario acaban en `Form` (36 clases, todas) | `ChangePasswordForm`, `OfferForm`, `CodeGeneratorForm`, `AegisSummaryForm` | `ModelForm` con sufijo `ModelForm` solo en `assets_location/forms.py` (`LocationModelForm`, `AssetLocationModelForm`, `AssetUpdateLocationModelForm`); 9 `ModelForm` más acaban en `Form` | `<app>/forms.py` | **Observada** (sufijo `Form`); sufijo `ModelForm`: **Pendiente** |
| Pasos de asistente: `<Tema>Form` o `...StepNForm` | `UserInformationForm`, `ForgotPasswordStep1Form`, `RequestTypeForm`, `NaturalHolderForm` | Dos estilos coexisten | `account/forms/`, `pqrs/forms.py` | **Observada** (local a cada app) |
| `*Widget` (7) y `*Field` (2) | `AssetNameWidget`, `CountryWidget`, `SupportingDocumentField` | `AssetNameWidget` y `CountryWidget` están duplicados en `buyers/form.py` y en las otras apps | forms | **Observada** |
| `*Mixin` (10) de acceso o flujo | `BuyerRequiredMixin`, `HolderRequiredMixin`, `InternalToolAccessMixin`, `HistoryAccessMixin`, `OTPSessionMixin`, `OfferMutationMixin`, `CommonCleanMixin` | Casi todos viven en el `views.py` de su app, no en `mixins.py` | `<app>/views.py`; `certificates/mixins.py`; `buyers/access.py` | **Observada** |
| Manager propio: `<Modelo>Manager(models.Manager)` | `GeaDailyUniqueCodeManager` | Único del repo; 0 clases `QuerySet`; la lógica de consulta va en `@classmethod` o en `access.py`/`history.py` | `utils/models.py` | **Observada** (un solo módulo) |
| Validadores: clases `Unicode*Validator`; funciones `validate_*` | `UnicodeNameValidator` (`users/validators.py`), `validate_barcode_payload` (`code_gen/services/codes.py`) | `validate_birth_date` es `staticmethod` del modelo | `users/validators.py` (único `validators.py`) | **Observada** (un solo módulo) |

**Middleware, señales, context processors, templatetags**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| Clases `*Middleware` sin base, estilo `__init__(get_response)` / `__call__` | `RedirectWWWMiddleware`, `BlockBadBotsMiddleware`, `DetectSuspiciousRequestMiddleware` | Fichero y clase no coinciden: `block_bots.py` / `BlockBadBots...`; `block_suspicious_request.py` / `DetectSuspicious...` | `utils/middleware/` | **Observada** (un solo paquete) |
| Handlers de señal: `auto_<verbo>_<objeto>_on_<evento>` o `auto_fill_<x>_translation`; se conectan con `pre_save.connect(...)` al pie de `models.py` | `auto_delete_asset_img_on_delete`, `auto_fill_offer_translation` | Única `@receiver`: `record_continued_use` (`core/signals.py`) con `dispatch_uid`, importada en `CoreConfig.ready` | `<app>/signals.py` en core, assets, buyers | **Observada** (assets y buyers: 8 conexiones); `@receiver` es local a core |
| Context processor | `custom_processors` | Único, devuelve `{}` | `utils/context_processors/__init__.py` | **Observada** (un solo caso) |
| Templatetags: una sola biblioteca `custom_filters` | `add_class`, `add_attrs`, `currency`, `active_class`, `aria_expanded` | 12 utilidades, `CLAUDE.md` lista 9 | `utils/templatetags/custom_filters.py` | **Observada** (un solo módulo) |

**Comandos, cron, servicios y helpers**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| Comando: fichero `snake_case` `verbo_objeto`; clase siempre `Command(BaseCommand)`; familia `check_*` para diagnóstico | `check_security`, `db_backup`, `rotate_logs`, `notify_legal_changes`, `upgrade_ots_anchors` | `runserver` y `start_app` heredan de comandos de Django; `utils/management/transcribe.py` es un script suelto fuera de `commands/` | `<app>/management/commands/` (utils 20, code_gen 3, core 1, certificates 1) | **Observada** (25 comandos) |
| Función de cron: `<verbo>_..._cron() -> None` | Ninguna existente | Las reales son `generate_and_send_gea_code()` y `warm_gea_app()` en `utils/cron.py`, sin sufijo `_cron` ni anotación | `utils/cron.py`, registradas por ruta de cadena en `CRONJOBS` (`app_core/settings.py`) | **Explícita — preferencia explícita del usuario, sin implementación localizada** |
| Cron por comando: entrada de `CRONJOBS` con `_call_command` y nombre del comando | `upgrade_ots_anchors`, `rotate_logs`, `notify_legal_changes` | — | `app_core/settings.py` | **Observada** (3 de 5 entradas) |
| Servicios de dominio: módulo por responsabilidad, verbos de dominio, prefijos `build_*`, `verify_*`, `render_*`, `generate_*`, `sha256_*` | `certify_document`, `seal_summary`, `build_bundle`, `export_state`, `anchor_with_tsa` | `sha256_hex` duplicado en `utils/functions/generate_hash.py` y `code_gen/services/hashing.py` | `code_gen/services/` | **Observada** (un solo paquete) |
| Helpers privados: prefijo `_` (300 `def` de 1162; 108 top-level) | `_forbidden`, `_layout_payload`, `_optimize_image`; clases privadas `_Replay`, `_Saneador` | — | mismo módulo que los usa | **Observada** (repetida en muchas apps) |
| Constantes: `UPPER_CASE` a nivel de módulo (441), `_PRIVADA` con guion bajo (14), comentario `#:` encima | `MAX_BLOCK`, `VALID_KINDS`, `UTILS_PATH`, `RISK_*`, `AVAILABILITY_*` | `constants.py` solo en `certificates` y `code_gen`; las demás apps las dejan en el módulo | idem | **Observada** |
| Excepciones propias: raíz propia, docstring de una línea | `CertificationError`, `TSAError`, `OTSError`, `MasterHashError`, `BackupCryptoError`, `CanonicalizationError` | Sin sufijo: `CommandNotAllowed`, `InsecureUrlScheme`, `NotReadyToExport`, `InvalidRequest`, `_Replay` | el módulo de servicio que las lanza | **Observada** el sufijo `Error` en 6 de 11; **Pendiente** para nuevas (sin jerarquía común ni regla) |
| Dataclasses y objetos de valor: sin sufijo fijo | `ScanResult`, `Option`, `Command` (`ops/registry.py`), `HistoryRow`, `CodeOptions`, `CertificationOutcome` | `RateLimit` y `ChatGPTAPI` son clases de servicio sin base | `utils/scanners.py`, `ops/registry.py`, `code_gen/history.py`, `code_gen/services/certification.py` | **Observada** (13 dataclasses) |

**Pruebas, ficheros, URLs, plantillas, base de datos**

| Patrón | Ejemplos verificados | Excepciones | Ubicación | Etiqueta |
|---|---|---|---|---|
| Ficheros `test_<tema>.py` en `<app>/tests/` con `__init__.py` | `buyers/tests/test_workflow.py`, `utils/tests/test_sri.py` | Fixture sin prefijo: `buyers/functions/tests/dummy_offer.py`; utilidades de prueba en `utils/test_runner.py` y `utils/testing.py` | carpeta `tests/` en las 13 apps y en `app_core/` | **Explícita** (`CLAUDE.md` §11); **Observada** (64 ficheros `test_*.py`) |
| Clases de prueba: por la propiedad que garantizan, no por la clase probada; sufijos `Tests`/`TestCase`/`Mixin` libres | `TestTheStateIsDerived`, `TheTrapCatchesRealScans`, `StaleContextTestCase`, `OfferFixtureMixin` | Clases en español solo en `utils/tests/test_realtime.py` (`CanalTestCase`...) | idem | **Observada** (106 acaban en `Tests`, 31 en `TestCase`, resto libre) |
| Métodos `test_<comportamiento>` en inglés (≈89 %) | `test_nothing_loads_unverified` | Español en 90 nombres (`test_la_...`), concentrados en 6 ficheros; `test_1_...` a `test_6_...` en `test_login_paths.py` | idem | **Observada** (inglés); español: local |
| Paquetes y módulos `snake_case`; `forms.py` o `forms/`, `admin.py` o `admin/` según app | ver sección 4 | `buyers/form.py` (singular) | raíz de la app | **Observada** |
| `app_name` en `urls.py` igual al nombre de la app; nombres de ruta `snake_case`; sin orden único recurso/acción | `code_generate`, `summary_anchor_proof`, `offer_wizard_action` | Faltan `app_name` en `users` y `notifications`; `verbo_recurso` en assets_location (`add_location`) y `recurso_verbo` en buyers/code_gen (`offer_update`); sufijos `_view`, `_index`, `_landing` sueltos | `<app>/urls.py` | **Observada** (nombre `snake_case`); orden verbo/recurso: **Pendiente** |
| `db_table` `apps_<app>_<modelo_snake>` | `apps_buyers_offer`, `apps_certificates_aegis_summary_document`, `apps_ops_command_run` | Palabras pegadas (`apps_assets_assetcategory`), con ruta completa (`apps_common_utils_ipblocked`), sin `apps_` (`utils_gea_daily_unique_code`), errata histórica `apps_users_userpersonalpnformation`, ausente en `video_masonry` | `Meta` del modelo | **Observada** (apps nuevas usan `snake_case`); **Explícita** que sea explícito (`CLAUDE.md` §5) |
| `related_name`: en apps antiguas `<app>_<modelo>_<campo>`; en apps nuevas sustantivo plural inglés | `buyers_offer_user`; `versions`, `acceptances`, `placements`, `held_certificates` | — | campos FK/M2M | **Observada** (dos estilos por antigüedad); estilo para nuevos: **Pendiente** |
| Plantillas `snake_case.html` por acción; carpeta `dashboard/pages/<rol>/`; prefijo `_` para fragmento de una página o repetido | `create_purchase_orders.html`, `edit_offer.html`, `_offer_approval_wizard.html` | `includes/_anchor_proof_button.html` mezcla carpeta y prefijo; las páginas de `ops` no llevan `_` | `templates/` | **Observada** (31 ficheros con `_`) |
| `AppConfig` `<Nombre>Config` con `name` de ruta completa | `CoreConfig`, `CodeGenConfig`, `OpsConfig` | `UtilsConfig.name = f'{settings.UTILS_PATH}'`; `PqrsConfig` no usa mayúsculas como `PQRSRequest` | `<app>/apps.py` | **Observada** |

### 3.2 Idioma

- Identificadores en inglés. Excepciones aisladas en español, no imitar: `_Saneador`, `_Conversor`, `fecha`, `codigo_unico`, `use_titular_contact`.
- Campos bilingües por duplicación (no hay librería de traducción): prefijo `es_*`/`en_*` es el dominante (`es_name`, `es_body`, `es_description`); sufijo `*_es`/`*_en` es local (`description_es` en `assets_location`, `change_note_es` en `core`). **Observada**: sigue el patrón del fichero que tocas; no se mezclan los dos dentro de un modelo nuevo.
- Español de comentarios: en el 79 % de los ficheros **sin tildes** («tambien», «funcion»). **Observada**: el texto visible al usuario sí lleva tildes. No hay regla escrita; un `grep` de una palabra acentuada no encuentra la mayoría de los comentarios.

---

## 4. Estructura de carpetas, archivos y dependencias

### 4.1 Árbol resumido

```
app_core/            settings.py, settings_test.py, env.py, urls.py, admin.py (GeaAdminSite), apps.py,
                     db/ (motor MySQL propio), tests/, locale/, signature.py, wsgi.py, asgi.py
apps/
  common/
    core/            landing, health, documentos legales: models.py, legal.py, legal_html.py,
                     legal_pdf.py, signals.py, legal_seed/, templates/core/, management/commands/
    utils/           base compartida: models.py, admin.py, blocking.py, scanning.py, throttling.py,
                     netintel.py, client_ip.py, cron.py, outbound.py, login_attempts.py, otp_email.py,
                     backup_crypto.py, scanners.py, wizards.py, logs.py, testing.py, test_runner.py,
                     backend/, context_processors/, functions/, middleware/, templatetags/,
                     management/commands/, data/, tests/
  project/
    common/
      account/       login_view.py, otp_login.py, emails.py, views.py, forms/, tests/
      notifications/ vacía a propósito (models, views, urls sin contenido)
      pqrs/          models.py, views.py (wizard), forms.py, deadlines.py, admin.py
      users/         models.py (UserModel, geografía, PII), validators.py, admin.py
    specific/
      assets_management/
        assets/          models.py, signals.py, forms.py, admin/ (paquete), views.py
        assets_location/ models.py, forms.py, admin/ (paquete), views.py
        buyers/          models.py (flujo de 12 etapas), access.py, form.py, signals.py,
                         functions/ (generadores de PDF), views.py, admin.py
      documents/
        certificates/    models.py, views.py, mixins.py, files.py, verification.py, external.py,
                         functions.py, utils.py, constants.py, checks.py, admin.py
        video_masonry/   models.py, views.py, utils.py, admin.py
      internal/
        code_gen/        models.py, views.py, api.py, access.py, history.py, preview.py, forms.py,
                         constants.py, services/ (17 módulos), usb_kit/ (3 guiones), admin.py
        ops/             registry.py, runner.py, summary.py, admin.py; urls.py vacío a propósito
templates/           raw.html, dashboard/{dashboard_layout_base.html,pages/,partials/}, account/, admin/,
                     core/, email/, errors_template.html, partials/, pqrs/, two_factor/, video_masonry/, locale/
public/staticfiles/  css/ (10 hojas), js/ (12 scripts a mano), assets/
docs/                ROUTES_MAP.md, FEATURES_MAP.md, NORMATIVA.md, SEGURIDAD.md, ANCLAJE.md,
                     DJANGO_5_2.md, GETTING_STARTED.md, TAREAS_EN_SEGUNDO_PLANO.md, env.example, guías HTML
deploy/              README.md, REDIS.md, media.htaccess, media-protected.htaccess
```

Cada app lleva además `apps.py`, `migrations/`, `locale/es/LC_MESSAGES/` y `tests/`. `notifications/` no tiene `locale/`.

### 4.2 Responsabilidades: verificado en código frente a deducido del árbol

| Carpeta o fichero | Responsabilidad | Verificación |
|---|---|---|
| `code_gen/services/` | Algoritmos de certificación; sin vistas, un módulo por responsabilidad, docstring largo con el porqué | Verificada en código (imports y firmas) |
| `buyers/access.py` | Reglas de quién ve y modifica una orden (`can_view_offer`, `can_modify_offer`) + `OfferMutationMixin` | Verificada en código |
| `code_gen/access.py` | Solo funciones (`is_operator`, `visible_registrations`, `can_see_internals`...); el mixin que las usa está en `code_gen/views.py` | Verificada en código |
| `certificates/mixins.py`, `files.py`, `verification.py`, `external.py` | OTP, entrega de PDF, cotejo de archivo subido, emisión externa (JSON) | Verificada en código |
| `utils/` (raíz) | Módulos planos de infraestructura transversal (bloqueo, límites, cron, correo OTP, respaldo) | Verificada en código; el listado es de la raíz, no se leyó cada módulo |
| `buyers/functions/` | Generadores de PDF de orden de compra y de servicio | Verificada en código |
| `utils/functions/` | `chatgpt_api.py`, `generate_hash.py`, `safe_redirect.py` | Verificada en código |
| `certificates/functions.py` (fichero) | OTP, HMAC, normalización, QR y barcode, IP | Verificada en código |
| `certificates/utils.py`, `video_masonry/utils.py` | Helpers de la app (comparten nombre con la app `utils` sin relación con ella) | Deducida de nombre y cabeceras |
| `notifications/` | Reservada, vacía | Verificada (sin clases) |
| `docs/*.html` y `*.pptx` | Material para enseñar fuera, no para desarrollar | Deducida de `CLAUDE.md` |

### 4.3 Dónde ubicar funcionalidad nueva

| Para añadir... | Haz esto y ubícalo en... | Etiqueta |
|---|---|---|
| Una app nueva | `uv run python manage.py start_app apps/project/specific/<grupo>/<nombre>` y añádela **a mano** al grupo de `app_core/settings.py` (`COMMON_APPS`, `PROJECT_COMMON_APPS`, `PROJECT_ASSETS_MANAGEMENT_APPS`, `PROJECT_DOCUMENTS_APPS`, `PROJECT_INTERNAL_APPS`). El orden de los grupos fija el del URLconf y el de `LOCALE_PATHS` | **Explícita** |
| Una ruta | Vista en `<app>/views.py` con el mixin de acceso, registro en `<app>/urls.py` y comprobación de que el path no contiene un término de `COMMON_ATTACK_TERMS` | **Explícita** |
| Una regla de negocio de una entidad | Método del modelo (`mark_*`, `clean`, `save`) y, si es del flujo de órdenes, también la restricción en BD | **Explícita** (invariantes 1-3) |
| Un algoritmo de certificación o anclaje | Módulo nuevo en `code_gen/services/` con docstring del porqué y excepción propia | **Observada** |
| Quién puede ver o modificar | Función en `access.py` de la app; el recorte, en el queryset | **Observada** (buyers, code_gen) |
| Un endpoint JSON interno | FBV en `code_gen/api.py` (con `@require_http_methods`) o CBV `View` con `JsonResponse`; no hay DRF | **Observada**; elegir entre FBV y CBV: **Pendiente** |
| Una tarea periódica | Función en `utils/cron.py` o comando en `management/commands/`, y entrada en `CRONJOBS`. Si es un efecto externo, por cron y no dentro de la petición | **Observada** |
| Un comando de gestión | `<app>/management/commands/`; si debe poder ejecutarse desde el panel, decláralo en `ops/registry.py` (`COMMANDS`, `NEVER_EXPOSED` o `NOT_USEFUL_HERE`: ninguno puede quedar sin decidir) | **Explícita** |
| Un `FileField` | Decidir si su carpeta se bloquea en `deploy/media.htaccess` o se declara en `PUBLICLY_SERVABLE_MEDIA` | **Explícita** (invariante 13) |
| Un middleware | `utils/middleware/` y alta en `MIDDLEWARE` respetando el orden documentado | **Observada** |

No hay un umbral documentado de tamaño para dividir un módulo. Existen ficheros de más de 800 líneas (`buyers/views.py` 1076, `code_gen/views.py` 905, `certificates/admin.py` 862) sin norma que los parta: no inventes una cifra.

### 4.4 Formas que coexisten

| Par | Estado real | Etiqueta |
|---|---|---|
| `forms.py` frente a `forms/` | `forms.py` en 6 apps; paquete `forms/` solo en `account` (6 módulos `*_form.py`); **`buyers/form.py` en singular es una excepción** y se importa como `from .form import ...`. Ninguna app mezcla las dos formas. `core/forms.py` está vacío | **Observada**; nombre singular: inconsistencia, no modelo |
| `admin.py` frente a `admin/` | `admin.py` en 9 apps; paquete `admin/` en `assets` y `assets_location` con el código en `__init__.py` (`assets` añade `filters.py`) | **Observada** |
| `functions/` frente a `functions.py` | Paquete en `utils` y `buyers`; fichero en `certificates` | **Pendiente** |
| `services/` | Solo `code_gen`. Otras apps ponen la lógica de servicio en módulos planos | **Observada** (un solo paquete) |
| `views.py` | Siempre módulo; no existe `views/` | **Observada** |
| `access.py` | `buyers` y `code_gen`; sin equivalente en las demás | **Observada** |
| `mixins.py` | Solo `certificates`; los demás mixins viven en `views.py` | **Observada** |
| `constants.py` | Solo `certificates` y `code_gen` | **Observada** |
| `signals.py` | `core`, `assets`, `buyers`; **no debe existir en `video_masonry`** (`CLAUDE.md` §7) | **Explícita** (esa excepción) |

### 4.5 Dirección real de las dependencias

- **`utils` no importa hacia arriba** en código de producción. Único caso: `check_health.py` importa `HealthCheckView` de `core` dentro de una función. Las pruebas de `utils` sí tocan `users` y `ops`. **Explícita** y verificada.
- **`users` es hoja**: solo importa `utils`. **Explícita** y verificada.
- **`ops` es terminal**: nadie lo importa en producción. **Explícita** y verificada.
- **`certificates` y `code_gen`**: `certificates` posee los modelos y `code_gen` los algoritmos. `code_gen` importa `certificates.models` siempre diferido, salvo `code_gen/forms.py`, donde el import está dentro de `class Meta:` y por tanto se ejecuta al cargar el módulo. `certificates` importa `code_gen.services.*` y `code_gen.constants` **en la cabecera** de `admin.py`, `external.py`, `verification.py` y `views.py`, y en diferido en otros puntos. Lo que evita el ciclo es que ningún `models.py` importe servicios. El patrón «siempre diferido en ambos lados» **no es sistemático**; para código nuevo, importa el modelo contrario dentro de la función y no importes servicios desde `models.py`. **Observada** (parcial).
- **`assets` ↔ `assets_location` ↔ `buyers`**: `assets/views.py` importa `HolderRequiredMixin` de `assets_location` y `BuyerRequiredMixin` de `buyers`; a la vez los modelos de `assets_location` y `buyers` importan `assets.models`. Hay un ciclo de paquetes que funciona porque unos son vistas y otros modelos. Mover un mixin rompe la otra app. `video_masonry/views.py` también importa `BuyerRequiredMixin`. **Observada**.
- `core` solo es importado por `account/views.py` (aceptación de documentos legales) y `check_health`. **Observada**.
- El orden de `ALL_CUSTOM_APPS` determina el URLconf y **no** es el orden de dependencias: `utils` (con el catch-all de la trampa anti-escaneo) queda 4.ª, antes de `assets`, `assets_location`, `buyers` y `account`. **Explícita**.

---

## 5. Tipado, imports y estilo Python

### 5.1 Tipado

| Medida (producción, 1162 funciones) | Valor |
|---|---|
| Con anotación de retorno | 421 (36 %) |
| Parámetros anotados | 368 de 1464 (25 %) |
| Totalmente tipadas | 274 (24 %) |
| Pruebas: retorno / parámetros | 2 % / 4 % |
| Módulos con funciones y ninguna anotación | 50 de 149 |

| Zona | Retorno anotado | Parámetros anotados |
|---|---|---|
| `code_gen/services/` | 85 % | 59 % |
| `code_gen` completa | 65 % | 45 % |
| `utils` (resto) | 41 % | 33 % |
| `certificates` | 29 % | 21 % |
| `buyers`, `account`, `core`, `users` | 18-20 % | 8-14 % |
| `assets`, `assets_location` | 12 % y 7 % | 1 % y 0 % |
| Vistas de `certificates`, `buyers`, `assets_location`, `core`; admin, forms y signals | 0-14 % | 0-13 % |

Reglas:

1. **Explícita.** Para una función nueva, anota todos los parámetros y el retorno, en el estilo de `block_duration(attempt_count: int, base: timedelta) -> timedelta` (`utils/blocking.py`). Referencia de módulo bien tipado: `code_gen/services/codes.py`, `utils/logs.py`. Implementación localizada de forma desigual (arriba); la regla vale para código nuevo, no obliga a anotar el existente.
2. **Observada** (repetida en varios módulos recientes). Se anotan los tipos primitivos (`str`, `int`, `bool`, `bytes`, `Path`, `timedelta`, `date`). Los objetos de Django (`request`, `user`, `queryset`, `instance`) casi nunca: `HttpRequest` aparece 3 veces; `QuerySet`, `HttpResponse`, `JsonResponse`, `Model`, `Self`: 0. Ejemplos del patrón «retorno sí, objeto Django no»: `can_view_registration(user, registration) -> bool` en `code_gen/access.py`, `note_failure(request, username: str, *, reason: str = '') -> None` en `utils/login_attempts.py`. **Pendiente**: si el código nuevo debe anotar `request`/`user`; no hay `django-stubs`, `mypy` ni `TYPE_CHECKING` que lo exija.
3. **Observada.** Retornos de `__str__` con `-> str` (25 de 32). `get_context_data` y `handle` de comandos no se anotan (0 de 28; 1 de 24).
4. **Optional frente a `|`.** `Optional[X]` 39 apariciones y `List[X]`/`Dict[X]` 36 frente a `X | None` 4 y `list[X]` 3, a veces mezclados en un mismo fichero (`app_core/urls.py`, `buyers/signals.py`). Con Python 3.11 valen ambos. **Pendiente**: sigue el estilo del fichero que tocas. **Propuesta** (no vinculante): `X | None` y `list[X]` en lo nuevo.
5. **Observada.** `typing` se importa por nombre (`from typing import Optional`), nunca `import typing`. Sin `TypedDict`, `Protocol`, `NamedTuple`, `Callable` ni `TYPE_CHECKING`; `Final` solo en `app_core/urls.py`; `Literal` solo en `utils/functions/chatgpt_api.py`.
6. **Observada.** Para tipar un modelo sin importarlo (dataclasses de `code_gen/history.py`) se usa `object`. Es coherente con no importar modelos entre `certificates` y `code_gen`, pero informa poco.
7. **Observada.** `from __future__ import annotations` solo en `video_masonry/*` y `app_core/urls.py`. No es una convención de proyecto.
8. **Dataclasses.** 13: `@dataclass` o `@dataclass(frozen=True)`, campos con valor por defecto y `field(default_factory=list)` para colecciones, comentarios `#:` encima de cada atributo. Ejemplo: `ScanResult` en `utils/scanners.py`; catálogo inmutable `Command` en `ops/registry.py`. **Observada** en varios módulos. Aviso: `Command` es `frozen` con `options: List[Option]` mutable.
9. **Instrucción práctica para código nuevo.** Cuando el retorno es un conjunto de valores con significado (`tuple[bool, int]`, `dict` con claves fijas), usa un `dataclass` como en `ExportState` o `HistoryRow` en lugar de una tupla posicional. **Propuesta** (no hay `NamedTuple`/`TypedDict` en el repositorio).

### 5.2 Imports

- **Observada** (repetida): dentro de una app, relativos (`from .constants import ...`; `from ..constants import ...` desde `code_gen/services/`); entre apps, absolutos completos (`from apps.project.specific.internal.code_gen.services.hashing import ...`). Las pruebas usan `..` (`from ..models import ...`) y `.` entre hermanos (`CLAUDE.md` §11). Cifras: `from .x` 145, `from ..x` 10, `from apps.*` 106 en producción.
- **Agrupación**: perfil por defecto de isort, sin isort instalado. Orden: stdlib; terceros **con Django mezclado alfabéticamente** (36 de 39 ficheros, sin línea en blanco entre ellos); `apps.*`; relativos. 86 % de los ficheros con ≥3 imports cumple el orden interno. **Observada**. Incumplen 28 ficheros (p. ej. `utils/cron.py`): no son modelo.
- **Multilínea**: estilo de rejilla alineada tras el paréntesis (57 casos) frente a un nombre por línea (14) y barra invertida (7). **Observada**; preferir paréntesis.
- **Diferidos**: 164 imports dentro de funciones en 55 ficheros. Motivos documentados: cortar ciclos (`certificates`/`code_gen`), no cargar librerías pesadas (`buyers/functions/generate_pdf_helper.py`), comandos de diagnóstico `check_*`. **Observada**.
- Un solo `import *`: `app_core/settings_test.py`. Ningún módulo define `__all__`. **Observada**: no los añadas.
- Los comentarios `# noqa: BLE001` (47) acompañan a `except Exception:`; también hay `F401`, `E402`, `S608` sueltos. **Observada**, sin linter detrás: úsalo para marcar una excepción ancha deliberada, con el motivo en el comentario de al lado.

### 5.3 Formato

- Indentación de 4 espacios; sin tabulaciones; sin CRLF. Líneas ≈79 (ver 1.3). **Observada**.
- **Comillas**: simples ≈74 % frente a ≈26 % dobles en producción y ≈99 % simples en pruebas; triples siempre `"""`. Los ficheros con dobles son los más antiguos (`utils/cron.py`, `utils/functions/chatgpt_api.py`, `video_masonry/*`, `app_core/urls.py`). **Observada**: comillas simples en lo nuevo; en un fichero antiguo, la de ese fichero.
- **Cadenas con formato**: f-strings (626 en producción) sobre `%` o `.format()`. Excepciones obligadas: mensajes de `logger.*` (perezosos) y todo texto con `_()` (`%` o `.format()` sobre la cadena ya traducida; ver `CLAUDE.md` §7). **Observada** y **Explícita**.
- Dos líneas en blanco antes de cada definición de nivel superior (27 incumplimientos, legado). Coma final en listas y diccionarios multilínea: sin norma impuesta (38 % de los cierres la llevan).
- Banners decorativos `# ====` solo en código heredado (`code_gen/services/certification.py`, `app_core/urls.py`). **Observada**: no los añadas.

### 5.4 Docstrings y comentarios

- **Observada**: docstring de módulo en el 47 % de los módulos de producción y 96 % de las pruebas; los largos explican el **porqué** (decisión, incidente, alternativa descartada), no el qué. Ejemplos: `ops/registry.py`, `utils/blocking.py`, `utils/throttling.py`, `code_gen/services/usb_bundle.py`.
- Se documentan más las funciones privadas (63 %) que las públicas (43 %), porque explican la decisión.
- Idioma: español. Estilo híbrido Google: secciones `Returns:` (65), `Args:` (24), `Parameters:` (22), `Raises:` (12); sin reST ni numpydoc. Dos variantes de argumentos conviven (`Parameters:` con tipo entre paréntesis en `utils/blocking.py`; `Args:` sin tipo en `code_gen/services/bitcoin_time.py`). **Pendiente**: sigue la del fichero. Si el docstring y la anotación dicen cosas distintas, la anotación manda y se corrige el docstring.
- **Cabecera `# ruta/del/fichero.py`** como primera línea: 101 de 189 módulos de producción y 62 de 68 de pruebas. Seis no se actualizaron al mover ficheros (`buyers/admin.py`, `buyers/models.py`, `buyers/views.py`, `account/forms/forgot_password_form.py`, `utils/management/commands/runserver.py`, `utils/management/transcribe.py`). **Observada** (en la mitad de los ficheros): en un fichero nuevo, ponla con la ruta exacta; si renombras uno que la tenga, corrígela.
- Comentarios: prosa larga en bloques sobre el código; `#:` para documentar atributos y constantes (385 líneas); casi sin comentarios al final de línea; sin convención de `TODO`/`FIXME` (hay uno explícito en `code_gen/access.py::can_generate_codes`). **Observada**.
- Loggers y constantes: ver 7.3 y 3.1. Sin `print` fuera de `management/` (1 caso).

---

## 6. Patrones Django y distribución de responsabilidades

### 6.1 Modelos

- **Orden de elementos** (35 modelos, muestra de 12 leída): `TextChoices` internas → campos → `objects` (si hay) → `@property` → métodos propios → `clean()` → `save()` → `__str__` → `class Meta` al final. `Meta` es el último elemento en 32 de 35. `__str__` antes o después de `save()` no tiene regla (14 antes, 7 después). **Observada**. Excepciones: `GeaDailyUniqueCode` y `MediaAsset` ponen `Meta` antes; `UserModel` pone `__str__` antes de `save`/`clean`.
- **`Meta`**: ningún modelo hereda `Meta` de `TimeStampedModel` (`class Meta(` 0 veces). Por eso su `ordering = ['default_order']` no se aplica a ningún modelo; solo 22 de 35 declaran un `ordering` propio. Para un modelo nuevo, declara `ordering` explícito. **Observada** (hallazgo; sin motivo documentado de si es intencional).
- `db_table` explícito (32 de 35) y `verbose_name` con `_()` (excepciones: `IPBlockedModel`, `WhiteListedIPModel` y los tres de `video_masonry`). **Observada**.
- **PK**: UUID (`models.UUIDField('ID', default=uuid.uuid4, primary_key=True, editable=False)`) en las entidades de negocio (13 modelos); `BigAutoField` en el resto (22), vía `DEFAULT_AUTO_FIELD`. La URL usa `<uuid:pk>` para los primeros e `<int:...>` para los segundos. **Observada**: la regla es por modelo, no por app.
- **Restricciones**: lo nuevo usa `UniqueConstraint` y `CheckConstraint(condition=..., name=...)` (12 `CheckConstraint`, 10 `UniqueConstraint`); `unique_together` solo en apps antiguas (7). Los `UniqueConstraint` van sin `condition` porque MariaDB no crea los condicionales (motivo escrito en `ServiceOrderRecipient`). `indexes` con `name=` solo donde importa (`ipblocked_lookup_idx`). **Observada**.
- **Estado derivado**: `OfferModel.status_code` es una `@property` que se calcula desde los sellos `*_at`, de más avanzado a más básico; no existe campo `status` en la orden. **Explícita** (invariante 1). `IPBlockedModel.is_currently_blocked` también se calcula al leer (invariante 25). Otros estados sí se almacenan (`LegalDocumentVersionModel.status`).
- **Flujo `mark_*`**: 10 métodos `@transaction.atomic` en `OfferModel` con este esqueleto: comprobar etapa previa → `ValidationError(_('...'))` → asignar `*_by` → fijar `*_at` solo si no existía → `save(update_fields=[...])`. Las etapas de revisión y aprobación no tienen `mark_*`: las resuelve `_apply_step` en `buyers/views.py`. La cascada «sin aprobar, se limpia lo posterior» y la creación de la orden de servicio están en `OfferModel.save`. **Explícita** (invariantes 1-3, 6) y **Observada**.
- **`clean()`/`save()`**: `save()` sobrescrito en 21 modelos; `clean()` en 9; solo 3 llaman `self.full_clean()` dentro de `save()` (`OfferModel`, `UserVerificationModel`, `CertificateViewLogModel`). El resto de `save()` normalizan o derivan. **Observada**: no llamar `full_clean()` en `save()` salvo para proteger un invariante.
- **Managers**: uno solo, `GeaDailyUniqueCodeManager`; sin `QuerySet` propios. **Observada**.
- **Bilingüe**: campos duplicados (ver 3.2); lectura localizada con métodos `body_for(language)` o con `get_language()`. Sin `parler`. **Observada**.
- **Borrado lógico**: `is_active = False` con `save(update_fields=['is_active'])`; `OfferModel.display = False` es otro interruptor. `.delete()` real solo para regenerar placements o miembros (`code_gen/api.py`) y destinatarios (`buyers/views.py`). **Explícita** (`CLAUDE.md` §5) y **Observada**.
- **Auditoría**: `auditlog.register(Modelo, serialize_data=True)` al pie de `models.py` en 7 apps (22 registros); no están registrados `pqrs`, `code_gen`, `ops` ni `video_masonry`. **Observada**; si un modelo nuevo debe registrarse: **Pendiente** (decisión de negocio).
- **Signals**: se conectan con `pre_save.connect(...)` al pie de `models.py`; llamadas síncronas a OpenAI dentro de `pre_save` (timeout 20 s). **Observada**, con coste conocido (`CLAUDE.md` §7).

### 6.2 Dónde vive cada responsabilidad

| Capa | Qué contiene | Ejemplos | Etiqueta |
|---|---|---|---|
| Modelo | Reglas de la entidad: flujo de la orden, aprobación de un texto legal, contadores atómicos | `OfferModel.mark_*`, `LegalDocumentVersionModel.approve`, `CodeSequenceModel.next_value` | **Explícita** |
| Servicio (`code_gen/services/`) | Procedimientos de certificación y anclaje, `@transaction.atomic` donde escribe | `certification.certify_document`, `summary.certify_summary` | **Explícita** |
| Módulo de acceso (`access.py`) | Predicados y recortes de queryset | `buyers/access.py::can_modify_offer`, `code_gen/access.py::visible_registrations` | **Explícita** |
| Vista | Orquesta; con lógica sustantiva en `OfferApprovalWizardActionView.post`, `ProfitabilityTemplateView` | — | **Observada** (no es un modelo a seguir; la regla es lo contrario) |
| Signal | Imagen (borrado, optimización) y traducción es↔en | `assets/signals.py`, `buyers/signals.py` | **Observada** (2 apps) |
| Helper de dominio suelto | `core/legal.py`, `certificates/verification.py`, `account/otp_login.py`, `code_gen/history.py` | — | **Observada** |
| Comando o cron | Efectos externos fuera de la petición | `upgrade_ots_anchors`, `notify_legal_changes` | **Explícita** |

Dato a tener presente: `GeaDailyUniqueCode.send_today` compone y envía el correo dentro del modelo, y el predicado «personal interno» (`is_authenticated and is_active and (is_staff or is_superuser)`) está duplicado en `buyers/access.py::is_internal`, `certificates/files.py::is_internal`, `code_gen/access.py::is_operator`, `code_gen/api.py::_is_internal` y `app_core/admin.py::_is_internal_staff`. **Observada**; centralizarlo es una **Propuesta**.

### 6.3 Vistas, URLs y formularios

- **Control de acceso** (**Explícita**, `CLAUDE.md` §5): mixins, nunca `@login_required`/`@permission_required` (0 en el repo). Orden de bases: `RolMixin, [OfferMutationMixin | PermissionRequiredMixin], VistaDjango`. Los mixins de rol dejan pasar siempre a `is_superuser` e `is_staff`.
  - Excepción **Observada**: las FBV de `code_gen/api.py` y `certificates/external.py` usan `@require_http_methods`, `@csrf_exempt`, `@require_POST`, y comprueban el acceso al empezar la función (`_is_internal`, `_forbidden`); `video_masonry/views.py` usa `@method_decorator(require_POST, name="dispatch")`.
- **AJAX**: `JsonResponse` con datos (49 sitios, 8 ficheros). **Solo** `OfferApprovalWizardActionView.post` devuelve HTML pre-renderizado con `render_to_string` dentro de JSON (`{"ok": True, "html": ...}`). Los sobres JSON no están unificados (`success`, `ok`, `detail`, `error`, `errors`). **Observada**; sobre único: **Pendiente**.
- **URLs**: todas las apps cuelgan de la raíz (`path("", include(...))`) vía `include_if_present`; el prefijo está en cada ruta y es por rol (`buyer/`, `holder/`, `verify/`, `generate/`). Nombres `snake_case`; rutas en minúsculas con `/` final; convertidores `uuid` (27), `int` (5), `str`, `slug`; kwarg `pk` en 24 de 29 (`id` solo en `buyers`, absorbido por `offer_url_kwarg`). Comillas simples o dobles según el fichero. **Observada**.
- **Formularios**: `Meta.fields` siempre lista explícita (12 de 12; 0 `exclude`, 0 `__all__`); `widgets` en 9. Atributos por `widget.attrs.update(...)` en `__init__` o por los filtros `|add_class`/`|add_attrs`; ambos coexisten. Mensajes con `_()`. Selectores con `django_select2` (`ModelSelect2Widget`). El patrón `user = kwargs.pop('user', None)` en `__init__` + `get_form_kwargs` de la vista está en `assets_location`. **Observada**.

### 6.4 Plantillas

- Jerarquía: `templates/raw.html` → `templates/dashboard/dashboard_layout_base.html` → página, **solo para el panel** (24 plantillas). Las públicas y de cuenta usan `raw.html` directamente o un layout propio (`account/layout/account.html`, `two_factor/_base.html`). **Observada**.
- Comentarios: 301 bloques `{% comment %}` y 0 `{#`; `{% comment %}` no puede ir antes de `{% extends %}` ni anidarse. **Explícita** (`utils/tests/test_scripts.py`).
- Plantillas globales en `templates/`; únicas en la app: 4 de `core` (`apps/common/core/templates/core/`). **Observada** (la regla de `CLAUDE.md` dice solo `core/index.html`).
- Parciales: prefijo `_` = fragmento de una página concreta o repetido; sin `_` = pieza estructural por directorio (`partials/nav/*`, `modals/*`). 140 `{% include %}`, 104 con `with`. **Observada**.
- Bloques `{% blocktrans count %}` siempre con `|default:0` (4 de 4 usos). **Explícita** (`CLAUDE.md` §7).
- Recursos externos con `integrity` y versión exacta; excepciones declaradas con motivo en `utils/tests/test_sri.py` (`kit.fontawesome.com`, `cdn.jotfor.ms`). **Explícita** (invariante 27).

### 6.5 i18n

- `from django.utils.translation import gettext_lazy as _` en 73 módulos; `gettext as _` en 5 (ejecución inmediata, p. ej. `core/legal_pdf.py`). Ningún otro alias. **Observada**.
- msgid en inglés (1792 llamadas en Python, 1178 `{% trans %}` y 82 `{% blocktrans %}` en plantillas); solo existe el catálogo `es` (14 `.po`: 13 apps, `app_core/locale` y `templates/locale`). `LANGUAGE_CODE = 'en'`. **Observada**.
- Al cambiar textos: `makemessages -l es` y `compilemessages`, o Rosetta. Contar las tres cifras de `polib`: traducidas, sin traducir y `fuzzy`. Estado actual: 0 sin traducir, 0 `fuzzy`, 221 obsoletas. **Explícita**.

### 6.6 Admin e import-export

- Atributos habituales: `list_display` y `search_fields` (33 de 34), `list_filter` (29), `readonly_fields` (28), `ordering` (24), `fieldsets` (19). Solo lectura / auditoría: `has_add/change/delete_permission` devolviendo `False` (`CommandRunModelAdmin`, `LegalAcceptanceAdmin`, `CertificateViewLogModelAdmin`). **Observada**.
- Import-export: `IMPORT_EXPORT_FORMATS` en settings; tres `ModelResource` explícitos en `assets/admin/__init__.py` (`AssetCategoryResource`, `AssetsNamesResource`, `AssetResource`); el resto usa el recurso autogenerado de `ImportExportActionModelAdmin`. **Observada**.
- El sitio exige personal activo con segundo factor verificado y responde 404 al resto (`app_core/admin.py::GeaAdminSite`). Las páginas del panel de operaciones cuelgan de `ModelAdmin.get_urls()` envueltas en `admin_site.admin_view` y con la declaración **antes** de la ruta dinámica (`ops/admin.py`). **Explícita** (invariante 7).

### 6.7 Transacciones, ajustes y entorno

- `DATABASES['default']['ATOMIC_REQUESTS'] = True`. Efectos externos: por cron, o degradados a aviso sin propagar el fallo (`code_gen/api.py::_send_to_blockchain`); la comprobación de estado va **antes** del efecto, no al guardar después (invariante 18). `select_for_update` solo en 2 sitios (`GeaDailyUniqueCodeManager`, `CodeSequenceModel.next_value`); 0 `transaction.on_commit`. **Explícita** y **Observada**.
- `app_core/settings.py` es un solo fichero. El orden: `load_dotenv()` → `check_environment()` (de `app_core/env.py`) → logging → grupos de apps → i18n → middleware → BD (`engine_for()` de `app_core/db`) → auth/axes → caché → certificación → media → correo → cron → negocio. **Observada**.
- Variables obligatorias: `os.getenv('X')` sin defecto (envuelto en `int()` o `.split(',')`), declaradas en `app_core/env.py` (`REQUIRED`, `REQUIRED_IN_PRODUCTION`, `ALLOWED_EMPTY`, `OPTIONAL_WITHOUT_DEFAULT` **con motivo**); opcionales: `os.getenv('X', defecto)`. `app_core/tests/test_env.py` recorre `settings.py` y falla ante una lectura sin declarar. **Explícita**.
- Lectura de ajustes en el código: `settings.X` directo 130 veces, `getattr(settings, 'X', d)` 59 veces, esta última para ajustes que pueden no existir. **Observada**.
- `DEBUG` sale de `DJANGO_DEBUG == 'True'`; lo peligroso no se separa por entorno: se saca de la lista (`ops/registry.py`). **Explícita**.

---

## 7. Pruebas, errores, logging e integraciones

### 7.1 Pruebas

- **Diseño** (**Explícita**, `CLAUDE.md` §11): paquete `tests/` por app con `__init__.py` y ficheros `test_*.py`; el descubrimiento de `unittest` los encuentra sin configurar. Ejecución: `uv run python manage.py test --settings=app_core.settings_test` (SQLite en memoria). Informe y cobertura: `uv run python manage.py test_report` (`coverage` es opcional). Cifras actuales: 293 clases y 1157 métodos `test*` en 64 ficheros `test_*.py`.
- **Cabecera de cada fichero** (**Observada**, 59-62 de 64): primera línea `# ruta/fichero.py`, docstring de módulo y, dentro, el comando `manage.py test <ruta con puntos> --settings=app_core.settings_test`.
- **Herramientas**: `django.test.TestCase` (153 clases), `SimpleTestCase` (63); sin `TransactionTestCase`, sin factory_boy ni model_bakery, sin `loaddata` ni fixtures JSON. Uso: `self.client` (374), `mock.patch` y variantes (≈187), `override_settings` (80), `subTest` (66), `call_command` (43), `RequestFactory` (25). **Observada**.
- **Fixtures** por mixin o clase base propios con `setUpTestData`/`setUp` (predomina `setUp`: 87 frente a 11): `OfferFixtureMixin` y `WorkflowMixin(OfferFixtureMixin)` (`buyers/tests/test_buyers.py`, `test_workflow.py`), `PQRSFixtureMixin`, `LocationFixtureMixin`, `GalleryFixtureMixin`, `LegalBase`, `LoginOTPMixin`. Helpers con nombre de acción: `make_offer`, `walk_to`, `approve`. **Observada**.
- **Docstrings que narran el fallo**: el de clase cuenta síntoma, causa y por qué ninguna otra prueba lo detectaba (`StaleContextTestCase` en `code_gen/tests/test_history_tree.py`; `test_backup.py` «reproduce el fallo para avisar el día que la biblioteca deje de comportarse así»). Una prueba que arregla un incidente reproduce primero el fallo. **Observada**.
- **Pruebas centinela** sobre el propio repositorio: `utils/tests/test_sri.py`, `test_scripts.py`, `test_media_exposure.py`, `app_core/tests/test_env.py` (recorren plantillas o `settings.py` y fallan si aparece algo sin decidir). **Observada**; el cajón de comandos de `ops` sigue la misma idea (ningún comando sin decidir).
- **Saltar con motivo**: `posix_only_because(reason)`, `posix_only` y `posix_rename_only` en `utils/testing.py`; el marcador lleva su motivo escrito. `login_with_otp(client, user)` para entrar al admin (que exige 2FA verificado). **Explícita** (`CLAUDE.md` §11).
- Invariantes del flujo de órdenes: se prueban saltándose `save()` y `clean()` con `QuerySet.update()` para que actúen las `CheckConstraint`. **Observada** (`buyers/tests/test_workflow.py`).
- Comprobar una URL en HTML: con comillas del atributo, `assertNotIn('href="%s"' % reverse(...), html)`, nunca `assertIn(reverse(...))` a pelo (prefijos de ruta). **Explícita** (`CLAUDE.md` §7).
- `os.environ` dentro de una prueba: se devuelve como estaba (el corredor `utils/test_runner.py` lee su destino al construirse). **Explícita**.
- Nombres de método en inglés (≈89 %); español local (ver 3.1). Un código TOTP generado en una prueba se rellena con ceros, `f'{value:06d}'` (`CLAUDE.md` §7). **Observada**.
- `settings_test.py` hace `from app_core.settings import *`, por lo que `check_environment()` sigue exigiendo un `.env` completo para correr la suite. **Observada**.

### 7.2 Errores y degradación

- Excepciones propias: una por módulo de servicio, raíz propia (hereda de `Exception` o `ValueError`), capturada en el borde (vista, API o comando) y convertida en mensaje. **Observada**. Docstring de una línea. Solo 6 `raise ... from ...` en todo el árbol: **Observada**, no una regla; para código nuevo encadenar la causa es una **Propuesta**.
- `except Exception` (133) es deliberado cuando un efecto externo no debe hundir la escritura; va con motivo escrito y, 47 veces, con `# noqa: BLE001`. 0 `except:` desnudos. **Observada**.
- Degradación documentada: sin `CHAT_GPT_API_KEY` el traductor devuelve el texto original; con la API caída devuelve `""` (matiz no documentado en `CLAUDE.md`). Sin Redis, `RateLimit` falla cerrado. `scanning.py` falla abierto (decide un bloqueo, no un permiso). El anclaje degrada a aviso y se reintenta (`anchoring.anchors_without_block_time`). **Explícita** (invariantes 21, 24, 32).
- Correo: `fail_silently=False` por defecto, decisión escrita en `account/emails.py` y `utils/otp_email.py`; `pqrs/views.py` lo pone a `True` solo en el acuse secundario. **Observada**.
- Una IP bloqueada recibe un 404 idéntico al de una ruta inexistente (`block_suspicious_request._not_found`). **Explícita** (invariante 20).
- Handlers 400-504 en `utils/views.py`, exportados en `app_core/urls.py`; `settings.ERROR_TEMPLATE` no existe y se lee con `try/except` hacia `'errors_template.html'`. **Observada**.

### 7.3 Logging

- **Observada**: `logger = logging.getLogger(__name__)` en 49 módulos (siempre `logger`, nunca `log` ni `LOGGER`). Niveles de uso: `warning` 39, `exception` 35, `error` 23, `info` 17, `debug` 3.
- Estilo de mensaje: perezoso `%s` en el código reciente (62 llamadas), f-string en el antiguo (18; `buyers/*`, `utils/views.py`). **Observada**; lo nuevo, perezoso.
- Mensajes de log en inglés en el código nuevo; los de `cron.py` llevan etiqueta en mayúsculas (`WARMUP ...`). **Observada**.
- Config: formateador `gea`, un `WatchedFileHandler` (necesario para que `rotate_logs` funcione en POSIX), logger `apps` en INFO. **Explícita**.

### 7.4 Integraciones, cron y límites

- **Cron** (`CRONJOBS`, 5 entradas): `upgrade_ots_anchors` (cada 15 min), `generate_and_send_gea_code` (19:00), `warm_gea_app` (cada 3 min), `rotate_logs` (cada hora), `notify_legal_changes` (cada 30 min). Las que ejecutan un comando usan `_call_command`. La función de cron comprueba el esquema de la URL antes de abrirla (`utils/outbound.py::is_http_url`). **Observada**.
- **Comandos de gestión**: `help = (...)` largo, docstring de módulo con el porqué y lo que **no** hace, `handle(self, *args, **options)`; `add_arguments` en 16 de 25; `CommandError` en 3; salida con `self.stdout.write(self.style.SUCCESS(...))`. **Observada**.
- **Consola de operaciones** (`ops`): la lista blanca es de programas, `fixed_args` es donde vive la seguridad, todo texto lleva `pattern`, nada marcado `DANGEROUS` puede ser `DEBUG_ONLY`, ejecución en subproceso. **Explícita** (`CLAUDE.md` §4-bis.F).
- **OpenAI**: `ChatGPTAPI` en `utils/functions/chatgpt_api.py`, modelo por defecto `gpt-4o-mini`, `timeout` 20 s, instanciada a nivel de módulo en `assets/signals.py` y `buyers/signals.py`. **Observada**.
- **TSA, OpenTimestamps y Bitcoin**: `code_gen/services/tsa.py`, `ots.py`, `bitcoin_time.py`; la hora de un bloque solo se resuelve desde el cron y exige dos exploradores que coincidan. **Explícita** (invariante 32).
- **Correo**: `EmailMultiAlternatives` (texto + HTML) para OTP, avisos legales y órdenes con PDF adjunto; `send_mail` plano en `pqrs` y `account`. **Observada**.
- **Límites de intentos**: `RateLimit(name, *, limit, window, [fail_open, reason])`; el cupo de un destinatario va por `scope`, nunca con la IP en la clave (14 instancias). **Explícita** (invariante 21).
- **Salida a la red**: toda URL que venga de configuración se valida con `utils/outbound.py::require_http_url` antes de `urlopen`. **Observada**.

---

## 8. Ejemplos representativos y guía para añadir una funcionalidad

### 8.1 Ejemplos reales (con sus nombres reales)

| Quiero ver... | Mira... |
|---|---|
| Modelo con flujo derivado, `mark_*`, `CheckConstraint` y `Meta` al final | `OfferModel` en `buyers/models.py` |
| Modelo pequeño y reciente con `UniqueConstraint`, `db_table` en `snake_case`, `related_name` en plural | `LegalDocumentVersionModel` en `core/models.py`; `CommandRunModel` en `ops/models.py` |
| Enumeración a nivel de módulo y anidada | `DocumentTypeChoices` en `certificates/models.py`; `IPBlockedModel.ReasonsChoices` en `utils/models.py` |
| Admin sobre `GeneralAdminModel` con acciones y columnas calculadas | `UserVerificationModelAdmin` en `certificates/admin.py` |
| CBV con mixin de rol y mixin de objeto | `OfferUpdateView` en `buyers/views.py` con `OfferMutationMixin` de `buyers/access.py` |
| Vistas con recorte por queryset y 404 | `CodeDetailView` en `code_gen/views.py` con `visible_registrations` de `code_gen/access.py` |
| Módulo de servicio con docstring del porqué, excepción propia y anotaciones | `code_gen/services/master.py`, `code_gen/services/codes.py` |
| Función anotada de un solo propósito | `block_duration` en `utils/blocking.py` |
| Contador de intentos que falla cerrado | `RateLimit` en `utils/throttling.py` |
| Comando de diagnóstico | `utils/management/commands/check_realtime.py` |
| Registro de comandos en lista blanca | `ops/registry.py` |
| Prueba con historia del fallo | `StaleContextTestCase` en `code_gen/tests/test_history_tree.py` |
| Entorno obligatorio y declarado | `app_core/env.py` y `app_core/tests/test_env.py` |

### 8.2 Guía paso a paso para una funcionalidad nueva

Flujo mínimo, siguiendo solo reglas con soporte:

1. **Decide la app.** Si no existe una adecuada, crea una con `manage.py start_app` y añádela a mano al grupo de `settings.py` (4.3).
2. **Modelo** en `<app>/models.py`: hereda `TimeStampedModel`, nombre `<Nombre>Model`, enumeraciones `TextChoices` con sufijo `Choices`, `db_table` explícito, `ordering` propio, `Meta` al final; PK UUID si es entidad de negocio. Regla de negocio en el propio modelo.
3. **Migración**: `uv run python manage.py makemigrations`. Un cambio en el flujo de órdenes exige tocar las tres capas y la migración.
4. **Acceso**: mixin de rol existente o función en `access.py`; en zona sensible, recorta el queryset y responde 404.
5. **Vistas**: CBV `Recurso + Acción + View`; efectos externos fuera de la petición o degradados.
6. **URL**: en `<app>/urls.py`, nombre `snake_case`, convertidor según el tipo de PK, sin términos de `COMMON_ATTACK_TERMS`.
7. **Plantilla** en `templates/dashboard/pages/<rol>/`, con `{% comment %}`, textos con `{% trans %}`, sin recargar scripts que ya trae `raw.html`.
8. **Admin**: `@admin.register(Modelo)`, hereda `GeneralAdminModel`, `list_display`, `search_fields`, `readonly_fields`.
9. **Textos**: `_()` en inglés, `makemessages -l es`, completa el `.po` y `compilemessages`; sin `fuzzy`.
10. **Pruebas** en `<app>/tests/test_<tema>.py`, mixin de fixtures, docstring del propósito, comando de ejecución en la cabecera.
11. **Dependencia nueva**: `uv add` **y** `uv export --no-dev --format=requirements-txt > requirements.txt` (`CLAUDE.md` §3); comprueba con `check_requirements`.
12. **Documentación**: si cambia una ruta, un flujo o una invariante, actualiza `CLAUDE.md`/`docs/` y esta guía (sección 10).

### 8.3 Ilustrativo — no existe en el repositorio

Un recurso hipotético `Inspection` ilustra los nombres exigidos. Los nombres de la app y los campos son inventados; solo se aplican reglas de las secciones 2 y 3.

```python
# Ilustrativo — no existe en el repositorio
import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel


class InspectionModel(TimeStampedModel):
    class StatusChoices(models.TextChoices):
        OPEN = 'OPEN', _('Open')
        CLOSED = 'CLOSED', _('Closed')

    id = models.UUIDField('ID', default=uuid.uuid4, primary_key=True, editable=False)
    status = models.CharField(_('status'), max_length=10, choices=StatusChoices.choices,
                              default=StatusChoices.OPEN)

    def __str__(self) -> str:
        return f'{self.id} ({self.status})'

    class Meta:
        db_table = 'apps_<app>_inspection'
        ordering = ['default_order', '-created']
        verbose_name = _('inspection')
        verbose_name_plural = _('inspections')
```

```python
# Ilustrativo — no existe en el repositorio
# Admin: <ClaseDelModelo>Admin, base GeneralAdminModel
@admin.register(InspectionModel)
class InspectionModelAdmin(GeneralAdminModel):
    list_display = ('id', 'status', 'created')
    search_fields = ('id',)

# Vistas: Recurso + Acción + View, sufijo igual que la base de Django
class InspectionCreateView(BuyerRequiredMixin, CreateView): ...
class InspectionListView(BuyerRequiredMixin, ListView): ...

# Cron: preferencia explícita del usuario <verbo>_..._cron() -> None
def close_stale_inspections_cron() -> None:
    """Cierra las inspecciones abiertas hace demasiado."""
```

Para el cron: el nombre sigue la preferencia del usuario (sin implementación localizada); el alta en `CRONJOBS` se hace por ruta de cadena, como las dos existentes.

---

## 9. Excepciones, contradicciones y decisiones pendientes

### 9.1 Decisiones pendientes (no son reglas)

| Tema | Variantes encontradas | Estado |
|---|---|---|
| Anotar `request`, `user`, `queryset` | Casi nadie lo hace (`HttpRequest` 3 veces) | Pendiente |
| `Optional[X]` frente a `X \| None` | 39 frente a 4, a veces mezclados | Pendiente |
| Nombre de una **nueva base** de admin | Solo `GeneralAdminModel` | Pendiente |
| Sufijo de excepciones propias | `Error` en 6 de 11 | Pendiente |
| Orden `verbo_recurso` / `recurso_verbo` en nombres de ruta | Ambos | Pendiente |
| Sufijo `ModelForm` | Solo en `assets_location` | Pendiente |
| `functions/` frente a `functions.py` | Ambos | Pendiente |
| Estilo de `related_name` y de campos bilingües | Dos estilos por antigüedad y por app | Pendiente |
| Importar el modelo de usuario | `AUTH_USER_MODEL`, `get_user_model()`, import directo | Pendiente |
| Dónde declarar una `TextChoices` nueva | Módulo o anidada según app | Pendiente |
| Sobre JSON único (`ok`, `success`, `detail`, `error`) | 7 formas | Pendiente |
| Centralizar el predicado «personal interno» (5 copias) | — | Propuesta |
| Registrar en `auditlog` modelos de `pqrs`, `code_gen`, `ops`, `video_masonry` | Decisión de negocio | Pendiente |

### 9.2 Contradicciones con `CLAUDE.md` (describen el repositorio, no autorizan a cambiarlo)

1. §5 «Todo son CBVs»: hay 15 FBV enrutadas (7 de `code_gen/api.py`, 3 de `certificates/external.py`, 3 de `certificates/views.py`, `set_language`, `robots_txt`), y las dos primeras usan decoradores de Django.
2. §5 «Las acciones AJAX devuelven `JsonResponse` con HTML pre-renderizado»: solo `OfferApprovalWizardActionView.post`; el resto devuelve datos.
3. §5 `db_table` explícito en todos los modelos: faltan los tres de `video_masonry`; además hay variantes de patrón.
4. §5 excepciones históricas al sufijo `Model`: faltan `GeaDailyUniqueCode` y `PQRSRequest`.
5. §5 `TimeStampedModel` «aporta `ordering = ['default_order']`»: ningún modelo hereda su `Meta`.
6. §5 y §4-bis.D citan `utils/tests_scripts.py` y `tests_login_paths.py`: hoy son `utils/tests/test_scripts.py` y `account/tests/test_login_paths.py`.
7. §5 plantillas globales «salvo `core/index.html`»: hay 4 plantillas de `core` dentro de la app.
8. §5 lista 9 filtros y tags propios: hay 12 (`is_any_active`, `link_collapsed_class`, `messages_as_data` faltan).
9. §11 «778 pruebas» y «`tests.py` de apps sin lógica»: hay 1157 métodos en 293 clases y ningún `tests.py`.
10. §2 y §4-bis.G directorios `api/` vacíos: no existe ninguno; §4-bis.G cita `video_masonry/signals.py`, que no existe (y §7 dice que no debe volver a haberlo).
11. §4-bis.B «cada lado importa al otro dentro de la función, nunca en la cabecera»: `certificates` importa `code_gen.services` en cabecera y `code_gen/forms.py` importa dentro de `class Meta:`.
12. §4-bis.D.1 el código diario de comprador «emitido por cron a las 19:00»: el cron solo emite el `GENERAL`; el de comprador sale del comando manual `generate_gea_code`. §4-bis.G tampoco menciona `notify_legal_changes` entre los crons.
13. §6 invariantes 7 y 20 (404 y no 403): `OfferDetailView` lanza `PermissionDenied`, `InternalToolAccessMixin` y `HistoryAccessMixin` dan 403 a un autenticado, `code_gen/api.py` da 403 JSON incluso a anónimos, y los mixins de rol redirigen (302) a `core:index`. No hay política global.
14. `utils/client_ip.py::get_client_ip` se presenta como respuesta única; sobreviven tres implementaciones con `X-Forwarded-For` (`certificates/functions.py::get_client_ip`, `core/legal.py::client_ip`, `ops/admin.py::_client_ip`).
15. §2 dice que `django-parler` ya no está: `PARLER_LANGUAGES` sigue en `settings.py`.
16. §7 `ChatGPTAPI` «devuelve el texto original»: solo sin clave o en `DEBUG`; ante un fallo real de la API devuelve cadena vacía.
17. `docs/ROUTES_MAP.md` omite `pqrs` y 25 de 74 nombres de URL, y dice TTL de OTP de 10 minutos (el código usa 15).
18. Un docstring de `assets/views.py` aún dice «caja AEGIS» frente a la convención «resumen».
19. `app_core/settings_test.py` conserva un comentario obsoleto sobre `ChatGPTAPI` y una línea `ATOMIC_REQUESTS = False` sin efecto.

### 9.3 Riesgos detectados — no reproducir

No son convenciones. Se listan para que no se copien.

- `OfferApprovalWizardActionView` llama a `_require_perm` fuera del `try` en tres pasos y `_require_perm` lanza `PermissionError` de Python (no `PermissionDenied`): lectura estática indica un 500 para quien no tenga el permiso (`buyers/views.py`; no ejecutado).
- `certificates/functions.py` hace `logging = logging.getLogger(__name__)`, que sombrea el módulo.
- `code_gen/constants.py` (`BARCODE_FORBIDDEN_CHARS`) contiene una secuencia de escape inválida `'\|'` (aviso de sintaxis desde Python 3.12).
- `assets/views.py` (`WhatsAppRedirectView`) construye un mensaje con `_()` dentro de una f-string; `makemessages` no la extrae. Además hay 7 `_(f"...")` con msgid dinámico (`utils/admin.py`, `certificates/admin.py`, `assets/signals.py`, `buyers/signals.py`).
- `apps/common/core/templates/core/index.html` carga `bootstrap-icons` sin versión ni `integrity`; `utils/tests/test_sri.py` solo recorre `templates/`, no `apps/**/templates`.
- `utils/client_ip.py::get_client_ip` **no** se fía de `X-Forwarded-For` salvo con `TRUSTED_PROXY_DEPTH`; las otras tres implementaciones citadas en 9.2 (punto 14) sí la leen tal cual. Para una IP nueva, usa la de `utils/client_ip.py`.
- `AssetLocationModelForm.clean` usa `self.initial.get('user')` tras sacar `user` de `kwargs`: la comprobación de duplicados parece inerte (no ejecutado).
- Ajustes leídos con `getattr(settings, ...)` y nunca definidos en `settings.py`: `OPENTIMESTAMPS_CALENDARS`, `TRUSTED_PROXY_DEPTH`, `GEA_WARMUP_URL` (el cron lo lee del entorno; `check_health` obtiene siempre `''`).
- `buyers/views.py` importa `gettext` y `gettext_lazy` como `_` seguidos: el segundo sombrea al primero.
- `AssetLocationDeleteView.form_valid(self, request, ...)` recibe el formulario en el parámetro `request`; funciona porque no lo usa.
- Ajustes huérfanos: `MIDDLEWARE_NOT_INCLUDE`, `ADMIN_DELETE_PERMISSION`, `ADMIN_ADD_PERMISSION`, `PARLER_LANGUAGES`.
- `PQRSLandingView` apunta a `pqrs/landing.html`, que no existe, y no está enrutada; ocho plantillas sin referencia alguna.
- Los modelos de `video_masonry` no usan `_()` ni `verbose_name`, `db_table` ausente; `video_masonry/views.py` devuelve un literal en español sin `_()`.
- `utils/views.py` lleva en `error_image` la URL absoluta de producción (7 apariciones).
- Import y exportación de modelos con PII sin sobrescribir permisos (`has_import_permission`, `has_export_permission`): sin verificar a fondo; derivar a la revisión de seguridad.

---

## 10. Checklist breve de revisión y mantenimiento del documento

### 10.1 Antes de entregar un cambio

- [ ] Nombres: modelo con `Model`, enumeración con `Choices`, admin `<Modelo>Admin` sobre `GeneralAdminModel`, vista `Recurso + Acción + View`, cron `<verbo>_..._cron() -> None`.
- [ ] Funciones nuevas con parámetros y retorno anotados; sin renombrar ni reanotar código ajeno al cambio.
- [ ] Textos visibles con `_()` en inglés; ningún `_()` dentro de una f-string; `.po` actualizado sin `fuzzy`.
- [ ] Plantillas: `{% comment %}`, sin scripts repetidos, recursos externos con versión e `integrity`.
- [ ] Migraciones generadas; `db_table` y `ordering` explícitos en modelos nuevos.
- [ ] Acceso por mixin o `access.py`; 404 donde la respuesta revelaría existencia.
- [ ] Efectos externos fuera de la transacción o degradados; contadores por `RateLimit`.
- [ ] Prueba nueva en `tests/`, ejecutable con `--settings=app_core.settings_test`, con docstring del fallo que previene.
- [ ] Ajustes nuevos en `settings.py` (nombre de módulo) y en `app_core/env.py` si son obligatorios; `requirements.txt` reexportado si hay dependencia.
- [ ] Ningún secreto, correo real, teléfono ni usuario de allowlist en código, pruebas o documentos.

### 10.2 Cómo actualizar este documento

1. **Convención acordada**: añade la regla en la sección 3 (si nombra) o en la 5-7 (si estructura), con alcance, ejemplo real, fuente (ruta y símbolo) y etiqueta **Explícita**, e indica si hay implementación localizada. Quítala de 9.1 si estaba pendiente y copia el cambio a `CLAUDE.md` si es normativo del proyecto.
2. **Excepción local**: regístrala en la tabla de su categoría (columna «Excepciones») con ruta y símbolo, y la razón si está escrita en el código; si no hay razón, escribe «sin motivo documentado». No conviertas la excepción en regla.
3. **Hallazgo o defecto**: va a 9.3, nunca a las reglas. Cuando se corrija, bórralo.
4. **Contradicción con `CLAUDE.md`**: añádela a 9.2 con la afirmación citada y lo que muestra el código; no corrijas `CLAUDE.md` sin que el usuario lo pida.
5. **Cifras**: se recalculan con `ast` sobre `apps/` y `app_core/` (sin `migrations/`, `locale/`, `public/`, `.venv/`). Cada cifra del documento (36 % de retornos, 64 ficheros de prueba, 33 admins...) es de la fecha de la revisión; no las uses como umbral.
6. **Verificación de citas**: tras editar, comprueba que cada ruta y símbolo citado existe (`os.path.exists` sobre las rutas con alias resueltos y `grep` de los símbolos).
7. **Propuestas** (`X | None`, centralizar el predicado de personal interno, dataclasses en lugar de tuplas) siguen siendo propuestas hasta que el usuario las acepte; entonces pasan a **Explícita**.
