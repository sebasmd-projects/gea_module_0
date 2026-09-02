# Redis para GEA, en un VPS con Docker

Por qué hace falta: los contadores de tasa de la plataforma —el OTP público de
verificación, el código de registro de compradores y el cupo de recuperación de
contraseña— viven en cache. Sin `CACHES` configurado Django usa `LocMemCache`,
que es **por proceso**: con N workers los límites son N veces más laxos y se
reinician en cada despliegue. Redis los convierte en un contador único y de
verdad.

El servidor web está en cPanel (Conexcol) y no admite Redis, así que Redis vive
en otra máquina y **el tráfico sale a internet**. Eso cambia el listón: no basta
con levantarlo, hay que cerrarlo. Redis tiene una larga historia de servidores
comprometidos por estar expuestos sin autenticación.

Tres capas, y las tres hacen falta:

| Capa | Qué evita |
|---|---|
| Cortafuegos a una sola IP | Que nadie más llegue siquiera al puerto |
| TLS con CA propia | Que el tráfico y la contraseña viajen en claro |
| Usuario ACL acotado | Que una fuga de la clave permita borrar o reconfigurar |

> Lo probado de este documento, contra un Redis real: la configuración de
> Django, el `rediss://` con CA propia, el rechazo cuando falta la CA, el
> `redis.conf` con sus tres usuarios —incluido que sin `user default off`
> se entra sin credenciales—, que `clear_cache` funciona, y el comportamiento
> con Redis caído. Lo no probado aquí, por no haber Docker en el entorno donde
> se redactó: el `compose.yaml` y las reglas de cortafuegos. Sigue el paso 6,
> que es el que lo comprueba desde fuera.

---

## Paso 0. Los datos de esta instalación

| Dato | Valor |
|---|---|
| Aplicación (cPanel, Conexcol) | `geausa.propensionesabogados.com` |
| IP del hosting compartido (estática) | **`190.90.160.103`** ← la única que se autoriza |
| VPS (IlimitadoHost, Webmin) | `sebasmoralesd.com` · **`5.189.155.153`** |
| Nombre del Redis | `redis.sebasmoralesd.com` → `5.189.155.153` |

Cada máquina hace un papel y conviene no mezclarlos: **cPanel es el cliente**
—desde ahí sale la conexión— y **el VPS es el servidor** que la recibe.

**Comprobación de un minuto antes de tocar nada.** La IP que autoriza el
cortafuegos es la de **salida** de cPanel, y en hosting compartido no siempre
coincide con la de entrada. Desde SSH en cPanel o un cron de la cuenta:

```bash
curl -s https://ifconfig.io
```

Si responde `190.90.160.103`, todo encaja. Si responde otra cosa, **esa** es la
que va en el paso 5; anótala, porque si no el cortafuegos bloqueará justamente
a la aplicación.

**El nombre del Redis.** El VPS es otra máquina, así que no vale
`geausa.propensionesabogados.com`. Crea un registro `A`
`redis.sebasmoralesd.com` → `5.189.155.153` desde Webmin (Servers → BIND DNS
Server, o el gestor de DNS de IlimitadoHost). Es preferible a usar la IP
directamente: si algún día cambias de VPS, cambias el DNS y no tocas el `.env`
de producción.

> **Sobre «IP address 5.189.155.153 (Shared by all servers)».** Ese texto de
> Webmin significa que el servidor virtual usa la IP compartida de la máquina
> en vez de una dedicada, y para esto da igual: lo que importa es que el puerto
> 6380 solo lo pueda alcanzar `190.90.160.103`. Lo que **sí** conviene mirar es
> si en esa máquina hay otros servicios tuyos escuchando, porque las reglas del
> paso 5 son específicas del 6380 y no tocan el resto.

En el resto del documento aparece como `redis.sebasmoralesd.com`.

---

## Paso 1. Estructura en el VPS

```bash
sudo mkdir -p /opt/gea-redis/{tls,data}
cd /opt/gea-redis
```

## Paso 2. Certificados

Se usa una **CA propia** en vez de Let's Encrypt a propósito: no hace falta
dominio ni renovación automática dentro del contenedor, y el cliente confía en
un certificado concreto en vez de en cualquier CA pública. Sustituye
`redis.sebasmoralesd.com` por el nombre o la IP con la que se va a conectar cPanel.

```bash
cd /opt/gea-redis/tls

# CA propia, 10 años
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.crt -subj "/CN=GEA Redis CA"

# Certificado del servidor
openssl genrsa -out redis.key 2048
openssl req -new -key redis.key -out redis.csr -subj "/CN=redis.sebasmoralesd.com"

printf "subjectAltName=DNS:redis.sebasmoralesd.com,IP:5.189.155.153\nextendedKeyUsage=serverAuth\n" > ext.cnf

openssl x509 -req -in redis.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out redis.crt -days 3650 -sha256 -extfile ext.cnf

# El contenedor corre como el usuario redis (uid 999)
sudo chown 999:999 redis.key redis.crt ca.crt
sudo chmod 600 redis.key
```

El `subjectAltName` no es opcional: sin él la verificación del cliente falla
aunque el certificado sea correcto.

## Paso 3. Configuración de Redis

`/opt/gea-redis/redis.conf`:

```conf
# --- Red ---------------------------------------------------------------
# Sin puerto en claro: solo TLS. Si alguien atraviesa el cortafuegos, no
# encuentra un puerto sin cifrar por el que colarse.
port 0
tls-port 6380
tls-cert-file /tls/redis.crt
tls-key-file  /tls/redis.key
tls-ca-cert-file /tls/ca.crt
tls-auth-clients no

protected-mode yes

# --- Memoria -----------------------------------------------------------
# Los contadores ocupan poquísimo. El tope existe para que Redis no se coma
# el VPS si algún día se cachea algo grande.
maxmemory 256mb
maxmemory-policy allkeys-lru

# --- Persistencia ------------------------------------------------------
# Ninguna, y es deliberado: esto es cache. Perder los contadores en un
# reinicio solo reinicia las ventanas de límite, que es lo que ya pasa hoy en
# cada despliegue. A cambio no hay disco que asegurar ni copias que custodiar.
save ""
appendonly no

# --- Comandos peligrosos ----------------------------------------------
rename-command DEBUG ""

# --- Usuarios ----------------------------------------------------------
# Van AQUI y no con «ACL SETUSER» desde fuera, por dos razones: ACL SAVE
# necesita un aclfile que no tenemos, y sin persistir, los usuarios creados a
# mano desaparecen al recrear el contenedor.
#
# 1) El usuario «default» viene de fabrica ENCENDIDO, SIN CONTRASENA y con
#    permiso para todo. Apagarlo es obligatorio: sin esta linea, cualquiera
#    que alcance el puerto entra sin credenciales y el usuario acotado de
#    abajo no sirve de nada. Comprobado: antes de apagarlo se podia escribir
#    y leer la configuracion sin autenticarse.
user default off

# 2) Un usuario solo para el healthcheck de Docker: sin contrasena, sin
#    acceso a ninguna clave y con un unico comando. Lo mas que puede hacer
#    quien lo use es confirmar que hay un Redis vivo.
user health on nopass resetkeys +ping

# 3) El de la aplicacion. La contrasena va como SHA-256, no en claro:
#       printf '%s' 'TU_CLAVE' | sha256sum
#    Solo toca claves «gea:*» -- el prefijo que pone Django -- y no puede
#    FLUSHALL, CONFIG ni SHUTDOWN.
#
#    OJO CON EL ORDEN: las reglas se aplican de izquierda a derecha, asi que
#    «-@dangerous» tiene que ir ANTES de «+flushdb». Al reves lo revoca, y
#    entonces «manage.py clear_cache» no vacia nada y el fallo se traga en
#    silencio. Se necesita flushdb, y no flushall, porque django-redis vacia
#    asi; flushdb solo afecta a esta base, que es solo de GEA.
user gea on #PEGA_AQUI_EL_SHA256 ~gea:* +@read +@write +@keyspace -@dangerous +flushdb

# 4) Solo si algun dia se monta una cola de tareas (Celery). Mientras no la
#    haya, esta linea sobra: no se abre lo que no se usa. El paso 9 lo explica
#    entero -- contrasena, base de datos y como comprobarlo.
#
#    Un broker necesita cosas que la cache no: sus propios nombres de clave,
#    PING (@connection), pub/sub y transacciones. Con la ACL del usuario «gea»
#    responde NOPERM a las cinco, y el sintoma seria de los peores --el Redis
#    contesta, la cache va, y las tareas desaparecen sin ruido--, asi que va
#    aparte y con otra contrasena.
#
#    Los tres patrones de clave son los que Celery usa de verdad. NO se pone
#    «~*»: las ACL de Redis no se acotan por base de datos, asi que un usuario
#    con «~*» conectado a la base 0 leeria y borraria las claves de la cache
#    aunque el broker viva en la base 1. Comprobado.
# user broker on #OTRO_SHA256 ~celery* ~_kombu* ~unacked* &* +@all -@dangerous -@admin
```

Genera el hash de la contraseña **antes** de arrancar:

```bash
openssl rand -base64 36                       # la contraseña; guárdala
printf '%s' 'LA_CONTRASEÑA' | sha256sum       # el hash que va en el fichero
```

> ⚠️ **Va el hash, no la contraseña.** Tiene que ser exactamente **64 caracteres
> hexadecimales en minúscula**. Si pegas ahí la contraseña —que sale en base64,
> con mayúsculas y símbolos— Redis **no arranca** y el contenedor entra en bucle
> de reinicio:
>
> ```
> *** FATAL CONFIG FILE ERROR ***
> Error in user declaration 'gea': The password hash must be exactly 64
> characters and contain only lowercase hexadecimal characters
> ```
>
> Y una comodidad: si ya habías creado el usuario con `ACL SETUSER gea on
> '>clave'`, Redis guardó el SHA-256 por ti. `ACL LIST` te lo enseña —el
> `#…` de esa línea— y puedes copiarlo tal cual al fichero. Así no hay
> forma de que deje de cuadrar con la contraseña que ya está en `REDIS_URL`.

**Si el contenedor se queda reiniciando**, la causa está siempre en el log, y
Redis es explícito con los errores de configuración:

```bash
sudo docker logs --tail 20 gea-redis
```

## Paso 4. Docker Compose

`/opt/gea-redis/compose.yaml`:

```yaml
services:
  redis:
    image: redis:7.4-alpine
    container_name: gea-redis
    restart: unless-stopped
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    volumes:
      - ./redis.conf:/usr/local/etc/redis/redis.conf:ro
      - ./tls:/tls:ro
    ports:
      # Publicado en la IP pública porque cPanel se conecta desde fuera.
      # Quien lo cierra es el cortafuegos del paso 5, no Docker.
      - "6380:6380"
    healthcheck:
      # Con «user default off», un ping sin credenciales responde NOAUTH y el
      # contenedor se marcaría enfermo estando sano. Va con el usuario del
      # healthcheck, que no lleva contraseña ni toca ninguna clave.
      test: ["CMD", "redis-cli", "--tls", "--cacert", "/tls/ca.crt",
             "-p", "6380", "--user", "health", "--pass", "", "ping"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Los usuarios ya están en `redis.conf`, así que solo hay que arrancar:

```bash
cd /opt/gea-redis
sudo docker compose up -d
sudo docker compose ps        # debe quedar «healthy» al cabo de un minuto
```

Comprueba que ha quedado como debe. Todo esto está verificado contra un Redis
real con esta misma configuración:

```bash
# Sin credenciales: fuera
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 PING
#   -> NOAUTH Authentication required.

# El usuario de la aplicación: lo suyo sí, lo demás no
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  --user gea --pass 'LA_CONTRASEÑA' --no-auth-warning SET gea:ping ok
#   -> OK
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  --user gea --pass 'LA_CONTRASEÑA' --no-auth-warning FLUSHALL
#   -> NOPERM ... 'flushall'
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  --user gea --pass 'LA_CONTRASEÑA' --no-auth-warning CONFIG GET maxmemory
#   -> NOPERM ... 'config|get'
```

Resumen de lo que puede cada uno:

| | anónimo | `health` | `gea` |
|---|---|---|---|
| `PING` | NOAUTH | **sí** | sí |
| `GET`/`SET` de `gea:*` | NOAUTH | NOPERM | **sí** |
| Otras claves | NOAUTH | NOPERM | NOPERM |
| `FLUSHDB` (lo usa `clear_cache`) | NOAUTH | NOPERM | **sí** |
| `FLUSHALL`, `CONFIG`, `SHUTDOWN` | NOAUTH | NOPERM | NOPERM |

Como los usuarios viven en `redis.conf`, sobreviven a recrear el contenedor sin
`ACL SAVE` —que además fallaría, porque no hay `aclfile` configurado.

## Paso 5. Cortafuegos — el paso que más se falla

**Docker se salta UFW.** Publicar un puerto con `ports:` inserta reglas de
DNAT que se procesan *antes* que las de UFW, así que `ufw deny` no cierra nada
y el Redis queda abierto a internet aunque el cortafuegos diga lo contrario.
Es el error clásico de este montaje.

Las reglas van en la cadena `DOCKER-USER`, que sí se consulta:

```bash
# Solo la IP de salida de cPanel puede llegar al 6380
sudo iptables -I DOCKER-USER -p tcp --dport 6380 -s 190.90.160.103 -j RETURN
sudo iptables -I DOCKER-USER 2 -p tcp --dport 6380 -j DROP

# Que sobrevivan al reinicio
sudo apt-get install -y iptables-persistent
sudo netfilter-persistent save
```

El orden importa: el `RETURN` de la IP permitida tiene que ir **antes** que el
`DROP`. Compruébalo con `sudo iptables -L DOCKER-USER -n --line-numbers`.

Y aparte, el cortafuegos del proveedor (el panel del VPS) si lo hay: dos capas
no sobran cuando lo que hay detrás es una base de datos.

## Paso 6. Comprobar que está cerrado

Esto no es opcional: es el paso que distingue "creo que está cerrado" de "está
cerrado". **Desde una máquina que no sea cPanel ni el VPS**:

```bash
nc -zv 5.189.155.153 6380     # tiene que dar timeout o rechazo
```

Si contesta, algo de lo anterior no se aplicó. No sigas hasta que dé timeout.

Y desde cPanel, que sí tiene que llegar:

```bash
openssl s_client -connect 5.189.155.153:6380 -CAfile ~/gea-redis-ca.crt </dev/null
```

## Paso 7. El lado de Django

Copia **solo la CA** (`ca.crt`) al servidor de cPanel —nunca `ca.key` ni
`redis.key`— y añade al `.env`:

```
REDIS_URL=rediss://gea:<LA_CLAVE>@redis.sebasmoralesd.com:6380/0?ssl_cert_reqs=required&ssl_ca_certs=/home/<usuario_cpanel>/gea-redis-ca.crt
REDIS_KEY_PREFIX=gea
REDIS_CONNECT_TIMEOUT=3
REDIS_TIMEOUT=3
```

`ssl_cert_reqs=required` **junto con** `ssl_ca_certs` es lo que hace que el TLS
sirva de algo. Comprobado: con la CA la conexión funciona; sin ella, con
verificación estricta, el certificado se rechaza y la aplicación sigue en pie
sin escribir nada.

**Instala la dependencia. En cPanel es `pip`, no `uv`** — uv es solo para el
entorno local; lo que se instala en el servidor es `requirements.txt`, y
`django-redis` ya está ahí:

- Desde el panel: *Setup Python App* → tu aplicación → **Run Pip Install**
  apuntando a `requirements.txt`.
- O por SSH, activando el entorno que el propio panel muestra en esa pantalla:

  ```bash
  source ~/virtualenv/<ruta_de_la_app>/3.11/bin/activate
  pip install -r requirements.txt
  ```

Antes de instalar conviene confirmar que el paquete llegó al fichero, porque
si no está, reinstalar no lo traerá:

```bash
python manage.py check_requirements
```

## Paso 8. Comprobar que la cache funciona de verdad

```bash
python manage.py check_cache
```

También en la consola de operaciones, como **«Cache»**, sin necesidad de SSH.

Esto es lo que hay que ejecutar, y no un `PING` al VPS. La pregunta no es si
Redis está vivo: es si **esta aplicación llega y si los contadores se comparten
entre procesos**. Un Redis impecable al que la aplicación no alcanza deja los
límites exactamente como estaban.

Y no se puede juzgar a ojo, porque `IGNORE_EXCEPTIONS` está puesto a propósito
para que un corte no tumbe el login: **un servidor inalcanzable no da error,
devuelve `None`**. Una cache rota se parece a una cache vacía.

Las tres salidas posibles, todas reproducidas:

**Bien** — es lo que tiene que salir:

```
1. Backend            django_redis.cache.RedisCache
2. Ida y vuelta       Escribe y lee correctamente.
                      Primera operacion: 54 ms (conexion y TLS, una vez por worker)
                      Ya conectado:       1 ms (esto paga cada peticion)
3. Contador (incr)    Cuenta bien: 1, 2.
4. Caducidad          Las claves caducan.
5. Compartida         El otro proceso la ve. La cache es compartida.

La cache funciona y se comparte entre procesos.
```

> **Los dos tiempos no son el mismo gasto, y confundirlos lleva a
> conclusiones equivocadas.** La primera operación incluye abrir el TCP y
> negociar el TLS: eso se paga **una vez por proceso**, porque django-redis
> mantiene un pool y las siguientes reutilizan la conexión. Lo paga cada worker
> nuevo, y en cPanel los workers se reciclan, así que no es gratis — pero no es
> lo que cuesta atender una petición.
>
> El segundo número sí. Con la conexión ya abierta, el tiempo de una operación
> es básicamente la ida y vuelta por la red, así que **mide la distancia
> física** entre el servidor web y el Redis. Si sale alto no se arregla
> configurando: se arregla acercándolos. Por encima de 200 ms el comando avisa,
> porque con `ATOMIC_REQUESTS` cada uno de esos milisegundos se paga con una
> transacción abierta.

**Sin `REDIS_URL`** — funciona, pero es por proceso:

```
1. Backend            django.core.cache.backends.locmem.LocMemCache
5. Compartida         El otro proceso NO la vio (leyó 'None').

LocMemCache: la cache funciona pero es POR PROCESO.
```

**Configurado pero inalcanzable** — el caso que `IGNORE_EXCEPTIONS` esconde y
que hay que saber leer:

```
2. Ida y vuelta       Se escribió y volvió None. Con IGNORE_EXCEPTIONS un
                      servidor inalcanzable devuelve None sin lanzar.

La cache NO responde. El sitio sigue en pie pero los límites no se aplican.
```

Si sale esa tercera, mira en este orden: que el contenedor esté arriba, que la
regla del paso 5 lleve la IP correcta, y que `REDIS_URL` tenga la contraseña y
la ruta de la CA bien.

La prueba que decide es la quinta, y es la que justifica todo el montaje:
escribe una clave y la lee **desde otro proceso**. Con Redis se ve; con
`LocMemCache` no. Esa diferencia es justo la que separa un límite de tasa real
de uno que se esquiva abriendo otra pestaña hasta que responda otro worker.

Después, `manage.py clear_cache` sigue funcionando igual, y la consola de
operaciones lo tiene en su lista blanca.

---

## Paso 9. El broker de la cola de tareas (solo si se monta Celery)

Este paso **no hace falta para la cache**. Se hace el día que se saque de la
petición el trabajo lento —la traducción por OpenAI dentro de una señal
`pre_save`, los PDF, el envío de correo, el anclaje— y se necesite una cola.

Lo que hay que entender antes de tocar nada: **el usuario `gea` no vale**. Está
acotado a `~gea:*` y a `+@read +@write +@keyspace`, y un broker necesita otras
claves y otros comandos. Con esas credenciales responde `NOPERM` a las cinco
operaciones que un broker hace:

| Operación | Para qué | Qué le falta al usuario `gea` |
|---|---|---|
| `PING` | saber si el servidor sigue ahí | `@connection` |
| `LPUSH celery` | encolar el trabajo | los nombres de clave: `celery`, `_kombu.binding.*`, `unacked` |
| `BRPOP` | repartirlo entre workers | ídem |
| `PUBLISH` | resultados y control de los workers | `@pubsub` |
| `MULTI`/`EXEC` | no perder un mensaje a medio repartir | `@transaction` |

> **El síntoma de dejarlo a medias es de los peores**: el Redis responde, la
> cache va perfecta, y las tareas desaparecen sin ruido. Por eso
> `check_workers` prueba comando a comando en vez de dar por bueno que «Redis
> funciona».

### 9.1 Otra contraseña

Otra, no la de la cache. Si un día se filtra la del worker, no debe abrir
también los contadores de límite.

```bash
openssl rand -base64 36                       # la contraseña; guárdala
printf '%s' 'LA_CONTRASEÑA_DEL_BROKER' | sha256sum
```

### 9.2 El usuario, en `redis.conf`

Va junto a los otros tres, por la misma razón que ellos: `ACL SETUSER` desde
fuera no persiste sin `aclfile`, y los usuarios creados a mano desaparecerían
al recrear el contenedor.

```conf
user broker on #PEGA_AQUI_EL_OTRO_SHA256 ~celery* ~_kombu* ~unacked* &* +@all -@dangerous -@admin
```

Cada trozo de esa línea está ahí por algo:

| Trozo | Por qué |
|---|---|
| `~celery*` | la cola (`celery`), el buzón de control (`celery.pidbox`) y los resultados (`celery-task-meta-*`) |
| `~_kombu*` | los enlaces que kombu mantiene (`_kombu.binding.*`) |
| `~unacked*` | los mensajes repartidos y aún sin confirmar (`unacked`, `unacked_index`, `unacked_mutex`) |
| `&*` | los canales de pub/sub. No son almacenamiento: por ahí no se lee ni se borra nada |
| `+@all -@dangerous -@admin` | todo lo que necesita, menos `FLUSHALL`, `CONFIG`, `SHUTDOWN` y compañía |

> ⚠️ **No pongas `~*`, y la base de datos aparte no te salva de ello.** Es un
> error que ya se cometió en este documento. **Las ACL de Redis no se acotan
> por base de datos**: un usuario con `~*` que se conecte a la base 0 lee y
> borra las claves `gea:*` tan tranquilo — entre ellas los contadores de
> intentos de acceso. Quien aísla es el patrón de claves; la base aparte es
> orden, no control. `check_workers` lo comprueba expresamente.

Recrea el contenedor para que lo tome:

```bash
cd /opt/gea-redis && sudo docker compose up -d --force-recreate
```

### 9.3 Comprobarlo desde el propio VPS

```bash
# Lo suyo, sí
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  --user broker --pass 'LA_CONTRASEÑA_DEL_BROKER' --no-auth-warning -n 1 \
  LPUSH celery x
#   -> 1

# La cache, no
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  --user broker --pass 'LA_CONTRASEÑA_DEL_BROKER' --no-auth-warning \
  GET gea:loquesea
#   -> NOPERM ... keys
```

Esa segunda es la que importa y la que más se olvida.

### 9.4 El lado de Django

Al `.env` de cPanel, **además** de `REDIS_URL` y sin sustituirla. Fíjate en las
dos diferencias: el usuario y la base de datos (`/1`, no `/0`).

```
CELERY_BROKER_URL=rediss://broker:<LA_CONTRASEÑA_DEL_BROKER>@redis.sebasmoralesd.com:6380/1?ssl_cert_reqs=required&ssl_ca_certs=/home/<usuario_cpanel>/gea-redis-ca.crt
```

Y se comprueba con:

```bash
python manage.py check_workers
```

También en la consola de operaciones, como **«Background workers»**. Sin
`CELERY_BROKER_URL` puesta el comando lo dice y no da nada por malo: mientras
no haya cola, no hay nada roto.

---

## Qué pasa cuando Redis se cae

Está resuelto y comprobado, porque con el Redis en otra máquina un corte de red
es cuestión de tiempo. `settings.py` usa `django-redis` con
`IGNORE_EXCEPTIONS = True`, y eso reparte las consecuencias así:

| Función | Con Redis caído |
|---|---|
| Login, panel, wizard de órdenes | **Siguen funcionando.** No dependen de cache |
| Contadores de tasa (OTP, recuperación) | Dejan de aplicarse mientras dure — igual que hoy con LocMemCache por worker |
| Código de registro de compradores | Deja de validar: **falla cerrado**, nadie se registra con un código inventado |

Lo verifiqué apagando el Redis a mitad de la suite: ninguna página da error 500,
solo dejan de contar los límites. Sin `IGNORE_EXCEPTIONS`, ese mismo corte
convertiría el login y la recuperación de contraseña en errores 500.

El fallo se registra en el log (`DJANGO_REDIS_LOG_IGNORED_EXCEPTIONS`), así que
un Redis caído se ve en `stderr.log` en vez de pasar inadvertido.

## Operación

```bash
# Estado
sudo docker compose -f /opt/gea-redis/compose.yaml ps
sudo docker logs --tail 50 gea-redis

# Cuántas claves y cuánta memoria
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 INFO memory | grep used_memory_human
sudo docker exec gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 DBSIZE

# Actualizar la imagen
cd /opt/gea-redis && sudo docker compose pull && sudo docker compose up -d
```

**Rotar la contraseña.** Como el usuario vive en `redis.conf`, se cambia el
hash del fichero y se recrea el contenedor:

```bash
printf '%s' 'LA_NUEVA' | sha256sum          # el hash nuevo
sudo nano /opt/gea-redis/redis.conf         # sustituye el de «user gea»
cd /opt/gea-redis && sudo docker compose up -d --force-recreate
```

Después, `REDIS_URL` en el `.env` de cPanel. En ese orden y con minutos de
margen: en medio los límites dejan de aplicarse, pero no se cae nada.

**Volver atrás**: quita `REDIS_URL` del `.env` y reinicia. Django vuelve a
`LocMemCache` sin tocar código. Es la salida de emergencia si el VPS da
problemas.

---

## Dos notas

**Certificados de cliente (mTLS).** El montaje de arriba autentica al servidor,
no al cliente; a este lo autentica la contraseña. Si quieres la vuelta también,
pon `tls-auth-clients yes`, emite un certificado de cliente con la misma CA y
añade `ssl_certfile` y `ssl_keyfile` a la URL. Es la siguiente vuelta de tuerca
si algún día el dato en cache deja de ser solo contadores.

**Licencia.** Redis dejó de ser BSD en 2024 (RSALv2/SSPL, y AGPL desde Redis 8).
Para uso interno como cache no genera obligaciones —no estás distribuyendo el
software—, pero si prefieres BSD, **Valkey** es el fork de la Linux Foundation y
es compatible: cambia la imagen por `valkey/valkey:8-alpine` y el resto del
documento vale igual.
