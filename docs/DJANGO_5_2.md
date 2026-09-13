# Subida a Django 5.2 LTS

Django 4.2 LTS recibió su última actualización el **7 de abril de 2026**. Desde
entonces no hay parches de seguridad para esa rama: un fallo nuevo en Django se
queda sin arreglar en este proyecto. **5.2 LTS tiene soporte extendido hasta
abril de 2028.**

Este documento es el registro de la subida: qué se comprobó, qué hubo que
cambiar y —lo más importante— **qué hay que verificar en el servidor antes de
desplegar**, que es lo único que no se puede comprobar desde un portátil.

| | |
|---|---|
| [1. Antes de desplegar](#1-antes-de-desplegar) | Lo que puede tumbar el servidor |
| [2. Qué se subió](#2-qué-se-subió) | Versiones, antes y después |
| [3. Checklist de cambios rompedores](#3-checklist-de-cambios-rompedores) | 5.0, 5.1 y 5.2, uno a uno |
| [4. Lo que hubo que cambiar](#4-lo-que-hubo-que-cambiar) | Cuatro cosas, y por qué |
| [5. Limpieza de dependencias](#5-limpieza-de-dependencias) | Lo que sobraba |
| [6. Cómo se verificó](#6-cómo-se-verificó) | Qué se ejecutó de verdad |
| [7. Lo siguiente: Django 6.0](#7-lo-siguiente-django-60) | Qué ya está preparado |

---

## 1. Antes de desplegar

⚠️ **Lo único que puede impedir que el servidor arranque es la versión de la
base de datos.** Cada versión de Django sube el mínimo del motor, y cuando no
se cumple **no es un aviso: es un `NotSupportedError` al conectar**. Django 5.2
exige:

| Motor | Mínimo que pide Django 5.2 |
|---|---|
| **MySQL** | **8.0.11** |
| **MariaDB** | **10.5** |
| PostgreSQL | 14 |
| SQLite | 3.31 |

(Los números salen de `django/db/backends/*/features.py`, no de las notas de
versión.)

**cPanel suele ir por detrás**, y ahí es donde corre esto. Compruébalo en el
servidor **antes** de subir nada:

```bash
python manage.py check_health
```

La primera línea de la salida lo dice ahora:

```
  Motor: MySQL 8.0.36 (Django 5.2.17 pide 8.0.11)
```

Si el motor está por debajo, **no despliegues**: la aplicación no arrancará, y
el sitio se queda caído hasta que se revierta. Primero hay que subir la base de
datos desde cPanel o pedirlo al hosting.

⚠️ **Y si el motor es MariaDB 10.7 o superior**, lee la §4.4 antes de nada: Django 5.0 cambió cómo se escriben los UUID en las consultas, y con una base creada por Django 4.2 eso rompe el acceso **sin dar ningún error**. Ya está resuelto en el código; lo que hay que saber es que no se puede quitar.

Lo demás del despliegue es lo de siempre:

```bash
pip install -r requirements.txt      # el fichero cambió: 121 → 73 paquetes
python manage.py migrate             # no hay migraciones nuevas
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py check_security
python manage.py check_requirements
```

---

## 2. Qué se subió

| Paquete | Antes | Después | Por qué |
|---|---|---|---|
| **django** | 4.2.30 | **5.2.17** | 4.2 sin soporte desde abril de 2026 |
| django-formtools | 2.6.1 | 2.7 | La 2.6.1 no declara 5.2; la 2.7 pide `Django>=5.2` |
| django-redis | 6.0.0 | 7.0.0 | Ídem |
| setuptools | 80.10.2 | 84.0.0 | Cierra `PYSEC-2026-3447` |

Los demás ya declaraban compatibilidad con 5.2 en la versión que estaba
instalada: `django-auditlog` 3.4.1, `django-axes` 8.3.1, `django-two-factor-auth`
1.18.1, `django-import-export` 4.4.1, `django-otp` 1.7.3, `django-select2` 8.4.8,
`django-compressor` 4.6.0, `django-cors-headers` 4.9.0, `django-ckeditor-5`
0.2.20.

**Tres no declaran 5.2 y se quedan**, con la razón:

| Paquete | Declara hasta | Por qué se queda |
|---|---|---|
| `django-encrypted-model-fields` 0.6.5 | Django 4.0 | No hay versión más nueva, y es lo que cifra la PII. Se verificó funcionando: la suite de `users/` prueba el ciclo completo de cifrado y descifrado, y una prueba de humo creó un usuario y releyó su correo de la base de datos. Si algún día deja de funcionar, el síntoma sería inmediato y total, no silencioso |
| `django-impersonate` 1.9.5 | Django 5.0 | Es la última publicada. Su URL responde en 5.2 |
| `django-rosetta` 0.10.3 | Django 5.0 | Es la última publicada. Su URL responde en 5.2 |

---

## 3. Checklist de cambios rompedores

Cada línea se comprobó **contra este código**, no contra las notas de versión.
«No aplica» quiere decir que se buscó y no hay ni un uso.

### Django 5.0

| Cambio | ¿Afecta? | Comprobado |
|---|---|---|
| **`UUIDField` pasa al tipo nativo `uuid` en MariaDB 10.7+** | **Sí, y rompe el acceso** | Ver §4.4. **Este se escapó del checklist** |
| Se quita `django.utils.timezone.utc` | No | Sin usos |
| Se quita el soporte de `pytz` y `USE_DEPRECATED_PYTZ` | No | Sin usos |
| Se quita `USE_L10N` | No | No está en `settings.py` |
| Se quitan `CryptPasswordHasher`, `UnsaltedMD5`, `UnsaltedSHA1` | No | Se usa Argon2 |
| `ManifestStaticFilesStorage` cambia el post-proceso | **Sí, sin cambios de código** | `collectstatic` reprocesa 234 ficheros sin error |
| Python mínimo 3.10 | No | El proyecto pide 3.11 |
| `forms.URLField` pasará a asumir `https` (transición a 6.0) | No | No hay ningún `URLField` de formulario |

### Django 5.1

| Cambio | ¿Afecta? | Comprobado |
|---|---|---|
| Se quitan `DEFAULT_FILE_STORAGE` y `STATICFILES_STORAGE` | No | Ya se usaba `STORAGES`, en los dos ficheros de settings |
| Se quita `Meta.index_together` | No | Sin usos; los índices son `Meta.indexes` |
| Se quita el filtro de plantilla `length_is` | No | Sin usos en `templates/` |
| Se quita `BaseUserManager.make_random_password()` | No | Sin usos |
| Se quita `django.core.files.storage.get_storage_class()` | No | Sin usos |
| `ModelAdmin.log_deletion()` → `log_deletions()` | No | El admin no los sobrescribe |
| **`CheckConstraint.check` → `.condition`** | **Sí** | 23 avisos en la suite. Ver §4 |
| `LoginRequiredMiddleware` (nuevo, opcional) | No se adopta | El acceso se controla con mixins por vista (§5 de `CLAUDE.md`). Un middleware global que exige sesión chocaría con el portal público de verificación y con la trampa anti-escaneo |

### Django 5.2

| Cambio | ¿Afecta? | Comprobado |
|---|---|---|
| **Mínimos de base de datos** (MySQL 8.0.11, MariaDB 10.5, PostgreSQL 14) | **Sí, en el servidor** | Ver §1. Se añadió la comprobación a `check_health` |
| `Model.save()` con argumentos posicionales queda obsoleto | No | Ningún `save(True)`; los `save()` propios usan `*args, **kwargs` |
| Se quita `DjangoDivFormRenderer` | No | Sin usos; no se toca `FORM_RENDERER` |
| Claves primarias compuestas (nuevo) | No se usa | — |
| `BoundField` cambia por dentro | No | Las plantillas no dependen de sus internos |

---

## 4. Lo que hubo que cambiar

Cuatro cosas. Ninguna de negocio.

### 4.1 `CheckConstraint(check=…)` → `condition=`

Es el único cambio que tocó modelos. **Es un renombrado del argumento, no un
cambio de semántica**: la restricción es la misma, el SQL es el mismo y
`makemigrations --check` no detecta nada nuevo. Se cambió en 23 sitios:

- 11 en `buyers/models.py` (las diez del flujo de 12 etapas, más la de
  `ServiceOrderRecipient`).
- 12 en las dos migraciones que las crearon.

**Se tocaron también las migraciones a propósito.** Una migración es historia y
normalmente no se edita, pero éstas se vuelven a ejecutar enteras cada vez que
se crea la base de pruebas: dejarlas con `check=` mantendría 23 avisos de
obsolescencia en cada ejecución de la suite. Un aviso permanente que no
significa nada enseña a no leer los avisos, que es como se pierde el siguiente
que sí importa.

Las tres capas del invariante 2 (`mark_*()`, `clean()`/`save()` y las
`CheckConstraint`) siguen exactamente igual: lo prueban los 834 tests, con las
restricciones ejercidas por `QuerySet.update()` para saltarse `save()`.

### 4.2 Las opciones de conexión eran de MySQL y se aplicaban a todos

No lo trajo Django 5.2: se destapó al intentar arrancar contra SQLite.

`DATABASES['default']['OPTIONS']` traía `charset` e `init_command` de MySQL
para **cualquier** motor. Con MySQL no hacía nada —el bloque de abajo reemplaza
el diccionario entero, que es la trampa que ya estaba documentada— y con
cualquier otro motor **rompía la conexión**:

```
TypeError: 'charset' is an invalid keyword argument for Connection()
```

O sea: inútil donde se usaba, impeditivo donde no. Levantar el proyecto contra
PostgreSQL en local era imposible sin editar `settings.py`.

Ahora el diccionario base va vacío y cada motor pone las suyas abajo. **La
configuración de MySQL en producción no cambia ni un carácter.**

### 4.4 Los UUID se siguen guardando como estaban (MariaDB 10.7+)

**Éste se escapó del checklist, y es el que más daño hizo.** Se revisó qué
APIs de Python cambiaban, no qué cambiaba en el **almacenamiento**. El aviso
de que faltaba llegó desde producción, no desde aquí.

Django 5.0 empezó a usar el tipo nativo `uuid` de MariaDB 10.7 o superior:

```python
# django/db/backends/mysql/features.py
@cached_property
def has_native_uuid_field(self):
    is_mariadb = self.connection.mysql_is_mariadb
    return is_mariadb and self.connection.mysql_version >= (10, 7)

# django/db/models/fields/__init__.py, UUIDField.get_db_prep_value
if connection.features.has_native_uuid_field:
    return value          # con guiones: 'd717d90c-5e8c-45a7-...'
return value.hex          # sin guiones: 'd717d90c5e8c45a7...'
```

Una base creada con Django 4.2 tiene la columna como `char(32)` y los valores
en hex **sin guiones**. Al subir, las consultas pasan a mandar el UUID **con
guiones** contra esa misma columna.

**No falla: se queda en silencio.** La fila existe, se lee, y
`filter(username=...)` la encuentra; sólo deja de funcionar lo que busca **por
clave primaria**. En el acceso eso significa que la contraseña se acepta —el
backend busca por `username` o por `email_hash`— y acto seguido el asistente
no puede recargar al usuario por su pk:

```
Acceso: se llegó al final del asistente sin usuario en el almacén.
Motivo: no hay ninguna cuenta con pk=d717d90c-5e8c-45a7-... en
propensi_geausadb en 127.0.0.1:3307, pero acaba de identificarse con esa clave
```

**Se apaga en vez de migrar la base.** `app_core/db/mysql` es el backend de
Django con `has_native_uuid_field = False`, y `settings.py` lo instala cuando
el `.env` declara MySQL (`app_core/db/engine_for()`). Migrar sería convertir
diez columnas `UUIDField` **y todas las claves ajenas que apuntan a ellas**
—usuarios, activos, ubicaciones, órdenes, certificados— en una base en
producción, de una vez y sin poder volver atrás a mitad. El tipo nativo no
aporta nada que este proyecto use: lo que aporta es que MariaDB muestre el
UUID formateado.

Apagarlo devuelve exactamente el comportamiento con el que se escribieron esos
datos, y es reversible: migrar sigue siendo posible el día que compense.

En MySQL (el de Oracle, no MariaDB) y en PostgreSQL esto no cambia nada.

**La lección para la próxima subida**: un checklist de cambios rompedores que
sólo mira el código propio no ve los que ocurren entre el ORM y el motor. Lo
que lo habría cazado es una prueba contra el motor de producción, y la suite
corre sobre SQLite por una razón que sigue siendo válida (§6). Mientras sea
así, cada subida de Django necesita **una entrada de sesión real contra la
base de verdad** antes de darla por buena.

### 4.3 `check_health` dice qué versión de base de datos hay

Ver §1. Pregunta los mínimos a Django (`features.minimum_database_version`) en
vez de escribirlos, porque escribirlos sería garantizar que se quedan viejos en
la siguiente subida.

---

## 5. Limpieza de dependencias

### 5.1 El grupo de desarrollo se instalaba en producción

`uv export` **incluye el grupo de desarrollo salvo que se le diga que no**, y
se venía exportando sin `--no-dev`. Resultado: `requirements.txt` llevaba 121
paquetes, de los cuales **48 sólo sirven para desarrollar**.

No es sólo peso. Entre ellos iba `safety` —exactamente la herramienta que este
proyecto decidió **no** ejecutar en el servidor porque se queda esperando una
credencial— y, con ella, `nltk`, que era el único paquete del entorno con un
aviso de seguridad **sin versión que lo corrija**. Estaba en producción sin que
nada de producción lo usara.

A partir de ahora:

```bash
uv export --no-dev --format=requirements-txt > requirements.txt
```

Y `manage.py check_requirements` lo comprueba: si encuentra en
`requirements.txt` un paquete declarado en `[dependency-groups]`, lo dice y
explica cómo reexportar. Acordarse del `--no-dev` ya se demostró que no
funciona.

### 5.2 Tres apps instaladas que nadie usaba

`django_filters`, `parler` y `django_countries` estaban en `INSTALLED_APPS` sin
un solo import, campo ni migración que los tocara. Junto con
`django-debug-toolbar`, `django-environ`, `django-phonenumber-field`,
`django-admin-sortable2` y `python-pptx` —declarados y nunca importados— son
ocho paquetes menos.

Una dependencia sin usar no es gratis: en esta subida obligaba a comprobar la
compatibilidad con 5.2 de tres paquetes que no hacen nada, y dos de ellos sólo
la dan en versiones que arrastran requisitos nuevos. Se paga por mantener lo
que no se usa. Es el mismo caso de `betterforms`, que ya se quitó por lo mismo.

### 5.3 Vulnerabilidades

Antes de esta revisión, `pip-audit` daba avisos en 12 paquetes. Después queda
**uno**: `nltk`, que ya no llega a producción porque es del grupo de
desarrollo. `setuptools` se subió a 84.0.0 para cerrar el suyo.

---

## 6. Cómo se verificó

No basta con que la suite pase: la suite corre sobre SQLite en memoria y no
levanta el servidor.

| Comprobación | Resultado |
|---|---|
| `manage.py check` | Sin problemas |
| `manage.py test` (834 pruebas) | **OK**, sin un solo cambio en el código de pruebas |
| Avisos de obsolescencia de Django en la suite | **0** tras el cambio de §4.1 |
| `manage.py makemigrations --check --dry-run` | Sin cambios: el modelo no se movió |
| `migrate` sobre una base vacía | Todo el historial de migraciones replica bien en 5.2 |
| `collectstatic` con `ManifestStaticFilesStorage` | 234 ficheros post-procesados, sin error |
| Servidor levantado de verdad | `/`, `/health/`, `/account/login/`, `/account/register/`, `/certificates/`, `/pqrs/`, `/robots.txt` → 200; el panel y una ruta inventada → 404 (invariante 7); `rosetta`, `impersonate`, `select2` y `ckeditor5` responden |
| Acceso de punta a punta, contra `settings.py` de verdad y con CSRF | Usuario creado, PII cifrada y releída, `POST` al asistente, sesión autenticada |
| Los dos PDF de orden (`reportlab` + buscadores de estáticos) | Se generan, 703 KB y 436 KB |
| `check_security` | bandit sin avisos nuevos; `pip-audit` con un solo aviso, y de desarrollo |
| `check_requirements` | Todo lo declarado exportado, y nada del grupo de desarrollo |

Una nota sobre `django-formtools` 2.7: se comprobó **en el código de la
librería** que `_resolved_form_list` y `_condition_dict_signature` siguen
existiendo, porque el proyecto depende de poder invalidarlos
(`apps/common/utils/wizards.py`). Si hubieran desaparecido, nuestro
`forget_resolved_steps()` habría pasado a no hacer nada **sin fallar**, y el
error de los asistentes habría vuelto en silencio.

---

## 7. Lo siguiente: Django 6.0

Tras esta subida, el proyecto **no tiene ningún aviso de obsolescencia de
Django** en toda la suite. Lo que hará falta cuando toque:

- Revisar de nuevo `django-encrypted-model-fields`, `django-impersonate` y
  `django-rosetta`: son los tres que ya van por detrás en lo que declaran.
- `forms.URLField` pasará a asumir `https`. Hoy no hay ninguno; si se añade uno
  antes de 6.0, ponle `assume_scheme` explícito.
- `Model.save()` dejará de aceptar argumentos posicionales. Hoy no se usan.
- Volver a mirar el mínimo de base de datos del servidor, que es lo que
  bloquea cada vez.

No hay prisa: 5.2 tiene soporte hasta abril de 2028.
