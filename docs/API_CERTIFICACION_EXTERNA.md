# API de certificación externa

Guía para quien integra una plataforma con GEA y para el operador que da de alta
a cada emisor. Se entrega tal cual a las empresas del grupo (por ejemplo
*fundacionattlas*, *tracecertificates*, *procesodeinsolvencia*) y a terceros
(por ejemplo *recovery repatriation*): el servicio es el mismo para todos y no
tiene coste; lo que cambia de uno a otro son sus parámetros (clave, cupos, hosts
del QR, logo, tipo de certificado), que el operador fija en el admin.

Referencias para quien desarrolla GEA: [`SEGURIDAD.md`](SEGURIDAD.md) («Emisores
externos»), `apps/project/specific/documents/certificates/external.py` y el modelo
`ExternalIssuerModel`.

---

## 1. Qué es y qué acredita

Una plataforma manda a GEA un PDF **sin códigos** junto con el texto de un QR, el
texto de un código de barras y el lugar de la página donde ponerlos. GEA estampa
los dos símbolos, calcula las huellas, guarda el conjunto y devuelve:

- un **código público** y una **URL de verificación** que cualquiera puede abrir;
- la **huella** del original y de la copia distribuible;
- una **copia distribuible** del PDF, idéntica a la vista y con una marca de agua
  oculta, que el emisor descarga cuando la necesita.

**Qué acredita: integridad, no veracidad.** La certificación prueba que el archivo
que alguien tiene en la mano es, byte a byte, el que se registró en esa fecha, y
que cualquier alteración posterior se puede detectar. **No prueba que lo que el
documento afirma sea cierto**: GEA registra lo que el emisor le manda, no responde
por ello. Ningún texto que el emisor muestre a sus clientes debe sugerir lo
contrario. (Es el límite que la propia página de verificación escribe en
`scope.does_not_attest` del registro de certificación.)

La página pública de cada documento dice **«Emitido por <nombre del emisor>»**,
para que quien verifica sepa qué entidad lo emitió.

---

## 2. Autenticación

Cada petición lleva dos cabeceras:

| Cabecera | Valor |
|---|---|
| `X-Issuer` | El *slug* del emisor, que le da el operador (`fundacionattlas`). También vale el campo `issuer` del formulario en el `POST` de emisión. |
| `X-Issuer-Key` | La clave del emisor. |

**Cómo se entrega la clave.** El operador la genera en el admin y la ve **una sola
vez**, en pantalla. GEA guarda solo un hash: no puede recuperarla ni volver a
mostrarla, solo sustituirla por otra. Se entrega por un canal que no sea el
correo en claro (gestor de secretos, mensajería cifrada) y se guarda **en el
servidor** de la plataforma emisora, en una variable de entorno: nunca en el
navegador, en una app móvil, en el repositorio ni en la URL. Quien tenga la clave
emite documentos con el sello de GEA.

- La clave tiene al menos 32 caracteres. Cambiarla (rotarla) invalida la anterior
  en el acto: coordina el cambio con el operador para no recibir 403 en medio.
- **Cualquier fallo de autenticación da el mismo 403** (clave mala, emisor que no
  existe, emisor desactivado o sin clave): el cuerpo no distingue cuál fue.
- Los intentos con credenciales malas se cuentan por dirección IP; pasado un
  número, esa IP recibe 429.
- La API no usa cookies ni CSRF: no la llames desde un navegador.

---

## 3. Los tres endpoints

Base: `https://geausa.propensionesabogados.com`. Respuestas siempre en JSON con
`Cache-Control: no-store` (salvo la descarga del PDF).

### 3.1 Certificar — `POST /api/certificates/external/`

`multipart/form-data`. Todos los campos son obligatorios.

| Campo | Qué es |
|---|---|
| `source` | El PDF (`.pdf`, empieza por `%PDF`, hasta 60 MB). |
| `title` | Título del documento. Hasta 200 caracteres, sin saltos de línea. |
| `reference` | Identificador del caso o registro en la plataforma emisora. Hasta 200. |
| `idempotency_key` | Clave de idempotencia (ver §5). Hasta 128. |
| `qr_payload` | Lo que lleva el QR: una URL `https` (hasta 1000 caracteres, sin espacios). Si el emisor tiene lista de hosts permitidos, el host de la URL tiene que ser uno de ellos. |
| `barcode_text` | Lo que lleva el código de barras (Code128): hasta 80 caracteres entre letras sin acentos, dígitos, espacio y `. _ -`. **Nunca una URL**: lo que no encaje va en el QR. |
| `placement` | JSON con la posición de los dos símbolos (abajo). |
| `issuer` | (opcional si se manda `X-Issuer`) El slug del emisor. |

**`placement`.** Un objeto con dos cajas, `qr` y `barcode`:

```json
{
  "qr":      {"page": 1, "x": 40,  "y": 30, "size": 90},
  "barcode": {"page": 2, "x": 200, "y": 30, "width": 220, "height": 60}
}
```

- `page`: entero desde **1**. Tiene que existir en el PDF.
- **Unidades: puntos PostScript** (1 punto = 1/72 de pulgada; una carta son
  612 × 792, un A4 595 × 842).
- **Origen: esquina inferior izquierda de la página**, tal como se *ve* (si la
  página está rotada 90°, se mide ya rotada). `x` crece a la derecha e `y` hacia
  arriba. `x` e `y` son la esquina inferior izquierda de la caja.
- El QR es cuadrado (`size`); el código de barras lleva `width` y `height`.
- Números finitos, `x` e `y` no negativos, tamaños positivos. La caja entera tiene
  que caber en la página.

```bash
curl -sS -X POST https://geausa.propensionesabogados.com/api/certificates/external/ \
  -H "X-Issuer: fundacionattlas" \
  -H "X-Issuer-Key: $GEA_ISSUER_KEY" \
  -F "source=@paz-y-salvo.pdf;type=application/pdf" \
  -F "title=Paz y salvo 0001" \
  -F "reference=caso-0001" \
  -F "idempotency_key=caso-0001-v1" \
  -F "qr_payload=https://fundacionattlas.org/verificar/abc123" \
  -F "barcode_text=ATLAS-2026-000123" \
  -F 'placement={"qr":{"page":1,"x":40,"y":30,"size":90},"barcode":{"page":2,"x":200,"y":30,"width":220,"height":60}}'
```

Respuesta **201** (**200** si es un reintento, §5):

```json
{
  "document_id": "5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11",
  "code": "K7Q2M9X4TB5A",
  "verification_url": "https://geausa.propensionesabogados.com/verify/aegis/asset/certification/5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11/",
  "source_hash": "…sha256 del PDF que mandaste…",
  "public_copy_hash": "…sha256 de la copia distribuible…",
  "public_copy_url": "https://geausa.propensionesabogados.com/api/certificates/external/5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11/public-copy/",
  "issued_at": "2026-11-01T17:20:31.482113+00:00"
}
```

Guarda `document_id`: es la llave de los otros dos endpoints.

### 3.2 Bajar la copia distribuible — `GET /api/certificates/external/<document_id>/public-copy/`

```bash
curl -sS -OJ \
  -H "X-Issuer: fundacionattlas" \
  -H "X-Issuer-Key: $GEA_ISSUER_KEY" \
  https://geausa.propensionesabogados.com/api/certificates/external/5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11/public-copy/
```

Responde **200** con el PDF (`Content-Type: application/pdf`, como adjunto). Su
SHA-256 es `public_copy_hash`. **Esta es la copia que se entrega a quien tiene que
verificar**; el original sin códigos y el certificado completo no salen de GEA.

### 3.3 Revocar — `POST /api/certificates/external/<document_id>/revoke/`

Campo opcional `reason` (hasta 1000 caracteres). La revocación **no borra nada**:
el documento pasa a `REVOKED` y la página pública de verificación lo muestra
revocado. El motivo se guarda pero **no se publica**. Es idempotente: revocar lo
ya revocado no cambia la fecha ni el motivo.

```bash
curl -sS -X POST \
  -H "X-Issuer: fundacionattlas" \
  -H "X-Issuer-Key: $GEA_ISSUER_KEY" \
  -F "reason=Emitido por error" \
  https://geausa.propensionesabogados.com/api/certificates/external/5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11/revoke/
```

Respuesta **200**:

```json
{
  "document_id": "5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11",
  "status": "REVOKED",
  "revoked_at": "2026-11-02T09:00:12.100000+00:00",
  "verification_url": "https://geausa.propensionesabogados.com/verify/aegis/asset/certification/5f0c3c1e-6c1b-4c3e-9f5a-0d3f9a2b7e11/"
}
```

**Cada emisor solo ve y revoca sus propios documentos.** Pedir uno de otro emisor
es un 404, igual que pedir uno que no existe.

---

## 4. Respuestas de error

| Código | Cuerpo | Cuándo |
|---|---|---|
| **200** | el del endpoint | Éxito; o reintento de una emisión ya hecha (§5). |
| **201** | el de §3.1 | Documento certificado. |
| **400** | `{"error": "invalid_request", "field": "qr_payload", "detail": "It must be an https URL."}` | Un campo falta o no es válido; `field` dice cuál (`source`, `title`, `reference`, `idempotency_key`, `qr_payload`, `barcode_text`, `placement`). No se emitió nada: corrige y reintenta. |
| **403** | `{"error": "forbidden"}` | Autenticación fallida, sea cual sea la causa. Siempre igual. |
| **404** | `{"error": "not_found"}` | El documento no existe **o es de otro emisor**. |
| **405** | (página HTML de Django) | Método equivocado. No gasta cupo. |
| **422** | `{"error": "certification_failed"}` | El PDF pasó las validaciones de §3.1 pero GEA no pudo certificarlo (el motor rechazó el archivo o la petición). Reintentar igual no ayuda; revisa el archivo y la posición de los símbolos. |
| **429** | `{"error": "rate_limited"}` | Pasaste tu cupo por hora, o hay demasiados intentos con credenciales malas desde tu IP. Reintenta más tarde. También responde 429 si el contador de cupos de GEA no está disponible: GEA prefiere rechazar a emitir sin freno. |
| **500** | `{"error": "server_error"}` | Fallo de GEA. No quedó nada a medias: reintentar con la **misma** `idempotency_key` es seguro. |

---

## 5. Idempotencia y cupos

**Idempotencia.** `idempotency_key` identifica *tu* intento de emitir un documento
(por ejemplo, el identificador del caso más una versión). Es única **por emisor**:
dos emisores pueden usar la misma sin chocar.

- Si repites una petición con una clave que ya produjo un documento, GEA devuelve
  **200 con el mismo cuerpo** que el primer 201, sin certificar de nuevo y **sin
  mirar el resto de campos**: un reintento no tiene que repetir el cuerpo.
- Si la primera vez fallaste (400, 422, 500, un corte de red antes de la
  respuesta), no quedó nada a medias, y reintentar con la misma clave certifica
  de verdad.
- Para emitir **otro** documento, usa otra clave. Reusar la clave con un PDF
  distinto devuelve el documento anterior, no uno nuevo.

**Cupos.** Cada emisor tiene dos cupos por hora, fijados por el operador (por
defecto 60 emisiones y 300 descargas o revocaciones). La ventana es de una hora
(una hora desde el primer uso del cubo, no «cada hora en punto»).

- *Emitir* (`POST` de §3.1) gasta el primer cupo.
- *Descargar* y *revocar* gastan el segundo, juntos.
- Un reintento idempotente **también** gasta cupo, porque ya pasó la autenticación.
- Una petición con clave mala no gasta tu cupo (se cuenta aparte, por IP).
- Pasado el cupo, 429 hasta que se renueva. Si necesitas más, pídeselo al
  operador: cambia el número en el admin y vale desde la siguiente petición.

---

## 6. Cómo da de alta el operador a un emisor nuevo

Todo se hace en el admin, en **Certificates → External issuers**. Hace falta ser
superusuario con segundo factor verificado.

1. **Añadir.** Rellena el nombre, el *slug* (minúsculas, guiones; es lo que el
   emisor manda en `X-Issuer`; **no se puede cambiar una vez que hay documentos
   emitidos con él**), el tipo (empresa del grupo o tercero) y el correo de
   contacto. Deja *Is active* marcado.
2. **Parámetros.**
   - *Documents it can issue per hour* / *Downloads and revocations per hour*:
     los cupos de §5.
   - *Allowed hosts for the QR*: un host por línea (`verify.fundacionattlas.org`),
     sin `https://` ni ruta. Vacío = cualquier URL `https`. Con valor, el QR solo
     puede apuntar a esos hosts exactos (los subdominios hay que listarlos).
   - *QR logo*: imagen (hasta 1 MB) que se estampa en el centro del QR. Vacío = el
     logo de GEA.
   - *Certificate type*: cómo se clasifican sus documentos (por defecto
     «Generic Document»).
3. **Guardar y generar la clave.** En el listado, marca el emisor y elige la
   acción **«Generate a new key»**. La clave aparece **una sola vez** en un
   mensaje en lo alto de la página: cópiala en ese momento. Si prefieres
   escribir una propia, el campo *New key* de la ficha (mínimo 32 caracteres) la
   guarda sin mostrarla.
4. **Entregar.** Pasa al emisor el *slug*, la clave y esta guía por un canal
   seguro.
5. **Rotar.** Repite «Generate a new key»: la anterior deja de valer en ese
   instante. Para **dar de baja**, desmarca *Is active*: el emisor recibe 403 y
   sus documentos ya emitidos siguen siendo verificables.

En el listado, la columna *Key* dice si la clave es propia (`Own key ...abcd`, los
cuatro últimos caracteres), si viene del entorno (`From the environment`) o si
falta (`No key`: ese emisor no puede autenticar).

**El caso `propensiones`.** Su clave es `SERVER_KEY`, la misma que comparten pag y
Vercel, y vive en el `.env` del servidor, no en la base de datos: la fila tiene
*Uses the environment key* marcado, y por eso «Generate a new key» no actúa sobre
ella. Se rota cambiando `SERVER_KEY` en los tres sitios.

**Qué se guarda de la clave.** Solo un HMAC-SHA256 (con la `SECRET_KEY` de la
plataforma) y los cuatro últimos caracteres para reconocerla. El historial de
auditoría tampoco guarda el hash.
