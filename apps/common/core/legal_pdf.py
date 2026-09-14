"""
El PDF de un documento legal, desde el HTML que se redacto en el editor.

Por que ReportLab y no un conversor de HTML
-------------------------------------------
Lo obvio seria WeasyPrint o similar, que pinta HTML con su CSS y sale precioso.
No se puede: piden Cairo y Pango, que son bibliotecas del sistema, y esto se
despliega en un cPanel donde solo hay `pip`. Una dependencia que no se puede
instalar en produccion no es una dependencia, es una pagina que no funciona
alli.

ReportLab ya esta --lo usa todo el motor de certificacion-- y con Platypus da
un documento correcto. El precio es que hay que traducir el HTML a flowables a
mano, que es lo que hace este modulo.

Que se traduce, y por que solo eso
----------------------------------
La lista de etiquetas que entiende este conversor y la barra de botones del
editor (`CKEDITOR_5_CONFIGS['legal']` en `settings.py`) son **la misma lista**,
y tienen que seguir siendolo. Ofrecer en el editor un boton que el PDF no sabe
pintar es prometer algo que no se cumple: el texto sale en la pantalla y
desaparece del papel, que es la copia que alguien se lleva.

Lo que no se reconoce **no se tira**: se pinta como parrafo con su texto. Un
documento legal al que le falta un apartado porque llevaba una etiqueta rara es
peor que uno con un apartado mal maquetado.
"""

import io
from html import escape
from html.parser import HTMLParser

from django.utils.translation import gettext as _
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (ListFlowable, ListItem, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .legal_html import sanitize_legal_html

#: Etiquetas de bloque que abren un flowable nuevo.
BLOQUES = {'p', 'h1', 'h2', 'h3', 'h4', 'li', 'dt', 'dd', 'td', 'th',
           'blockquote'}

#: Etiquetas en linea que Paragraph entiende tal cual.
EN_LINEA = {'b', 'strong', 'i', 'em', 'u', 'br', 'a', 'sub', 'super'}

#: Como se traduce cada una a lo que Paragraph acepta.
EQUIVALENCIAS = {'strong': 'b', 'em': 'i'}


def _styles():
    hoja = getSampleStyleSheet()

    base = ParagraphStyle(
        'LegalBody',
        parent=hoja['BodyText'],
        fontSize=9.5,
        leading=13.5,
        spaceAfter=7,
        alignment=TA_JUSTIFY,
    )

    return {
        'body': base,
        'h1': ParagraphStyle('LegalH1', parent=base, fontSize=16, leading=20,
                             spaceBefore=0, spaceAfter=4,
                             fontName='Helvetica-Bold', alignment=0),
        'h2': ParagraphStyle('LegalH2', parent=base, fontSize=12, leading=16,
                             spaceBefore=16, spaceAfter=6,
                             fontName='Helvetica-Bold', alignment=0),
        'h3': ParagraphStyle('LegalH3', parent=base, fontSize=10.5,
                             leading=14, spaceBefore=10, spaceAfter=4,
                             fontName='Helvetica-Bold', alignment=0),
        'meta': ParagraphStyle('LegalMeta', parent=base, fontSize=8,
                               leading=11, textColor=colors.HexColor('#6c757d'),
                               alignment=0),
        'cell': ParagraphStyle('LegalCell', parent=base, fontSize=8.5,
                               leading=11.5, spaceAfter=0, alignment=0),
        'dt': ParagraphStyle('LegalDT', parent=base, fontName='Helvetica-Bold',
                             spaceBefore=6, spaceAfter=1, alignment=0),
        'dd': ParagraphStyle('LegalDD', parent=base, leftIndent=14,
                             spaceAfter=4),
        'note': ParagraphStyle('LegalNote', parent=base,
                               backColor=colors.HexColor('#FBF7EA'),
                               borderColor=colors.HexColor('#A17F1A'),
                               borderWidth=0.6, borderPadding=6,
                               spaceBefore=8, spaceAfter=10),
    }


class _Conversor(HTMLParser):
    """
    Recorre el HTML y va soltando flowables.

    No es un motor de HTML ni lo pretende: es un traductor de la docena de
    etiquetas que produce el editor. Todo lo demas cae en «parrafo».
    """

    def __init__(self, styles):
        super().__init__(convert_charrefs=True)
        self.styles = styles
        self.flowables = []

        self._inline = []          # trozos del bloque que se esta armando
        self._bloque = None        # etiqueta de bloque abierta
        self._listas = []          # pila de (tipo, items)
        self._tabla = None         # filas de la tabla en curso
        self._fila = None
        self._nota = False

    # ---------- utilidades ----------

    def _texto(self):
        return ''.join(self._inline).strip()

    def _estilo(self, etiqueta):
        if self._nota:
            return self.styles['note']

        return self.styles.get(etiqueta, self.styles['body'])

    def _emitir(self, flowable):
        """Un flowable va a la lista, o al item de lista o celda en curso."""
        if self._fila is not None:
            self._fila.append(flowable)
        elif self._listas:
            self._listas[-1][1].append(ListItem(flowable, leftIndent=16))
        else:
            self.flowables.append(flowable)

    def _cerrar_bloque(self):
        texto = self._texto()
        etiqueta = self._bloque

        self._inline = []
        self._bloque = None

        if not texto:
            return

        estilo = (self.styles['cell'] if etiqueta in {'td', 'th'}
                  else self._estilo(etiqueta))

        if etiqueta == 'th':
            texto = f'<b>{texto}</b>'

        self._emitir(Paragraph(texto, estilo))

    # ---------- HTMLParser ----------

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)

        if tag in EN_LINEA:
            nombre = EQUIVALENCIAS.get(tag, tag)

            if tag == 'br':
                self._inline.append('<br/>')
            elif tag == 'a':
                destino = escape(atributos.get('href', ''), quote=True)
                self._inline.append(f'<a href="{destino}" color="#8a6d1a">')
            else:
                self._inline.append(f'<{nombre}>')
            return

        if tag == 'code':
            self._inline.append('<font face="Courier">')
            return

        if tag in BLOQUES:
            self._cerrar_bloque()
            self._bloque = tag

            if tag in {'td', 'th'}:
                self._fila = self._fila if self._fila is not None else []
            return

        if tag in {'ul', 'ol'}:
            self._cerrar_bloque()
            self._listas.append((tag, []))
            return

        if tag == 'tr':
            self._cerrar_bloque()
            self._fila = []
            return

        if tag == 'table':
            self._cerrar_bloque()
            self._tabla = []
            return

        if tag == 'div' and 'legal__note' in atributos.get('class', ''):
            self._cerrar_bloque()
            self._nota = True
            return

        if tag == 'hr':
            self._cerrar_bloque()
            self.flowables.append(Spacer(1, 8))

    def handle_endtag(self, tag):
        if tag in EN_LINEA and tag != 'br':
            nombre = EQUIVALENCIAS.get(tag, tag)
            self._inline.append(f'</{nombre}>')
            return

        if tag == 'code':
            self._inline.append('</font>')
            return

        if tag in {'td', 'th'}:
            self._cerrar_bloque()
            return

        if tag == 'tr':
            self._cerrar_bloque()

            if self._tabla is not None and self._fila:
                self._tabla.append(self._fila)

            self._fila = None
            return

        if tag == 'table':
            self._cerrar_bloque()
            self._emitir_tabla()
            return

        if tag in {'ul', 'ol'}:
            self._cerrar_bloque()

            if self._listas:
                tipo, items = self._listas.pop()

                if items:
                    self._emitir(ListFlowable(
                        items,
                        bulletType='1' if tipo == 'ol' else 'bullet',
                        bulletFontSize=8,
                        leftIndent=14,
                        spaceAfter=6,
                    ))
            return

        if tag in BLOQUES:
            self._cerrar_bloque()
            return

        if tag == 'div' and self._nota:
            self._cerrar_bloque()
            self._nota = False

    def handle_data(self, data):
        if not data.strip() and not self._inline:
            return

        self._inline.append(escape(data))

    # ---------- tabla ----------

    def _emitir_tabla(self):
        filas = self._tabla or []
        self._tabla = None

        if not filas:
            return

        # Las filas pueden venir con distinto numero de celdas si el editor
        # dejo una a medias; se rellena en vez de reventar.
        ancho = max(len(fila) for fila in filas)
        filas = [fila + [''] * (ancho - len(fila)) for fila in filas]

        util = 17 * cm
        tabla = Table(filas, colWidths=[util / ancho] * ancho, repeatRows=1)
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F3F5')),
            ('LINEBELOW', (0, 0), (-1, -1), 0.4, colors.HexColor('#DEE2E6')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))

        self.flowables.append(Spacer(1, 4))
        self.flowables.append(tabla)
        self.flowables.append(Spacer(1, 8))

    def close(self):
        super().close()
        self._cerrar_bloque()


def html_to_flowables(html: str, styles=None) -> list:
    """El HTML del editor, convertido en flowables de Platypus."""
    conversor = _Conversor(styles or _styles())
    # Por el mismo sitio que la web: el papel tiene que decir lo mismo que la
    # pantalla, y eso incluye lo que se descarta.
    conversor.feed(sanitize_legal_html(html))
    conversor.close()
    return conversor.flowables


def render_document_pdf(version, language: str = 'es') -> bytes:
    """
    El PDF de una version concreta, en el idioma que se pida.

    Se genera **al vuelo** y no se guarda en disco. Guardarlo obligaria a
    decidir su carpeta en `deploy/media.htaccess` o declararla en
    `PUBLICLY_SERVABLE_MEDIA` (invariante 13), y a regenerarlo cada vez que
    cambia el texto — para un documento que se descarga de vez en cuando y que
    ya esta entero en la base de datos.
    """
    styles = _styles()
    documento = version.document

    buffer = io.BytesIO()
    titulo = documento.name_for(language)

    plantilla = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=2.2 * cm, rightMargin=2.2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f'{titulo} · {version.version}',
        author='Propensiones Abogados',
        subject=_('Legal document'),
    )

    piezas = [Paragraph(escape(titulo), styles['h1'])]

    vigencia = (
        version.effective_from.strftime('%d/%m/%Y')
        if version.effective_from else _('not in force yet')
    )
    piezas.append(Paragraph(
        escape(_('Version %(version)s · In force since %(date)s')
               % {'version': version.version, 'date': vigencia}),
        styles['meta'],
    ))

    # El estado va impreso, porque un PDF se reenvia suelto: quien lo reciba
    # tiene que poder ver que es un borrador sin volver a la web.
    if not version.is_approved:
        piezas.append(Spacer(1, 10))
        piezas.append(Paragraph(escape(_(
            'Draft. This text has not been approved, and does not govern.'
        )), styles['note']))

    piezas.append(Spacer(1, 6))
    piezas.extend(html_to_flowables(version.body_for(language), styles))

    # La huella cierra el documento: es lo que permite comprobar que este
    # papel y lo que alguien acepto son el mismo texto.
    if version.content_hash:
        piezas.append(Spacer(1, 14))
        piezas.append(Paragraph(
            escape(_('Content fingerprint (SHA-256): %(hash)s')
                   % {'hash': version.content_hash}),
            styles['meta'],
        ))

    plantilla.build(piezas)

    return buffer.getvalue()
