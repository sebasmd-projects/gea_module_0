# summary.md — Contexto de arranque para una nueva sesión

Este archivo es el **punto de entrada**. Léelo primero, entero. Después lee
`CLAUDE.md` (ficha técnica del repo, invariantes, mapa de arquitectura) y los
documentos que enlaza (`docs/ROUTES_MAP.md`, `docs/FEATURES_MAP.md`,
`docs/NORMATIVA.md`, `docs/ANCLAJE.md`, `docs/SEGURIDAD.md`, `docs/DJANGO_5_2.md`).
Este archivo no se referencia desde `CLAUDE.md` a propósito: es de arranque de
sesión, no documentación del proyecto.

Repositorio: `sebasmd-projects/gea_module_0`. Generado: 2026-09-15.

---

## 1. Ramas y dónde está cada cosa

| Rama | Último commit | Estado |
|---|---|---|
| `master` | `42dbf03` (2026-09-15) | Base estable. Incluye login unificado, PQRS, legales, USB, anclaje, modo titular del histórico de códigos, comando `check_realtime` (Fase 0 del centro de notificaciones). |
| `feat/notificaciones` | `9db450f` (2026-09-15) | **Rama actual de trabajo** (`checkout` en esta sesión). Contiene todo `master` fusionado + la Fase 0 del plan de notificaciones (medición de si cPanel aguanta tiempo real contra el Redis del VPS). Working tree limpio, sin commits por subir. |
| `feat/jotform-a-local` | — | Existe, no explorada en esta sesión. Relacionada con el Bloque B del plan (sacar el formulario de JotForm). |
| `feat/solicitud-formulario-de-certificacion-documental` | — | Existe, no explorada en esta sesión. |
| `claude/guia-verificacion-certificados`, `claude/guia-verificacion-bilingue`, `claude/guia-verificacion-pptx` | 2026-09-01 | **Ya fusionadas en `master`**: son el origen de `docs/verificar-certificado.html` / `docs/verify-certificate.html` (guía es/en + versión .pptx). No tienen commits pendientes de fusionar (`master..rama` vacío). |
| `claude/claude-md-context-architecture-map-jlazo4` | — | Rama de PRs recientes de mapa de arquitectura (PR #56-#60 ya fusionados en `master`). |
| Resto de ramas `claude/*` (`auditoria-seguridad`, `diagnostico-cache`, `emitir-resumen`, `feather-no-definido`, `legales-visibles-y-media`, `limites-fallan-cerrado`, `pqrs-y-legales`, `tdc-cobertura`, `tdc-cobertura-2`, `trampa-rota`) | — | No exploradas en esta sesión; probablemente ramas de trabajo ya fusionadas o abandonadas. Verificar con `git log master..<rama> --oneline` antes de asumir que están vivas. |

Comando útil para retomar: `git fetch --all` y luego `git log master..<rama> --oneline`
por cada una, para saber cuáles siguen teniendo commits sin fusionar.

---

## 2. Tarea en progreso: actualizar la guía "How to verify a certificate"

### Qué pide el usuario (textual, dos veces, con matices crecientes)

> "Para la siguiente presentación que también está en artefactos de forma
> completa, se debe agregar lo nuevo, cómo se ven las nuevas vistas y añadir
> la vista de usuario cuando tiene uno o varios certificados asignados y lo
> que puede encontrar dentro de cada uno, **no me des un artefacto, siempre
> entrega un documento descargable**, tienes que basarte en la rama master y
> que tenga los flujos de usuario, no de administrador, y no se vean textos
> innecesarios como 'The barcode has ## characters; above 48 the symbol
> becomes very wide and harder to scan when printed.' que es información no
> relevante para la presentación."

### Restricciones duras (no negociables)

1. **Nunca un Artifact de claude.ai.** El usuario lo dijo dos veces. Entregar
   siempre un archivo descargable real: escribir el HTML a disco y mandarlo
   con `SendUserFile` (o convertirlo a `.pptx`/`.pdf` si aplica), nunca
   publicarlo con la herramienta `Artifact`.
2. **Basado en la rama `master` real**, no inventado. El contenido nuevo debe
   verificarse contra el código/plantillas de `master`, no contra
   CLAUDE.md solo (CLAUDE.md orienta dónde mirar, no sustituye la lectura).
3. **Solo flujos de usuario/titular.** Nunca pantallas ni acciones de
   administrador/operador/staff.
4. **Sin texto técnico irrelevante para una presentación** (el ejemplo dado:
   la frase sobre el número de caracteres del código de barras). Limpiar
   cualquier frase de ese estilo (advertencias de implementación, detalles de
   debug) que ya estuviera en el documento base.

### Documento base a actualizar

**Ya existe en el repo, en `master`**, no hace falta reconstruirlo desde cero
ni depende solo de lo pegado por el usuario en el chat:

- `docs/verify-certificate.html` (inglés) — **473 líneas**, éste es el que hay
  que actualizar (el usuario pidió el documento en inglés: "How to verify a
  certificate").
- `docs/verificar-certificado.html` (español) — la misma guía, generada del
  mismo guion bilingüe. Si se actualiza una, según CLAUDE.md "una frase
  añadida en uno y olvidada en el otro falla al generar y no en la página":
  **revisar si hay un script/guion generador** (buscar en `docs/` o donde
  vivan las claves de texto por idioma) antes de editar el HTML a mano en los
  dos archivos por separado.
- Existe también una versión `.pptx` en los dos idiomas (rama
  `claude/guia-verificacion-pptx`, ya fusionada) — confirmar si el usuario
  también quiere la actualización reflejada ahí, no lo pidió explícitamente
  esta vez.

**Contenido verificado ya presente en `docs/verify-certificate.html`** (para no
repetir investigación): los tres archivos de un documento certificado, los dos
portales públicos (AEGIS Documents Certificates con OTP, IPCON Employee
Certificate sin OTP), verificación por código vs. por archivo, autocomprobación
con `sha256sum`, resumen AEGIS y página de anclaje temporal. Ya menciona
"Certificate holders" y la copia del titular, pero **no** documenta ninguna
vista del panel/dashboard (login del titular, listado de sus certificados
asignados, ni el detalle de qué contiene cada uno) — eso confirma que lo
pedido es trabajo real y no ya está hecho.

### Lo que falta investigar en `master` antes de escribir una sola línea

La vista nueva a documentar es casi con toda seguridad el **invariante 33** de
CLAUDE.md (histórico de códigos con dos lecturas: operador vs. titular).
Archivos a abrir, todos en `apps/project/specific/internal/code_gen/` salvo
que se indique otra cosa:

- `code_gen/history.py` — "Historial de códigos agrupado por resumen; lo que
  se pagina son ramas, no filas". Es el entry point de la vista.
- `code_gen/access.py` — `visible_registrations()` (filtro por titular en el
  queryset) y `can_see_internals()` (qué NO se le enseña a un titular: el
  original sin códigos, los símbolos PNG sueltos, las coordenadas de
  estampado — esas tres piezas ni se producen, no solo se ocultan).
- Plantillas que renderizan esas vistas para el titular — buscar bajo
  `templates/dashboard/pages/` (probablemente en un directorio de `code_gen`
  o `certificates`); confirmar el nombre exacto explorando el repo, no
  asumirlo.
- `code_gen/tests/test_holder_history.py` — las pruebas documentan el
  comportamiento exacto esperado (qué ve un titular con uno vs. varios
  certificados, qué devuelve un código ajeno — 404, nunca 403).
- Capturas: si se van a anotar capturas de pantalla reales (como hace el resto
  de la guía, "measuring the real box of each element in the browser"), hace
  falta levantar el servidor (`uv run python manage.py runserver`) y navegar
  como un titular de prueba para verlas de verdad, no inventar el layout.

### Diseño a reutilizar (ya extraído en la sesión anterior, no hay que
redescubrirlo)

Tokens CSS: `--paper`, `--surface`, `--ink`, `--seal` (dorado), `--verify`
(verde), `--caution` (óxido), `--marine` (azul); modo claro/oscuro con
`@media (prefers-color-scheme: dark)` y `:root[data-theme="dark"]`.
Tipografías: Spectral (títulos), Source Sans 3 (cuerpo), IBM Plex Mono
(código/técnico). Patrones: pasos numerados (`.numeral`), capturas anotadas
con círculos `.mark` posicionados en porcentaje + leyenda numerada, cajas
`.note` / `.note.warn` / `.note.good`, bloques `pre.term`, tabla `.matrix` de
qué se puede/no se puede compartir.

### Estado: NADA hecho todavía en esta sesión

No se ha leído `code_gen/history.py` ni `access.py` con la herramienta Read,
no se ha explorado la plantilla del titular, no se ha redactado ninguna
sección nueva del HTML, no se ha llamado a `SendUserFile`. El paso siguiente
es exactamente esa investigación.

### Próximo paso concreto

1. Leer `code_gen/history.py`, `code_gen/access.py`,
   `code_gen/tests/test_holder_history.py` en `master` (o en `feat/notificaciones`,
   que ya lo contiene fusionado).
2. Encontrar y leer la plantilla del histórico en modo titular.
3. Si se puede, levantar el servidor y navegar la vista como titular para
   capturar el layout real (no inventarlo).
4. Editar `docs/verify-certificate.html` (y su contraparte en español si hay
   guion compartido) añadiendo la sección nueva con el mismo sistema de
   diseño, quitando cualquier texto técnico irrelevante tipo el ejemplo del
   código de barras, y sin ninguna pantalla de operador.
5. Entregar con `SendUserFile`, **nunca** con `Artifact`.

---

## 3. Plan en curso: Centro de notificaciones + migración de JotForm

Plan completo guardado en `/root/.claude/plans/immutable-splashing-parrot.md`
(puede no sobrevivir a una sesión nueva — si no está, reconstruir desde este
resumen y desde el propio plan si sigue accesible).

### Qué es

Dos encargos relacionados: (A) un centro de notificaciones in-app + correo
(la campanita del navbar ya está escrita y comentada, la app
`apps/project/common/notifications/` existe vacía); (B) sacar el formulario de
solicitud de crédito de JotForm (que hoy sube pasaportes y extractos
bancarios a servidores de un tercero) y reemplazarlo por un formulario interno
con ciclo de vida auditado.

### Estado por fase

| Fase | Contenido | Estado |
|---|---|---|
| **0** | Verificación de infraestructura: ¿cPanel alcanza el Redis del VPS?, ¿el worker Celery del VPS alcanza el MySQL de cPanel?, subdominio de tiempo real, latencia, carga | **Hecha** — comando `check_realtime` completo, registrado en la consola de operaciones, con pruebas y documentación (tareas #52-54 de la lista de tareas; commits en `feat/notificaciones`: "Fase 0: medir si cPanel aguanta el tiempo real...", "Fase 0: dos cosas que solo se vieron ejecutándolo contra producción", "Decir que es el relay, porque el nombre no lo dice") |
| **1** | Modelos (`NotificationModel`, `NotificationDeliveryModel`, `NotificationPreferenceModel`), registro central de eventos, `notify()`, admin, pruebas | **Pendiente** |
| **2** | Campanita, página `notifications:list`, preferencias (sin tiempo real todavía) | **Pendiente** |
| **3** | Celery + correo asíncrono + estados de entrega | **Pendiente** |
| **4** | Relay de tiempo real + reconexión sin duplicados | **Pendiente** |
| **5** | Eventos de seguridad enganchados a los puntos existentes | **Pendiente** |
| **6** | Formulario interno de solicitud de crédito (`credit_requests/`), modelos, ciclo de vida, auditoría | **Pendiente** (puede haber algo de trabajo en `feat/jotform-a-local` o `feat/solicitud-formulario-de-certificacion-documental` — **no explorado en esta sesión, revisar antes de asumir que está en cero**) |
| **7** | Vistas de solicitante y de gestión, "Generate a new code" apuntando al nuevo formulario | **Pendiente**, depende de 6 |
| **8** | Quitar JotForm, i18n a cero, `check_security`, documentación | **Pendiente**, depende de todas |

### Antes de tocar código de este plan

Releer el propio plan (`Fase 0` ya resuelta según qué dio verde — revisar los
commits de Fase 0 en `feat/notificaciones` para saber si el resultado fue
"cPanel aguanta" (plan A: se queda en cPanel) o si hizo falta el plan B
(migrar toda la app al VPS), porque eso decide la arquitectura de las fases 1-4.

---

## 4. Historial de tareas ya completadas (referencia rápida)

54 tareas completadas registradas en el tracker de esta sesión, agrupadas por
tema — no se repite el detalle de cada una aquí, se listan los temas para
saber qué **no** hay que redescubrir ni rehacer:

- Pruebas por app (`users`, `buyers`, `assets_location`, `account`, `core`,
  `video_masonry`, `assets`) movidas a `tests/` por app, corriendo también en
  Windows, con `test_report` + cobertura y panel de resumen en la consola.
- Consola de operaciones: comandos separados por entorno, cumplimiento
  excluido, admin legible.
- App PQRS completa (modelo con plazos legales, wizard de 5 pasos).
- Documentos legales completos: modelos, editor CKEditor 5, vistas públicas,
  PDF, registro de aceptación (alta/login/uso continuado), aviso por cron.
- Declaración de transferencia a OpenAI y límite de los claims de IA.
- Login: pantalla única de código, contador de fallos unificado, UI/UX,
  plantilla de correo OTP compartida.
- Seguridad de red: `check_workers`, `CELERY_BROKER_URL`, `netintel.py`,
  `IPBlockedModel` con columnas, detector de ráfagas 404, separación
  bots/escáneres, SRI en CDN, límites que fallan cerrado.
- `db_backup`: PII cifrada no sale en claro en los volcados.
- Migración completa Django 4.2 → 5.2 LTS, con checklist e inventario previo.
- Certificación: verificación visible para comprador y proveedor, dossier
  USB (cinco condiciones), botón de exportar, texto aclaratorio
  subir-vs-código, prueba `.ots` descargable, fecha del anclaje (altura de
  bloque, dos exploradores).
- **Invariante 33 completo**: campo `holder`, `code_gen/access.py`, histórico
  y detalle en modo titular, con sus pruebas, traducciones y CLAUDE.md — **es
  justo la base sobre la que hay que construir la sección nueva de la guía
  (§2 de este archivo)**.
- Fase 0 del centro de notificaciones (ver §3).

---

## 5. Resumen accionable para arrancar

1. **Tarea abierta con mayor prioridad explícita del usuario**: actualizar
   `docs/verify-certificate.html` (y su par en español) con la vista de
   titular/certificados asignados, basada en código real de `master`
   (invariante 33), sin pantallas de admin, sin texto técnico irrelevante, y
   entregada como archivo descargable — **nunca** como Artifact de claude.ai.
   Nada de esta tarea está hecho todavía; el siguiente paso es leer
   `code_gen/history.py` y `code_gen/access.py`.
2. **Plan de fondo, en pausa**: centro de notificaciones + JotForm, Fase 0
   completa, Fases 1-8 pendientes. No es lo que el usuario pidió en el último
   mensaje, pero es trabajo declarado y en curso en `feat/notificaciones`
   (rama activa del checkout actual).
3. Verificar antes de asumir nada: contenido real de `feat/jotform-a-local` y
   `feat/solicitud-formulario-de-certificacion-documental`, y si el plan
   `/root/.claude/plans/immutable-splashing-parrot.md` sigue accesible en la
   sesión nueva.
