# GEA — Gestión de Activos Históricos

Plataforma web de **Propensiones Abogados** para la gestión de activos
históricos (bonos alemanes, oro, billetes de alta denominación y similares),
el flujo de compra sobre ellos y la **verificación pública de certificados**.

**Producción:** <https://geausa.propensionesabogados.com>
**Idiomas:** español (contenido primario) e inglés.

> **¿Primera vez aquí?** → **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**
> te lleva desde clonar el repositorio hasta desplegar, paso a paso.

---

## Qué hace

Cuatro procesos de negocio, y un quinto transversal:

| | Proceso | Dónde vive |
|---|---|---|
| 1 | **Tenedores** registran activos y sus ubicaciones físicas | `assets/`, `assets_location/` |
| 2 | **Compradores** crean órdenes de compra | `buyers/` |
| 3 | Un **flujo de aprobación de 12 etapas** lleva la orden desde la revisión hasta la liquidación, con permisos por etapa y generación de PDF | `buyers/` |
| 4 | **Portal público de verificación** de certificados (personas y documentos), con QR, código de barras y protección OTP | `certificates/`, `code_gen/` |
| 5 | **PQRS**: derecho de petición con plazos legales | `pqrs/` |

La **certificación acredita integridad, no veracidad**: la plataforma prueba
que un archivo no ha cambiado desde que se registró, no que sea cierto lo que
el documento afirma. El propio registro de certificación lo dice en
`scope.does_not_attest`.

---

## Stack

| Capa | Tecnología |
|---|---|
| Runtime | Python **3.11+** |
| Framework | **Django 5.2 LTS** (`>=5.2,<6.0`) — soporte hasta abril de 2028 |
| Paquetes | **uv** (`pyproject.toml` + `uv.lock`); `requirements.txt` se **exporta** para producción |
| Base de datos | **MySQL** o **PostgreSQL**, por `DB_ENGINE`; charset `utf8mb4` |
| Caché / límites | **Redis** (opcional, muy recomendado) |
| Frontend | Plantillas Django + Bootstrap 5 por CDN. **Sin SPA, sin build de JS** |
| PDF | ReportLab (estampado), pypdf (fusión y marca de agua), `python-barcode`, `qrcode` |
| IA | OpenAI — traducción es↔en y transcripción de audio. **Opcional**: sin clave, devuelve el texto original |

**Terceros clave:** `django-two-factor-auth` + `django-otp` (2FA),
`django-axes` (fuerza bruta), `django-auditlog`,
`django-encrypted-model-fields` (PII cifrada), `django-import-export`,
`django-crontab`, `django-formtools`, `rosetta`, `impersonate`, `argon2-cffi`.

**No hay Django REST Framework.** Los directorios `api/` existen pero están
vacíos: no asumas endpoints REST.

---

## Arranque rápido

Para el recorrido completo —y sobre todo para el `.env`, que es donde se
atasca todo el mundo— ve a **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)**.

```bash
git clone https://github.com/sebasmd-projects/gea_module_0.git
cd gea_module_0

uv sync                                   # crea .venv e instala
cp docs/env.example .env                  # y RELLÉNALO: sin él no arranca
mkdir -p logs public/media public/static  # el directorio del log debe existir

uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver         # sirve en 0.0.0.0:8000
```

`runserver` está sobrescrito: sirve en `0.0.0.0:8000` e imprime la IPv4 de la
red local, para poder abrirlo desde el móvil.

> ⚠️ **Sin un `.env` completo el proyecto no arranca** — muchos `os.getenv()`
> se pasan directos a `int()` o a `.split(',')` sin valor por defecto. Pero el
> error **dice cuáles faltan, por su nombre y todas de una vez**:
>
> ```
> Faltan 3 variables de entorno y el proyecto no puede arrancar sin ellas.
>
> Se leen del fichero `.env` en la raiz del repositorio (modo produccion):
>
>   DB_PORT
>       Puerto de la base de datos. Se convierte a entero.
>   FIELD_ENCRYPTION_KEY
>       Clave Fernet con la que se cifra la PII en la base de datos. …
>   CORS_ALLOWED_ORIGINS
>       Origenes permitidos, separados por comas. Vacio es valido y …
>
> La plantilla con todas, comentadas una a una, esta en docs/env.example:
>     cp docs/env.example .env
> ```
>
> Lo comprueba `app_core/env.py` antes de que `settings.py` lea nada. Una
> variable **vacía** cuenta como ausente salvo donde vacío significa algo
> (`CORS_ALLOWED_ORIGINS`, `COMMON_ATTACK_TERMS`, las contraseñas), y
> `DJANGO_ALLOWED_HOSTS` solo se exige con `DEBUG=False`, que es la única rama
> que la lee.
>
> La comprobación cubre lo que **impide arrancar**. Lo que falta y solo
> degrada no sale ahí y conviene repasarlo a mano: sin `REDIS_URL` los
> contadores de intentos pasan a ser por worker, sin
> `CERTIFICATION_SIGNING_KEY` el registro se sella con HMAC y no lo puede
> verificar un tercero, sin `GEA_BACKUP_PASSPHRASE` `db_backup` se niega a
> escribir la PII, y sin `PQRS_NOTIFICATION_RECIPIENTS` nadie se entera de una
> PQRS nueva mientras su plazo legal corre.

---

## Comandos

### Antes de cada despliegue

Cuatro. Si los cuatro salen limpios, adelante.

```bash
uv run python manage.py check --deploy          # los ajustes de Django
uv run python manage.py check_security          # la superficie propia de este proyecto
uv run python manage.py check_requirements      # que producción instale lo declarado
uv run python manage.py check_cron              # que las tareas estén instaladas
```

Los cuatro están también en la **consola de operaciones**, dentro del panel.

### Diagnóstico

| Comando | Para qué |
|---|---|
| `check_health` | Base de datos, caché y correo — desde dentro (`--local`) o por HTTP (`--http`) |
| `check_cache` | Que Redis contesta y con qué latencia |
| `check_workers` | Si el hosting sostiene procesos en segundo plano |
| `check_media` | Que `MEDIA_ROOT` apunta donde están los archivos |
| `check_attack_terms` | Colisiones de la trampa anti-escaneo con rutas reales |
| `check_certifications` · `check_anchoring` | Integridad de lo certificado y estado del anclaje |
| `show_log` · `rotate_logs` | Leer y rotar el log |

### Operación

| Comando | Para qué |
|---|---|
| `db_backup -o backups/` | Respaldo **cifrado** de lo que lleva PII |
| `generate_gea_code` | El código diario de registro |
| `generate_certification_key` | Clave Ed25519 para firmar el registro de certificación |
| `upgrade_ots_anchors` | Madura las pruebas de OpenTimestamps |
| `clear_cache` | Vacía la caché |

⚠️ **No ejecutes `delete_migrations` ni `rename_migrations`** salvo petición
explícita: borran o renombran ficheros de migración de todo el proyecto.

### Pruebas

```bash
uv run python manage.py test --settings=app_core.settings_test
```

**El `--settings` no es opcional:** la suite corre sobre SQLite en memoria
porque el usuario de MySQL en cPanel no puede crear la base `test_*`.

Con informe estructurado y cobertura:

```bash
uv add --dev coverage          # opcional
uv run python manage.py test_report
```

El resultado se lee en el panel, en **Resumen de pruebas** (sólo con
`DEBUG=True`). Ver [docs/GETTING_STARTED.md §8](docs/GETTING_STARTED.md#8-pruebas).

---

## Estructura

```
app_core/                    settings, urls, wsgi/asgi, admin propio, locale
apps/
  common/
    core/                    landing pública, health check
    utils/                   modelo base, middleware, cron, comandos, helpers
  project/
    common/
      account/               registro (wizard), login/logout, contraseñas
      pqrs/                  derecho de petición con plazos legales
      users/                 UserModel + geografía + PII cifrada
    specific/
      assets_management/     assets · assets_location · buyers
      documents/             certificates · video_masonry
      internal/              code_gen (certificación) · ops (consola)
templates/                   plantillas globales
public/staticfiles/          css, js, imágenes WebP, vídeo
deploy/                      .htaccess de media y montaje de Redis
docs/                        toda la documentación
```

Las apps se declaran agrupadas en `settings.py` y se concatenan en
`ALL_CUSTOM_APPS`. **Ese orden determina el orden del URLconf**, lo cual
importa: `utils` registra una regex catch-all antes que varias apps reales.

Para crear una app nueva usa el comando propio, que ya fija el `name` con ruta
completa y crea `urls.py` y `locale/`:

```bash
uv run python manage.py start_app apps/project/specific/<grupo>/<nombre>
```

Después hay que **añadirla a mano** al grupo correspondiente en `settings.py`.

---

## Seguridad

Lo que conviene saber antes de tocar nada:

- **El admin se protege con la sesión, no con la URL.** Exige personal activo
  **con segundo factor verificado**, y a quien no cumple le responde **404**,
  nunca 403: un 403 confirmaría que la ruta existe. `DJANGO_ADMIN_URL` sigue
  viniendo del entorno, pero ya no es el control de acceso.
- **La PII va cifrada en la base de datos** (`FIELD_ENCRYPTION_KEY`). Perder
  esa clave inutiliza los datos cifrados; **no se rota** sin migrarlos.
- **Los respaldos se cifran.** `dumpdata` serializa el valor *descifrado*, así
  que un volcado sin cifrar deshacía el cifrado de campo. Sin
  `GEA_BACKUP_PASSPHRASE`, `db_backup` **no escribe** la PII.
- **Los archivos de certificación nunca se sirven por `MEDIA_URL`.** La única
  vía comprueba permisos — y en el servidor hace falta además el `.htaccess`
  de `deploy/`.
- **Tres capas contra escaneo**: trampa por términos, detector de ráfagas de
  404 y firma de herramientas. Las tres acaban en el mismo bloqueo por IP, y
  una IP bloqueada recibe **un 404 y sólo eso**.

Detalle completo, con la auditoría y lo que se encontró:
**[docs/SEGURIDAD.md](docs/SEGURIDAD.md)**.

---

## Documentación

| Documento | Qué contesta |
|---|---|
| **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** | Cómo lo pongo en marcha, y cómo lo despliego |
| [SEGURIDAD.md](docs/SEGURIDAD.md) | Checklist de despliegue y la auditoría completa |
| [DJANGO_5_2.md](docs/DJANGO_5_2.md) | La subida a Django 5.2: cambios rompedores, qué se verificó y qué mirar en el servidor antes de desplegar |
| [NORMATIVA.md](docs/NORMATIVA.md) | Qué exigen los reguladores a la certificación |
| [ANCLAJE.md](docs/ANCLAJE.md) | El anclaje temporal de punta a punta |
| [ROUTES_MAP.md](docs/ROUTES_MAP.md) | Todas las URLs, namespaces, vistas y permisos |
| [FEATURES_MAP.md](docs/FEATURES_MAP.md) | Funcionalidades por dominio y reglas de negocio |
| [deploy/REDIS.md](deploy/REDIS.md) | Montar Redis con TLS y ACL en un VPS |
| [deploy/README.md](deploy/README.md) | Media protegida y estáticos |
| **[CLAUDE.md](CLAUDE.md)** | Ficha técnica para asistentes de IA: mapa de arquitectura, invariantes y trampas conocidas. **Útil también para humanos** |

Y para enseñar fuera, no para desarrollar:
[verificar-certificado.html](docs/verificar-certificado.html) /
[verify-certificate.html](docs/verify-certificate.html) — el recorrido público
de verificación con capturas anotadas, en español y en inglés.

---

## Contribuir

- Rama principal: `master`. El trabajo va en ramas y entra por pull request.
- **Las pruebas viven en `apps/<app>/tests/`**, un paquete por app, ficheros
  `test_*.py`.
- Todo texto visible va envuelto en `gettext_lazy as _`.
- Los comentarios de plantilla van en `{% comment %}…{% endcomment %}`, nunca
  en `{# … #}` — hay una prueba que lo comprueba.
- Antes de abrir un PR: la suite en verde y `check_security` limpio.

Lee **[CLAUDE.md §6 (invariantes)](CLAUDE.md)** antes de tocar el flujo de
órdenes, la certificación o el acceso. Son reglas que ya costaron un incidente.

---

## Autores

**Sebastián Morales** y **Carlos Morales** — Propensiones Abogados.
