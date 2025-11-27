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
