import io

from reportlab.platypus import Image, Spacer


def build_offer_image_story(offer, doc, max_height=200):
    """
    Devuelve una lista de Flowables (Imagen + Spacer) con la imagen de la oferta,
    ajustada al ancho del documento, o lista vacía si no hay imagen.
    """
    if not offer.offer_img:
        return []

    try:
        # Abrir el archivo desde el storage
        offer.offer_img.open('rb')
        img_bytes = offer.offer_img.read()
    except Exception:
        return []

    # Crear imagen desde BytesIO, no desde ruta (sirve tanto para disco como para S3)
    img_buffer = io.BytesIO(img_bytes)
    img = Image(img_buffer)

    # Ajustar al ancho del documento manteniendo proporción
    iw, ih = img.imageWidth, img.imageHeight
    if iw == 0 or ih == 0:
        return []

    scale = doc.width / float(iw)
    new_width = doc.width
    new_height = ih * scale

    # limitar altura si es muy grande
    if new_height > max_height:
        factor = max_height / new_height
        new_width *= factor
        new_height *= factor

    img.drawWidth = new_width
    img.drawHeight = new_height
    img.hAlign = "CENTER"

    return [img, Spacer(1, 10)]


def static_file_path(relative_path):
    """
    Donde esta en **disco** un estatico, o ``None`` si no aparece.

    `finders` lo encuentra en desarrollo sin `collectstatic`; `STATIC_ROOT`
    lo tiene despues de recogerlos. Entre los dos cubren los dos entornos.
    """
    import logging
    from pathlib import Path

    from django.conf import settings
    from django.contrib.staticfiles import finders

    found = finders.find(relative_path)

    if found:
        return found

    candidate = Path(str(settings.STATIC_ROOT)) / relative_path

    if candidate.is_file():
        return str(candidate)

    logging.getLogger(__name__).error(
        'No se encontro el estatico %r ni con los buscadores ni en '
        'STATIC_ROOT.', relative_path,
    )

    return None


def brand_image(relative_path, **kwargs):
    """
    Una imagen de marca del PDF, leida **del disco**.

    Antes las imagenes de los dos generadores venian de una URL absoluta de
    produccion escrita a mano en el codigo. Eso significaba que cada orden de
    compra y cada orden de servicio salia a Internet a descargar sus propios
    logotipos -- dentro de la peticion, con `ATOMIC_REQUESTS` puesto, o sea
    con una transaccion abierta esperando a que respondiera un servidor web.

    Tres cosas malas a la vez: una llamada de red en el camino critico; un PDF
    que no se puede generar sin salida a Internet (ni en un portatil, ni en
    las pruebas, ni si el propio sitio esta caido); y un documento que sale a
    terceros dependiendo de que una URL siga existiendo. `reportlab` 5 acabo
    de hacerlo evidente al dejar de poder abrir esas URLs, pero el problema no
    lo trajo la actualizacion: solo lo destapo.

    Si la imagen no aparece se devuelve ``None`` y quien llama la omite: un
    logotipo que falta no puede impedir que salga una orden de servicio, que
    es el documento. Queda en el log, que es donde se mira por que un PDF
    salio sin su marca.

    Args:
        relative_path: la ruta tal y como se pediria con ``{% static %}``.
        **kwargs: lo que se le pasa a ``Image`` (``width``, ``height``...).

    Returns:
        Image | None
    """
    found = static_file_path(relative_path)

    return Image(found, **kwargs) if found else None


#: El logotipo que va inline en los correos de orden.
EMAIL_LOGO = 'assets/imgs/logos/gea_logo.webp'


def attach_inline_logo(email, relative_path=EMAIL_LOGO, content_id='gea_logo'):
    """
    Cuelga el logotipo del correo como adjunto inline, leyendolo del disco.

    Antes se descargaba con `requests.get()` de la URL publica de produccion,
    en cada correo de orden de compra y de servicio. Eso ponia una llamada de
    red dentro de la peticion --con `ATOMIC_REQUESTS`, o sea con la
    transaccion abierta-- para traer un fichero que ya estaba en el disco de
    ese mismo servidor. Y si el sitio no respondia, el correo salia sin
    logotipo sin que nadie se enterara.

    Si el fichero no aparece no se adjunta nada: el correo sale igual, que es
    lo que importa, y el motivo queda en el log.

    Returns:
        bool: si se llego a adjuntar.
    """
    import logging
    from email.mime.image import MIMEImage
    from pathlib import Path

    found = static_file_path(relative_path)

    if not found:
        return False

    try:
        content = Path(found).read_bytes()
    except OSError as error:
        logging.getLogger(__name__).error(
            'No se pudo leer el logotipo del correo (%s): %s', found, error)
        return False

    image = MIMEImage(content, _subtype=Path(found).suffix.lstrip('.'))
    image.add_header('Content-ID', f'<{content_id}>')
    image.add_header(
        'Content-Disposition', 'inline', filename=Path(found).name)

    email.attach(image)

    return True
