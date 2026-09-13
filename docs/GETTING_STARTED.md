# Puesta en marcha de GEA

De clonar el repositorio a desplegar, paso a paso. Está escrito para que
funcione a la primera **en Windows, macOS y Linux**, y para avisar de las
trampas justo antes de caer en ellas, no después.

| | |
|---|---|
| [1. Requisitos](#1-requisitos) | Qué hace falta tener instalado |
| [2. Clonar e instalar](#2-clonar-e-instalar) | `uv sync` y poco más |
| [3. El `.env`](#3-el-env) | Donde se atasca todo el mundo |
| [4. La base de datos](#4-la-base-de-datos) | MySQL o PostgreSQL |
| [5. Redis](#5-redis) | Opcional en local, importante en el servidor |
| [6. Migrar y crear el primer usuario](#6-migrar-y-crear-el-primer-usuario) | Incluido el 2FA del panel |
| [7. Arrancar](#7-arrancar) | Y qué mirar si no arranca |
| [8. Pruebas](#8-pruebas) | Suite, cobertura e informe |
| [9. Despliegue](#9-despliegue) | cPanel, estáticos, media y cron |
| [10. Si algo falla](#10-si-algo-falla) | Los síntomas reales y su causa |

---

## 1. Requisitos

| | Versión | Notas |
|---|---|---|
| **Python** | 3.11 o superior | |
| **uv** | reciente | El gestor de paquetes. [Instalación](https://docs.astral.sh/uv/getting-started/installation/) |
| **MySQL** o **PostgreSQL** | — | Para desarrollo sirve cualquiera de los dos |
| **git** | — | |
| **ffmpeg** | — | **Sólo** si vas a tocar la galería multimedia: `video_masonry` lo invoca para quitar el audio de los vídeos. Sin él en el `PATH`, esa subida falla |
| **Redis** | — | Opcional en local. Lee el [§5](#5-redis) antes de decidir |

En Windows, PowerShell va bien. No hace falta WSL.

---

## 2. Clonar e instalar

```bash
git clone https://github.com/sebasmd-projects/gea_module_0.git
cd gea_module_0
uv sync
```

`uv sync` crea el entorno virtual en `.venv/` e instala exactamente lo que fija
`uv.lock`. No hace falta activarlo: `uv run <comando>` lo usa solo.

Si prefieres activarlo:

```bash
# Linux / macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

### Sobre los dos ficheros de dependencias

Hay dos, y **cada uno manda en un sitio distinto**:

| Fichero | Quién lo usa | Con qué |
|---|---|---|
| `pyproject.toml` + `uv.lock` | Sólo **local** | `uv` |
| `requirements.txt` | **Producción** (cPanel) | `pip` — ahí no hay uv |

El puente entre los dos es manual:

```bash
uv add <paquete>
uv export --no-dev --format=requirements-txt > requirements.txt   # ⚠️ NO es opcional
```

**Olvidar ese `export` ya rompió producción.** Pasó con `opentimestamps`,
declarada un día y exportada al siguiente: en medio, el anclaje en la cadena de
bloques fallaba en el servidor, y el fallo aparecía en tiempo de ejecución,
lejos de la causa. Para no repetirlo:

```bash
uv run python manage.py check_requirements
```

---

## 3. El `.env`

```bash
cp docs/env.example .env
```

Y **rellénalo**. No es opcional ni se puede dejar a medias:

> ⚠️ **Sin un `.env` completo el proyecto no arranca.** Muchos `os.getenv()`
> se pasan directos a `int()` o a `.split(',')` sin valor por defecto.

La buena noticia es que **el error te dice cuáles faltan**, por su nombre,
todas de una vez y con una línea de para qué sirve cada una:

```
Faltan 3 variables de entorno y el proyecto no puede arrancar sin ellas.

Se leen del fichero `.env` en la raiz del repositorio (modo DEBUG):

  DB_PORT
      Puerto de la base de datos. Se convierte a entero.
  FIELD_ENCRYPTION_KEY
      Clave Fernet con la que se cifra la PII en la base de datos. Generala
      con `python -c "from cryptography.fernet import Fernet; …"`. PERDERLA
      INUTILIZA LOS DATOS YA CIFRADOS.
  CORS_ALLOWED_ORIGINS
      Origenes permitidos, separados por comas. Vacio es valido y significa
      ninguno.

La plantilla con todas, comentadas una a una, esta en docs/env.example:
    cp docs/env.example .env
```

Tres detalles de esa comprobación (`app_core/env.py`), por si el mensaje te
sorprende:

- **Una variable vacía cuenta como ausente.** `DB_PORT=` rompe igual que no
  ponerla, porque `int('')` también falla. Las excepciones son donde vacío
  *significa* algo: `CORS_ALLOWED_ORIGINS` (ningún origen),
  `COMMON_ATTACK_TERMS` (trampa desactivada) y las dos contraseñas.
- **`DJANGO_ALLOWED_HOSTS` solo se exige con `DEBUG=False`**, que es la única
  rama que la lee. En local no hace falta.
- **Solo cubre lo que impide arrancar.** Lo que falta y únicamente degrada no
  sale ahí: `REDIS_URL`, `CERTIFICATION_SIGNING_KEY`, `GEA_BACKUP_PASSPHRASE`
  y `PQRS_NOTIFICATION_RECIPIENTS` tienen cada una su consecuencia, y están
  explicadas donde toca en esta guía.

`docs/env.example` tiene cada variable con su explicación y marca cuáles son
obligatorias. Lo mínimo para levantar en local:

```ini
DJANGO_SECRET_KEY=<genérala, abajo está el comando>
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DJANGO_ADMIN_URL=panel-dev
DJANGO_STATIC_URL=/public/static/
DJANGO_STATIC_ROOT=public/static
DJANGO_MEDIA_URL=/public/media/
DJANGO_MEDIA_ROOT=public/media
DJANGO_LOG_FILE=logs/stderr.log

DB_ENGINE=django.db.backends.mysql
DB_NAME=gea
DB_USER=gea
DB_PASSWORD=...
DB_HOST=127.0.0.1
DB_PORT=3306

DJANGO_EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
DJANGO_EMAIL_HOST=smtp.ejemplo.com
DJANGO_EMAIL_PORT=465
DJANGO_EMAIL_USE_SSL=True
DJANGO_EMAIL_HOST_USER=no-reply@ejemplo.com
DJANGO_EMAIL_HOST_PASSWORD=
DJANGO_EMAIL_DEFAULT_FROM_EMAIL=GEA <no-reply@ejemplo.com>

FIELD_ENCRYPTION_KEY=<genérala, abajo>
CORS_ALLOWED_ORIGINS=
COMMON_ATTACK_TERMS=wp-admin,wp-login,xmlrpc,phpmyadmin,.env,.git
IP_BLOCKED_TIME_IN_MINUTES=15
MIDDLEWARE_NOT_INCLUDE=
CHAT_GPT_API_KEY=
GEA_DAILY_CODE_GENERAL_RECIPIENTS=
GEA_DAILY_CODE_BUYER_RECIPIENTS=
PQRS_NOTIFICATION_RECIPIENTS=
```

### Las dos claves que hay que generar

```bash
# La de Django
uv run python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

# La que cifra la PII en la base de datos
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Por qué la segunda no usa `manage.py generate_encryption_key`**, aunque ese
> comando exista: **no se puede ejecutar cuando todavía no tienes la clave.**
> `django.setup()` importa los modelos, y los modelos importan
> `encrypted_model_fields`, que exige una `FIELD_ENCRYPTION_KEY` válida **al
> importarse**. Con la variable vacía, el comando muere antes de arrancar con
> `ImproperlyConfigured: Fernet key must be 32 url-safe base64-encoded bytes`.
> Es el clásico problema del huevo y la gallina. La línea de arriba genera
> exactamente la misma clave sin pasar por Django.
>
> `generate_encryption_key` sí sirve **después**, para rotarla — con todo lo que
> eso implica, que es migrar los datos ya cifrados.

### Crea el directorio del log

```bash
mkdir -p logs public/media public/static
```

El directorio de `DJANGO_LOG_FILE` **tiene que existir antes de arrancar**. Si
no, Django falla al configurar el logging con un `ValueError: Unable to
configure handler 'file'` que no menciona ni la ruta ni la variable.

> ⚠️ **`FIELD_ENCRYPTION_KEY` no se rota.** Cifra el correo, el teléfono y el
> pasaporte de cada usuario. Cambiarla **inutiliza todo lo ya cifrado**: no se
> pierde, queda ilegible. En producción, guarda una copia fuera del servidor
> **antes** de meter el primer dato.

### Con el correo en consola

`django.core.mail.backends.console.EmailBackend` imprime los correos en el
terminal en vez de mandarlos. Es lo que quieres en local: el registro y el
acceso por código mandan correos de verdad, y así ves el código en pantalla sin
configurar un SMTP.

---

## 4. La base de datos

`DB_ENGINE` lleva la **ruta completa** del backend, no un nombre corto.

### MySQL / MariaDB

```sql
CREATE DATABASE gea CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'gea'@'localhost' IDENTIFIED BY 'la-que-pongas';
GRANT ALL PRIVILEGES ON gea.* TO 'gea'@'localhost';
FLUSH PRIVILEGES;
```

```ini
DB_ENGINE=django.db.backends.mysql
DB_PORT=3306
```

Necesitas `mysqlclient`, que compila: en Debian/Ubuntu hace falta
`default-libmysqlclient-dev` y `build-essential`; en Windows suele instalarse
como rueda precompilada sin más.

### PostgreSQL

```sql
CREATE DATABASE gea ENCODING 'UTF8';
CREATE USER gea WITH PASSWORD 'la-que-pongas';
GRANT ALL PRIVILEGES ON DATABASE gea TO gea;
```

```ini
DB_ENGINE=django.db.backends.postgresql
DB_PORT=5432
DB_SSLMODE=prefer
```

`DB_SSLMODE` **sólo se aplica con `DEBUG=False`**.

### Conectarse a la base de producción por un túnel

Para leer datos reales desde local, sin exponer el puerto:

```powershell
ssh -p 1022 -i "$env:USERPROFILE\.ssh\ssh_access" -L 3307:127.0.0.1:3306 usuario@servidor
```

Y en el `.env`, `DB_HOST=127.0.0.1` con `DB_PORT=3307`. **Deja el terminal
abierto**: si lo cierras, se cae el túnel.

### Una trampa que conviene conocer

En `settings.py` se define un `OPTIONS` con `charset` y `init_command`, y si
`DB_ENGINE` es MySQL el bloque siguiente **reemplaza el diccionario entero** —
se pierden el `charset` y el `COLLATE utf8mb4_bin`. Está así hoy; si ves
problemas de ordenación o de acentos, mira ahí primero.

---

## 5. Redis

**En local puedes prescindir de él.** Sin `REDIS_URL`, Django cae en
`LocMemCache` y todo funciona.

**En producción importa, y bastante.** `LocMemCache` es **por proceso**, así
que los límites de intentos pasan a ser *por worker*: con seis workers, un
límite de seis intentos son treinta y seis. Los contadores que protegen el
acceso, el envío de códigos y la consulta pública de certificados dejan de
significar lo que dicen.

```ini
REDIS_URL=rediss://usuario:clave@host:6380/0?ssl_cert_reqs=required&ssl_ca_certs=/ruta/ca.crt
REDIS_KEY_PREFIX=gea
```

Montarlo con TLS y ACL en un VPS está explicado paso a paso en
**[deploy/REDIS.md](../deploy/REDIS.md)**.

Comprueba que contesta:

```bash
uv run python manage.py check_cache
```

> **Con Redis caído no pasa lo que parece.** `django-redis` va con
> `IGNORE_EXCEPTIONS`, que **no lanza la excepción: devuelve `None`**. Un
> `try/except` alrededor de una operación de caché no se entera de nada. Por eso
> todos los contadores pasan por `apps/common/utils/throttling.py`, que detecta
> la avería por lo que devuelve `incr` y **falla cerrado**. Consecuencia
> práctica: con Redis caído, los envíos de correo y la consulta pública dejan de
> funcionar hasta que vuelva. Es deliberado.

`CELERY_BROKER_URL` **no es** `REDIS_URL`: el broker necesita su propio usuario
y su propia base, porque el de la caché está acotado a `~gea:*` y responde
`NOPERM` a las operaciones de un broker. Hoy va vacía: no hay cola de tareas.

---

## 6. Migrar y crear el primer usuario

```bash
uv run python manage.py migrate
uv run python manage.py createsuperuser
```

### El panel exige segundo factor

**Con ser superusuario no basta.** El admin exige personal activo **con segundo
factor verificado**, y a quien no cumple le responde **404** — nunca 403 ni el
formulario de login del admin, porque un 403 confirmaría que la ruta existe.

Así que después de crear el superusuario:

1. Arranca el servidor.
2. Entra por **`/account/login/`** con tu usuario.
3. Ve a **`/account/two_factor/setup/`** y **da de alta un TOTP** (Google
   Authenticator, Aegis, 1Password…). Guarda los códigos de respaldo.
4. Ahora sí, el panel responde en **`/<DJANGO_ADMIN_URL>/`**.

Si entras al panel y ves un 404, **casi siempre es esto**: sesión sin segundo
factor verificado. La excepción es el personal interno sin OTP, al que se le
redirige a darlo de alta.

---

## 7. Arrancar

```bash
uv run python manage.py runserver
```

`runserver` está sobrescrito: sirve en `0.0.0.0:8000` e imprime la IPv4 de la
red local, para poder abrirlo desde el móvil sin buscarla.

Comprueba que todo responde:

```bash
uv run python manage.py check_health
```

Base de datos, caché y correo. Con `--http` lo pide por la URL pública, que
además atraviesa el servidor web, el DNS y el certificado — si el local pasa y
el HTTP no, el problema está **delante** de la aplicación.

---

## 8. Pruebas

```bash
uv run python manage.py test --settings=app_core.settings_test
```

**El `--settings` no es opcional.** La suite corre sobre SQLite en memoria
porque el usuario de MySQL en cPanel no puede crear la base `test_*`.

### Cobertura e informe

```bash
uv add --dev coverage bandit pip-audit    # opcionales
uv run python manage.py test_report
```

Guarda lo que la suite normalmente tira —qué prueba, de qué app, cuánto tardó,
cómo acabó— y mide la cobertura. El resultado se lee en el panel, en **Consola
de operaciones → Resumen de pruebas**, que sólo existe con `DEBUG=True`.

La cobertura **descuenta las pruebas y las migraciones**: un fichero de pruebas
se ejecuta entero por definición, así que contarlo sube el porcentaje por
escribir más pruebas de lo mismo.

### En Windows

La suite corre, con **tres pruebas saltadas** y ningún error. No es un fallo:

- los permisos `rw-------` no existen en Windows;
- **no se puede renombrar un fichero abierto** (`WinError 32`), y la rotación
  del log es exactamente eso.

Las tres van marcadas con su motivo escrito. Si te salen **errores** y no
saltos, lo primero que hay que mirar es si el entorno está al día: `uv sync`.

---

## 9. Despliegue

El servidor es **cPanel con Passenger**, y ahí **no hay uv**: se instala con
`pip` desde `requirements.txt`.

### Antes de subir nada

```bash
uv run python manage.py check --deploy          # los ajustes de Django
uv run python manage.py check_security          # la superficie propia de este proyecto
uv run python manage.py check_requirements      # que producción instale lo declarado
uv run python manage.py check_cron              # que las tareas estén instaladas
```

Y a ojo, estas seis:

| | Qué mirar | Por qué |
|---|---|---|
| ☐ | `DJANGO_DEBUG` **no** es `True` | Con `DEBUG`, cada error muestra la traza entera, con ajustes y consultas dentro |
| ☐ | `REDIS_URL` puesta **y contestando** | Sin ella los límites se multiplican por el número de workers (§5) |
| ☐ | `CERTIFICATION_SIGNING_KEY` puesta | Sin ella el registro se sella con HMAC y sólo esta plataforma puede verificarlo |
| ☐ | `FIELD_ENCRYPTION_KEY` es **la misma de siempre** | Cambiarla inutiliza toda la PII ya cifrada |
| ☐ | El `.htaccess` de `deploy/` está en la carpeta de media | Sin él, el servidor web reparte los PDF por su cuenta |
| ☐ | `migrate` y `collectstatic` ejecutados | Una restricción sin migrar no existe; un JS sin recoger no llega |

### En el servidor

```bash
git pull --ff-only
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py compilemessages        # si cambiaron textos traducidos
touch tmp/restart.txt                   # Passenger recarga
```

`collectstatic` es **obligatorio**: `ManifestStaticFilesStorage` añade un hash
al nombre de cada archivo, así que un JS actualizado deja de quedarse cacheado
en el navegador. Si un fichero referenciado desde un CSS no existe,
`collectstatic` falla — y eso es intencionado: avisa del enlace roto antes de
que llegue a producción.

### Media protegida

`MEDIA_ROOT` vive **dentro** del árbol que sirve el servidor web, y tiene que
seguir así: las imágenes de activos y la galería se sirven directas. Lo que no
puede servirse directo es lo sensible:

```bash
cp deploy/media.htaccess "$DJANGO_MEDIA_ROOT/.htaccess"

for d in certificates passport_images signature_images pqrs; do
    mkdir -p "$DJANGO_MEDIA_ROOT/$d"
    cp deploy/media-protected.htaccess "$DJANGO_MEDIA_ROOT/$d/.htaccess"
done
```

Comprueba que quedó bien — debe responder **404**, no el PDF:

```bash
curl -I https://tu-dominio/public/media/certificates/documents/certified_<uuid>.pdf
```

**Esto no es un detalle de configuración.** Sin el `.htaccess`, el servidor web
sigue repartiendo los PDF por su cuenta y el control de acceso de Django no
pinta nada. `pqrs/` se cayó de esa lista al crear la app, y ahí un formulario
público deposita cédulas.

### Tareas programadas

```bash
python manage.py crontab add
python manage.py check_cron          # que quedaron instaladas
```

| Cuándo | Qué |
|---|---|
| cada 15 min | `upgrade_ots_anchors` — madura las pruebas de OpenTimestamps. Sin anclajes pendientes no sale a la red |
| 19:00 | El código diario de registro, por correo |
| cada 3 min | Calentamiento, para que el primer visitante no espere el arranque |
| cada hora | `rotate_logs` — sin llegar al tope es un `stat`, así que sale barato |

### Respaldos

```bash
python manage.py db_backup -o backups/
```

Cifra lo que lleva PII con `GEA_BACKUP_PASSPHRASE` y escribe todo con permisos
`600`. **Sin esa contraseña no escribe la PII**: hay que pedirlo a propósito con
`--allow-plaintext`, y conviene entender por qué antes de hacerlo —`dumpdata`
serializa el valor **ya descifrado**, así que un volcado sin cifrar deshace el
cifrado de campo.

---

## 10. Si algo falla

| Síntoma | Causa casi segura |
|---|---|
| **No arranca** y el error no dice qué falta | Falta una variable en `.env`. Compara con `docs/env.example` |
| **El panel da 404** con un superusuario | Sesión sin segundo factor verificado (§6). Es lo esperado, no un fallo |
| **Una página normal da 404** y antes iba | Puede ser un bloqueo por IP: desde fuera se ve igual que una ruta inexistente. Mira `IPBlockedModel` en el admin y el log (`Blocked IP …`) |
| **Se bloquea una ruta legítima tuya** | Un término de `COMMON_ATTACK_TERMS` la está secuestrando. `check_attack_terms` lo dice, respetando el orden del URLconf |
| **Los límites de intentos no frenan nada** | Falta `REDIS_URL` y la caché es por worker (§5) |
| **Las subidas de vídeo fallan** | `ffmpeg` no está en el `PATH` |
| **Un JS actualizado no llega** | Falta `collectstatic` |
| **Los PDF se descargan sin pasar por Django** | Falta el `.htaccess` de `deploy/` (§9) |
| **Una dependencia nueva no está en el servidor** | Falta el `uv export`. `check_requirements` lo detecta |
| **Guardar un activo va lento** | La traducción automática llama a OpenAI **dentro del guardado**, de forma síncrona. No hay cola de tareas |
| **Las pruebas fallan en Windows con errores** | Sincroniza el entorno: `uv sync`. Con todo al día sólo debería haber 3 saltadas |

### Dónde mirar

```bash
uv run python manage.py show_log             # el log, con filtro por texto
uv run python manage.py check_health         # base de datos, caché y correo
uv run python manage.py check_media          # que MEDIA_ROOT apunta bien
uv run python manage.py check_workers        # si el hosting sostiene procesos
```

Todo eso está también en el panel, en **Consola de operaciones** — una lista
blanca de comandos, con su explicación, que deja constancia de quién ejecutó
qué. Sólo para superusuarios.

---

## Y a partir de aquí

- **[CLAUDE.md](../CLAUDE.md)** — el mapa de arquitectura (quién llama a quién),
  los invariantes que no se pueden romper y las trampas conocidas. Está escrito
  para asistentes de IA, pero es lo más útil que hay para orientarse.
- **[docs/SEGURIDAD.md](SEGURIDAD.md)** — la auditoría, con lo que se encontró
  y por qué importa.
- **[docs/ROUTES_MAP.md](ROUTES_MAP.md)** y **[docs/FEATURES_MAP.md](FEATURES_MAP.md)**
  — todas las URLs y todas las funcionalidades por dominio.
