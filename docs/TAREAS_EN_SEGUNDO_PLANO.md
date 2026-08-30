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

**Cómo se abriría, sin tocar la cache.** Un usuario aparte y una base de datos
aparte, para que el broker no pueda ni leer ni borrar las claves de la cache:

```
# En redis.conf, junto a los otros usuarios. La contraseña es otra.
user broker on #<sha256 de otra contraseña> ~* &* +@all -@dangerous -@admin
```

Y el broker apuntando a otra base de datos que la cache:

```
CELERY_BROKER_URL=rediss://broker:<clave>@redis.sebasmoralesd.com:6380/1?...
```

`~*` y `&*` (todas las claves, todos los canales) son necesarios: Celery no
deja elegir los nombres de sus claves internas. Se compensa aislándolo en su
propia base de datos y quitándole `@admin`.

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

Lo que hay que resolver antes de decidirla:

- El worker necesita **el código de la aplicación** en el VPS: un despliegue
  más que mantener sincronizado con cPanel.
- Necesita **acceso a la base de datos** de cPanel (Remote MySQL, con la IP del
  VPS en la lista blanca). Eso mete la latencia Colombia↔VPS en cada consulta
  del worker — que no bloquea al usuario, pero hace las tareas más lentas.
- Los ficheros: si una tarea genera un PDF, tiene que llegar al `MEDIA_ROOT` de
  cPanel. Habría que subirlo, no escribirlo directamente.

Ninguno es insalvable. Los tres son trabajo real, y conviene contarlos antes de
empezar y no a mitad.

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

**Primero medir** (§4), porque descarta o abre la opción A sin discusión.

Con lo que hoy se sabe, el orden sería:

1. **C (cron) para lo que bloquea ahora.** Resuelve el problema real —sacar
   OpenAI del `pre_save`— sin depender de que el hosting permita nada nuevo, y
   reutiliza lo que ya corre. Es lo más barato y lo menos frágil.
2. **B (worker en el VPS) si hace falta más.** Cuando el minuto de retraso o la
   falta de paralelismo estorben de verdad, y asumiendo los tres costes del §5.B.
3. **A solo si la medición sale bien de sobra**, y aun así con vigilancia.

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
