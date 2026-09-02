# Seguridad

Dos partes: el **checklist de despliegue**, para leer en dos minutos, y la
**auditoría** con lo que se encontró y por qué importa cada cosa.

---

## Checklist antes de desplegar

Cuatro comandos. Si los cuatro salen limpios, adelante.

```bash
python manage.py check --deploy      # ajustes de Django
python manage.py check_security      # la superficie propia de este proyecto
python manage.py check_requirements  # que producción instale lo declarado
python manage.py check_cron          # que las tareas estén instaladas
```

Los cuatro están también en la consola de operaciones.

### Y estas seis a ojo

| | Qué mirar | Por qué |
|---|---|---|
| ☐ | `DJANGO_DEBUG` **no** es `True` | Con `DEBUG` cada error muestra la traza entera, con ajustes y consultas dentro |
| ☐ | `REDIS_URL` puesta **y contestando** | Sin ella la caché es por proceso y **los límites se multiplican por el número de workers**. Puesta pero caída es distinto: los cupos que protegen a terceros cierran, así que la consulta pública de códigos y los envíos de correo dejan de funcionar hasta que vuelva (§3) |
| ☐ | `CERTIFICATION_SIGNING_KEY` puesta | Sin ella el registro se sella con HMAC y sólo esta plataforma puede verificarlo: un tercero no |
| ☐ | `FIELD_ENCRYPTION_KEY` es la misma de siempre | Cambiarla **inutiliza toda la PII ya cifrada**. No se rota sin migrar los datos |
| ☐ | El `.htaccess` de `deploy/` está en la carpeta de media | Sin él el servidor web reparte los PDF por su cuenta y el control de acceso no pinta nada |
| ☐ | `migrate` y `collectstatic` ejecutados | Una restricción sin migrar no existe; un JS sin recoger no llega |
| ☐ | El correo sale de verdad | Desde que el acceso se puede hacer con un código enviado al buzón, un servidor de correo caído no es una molestia: es gente que no entra. `DJANGO_EMAIL_*` completas y una prueba de envío |

### Después de desplegar

```bash
python manage.py check_health --http   # que responda de verdad, no sólo por dentro
```

---

## Auditoría — lo que se encontró

Orden por gravedad. Todo lo listado está **corregido**, salvo lo marcado como
decisión pendiente.

### 1. Enumeración de la plantilla completa · CRÍTICO · corregido

**Dónde:** `certificates/views.py::InputEmployeeIPCONFormView`

El portal público de certificados de persona aceptaba un código de **cuatro
caracteres** sobre `A-Z0-9` —1.679.616 combinaciones— sin autenticación, sin
OTP y **sin ningún límite de intentos**. Un acierto redirige a una página
también pública que muestra nombre, apellidos y **fotografía** del empleado.

Sin freno, eso no es un secreto: es un rato de barrido. Y lo que sale del otro
lado no son códigos, es la plantilla del despacho con sus fotos. El mismo
formulario acepta números de documento, así que servía además para comprobar
si una persona concreta tiene credencial.

Lo que lo hacía evidente es la asimetría: el portal de **documentos** exige
OTP a un anónimo y limita los intentos; el de **personas** no tenía ninguna de
las dos.

**Corregido:** límite de 15 intentos por IP cada 10 minutos, consumido *antes*
de buscar para que acertar y fallar cuesten lo mismo. 12 pruebas, incluida una
que comprueba que borrar la cookie no reinicia el contador.

**Queda por decidir:** cuatro caracteres son pocos aunque haya límite. Para
credenciales nuevas conviene un código más largo; las ya impresas no se pueden
cambiar.

### 2. Un identificador inválido devolvía un certificado ajeno · ALTO · corregido

**Dónde:** el mismo formulario.

Si el código no medía 4, 8 ni 36 caracteres, el filtro se quedaba **sólo con
el tipo de certificado**, y el `.get()` devolvía *un certificado cualquiera*
si sólo había uno en la base, o reventaba con `MultipleObjectsReturned` —un
500— si había varios.

**Corregido:** una consulta que no identifica a nadie ahora no encuentra a
nadie, con el mismo mensaje que un código inexistente para no decirle al que
barre qué formato probar.

### 3. Los límites de intentos se apagaban solos si Redis se caía · ALTO · corregido

**Dónde:** los seis contadores del proyecto, y `app_core/settings.py`.

Todos los cupos —el del OTP, el de recuperación de contraseña, el del código
de registro, el de PQRS y el de códigos públicos— se llevaban leyendo la caché
a mano. Y la caché va con `IGNORE_EXCEPTIONS` **a propósito**, porque un Redis
caído no puede tumbar el login.

Lo que no es obvio, y es lo que falla, es qué hace exactamente esa opción:
`django-redis` **no lanza la excepción, la devuelve como `None`**. De modo que
un `try/except` alrededor de una operación de caché no se entera de nada, y
esto:

```python
if (cache.get(key) or 0) >= LIMITE:
```

con Redis caído es `None or 0` → `0`, y `0 >= 3` es falso. **Pasa siempre.**

Así que un corte de red en el VPS de Redis dejaba a la plataforma sin ningún
freno en su única superficie no autenticada, sin excepción, sin log y sin
síntoma. Y de paso **reabría el hallazgo nº 1** —el barrido de la plantilla—
que se acababa de cerrar: un rato de avería y una plantilla enumerada, que ya
no se desenumera cuando Redis vuelve.

**Corregido:** los seis pasan por `apps/common/utils/throttling.py`, que
detecta la avería por lo que devuelve `incr` —un entero si la caché vive,
`None` si se lo tragaron— y decide **por cupo**, no en bloque. La pregunta que
decide es qué impide el límite:

| Cupo | Con la caché caída | Por qué |
|---|---|---|
| Códigos públicos (personas y documentos) | **cierra** | El límite *es* el control: no hay nada más entre un desconocido y 1.679.616 combinaciones |
| Envío de OTP | **cierra** | El correo sale hacia un buzón ajeno |
| Recuperación de contraseña | **cierra** | Igual: llena la bandeja de un tercero |
| Código de registro de comprador | **cierra** | Igual — y además el código se guarda en esa misma caché, así que mandarlo sería mandar algo que ya se sabe que no se va a poder comprobar |
| Verificación del OTP recibido | abre | No se adivina nada de otro: el código llegó al buzón de quien teclea, y el bloqueo a los 5 fallos vive en la sesión, o sea en la base de datos |
| Radicar un PQRS | abre | Es un derecho de petición, y el plazo legal corre desde que se radica. El coste del abuso es spam que se absorbe |

La asimetría es la que manda: fallar cerrado cuesta que una función no esté
disponible mientras dure una avería que ya es una avería; fallar abierto cuesta
una fuga permanente de la que nadie se entera. Por eso el defecto es cerrado, y
`fail_open=True` hay que pedirlo a mano **con la razón escrita al lado** —el
constructor lanza `ValueError` si falta.

**Y un segundo fallo que salió al unificarlos:** dos de los cupos "por
destinatario" llevaban la IP en la llave (`{ip}:{correo}`), así que no eran del
buzón sino de la pareja. Tres correos, cambio de IP, tres más. Ahora el
destinatario va por `scope` y la IP no entra —y el `scope` se guarda hasheado,
porque una llave de caché es un sitio donde nadie espera encontrar un correo o
una cédula.

**Cómo se prueba una avería:** con `incr` devolviendo `None`, no lanzando.
Lanzar es lo que *no* hace en producción, y una prueba que simulara una
excepción habría pasado en verde sobre el código roto.

### 4. Los adjuntos del PQRS los servía el servidor web · ALTO · corregido

**Dónde:** `deploy/media.htaccess`, y `pqrs/models.py::identity_document_path`.

El formulario de PQRS es **público y sin sesión**, y sus adjuntos son
documentos de identidad: cédula, pasaporte, certificado de existencia. Van a
`MEDIA_ROOT/pqrs/`, y esa carpeta **no estaba en la lista de bloqueadas**. Se
cayó al crear la app.

El invariante 13 dice que lo sensible no se sirve por `MEDIA_URL`, pero ese
invariante no lo aplica Django: lo aplica el `.htaccess`. Un fichero que Apache
entrega antes de que Django lo vea no pasa por ningún control, por muchas
comprobaciones que tenga la vista.

La ruta lleva el radicado, pero **un radicado no es un secreto**: va impreso en
el acuse, viaja por correo y por captura de pantalla, y la página del
comprobante es pública a propósito. Apoyar la confidencialidad de una cédula en
eso es no apoyarla en nada.

**Corregido:** `pqrs/` bloqueado por los dos mecanismos —`mod_rewrite` y el
respaldo `RedirectMatch`, porque en hosting compartido nadie garantiza que el
primero esté activo.

**Y para que no vuelva a pasar:** `check_security` tiene una sección nueva que
recorre **todos** los campos de fichero del proyecto, saca a qué carpeta
escribe cada uno y comprueba que esté bloqueada o declarada como servible con
su razón. Un campo nuevo aparece ahí la primera vez que se ejecuta.

La validación de tipo y tamaño de esos mismos adjuntos es el hallazgo nº 5, y
ya estaba corregida; esto es la otra mitad —qué pasa con el fichero **después**
de aceptarlo.

### 5. Restricción única que no existía en producción · ALTO · corregido

**Dónde:** `buyers/models.py::ServiceOrderRecipient`

Salió del `migrate` del propio despliegue: `models.W036`. MariaDB no admite
únicos condicionales y **no falla — avisa y no los crea**. En producción las
dos restricciones no existían, así que el mismo destinatario podía añadirse
dos veces y recibir la orden de servicio por duplicado.

En desarrollo funcionaba, que es lo peor: SQLite sí admite índices parciales.

**Corregido:** sin `condition=`. La condición sobraba —un índice único ya
admite varios `NULL`— así que quitarla no relaja nada: es lo que hace que
existan.

### 6. Subidas públicas sin validar · ALTO · corregido

**Dónde:** `pqrs/forms.py`

El formulario de PQRS es público y sin sesión, y sus dos campos de fichero no
comprobaban ni tipo ni tamaño. Cualquiera podía subir cualquier cosa de
cualquier peso, y quedaba guardada.

**Corregido:** lista de permitidos (`.pdf .jpg .jpeg .png .webp`) y tope de
10 MB, en un campo compartido por los dos formularios.

### 7. Ejecución por shell innecesaria · MEDIO · corregido

**Dónde:** `check_cron.py`

`os.popen(f'{executable} -l 2>&1')` lanza una shell con la ruta interpolada.
Hoy esa ruta sale de `settings` y no del usuario, así que no era explotable —
pero es ejecución por shell sin ninguna necesidad, en un comando que además se
puede lanzar desde la consola de operaciones.

**Corregido:** `subprocess.run([executable, '-l'])`, sin shell. Sin shell no
hay nada que escapar.

### 8. Ajustes de sesión implícitos · MEDIO · corregido

`SESSION_COOKIE_HTTPONLY` y `SESSION_COOKIE_SAMESITE` dependían del valor por
defecto de Django. Son de las cosas que se desactivan sin querer al depurar y
nadie vuelve a mirar.

**Corregido:** explícitos, con `DATA_UPLOAD_MAX_MEMORY_SIZE` y
`DATA_UPLOAD_MAX_NUMBER_FILES`.

---

## Lo que se revisó y salió limpio

Merece decirse: la mayor parte del proyecto aguantó la revisión.

- **Secretos:** ningún `.env` ha estado versionado nunca, y no hay claves
  escritas en el código. La única constante con aspecto de clave es la de
  pruebas, y lo dice en su propio nombre.
- **Inyección SQL:** ni un `.raw()`, ni un `.extra()`, ni una consulta
  construida por interpolación. El único `cursor.execute` es un `SELECT 1`
  literal del health check.
- **Deserialización:** ni `pickle` ni `yaml.load`.
- **Los 7 endpoints JSON de `code_gen`** —incluidos los que sellan, anclan y
  emiten— comprueban `_is_internal`. Verificado con AST, no a ojo.
- **Descarga de ficheros certificados:** pasa por `files.can_access`, con
  `source` y `certified` sólo para personal interno.
- **IDOR en el área del tenedor:** `get_queryset()` acota por `created_by` en
  las seis rutas; un objeto ajeno da 404.
- **El admin:** una sola puerta, con segundo factor verificado, y 404 —no
  403— al que no cumple.
- **Contraseñas:** Argon2 primero.
- **Cookies:** no hay analítica ni pixels.

---

## El acceso con código al correo

Se añadió después de la auditoría, así que conviene dejar escrito qué sostiene
y qué no.

**Qué sustituye.** La contraseña, y sólo la contraseña. El código va **dentro**
del asistente de dos factores, en el lugar del formulario de credenciales:
quien tenga un dispositivo TOTP configurado sigue pasando por él después. Si
esto viviera en una vista aparte que llamara a `login()`, el acceso al buzón de
alguien bastaría para saltarse su segundo factor. Eso no es una comodidad, es
una puerta trasera, y es la razón de que el código sea más largo de lo que
parecería necesario.

**Qué no apaga.** El freno de `django-axes`. El paso de contraseña no
desaparece de la lista cuando se ofrece el código, y la oferta se hace una sola
vez: si desapareciera, los envíos posteriores de contraseña no llegarían a
validarse, axes no contaría esos fallos y su bloqueo de seis intentos no se
alcanzaría nunca desde el navegador. La ayuda al despistado habría desactivado
el freno al que ataca. Está fijado en una prueba.

**Y ahora cuenta las tres puertas, no solo una.** Se puede entrar de tres
formas --contraseña, código al correo y, si lo hay, el segundo factor-- y hasta
ahora solo la primera alimentaba el contador de axes: las otras dos no pasan
por `authenticate()`, así que sus fallos no llegaban a ninguna parte. Eso dejaba
el freno del revés. Quien probara códigos de seis cifras tenía barra libre --el
tope de cinco intentos por código se esquiva pidiendo otro-- y quien probara
segundos factores también; el camino más barato para quien atacaba era justo el
que no dejaba rastro, mientras que el bloqueo solo estorbaba a quien de verdad
había olvidado su contraseña. Hoy los tres pasan por
`apps/common/utils/login_attempts.py`, que apunta el fallo por la señal de axes
--su interfaz, para no replicar sus ajustes-- y **consulta el bloqueo antes** de
comparar nada: apuntar sin consultar deja el bloqueo escrito en una tabla y a
quien ataca dentro.

Un detalle que parece menor: el contador va por lo **tecleado** al
identificarse, no por el usuario resuelto. `UserModel.USERNAME_FIELD` es el
correo, así que quien entra como «ana» y falla el segundo factor alimentaría
una cuenta atrás distinta de la del primer paso — y dos contadores para el
mismo intruso son ninguno, porque basta con alternar de puerta para no agotar
ninguna.

**Qué no cuenta.** Preguntar por un usuario contesta lo mismo exista o no, y
el correo sólo sale si hay a quién mandárselo. La pantalla del código dice «se
ha enviado» en los dos casos, incluso cuando el cupo lo impidió: decir ahí que
no salió delataría que la cuenta existe.

**Dónde vive el código.** Hasheado con HMAC-SHA256 sobre `SECRET_KEY`, nunca
en claro, y en la sesión —que aquí va en base de datos, así que sobrevive a una
caída de Redis—. Caduca a los 15 minutos, vale una sola vez y se **tira** —no
sólo se corta la pantalla— tras cinco intentos: un tope que sólo cerrara la
sesión lo esquiva quien borre la cookie.

**Los dos cupos de envío** fallan cerrados, como los demás (§3). Uno va por
destinatario y otro por origen: sin el primero, teclear el usuario de otro en
bucle le llena el buzón, y quien recibe no eligió nada; sin el segundo, se
recorre una lista de usuarios mandando tres a cada uno.

**El correo, uno solo para los dos códigos.** El de la verificación documental
era un `send_mail` de tres líneas en texto plano, sin logos y sin el aviso de
que nadie del despacho pide el código. Va a quien acaba de escanear el QR de un
papel, no es usuario de la plataforma y no tiene por qué reconocer el
remitente: justo a quien menos contexto tiene se le mandaba el mensaje que
menos se parece a algo. Hoy los dos usan la misma plantilla
(`apps/common/utils/otp_email.py`) y solo cambian el asunto y la frase que dice
para qué es el código.

**Lo que queda fuera de la plataforma.** Que el correo del titular esté a su
vez protegido. El aviso del pie del mensaje —*nadie del despacho te pedirá este
código*— es lo único que se puede hacer contra la estafa habitual, la llamada
diciendo «léeme el código que te acaba de llegar». Va en el propio correo y no
sólo en la web, porque es ahí donde se lee en el momento en que importa.

---

## Decisiones pendientes

No son fallos, son cosas que alguien tiene que decidir:

1. **Códigos públicos de 4 caracteres** para certificados de persona. Con el
   límite ya no son barribles, pero son cortos. Alargarlos afecta sólo a los
   nuevos.
2. **La transferencia a OpenAI.** La traducción manda texto libre fuera del
   país en cada guardado. Mantenerla con los instrumentos de la SIC,
   restringir campos, o traducir sólo a petición.
3. **jQuery desde `ajax.googleapis.com`.** Le da a Google la IP de cada
   visitante sin ganar nada frente a servirlo desde los estáticos propios.
4. **JotForm embebido** en dos páginas: lo que se escribe ahí lo recibe y
   guarda un tercero.
5. **`DATA_UPLOAD_MAX_NUMBER_FIELDS = 15000`**, quince veces el valor por
   defecto de Django. Si fue por un formset concreto, conviene saber cuál;
   si no, bajarlo.
6. **`asset/` y `offer/` los sirve el servidor web.** No son documentos de
   identidad —son fotos de activos y de órdenes—, pero sí son el inventario de
   un cliente concreto, y la ruta lleva el nombre del activo. Hoy se pintan con
   `<img>` en el panel del tenedor y en la ficha de una orden, así que
   bloquearlas sin poner antes una vista que las entregue deja esas páginas con
   los huecos rotos: no es un cambio de una línea. Están declaradas en
   `check_security` con esa razón para que el aviso no tape a uno nuevo.
