# Sacar el trabajo lento de la petición: qué haría falta y qué hay hoy

Documento de decisión sobre adoptar Celery (o cualquier cola) en GEA. La
conclusión corta está en el §6; lo de antes es lo que la sostiene.

**Estado: sin decidir.** Falta una medición que solo se puede hacer en el
servidor de producción, y este documento explica cómo hacerla.

---

## 1. Qué bloquea hoy

Con `ATOMIC_REQUESTS = True` cada petición es una transacción. Lo que tarda no
solo hace esperar al usuario: mantiene abierta una transacción de base de datos
mientras espera.

| Qué | Dónde | Cuánto |
|---|---|---|
| Traducción es↔en por OpenAI | `assets/signals.py`, señal `pre_save` | hasta 20 s (timeout) |
| Traducción de ofertas | `buyers/signals.py` | ídem |
| Generación de PDF de orden | `buyers/functions/generate_*.py` | segundos |
| Envío de correo | orden de servicio, recuperación de contraseña | segundos, y depende del SMTP |
| Certificación de un PDF | `code_gen/services/certification.py` | segundos |
| Anclaje en OpenTimestamps | `code_gen/services/anchoring.py` | ya está degradado a aviso |

El peor es el primero: **una llamada de red a un tercero dentro de un
`pre_save`**. Si OpenAI va lento, guardar un activo tarda 20 segundos con una
transacción abierta. No hay cola de tareas: eso es hoy el diseño.

---

## 2. Qué es un worker, y por qué no es una decisión de librería

Un worker no es un paquete que se instala. Es **un proceso que vive fuera de la
petición y no se muere**. Instalar Celery es lo fácil y lo barato; sostener el
proceso es lo que decide.

Hacen falta cuatro cosas, y las cuatro tienen que salir:

1. La librería instalada — se arregla con `pip`.
2. Un **broker** donde dejar los mensajes — el Redis.
3. Sitio para otro proceso dentro del límite del hosting.
4. Que ese proceso **sobreviva**. La de verdad.

`manage.py check_workers` (consola de operaciones → «Workers en segundo plano»)
comprueba las cuatro. No propone nada: mide.

---

## 3. El Redis actual NO sirve de broker

Esto ya está verificado, y es contraintuitivo: **el Redis funciona como cache y
rechazaría un broker**. La ACL de [`deploy/REDIS.md`](../deploy/REDIS.md) está
escrita para la cache:

```
user gea on #<hash> ~gea:* +@read +@write +@keyspace -@dangerous +flushdb
```

Un broker de Celery necesita otras cosas. Probado contra un Redis real con esa
misma ACL, las cinco responden `NOPERM`:

| Operación | Para qué | Por qué falla |
|---|---|---|
| `LPUSH celery` | la cola de trabajo | las claves están limitadas a `~gea:*`, y el broker usa las suyas (`celery`, `_kombu.binding.*`, `unacked`) |
| `BRPOP` | repartir entre workers | ídem |
| `PING` | saber si el servidor sigue ahí | no se concede `@connection` |
| `PUBLISH` | resultados y control de workers | no se concede `@pubsub` |
| `MULTI/EXEC` | no perder un mensaje a medio repartir | no se concede `@transaction` |

> **El síntoma sería de los peores**: el Redis responde, la cache va bien, y
> las tareas desaparecerían sin ruido. Por eso `check_workers` prueba comando a
> comando en vez de dar por bueno que «Redis funciona».

**Cómo se abre, sin tocar la cache.** Un usuario aparte, limitado a los
nombres de clave que Celery usa de verdad. El procedimiento completo —con la
contraseña, la base de datos y las comprobaciones— está en
[`deploy/REDIS.md`](../deploy/REDIS.md), **paso 9**:

```
# En redis.conf, junto a los otros usuarios. La contraseña es otra.
user broker on #<sha256 de otra contraseña> ~celery* ~_kombu* ~unacked* &* +@all -@dangerous -@admin
```

Y apuntándolo a otra base de datos que la cache, por orden:

```
CELERY_BROKER_URL=rediss://broker:<clave>@redis.sebasmoralesd.com:6380/1?...
```

> **Esa variable es la que `check_workers` mira.** No es un detalle de
> despliegue: el comando prueba el broker **con las credenciales del broker**,
> y sin ella no tiene nada que probar. Durante un tiempo probaba con la
> conexión de la cache —el usuario `gea`, en la base 0—, así que decía «0 de 5»
> y mandaba a arreglar la ACL… incluso con la ACL ya bien puesta. Una
> comprobación que no puede dar verde no mide nada.

Verificado contra un Redis real con esa ACL: las cinco operaciones que fallaban
pasan —`PING`, `LPUSH`/`BRPOP` sobre `celery`, `PUBLISH`, `MULTI`, y las claves
`unacked`, `_kombu.binding.*` y `celery-task-meta-*`— mientras `FLUSHALL` y
`CONFIG` siguen denegados.

> **Una corrección, porque este documento decía otra cosa.** La primera versión
> daba `~*` (todas las claves) y afirmaba que la separación en otra base de
> datos impedía que el broker tocara la cache. **Es falso, y está comprobado:**
> las ACL de Redis no se acotan por base de datos, así que un usuario con `~*`
> que se conecte a la base 0 lee y borra las claves `gea:*` sin problema.
>
> Con los tres patrones de arriba sí queda fuera: `GET gea:secreto` responde
> `NOPERM`. La base de datos aparte sigue siendo buena idea por orden y por si
> alguien ejecuta un `FLUSHDB`, pero **quien aísla es el patrón de claves**.

---

## 4. La pregunta abierta: ¿aguanta cPanel un proceso?

Es la que no se puede contestar desde aquí, porque depende de límites que el
proveedor no publica. Lo que se sabe del terreno:

- cPanel compartido con **Passenger** arranca la aplicación web bajo demanda.
  Un worker no lo gestiona Passenger: nadie lo levanta si se cae.
- La mayoría de estos hostings corren **CloudLinux/LVE**, que limita procesos y
  memoria por cuenta y **mata lo que se pase**, sin avisar.
- Muchos proveedores prohíben demonios persistentes en sus condiciones, con
  independencia de que técnicamente arranquen.
- No hay `systemd` ni `supervisor` para un usuario normal. Lo más parecido es
  un cron `@reboot` o un cron que compruebe y relance.

Nada de eso es una respuesta: es el motivo para medir. La medición:

```bash
manage.py check_workers --spawn     # lanza un proceso desprendido
# ... media hora después ...
manage.py check_workers             # dice cuánto sobrevivió
```

También desde la consola de operaciones, sin SSH. El proceso de prueba no hace
nada salvo escribir la hora cada 30 segundos: si desaparece, es que lo mataron.

**Cómo leer el resultado:**

| Lo que dice | Qué significa |
|---|---|
| «lo mataron de inmediato» | No hay worker posible aquí. Cerrado. |
| «solo duró N minutos» | Peor que no arrancar: parecería funcionar y moriría solo, con las tareas a medias |
| «lo mataron antes de acabar» | Igual de malo, solo que más tarde |
| «aguantó la prueba entera» | Prometedor, **no concluyente**: media hora no son semanas. Déjalo un día antes de fiarle nada |

---

## 5. Las tres salidas

### A. Worker en cPanel

Solo si el §4 sale bien tras un día entero. Ventaja: todo en una máquina, sin
tocar red ni base de datos. Riesgo: el worker se muere en silencio y las tareas
se quedan encoladas sin que nadie se entere. Exige vigilancia propia (un
`heartbeat` en Redis y una alerta).

### B. Worker en el VPS — **la más prometedora**

El VPS ya está montado, ya corre el Redis, y ahí **sí** se pueden tener
procesos: es Docker, con reinicio automático. El reparto sería:

```
cPanel (web)                          VPS (Docker)
  encola la tarea  ──► Redis (broker) ──►  worker Celery
  responde al momento                       ejecuta
                     ◄── resultado  ◄───    escribe el resultado
```

**Por qué funciona, que no es obvio.** El worker nunca habla con la aplicación
web, ni ella con él. Los dos hablan con el broker: la web deja un mensaje en
Redis y el worker lo recoge. No hace falta que se conozcan, ni que estén en la
misma máquina, ni abrir nada nuevo hacia cPanel.

Y el broker no es interno: es un servicio de red desde el primer día. Está en
el VPS, en el 6380 con TLS, y el cortafuegos deja entrar exactamente una IP
—la de cPanel—. Por eso puede servir a los dos lados.

**Para un worker en el VPS es incluso más barato**: alcanza el Redis por la red
de Docker, sin salir a internet. Ni saludo TLS por el cable, ni latencia, ni
una regla de cortafuegos más. La mitad «broker» del problema desaparece.

**Pero el problema se mueve, no se va.** Hoy la distancia la paga la web al
hablar con el Redis, y se paga una vez por worker. Con el worker en el VPS, lo
que queda lejos es lo que el worker más necesita:

- **La base de datos.** MySQL vive en cPanel. Cada consulta del worker cruza
  Colombia↔VPS, y una tarea que haga veinte consultas paga esa ida y vuelta
  veinte veces. No bloquea al usuario —para eso se encoló—, pero las tareas se
  vuelven notablemente más lentas.
- **Los ficheros.** Un worker en el VPS no puede escribir en el disco de
  cPanel. Todo lo que produzca un archivo tiene que subirlo, no guardarlo.
- **El código.** Un despliegue más que mantener sincronizado.

**Qué tarea encaja y cuál no**, con eso en la mano:

| Tarea | Consultas | Ficheros | ¿Encaja en el VPS? |
|---|---|---|---|
| Traducción por OpenAI (hoy 20 s dentro de un `pre_save`) | pocas | no | **Sí.** Es además la que más molesta |
| Envío de correo | pocas | no | **Sí** |
| Anclaje en OpenTimestamps | pocas | no | Sí, aunque ya está resuelto por cron |
| Generación de PDF y certificación | varias | **escribe tres** | **No**, mientras no se resuelvan los ficheros |

O sea: un worker en el VPS resuelve hoy lo que de verdad estorba, y deja fuera
la certificación. Eso no es un impedimento —la certificación se lanza a mano y
nadie la espera de fondo—, pero conviene saberlo antes y no a mitad.

**Lo que hay que comprobar antes de escribir una línea de código.** ¿Alcanza el
VPS la base de datos de cPanel? cPanel tiene «Remote MySQL» para autorizar una
IP, pero muchos hostings compartidos cierran el 3306 hacia fuera de todas
formas. Desde el VPS:

```bash
nc -zv 190.90.160.103 3306        # o el host que diga DB_HOST
```

Si eso no conecta, la opción B se cae entera antes de empezar, y la respuesta
pasa a ser C. Son treinta segundos y ahorran un rediseño.

### C. Quedarse con cron — **lo que ya funciona**

`django-crontab` ya corre en producción (`upgrade_ots_anchors` cada hora, el
código diario, el warm-up). Un cron cada minuto que procese una tabla de
pendientes es una cola: más tosca, con hasta un minuto de retraso, y sin
paralelismo. Pero **no necesita ningún proceso persistente**, que es justo lo
que el hosting puede no permitir.

Para lo que hoy bloquea —traducciones, PDF, correos— un minuto de retraso es
perfectamente aceptable.

---

## 6. Recomendación

Dos mediciones, y ninguna cuesta más de unos minutos. Las dos descartan una
opción entera si salen mal, así que van antes que cualquier código:

| Qué medir | Cómo | Qué descarta si falla |
|---|---|---|
| ¿Sobrevive un proceso en cPanel? | `check_workers --spawn`, y volver a mirar media hora después (§4) | La opción A |
| ¿Alcanza el VPS el MySQL de cPanel? | `nc -zv <DB_HOST> 3306` desde el VPS | La opción B |

Con lo que hoy se sabe, el orden sería:

1. **C (cron) para lo que bloquea ahora.** Resuelve el problema real —sacar
   OpenAI del `pre_save`— sin depender de que el hosting permita nada nuevo, y
   reutiliza lo que ya corre. Es lo más barato y lo menos frágil.
2. **B (worker en el VPS) si hace falta más.** Cuando el minuto de retraso o la
   falta de paralelismo estorben de verdad, asumiendo los costes del §5.B y
   sabiendo que la certificación se queda fuera mientras los ficheros no se
   resuelvan.
3. **A solo si la medición sale bien de sobra**, y aun así con vigilancia:
   CloudLinux mata procesos sin avisar, y un worker que se muere en silencio se
   lleva por delante las tareas que tuviera a medias.

Un matiz que hace que esto no sea una apuesta: **B y C no compiten en el
código.** Las dos necesitan lo mismo —la tabla de tareas, la vista que encola,
el endpoint de estado— y solo cambia quién ejecuta. Empezar por C no cierra la
puerta a B; es el mismo trabajo hecho antes.

Lo que **no** conviene es adoptar Celery para dejarlo apuntando al Redis actual:
no arrancaría, y el motivo (`NOPERM` sobre claves que la cache nunca usa) es de
los que cuesta un día encontrar.

---

## 7. Lo que hace falta en cualquiera de los tres

La forma que pide el encargo —**lanzar, obtener resultado, avisar**— es la
misma con cron, con Celery en cPanel o con Celery en el VPS. Lo que cambia es
quién ejecuta; lo demás se escribe una vez:

1. **Una tabla de tareas**: qué hay que hacer, estado (`pendiente`,
   `ejecutando`, `hecha`, `fallida`), resultado, error, quién la pidió. Sin
   esto no hay nada que consultar ni nada que reintentar.
2. **La vista responde al momento** dejando la tarea encolada, en vez de
   esperar. Es el cambio que quita la transacción larga.
3. **Un endpoint de estado** que el navegador consulte cada pocos segundos.
4. **El aviso**, que tiene que verse esté donde esté el usuario en la página.

El punto 4 ya está resuelto: los avisos son toasts flotantes, visibles con la
página scrolleada hasta el pie. Ver `public/staticfiles/js/toasts.js`.

Los puntos 1 a 3 son el trabajo de verdad, y **no dependen del motor**: escritos
para cron, siguen valiendo si mañana se pone Celery. Esa es otra razón para
empezar por C.
