"""
Quien ve que en el historial de codigos. No repartido por las vistas.

Hay dos papeles, y no son «el mismo con menos botones»
-----------------------------------------------------
**El operador** (personal interno) emite codigos y certifica documentos. Ve
todo el historial, compone resumenes, se lleva un dossier a un USB, descarga el
original sin codigos y mira donde se estamparon los simbolos. Es la herramienta
de trabajo.

**El titular** es la persona para la que se emitio un certificado. Ve **sus**
certificados y nada mas, y los ve para saber que existen y comprobarlos: no
para operarlos. Por eso no es «la misma pantalla con menos botones» sino otra
lectura de las mismas filas.

Que se le quita al titular, y por que cada cosa
-----------------------------------------------
- **El archivo original** (`source_file`) es el certificado **sin los codigos
  estampados**. Quien lo tenga tiene una version limpia de un documento que
  hace fe; no sale de casa ni para su titular.
- **El QR y el codigo de barras sueltos**, en PNG, son los simbolos que se
  estampan. Sueltos y descargables son piezas para montar algo que se parezca a
  un certificado.
- **Donde se estamparon** es la geometria de la disposicion: las coordenadas
  exactas de cada simbolo en la pagina. Es el plano de la falsificacion.
- **Componer un resumen** y **exportar a un USB** son actos del emisor. El
  dossier del USB lleva ademas documentos de otros titulares.
- **Generar un codigo** emite algo institucional. Un titular no emite.

Lo que si ve: que certificados tiene, cuando se emitieron, su codigo publico, y
el enlace a la verificacion publica, que es donde de verdad se comprueban.

Donde vive la regla
-------------------
**En el queryset, no en la plantilla.** Esconder un boton no es un control
--basta con teclear la URL-- asi que `visible_registrations()` filtra en la base
de datos y el detalle de un codigo que no es suyo responde **404**: un 403 le
confirmaria que ese codigo existe (invariante 7 y 20).
"""


def is_operator(user) -> bool:
    """
    Personal interno: el que emite. Es el criterio de siempre del generador.
    """
    return bool(
        user
        and user.is_authenticated
        and user.is_active
        and (user.is_staff or user.is_superuser)
    )


def is_holder(user) -> bool:
    """
    Alguien que ha entrado y no es operador.

    No se le pide `user_type`: un certificado se emite para quien sea --un
    tenedor, un comprador, un tercero-- y lo que decide que puede ver es que
    figure como titular de algo, no la etiqueta de su cuenta. Atarlo al
    `user_type` obligaria a tocar esta regla cada vez que aparezca un tipo
    nuevo, y el dia que se olvidara dejaria a alguien sin ver lo suyo.
    """
    return bool(user and user.is_authenticated and user.is_active
                and not is_operator(user))


def can_use_history(user) -> bool:
    """Quien puede abrir el historial: operadores y titulares."""
    return is_operator(user) or is_holder(user)


def visible_registrations(queryset, user):
    """
    Recorta el historial a lo que esta persona puede ver.

    El operador lo ve entero. El titular ve **solo los codigos de documentos de
    los que es titular**, y por tanto ningun codigo suelto: un codigo sin
    documento no es de nadie, asi que no puede ser suyo.
    """
    if is_operator(user):
        return queryset

    if not is_holder(user):
        return queryset.none()

    return queryset.filter(document__holder=user)


def can_view_registration(user, registration) -> bool:
    """Si esta persona puede abrir el detalle de este codigo."""
    if is_operator(user):
        return True

    if not is_holder(user):
        return False

    document = registration.document

    return bool(document and document.holder_id == user.pk)


def can_see_internals(user) -> bool:
    """
    Si se le enseñan las piezas de trabajo: simbolos sueltos, el original y la
    geometria del estampado.

    Es una sola pregunta para las tres porque las tres responden a lo mismo
    --quien puede reconstruir un certificado-- y separarlas invitaria a
    contestar distinto a una de ellas por descuido.
    """
    return is_operator(user)


def can_compose_summaries(user) -> bool:
    """Componer un resumen y llevarselo en un USB: actos del emisor."""
    return is_operator(user)


def can_generate_codes(user) -> bool:
    """
    Emitir un codigo nuevo.

    TODO: lo que le falta a un titular no es este boton, es **pedir** un
    certificado — una solicitud que alguien revisa y aprueba, con su traza.
    Eso es una funcionalidad aparte y no esta hecha. Mientras no lo este, el
    boton no se le enseña: uno que emitiera de verdad le daria a un titular la
    capacidad del operador, y uno que no hiciera nada seria peor que no estar.
    """
    return is_operator(user)
