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

> Lo probado de este documento: la configuración de Django, el `rediss://` con
> CA propia, el rechazo cuando falta la CA, el usuario ACL y el comportamiento
> con Redis caído. Lo no probado aquí, por no haber Docker en el entorno donde
> se redactó: el `compose.yaml` y las reglas de cortafuegos. Sigue el paso 6,
> que es el que lo comprueba desde fuera.

---

## Paso 0. Los datos de esta instalación

| Dato | Valor |
|---|---|
| Aplicación | `geausa.propensionesabogados.com` |
| IP del hosting compartido (estática) | **`190.90.160.103`** |
| Host del Redis | el VPS — **falta elegir nombre** (ver abajo) |

Todo el cortafuegos depende de la IP de cPanel, y es la única que se autoriza.

**Una comprobación de un minuto antes de seguir.** La IP que autoriza el
cortafuegos es la de **salida** —desde la que cPanel abre la conexión—, y en
hosting compartido no siempre coincide con la de entrada. Desde SSH en cPanel o
un cron de la cuenta:

```bash
curl -s https://ifconfig.io
```

Si responde `190.90.160.103`, todo encaja y sigue adelante. Si responde otra
cosa, **esa** es la que hay que autorizar en el paso 5; anótala, porque si no el
cortafuegos bloqueará justamente a la aplicación.

**El nombre del Redis.** El VPS es otra máquina, así que no vale
`geausa.propensionesabogados.com`. Dos opciones:

- Un registro DNS `A` propio, por ejemplo `redis.propensionesabogados.com`
  apuntando al VPS. Es lo recomendable: si algún día cambias de VPS, cambias el
  DNS y no tocas el `.env` de producción.
- La IP del VPS a secas, si prefieres no crear el registro. Funciona igual;
  solo recuerda que el certificado del paso 2 tiene que llevar esa IP en su
  `subjectAltName`.

En el resto del documento aparece como `redis.propensionesabogados.com`.

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
`redis.propensionesabogados.com` por el nombre o la IP con la que se va a conectar cPanel.

```bash
cd /opt/gea-redis/tls

# CA propia, 10 años
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.crt -subj "/CN=GEA Redis CA"

# Certificado del servidor
openssl genrsa -out redis.key 2048
openssl req -new -key redis.key -out redis.csr -subj "/CN=redis.propensionesabogados.com"

printf "subjectAltName=DNS:redis.propensionesabogados.com,IP:<IP_DEL_VPS>\nextendedKeyUsage=serverAuth\n" > ext.cnf

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
      test: ["CMD", "redis-cli", "--tls", "--cacert", "/tls/ca.crt",
             "-p", "6380", "ping"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Arranca y crea el usuario de la aplicación:

```bash
cd /opt/gea-redis
sudo docker compose up -d

# Contraseña larga y aleatoria; guárdala, no se puede recuperar
openssl rand -base64 36

sudo docker exec -it gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  ACL SETUSER gea on '><LA_CLAVE_GENERADA>' '~gea:*' \
  '+@read' '+@write' '+@keyspace' '-@dangerous'

sudo docker exec -it gea-redis redis-cli --tls --cacert /tls/ca.crt -p 6380 \
  ACL SAVE
```

Ese usuario puede leer y escribir **solo** claves que empiecen por `gea:` —el
prefijo que pone Django—, y no puede `FLUSHALL`, ni `CONFIG`, ni `SHUTDOWN`.
Comprobado:

```
FLUSHALL            -> NOPERM this user has no permissions to run 'flushall'
CONFIG GET maxmemory-> NOPERM this user has no permissions to run 'config|get'
GET gea:...         -> funciona
```

> `ACL SAVE` necesita un `aclfile` configurado para persistir. Si no lo añades,
> el usuario se pierde al recrear el contenedor: o bien declaras
> `aclfile /usr/local/etc/redis/users.acl` en `redis.conf` y montas ese
> fichero, o bien dejas el `user gea ...` escrito directamente en `redis.conf`.
> La segunda opción es más simple y es la que recomiendo.

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
nc -zv <IP_DEL_VPS> 6380     # tiene que dar timeout o rechazo
```

Si contesta, algo de lo anterior no se aplicó. No sigas hasta que dé timeout.

Y desde cPanel, que sí tiene que llegar:

```bash
openssl s_client -connect <IP_DEL_VPS>:6380 -CAfile ~/gea-redis-ca.crt </dev/null
```

## Paso 7. El lado de Django

Copia **solo la CA** (`ca.crt`) al servidor de cPanel —nunca `ca.key` ni
`redis.key`— y añade al `.env`:

```
REDIS_URL=rediss://gea:<LA_CLAVE>@redis.propensionesabogados.com:6380/0?ssl_cert_reqs=required&ssl_ca_certs=/home/<usuario_cpanel>/gea-redis-ca.crt
REDIS_KEY_PREFIX=gea
REDIS_CONNECT_TIMEOUT=3
REDIS_TIMEOUT=3
```

`ssl_cert_reqs=required` **junto con** `ssl_ca_certs` es lo que hace que el TLS
sirva de algo. Comprobado: con la CA la conexión funciona; sin ella, con
verificación estricta, el certificado se rechaza y la aplicación sigue en pie
sin escribir nada.

Instala la dependencia y comprueba:

```bash
uv sync
uv run python manage.py shell -c "from django.core.cache import cache; cache.set('gea:ping', 'ok', 30); print(cache.get('gea:ping'))"
```

Debe imprimir `ok`. Después, `manage.py clear_cache` sigue funcionando igual, y
la consola de operaciones lo tiene en su lista blanca.

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

**Rotar la contraseña**: `ACL SETUSER gea on '>nueva'` en el contenedor y
`REDIS_URL` en el `.env` de cPanel. Hazlo en ese orden y en minutos de margen:
entre una cosa y la otra los límites dejan de aplicarse, no se cae nada.

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
