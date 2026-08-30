# Anclaje en la cadena de bloques: qué pasa, cuándo, y dónde se mira

Documento de referencia para entender el anclaje temporal de GEA sin haber
escrito el código. Responde a las preguntas que se hacen al ver «enviado» en
pantalla y no saber qué hacer con eso.

Complementa a [`NORMATIVA.md`](NORMATIVA.md), que trata de qué valor legal
tiene esto; aquí se trata de cómo funciona.

---

## 1. Qué se está probando, exactamente

Un anclaje prueba **una sola cosa**: que un dato concreto ya existía en una
fecha. Ni que sea cierto, ni que lo firmara quien dice, ni que nadie lo haya
copiado. Solo que *ya existía*.

Ese dato es el **master hash** de una caja AEGIS: 64 caracteres que resumen a
todos sus miembros. No sale de la plataforma ni el documento, ni el payload, ni
un nombre. Sube el hash y nada más, así que anclar no publica información de
nadie: quien vea la cadena de bloques ve una cifra que no significa nada sin el
documento original.

Y por la misma razón, **el anclaje no puede recuperar nada**. No es una copia
de seguridad. Si se pierde el documento, el hash anclado no lo devuelve: sirve
para comprobar uno que ya se tiene.

---

## 2. Por qué es gratis, y por qué eso implica esperar

Anclar en Bitcoin de forma directa costaría una transacción por documento.
OpenTimestamps evita ese coste con un reparto: unos servidores públicos —los
**calendarios**— recogen miles de hashes de todo el mundo, los juntan en un
árbol y publican **una sola** transacción con la raíz. Tu hash queda probado
por el camino que va desde él hasta esa raíz.

Es gratis porque el coste se reparte entre miles. Y de ahí sale la
característica que más confunde: **hay que esperar al siguiente lote.**

```
tú envías un hash  ──┐
otro envía el suyo ──┼──► el calendario junta miles ──► 1 transacción
mil personas más   ──┘        (cada hora larga)        en Bitcoin
                                                            │
                                                    y luego un bloque
                                                    la confirma
```

No hay cartera, ni dinero, ni claves que custodiar. Lo que hay es una espera.

---

## 3. Los dos tiempos

Esta es la parte que hay que tener clara, porque todo lo demás se deduce de
ella.

### Momento 1 — al sellar y enviar: **compromiso, sin bloque**

El calendario responde **al instante** con una promesa firmada: «me comprometo
a incluir este hash en mi próximo árbol». Eso es una `PendingAttestation`, y es
lo que se guarda en `CertificationAnchorModel.proof` con estado `PENDING`.

Ya hay algo real: el calendario se ha comprometido. Lo que todavía no hay es
bloque de Bitcoin, así que **todavía no acredita una fecha frente a nadie**.

### Momento 2 — entre 1 y 6 horas después: **el bloque**

El calendario publica su transacción, entra en un bloque, y a partir de ahí
puede entregar el camino completo desde tu hash hasta la cabecera de ese
bloque. Entonces la prueba **madura**: pasa a `CONFIRMED` y ya acredita fecha
contra la cadena de bloques, sin depender de la plataforma ni del calendario.

> **Nadie avisa cuando eso ocurre.** No hay correo, ni webhook, ni un enlace
> que llegue después. OpenTimestamps no tiene forma de contactar contigo:
> nunca supo quién eras. La única manera de enterarse es **volver a
> preguntar** con la prueba en la mano.

De ahí salen dos decisiones de diseño que si no, parecen arbitrarias:

- **Certificar no espera.** Bloquear una petición seis horas es imposible, y
  con `ATOMIC_REQUESTS` sería una transacción abierta seis horas.
- **El QR impreso lleva una URL, no la prueba.** Si el PDF llevara el número de
  bloque impreso habría que reestampar el papel cuando madurase. Con la URL, el
  papel se emite una vez y la página se actualiza sola.

---

## 4. Quién madura las pruebas

Nadie lo hace solo. Lo hace un cron, cada hora, en el minuto 15:

```python
# app_core/settings.py
('15 * * * *', 'django.core.management.call_command', ['upgrade_ots_anchors']),
```

`upgrade_ots_anchors` recorre los anclajes en `PENDING`, le pregunta a su
calendario si ya hay camino hasta un bloque, y al que lo tiene le guarda la
prueba completa y lo pasa a `CONFIRMED`. Que uno todavía no esté listo **no es
un error**: se deja para la vuelta siguiente.

**Si ese cron no corre, los anclajes se quedan pendientes para siempre.** El
envío habrá salido bien y la prueba estará guardada, pero nadie la completa. Es
el fallo más fácil de confundir con «el envío no funcionó», y son cosas
distintas: el envío ya ocurrió.

Para ejecutarlo a mano y ponerse al día:

```bash
manage.py upgrade_ots_anchors
```

---

## 5. Dónde se mira el estado

### La página de anclaje — lo que ve cualquiera

Es el destino del QR del resumen, es pública y no pide OTP:

```
https://geausa.propensionesabogados.com/verify/aegis/summary/<uuid>/anchor/
```

Se actualiza sola. Mientras la prueba está pendiente lo dice; cuando madura
muestra el bloque. Esta es la respuesta a «dónde envío a alguien a comprobarlo».

### La consola de operaciones — para diagnosticar

En el admin, **Operaciones → Anclaje en cadena de bloques**
(`manage.py check_anchoring`). Sin marcar nada comprueba tres cosas:

1. Que la librería `opentimestamps` esté instalada.
2. Que el hosting deje salir hacia los calendarios.
3. **Cómo van los anclajes reales**: cuántos confirmados, cuántos esperando, y
   cuánto lleva esperando el más antiguo. Si ese número pasa de un día, avisa
   de que el problema es el cron del punto 4, no el envío.

### El admin — el detalle de uno

`Certification anchor` guarda por cada anclaje el hash anclado, el estado, el
proveedor, la prueba y, cuando confirma, el número de bloque en `serial`.

### Un explorador de bloques — sin depender de nosotros

Con el número de bloque, cualquiera lo comprueba por su cuenta:

```
https://blockstream.info/block-height/<numero>
```

Eso es lo que hace que la prueba valga: no hay que fiarse de la plataforma.

---

## 6. El envío de prueba, y cómo comprobarlo

`check_anchoring --stamp` manda un hash **inventado**, que no pertenece a
ningún documento, para probar el camino de salida entero. Es inofensivo.

Antes se quedaba a medias: decía «aceptado» y tiraba la prueba, así que no
había dónde volver a mirar — y «aceptado» solo significa que hubo compromiso,
que es el Momento 1 del punto 3. Ahora la guarda en
`MEDIA_ROOT/ots_selftest/` y se puede retomar.

Ese directorio se crea solo, y al crearse se cierra al web con un `.htaccess`
de denegación: cuelga de `MEDIA_ROOT`, donde el servidor sirve por defecto y
solo se bloquean tres subdirectorios por nombre. Lo que guarda no es sensible
—pruebas de hashes inventados—, pero un directorio que aparece solo no puede
depender de que alguien lo añada al script de despliegue.

**Al enviar:**

```
4. Envio de prueba
   hash de prueba: 0f997c0ec631d300c4e7d561f85c94401e79cd7ccdb122a105eb10c2b5d81d56
   Aceptado por 3 calendario(s); prueba de 635 bytes.
      https://alice.btc.calendar.opentimestamps.org
      https://bob.btc.calendar.opentimestamps.org
      https://finney.calendar.eternitywall.com
   Prueba guardada en /home/.../media/ots_selftest/20260830-233433-0f997c0e.ots
   Todavia sin bloque. El compromiso existe: estos calendarios se han
   comprometido a incluirlo.
      https://alice.btc.calendar.opentimestamps.org

   Que esperar: entre 1 y 6 horas. Nadie avisa cuando pase -- OpenTimestamps
   no manda correos ni devuelve ningun enlace despues. Hay que volver a
   preguntar:
      manage.py check_anchoring --verify
```

**Unas horas después**, `check_anchoring --verify` (o la casilla «Comprobar el
último envío» en la consola):

```
5. Comprobacion del ultimo envio de prueba
   Enviado hace 4.2 horas: 20260830-233433-0f997c0e.ots
   hash: 0f997c0ec631d300c4e7d561f85c94401e79cd7ccdb122a105eb10c2b5d81d56
   Confirmado en el bloque de Bitcoin 912345.
   Se comprueba en cualquier explorador de bloques, sin depender de esta
   plataforma:
      https://blockstream.info/block-height/912345
```

Si todavía no ha madurado lo dice y no lo presenta como avería, que es lo
normal las primeras horas. Solo avisa cuando pasa de un día.

---

## 7. Qué significa cada estado

| Lo que se ve | Qué pasó | Qué hacer |
|---|---|---|
| «Sellado, pero el envío falló» | El sello sí se guardó. La salida a los calendarios no funcionó | `check_anchoring`: o falta la librería (pip desde `requirements.txt`) o el hosting bloquea la salida |
| `PENDING`, unas horas | Compromiso hecho, sin bloque todavía | Esperar. Es el estado normal |
| `PENDING`, días | El envío salió bien, pero nadie madura la prueba | Comprobar que el cron `upgrade_ots_anchors` corre; ejecutarlo a mano |
| `CONFIRMED` con bloque | La fecha está probada contra Bitcoin | Nada. La página de anclaje ya lo muestra |
| «El anclaje es válido, pero cubre un master hash anterior» | La caja se volvió a sellar después de anclarse | Volver a anclar: el anclaje viejo sigue siendo cierto, pero de la caja de entonces |

---

## 8. Las dos vías, y por qué hay dos

Una caja puede llevar dos anclajes a la vez, y cubren fallos distintos.

| | **TSA (RFC 3161)** | **OpenTimestamps (Bitcoin)** |
|---|---|---|
| Cuándo vale | Al instante | Entre 1 y 6 horas |
| Coste | De pago, si es cualificada | Gratis |
| En quién se confía | En la autoridad y su certificado | En nadie: en la cadena |
| Aguante | Hasta que ese certificado caduque o la autoridad cierre | Mientras exista Bitcoin |
| Ante un tribunal, hoy | El instrumento que se reconoce | Aún poco frecuente |

La TSA es lo que un tribunal admite hoy sin discusión. Bitcoin es lo que
seguirá en pie dentro de veinte años, cuando el certificado de esa TSA haya
caducado y quizá la empresa ya no exista. Por eso no compiten: se ponen las
dos.

Ver [`NORMATIVA.md`](NORMATIVA.md) sobre qué falta para que la vía TSA sea
plenamente cualificada.

---

## 9. Dónde está el código

| Pieza | Fichero |
|---|---|
| Envío, lectura y maduración de una prueba | `code_gen/services/ots.py` |
| Fachada: crear anclajes, madurar, verificar | `code_gen/services/anchoring.py` |
| Sellado de tiempo por TSA | `code_gen/services/tsa.py` |
| Master hash de la caja | `code_gen/services/master.py` |
| Guardado del anclaje | `code_gen/models.py::CertificationAnchorModel` |
| Cron horario | `upgrade_ots_anchors` (en `settings.CRONJOBS`) |
| Diagnóstico | `check_anchoring` (consola de operaciones) |
| Página pública | `certificates:summary_anchor` |
