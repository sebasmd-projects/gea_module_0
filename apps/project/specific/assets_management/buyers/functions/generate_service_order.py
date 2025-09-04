import io

from reportlab.graphics.barcode import code128
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)


def generate_service_order_pdf(offer, user):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20,
        rightMargin=20,
        topMargin=30,
        bottomMargin=30
    )
    elements = []
    styles = getSampleStyleSheet()

    # ---------------- LOGOS ----------------
    logo_header = Image(
        "https://propensionesabogados.com/static/assets/imgs/GEA/alliance-ampro-repatriation-propensiones.webp",
        width=doc.width,
        height=80
    )
    logo_header.hAlign = "CENTER"  # Centra la imagen en el PDF

    elements.append(logo_header)
    elements.append(Spacer(1, 20))

    # ---------------- BARCODE ----------------
    codigo_unico = f"OS-{str(offer.id)[:8].upper()}"
    fecha_str = offer.created.strftime("%d%m%Y")
    barcode_value = f"ORDEN DE SERVICIO {fecha_str} M9Q0 {codigo_unico}"
    barcode = code128.Code128(barcode_value, barHeight=25 * mm, barWidth=0.85)

    # Envolver barcode en una tabla de una celda para centrarlo y darle ancho total
    barcode_table = Table(
        [[barcode]],
        colWidths=[doc.width]
    )
    barcode_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER")
    ]))

    elements.append(barcode_table)

    # Texto debajo del código de barras centrado
    centered_style = ParagraphStyle(
        name="Centered", parent=styles["Normal"], alignment=1
    )

    elements.append(Paragraph(barcode_value, centered_style))
    elements.append(Spacer(1, 20))

    # ---------------- PURCHASE ORDER ID + DATE ----------------
    fecha = offer.created

    # Columna izquierda (Purchase Order ID con estilo rojo y grande)
    id_style = ParagraphStyle(
        name="IdStyle",
        parent=styles["Normal"],
        textColor=colors.red,
        fontSize=12,       # más grande
        leading=16,        # interlineado para que respire
    )

    left_cell = Table(
        [[
            Paragraph("<b>Orden de servicio id:</b>", styles["Normal"]),
            Paragraph(f"{str(offer.id)[:8].upper()}", id_style)
        ]],
        colWidths=[120, 80]
    )

    # Columna derecha (Fecha: día, mes, año)
    right_cell = Table(
        [[
            Paragraph("<b>Día:</b>", styles["Normal"]), fecha.strftime("%d"),
            Paragraph("<b>Mes:</b>", styles["Normal"]), fecha.strftime("%m"),
            Paragraph("<b>Año:</b>", styles["Normal"]), fecha.strftime("%Y"),
        ]],
        colWidths=[40, 40, 50, 40, 40, 50]
    )

    # Tabla contenedora con 2 columnas (izquierda y derecha)
    t_order = Table(
        [[left_cell, right_cell]],
        colWidths=[doc.width/2, doc.width/2]  # mitad y mitad
    )
    t_order.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),  # Fecha alineada a la derecha
    ]))

    elements.append(t_order)
    elements.append(Spacer(1, 15))

    # ---------------- AUTHORIZES and ADDRESSED TO ----------------
    addressed_and_authorizes_table = Table(
        [
            ["AUTORIZA:", "CARGO:"],
            ["DR. JORGE URIEL VEGA L.", "DELEGADO OFICIAL COMPRA EE. UU."],
            ["DIRIGIDO A:", "OFFICIAL'S POSITION:"],
            ["JOSÉ HENRY RIVAS", "ESPECIALISTA EN CAPTACIÓN DE ACTIVOS"],
        ],
        colWidths=[275, 275],
    )
    addressed_and_authorizes_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        # Negrita en encabezados
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 2), (0, 2), "Helvetica-Bold"),
        ("FONTNAME", (1, 2), (1, 2), "Helvetica-Bold"),
    ]))
    elements.append(addressed_and_authorizes_table)
    elements.append(Spacer(1, 20))

    # ---------------- DETALLE ----------------
    detalle_data = [
        ["Activo", "Tipo de Cantidad", "Cantidad"],
        [
            offer.asset_display_name,
            offer.get_quantity_type_display(),
            str(offer.offer_quantity)
        ],
    ]
    detalle_table = Table(detalle_data, colWidths=[380, 90, 80])
    detalle_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#007bff36")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ])
    )
    elements.append(detalle_table)
    elements.append(Spacer(1, 20))

    # ---------------- OBSERVACIONES ----------------
    obs_data = [["Observaciones - Descripción"]]
    
    if offer.observation:
        obs_text = ""
        if offer.observation:
            obs_text += f"{offer.observation}<br/>"
        obs_data.append([Paragraph(obs_text, styles["Normal"])])

    if offer.description:
        desc_text = ""
        if offer.description:
            desc_text += f"{offer.description}<br/>"
        obs_data.append([Paragraph(desc_text, styles["Normal"])])

    # Tabla Observations independiente
    obs_table = Table(obs_data, colWidths=[550])  # ancho total
    obs_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),  # título en negrilla
    ]))
    elements.append(obs_table)
    elements.append(Spacer(1, 10))

    # ---------------- QUANTITY + TOTAL VALUE ----------------
    qt_data = [
        [Paragraph("<b>Tipo de Cantidad</b>", styles["Normal"]),
         Paragraph("<b>Cantidad</b>", styles["Normal"])],
        [
            f"{offer.get_quantity_type_display()}",
            str(offer.offer_quantity),
        ],
    ]

    qt_table = Table(qt_data, colWidths=[90, 90])
    qt_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ALIGN", (0, 1), (-1, -1), "LEFT"),   # datos alineados a la izquierda
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    # Crear un wrapper con dos columnas: una vacía que ocupa el espacio restante
    qt_wrapper = Table(
        [["", qt_table]],
        colWidths=[doc.width - 220, 220]  # espacio libre + ancho tabla
    )
    qt_wrapper.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (1, 0), (1, 0), "TOP"),
    ]))

    elements.append(qt_wrapper)
    elements.append(Spacer(1, 30))

    # ---------------- FOOTER ----------------
    footer_img = Image(
        "https://propensionesabogados.com/static/assets/imgs/GEA/stamp_propensiones.webp",
        width=80,
        height=80
    )

    contacto = "\ndirector@propensionesabogados.com\n+57 318 328 01 76"

    # Columna izquierda: imagen centrada sobre el texto
    contacto_table = Table(
        [
            [footer_img],
            [contacto],
        ],
        colWidths=[200],  # ancho fijo para alinear
    )
    contacto_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (0, 0), "CENTER"),  # centrar imagen
        ("ALIGN", (0, 1), (0, 1), "LEFT"),  # centrar texto bajo la imagen
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    # Footer completo: bloque contacto a la izquierda + firma a la derecha
    footer_table = Table(
        [
            [
                contacto_table,
                "AUTHORIZES:\n\n\n\n\n\n\n\n_____________________________",
            ],
            [
                "",
                f"{user.get_full_name().upper()}\n{user.email}"
            ],
        ],
        colWidths=[350, 200],
    )

    footer_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "LEFT"),
    ]))

    elements.append(footer_table)

    # Build PDF
    doc.build(elements)
    pdf_value = buffer.getvalue()
    buffer.close()
    return pdf_value
