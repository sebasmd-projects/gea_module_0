"""
Deja el HTML de un documento legal en las etiquetas que estan permitidas.

Por que hace falta, si lo escribe el propio personal
---------------------------------------------------
Porque estas paginas son **publicas y sin autenticar**, y el editor tiene boton
de «editar codigo fuente». Sin sanear, quien pueda entrar al admin puede poner
un `<script>` en una pagina que ve todo el que visita el sitio --incluida la
gente que llega desde el QR de un certificado. Eso no es «lo mismo que ya
podria hacer un administrador»: el resto de lo que toca el admin lo ven
usuarios autenticados, esto lo ve cualquiera.

Y no se arregla confiando en la cuenta. Una cuenta de personal se puede
perder, y el segundo factor del admin protege la puerta, no lo que se escribe
una vez dentro. Sanear la salida hace que el peor caso de esa perdida sea un
texto legal equivocado --malo, visible y reversible-- en vez de codigo
ejecutandose en el navegador de cada visitante.

Por que a mano y no con una biblioteca
--------------------------------------
`bleach` esta archivado y `nh3` trae una extension compilada de Rust, que en el
cPanel donde esto se despliega es una dependencia que puede no instalarse. Lo
que hace falta aqui es una lista blanca de doce etiquetas, que son las mismas
que ofrece el editor y las mismas que sabe pintar el PDF. Una biblioteca
general resolveria un problema mas grande del que hay.

**La lista vive aqui y la leen los tres**: el editor la ofrece
(`CKEDITOR_5_CONFIGS['legal']`), esto la deja pasar y `legal_pdf.py` la pinta.
Si divergen, algo que se escribe no se ve, o algo que se ve no llega al papel.
"""

from html import escape
from html.parser import HTMLParser

#: Etiquetas que sobreviven. Cualquier otra se descarta **conservando su
#: texto**: perder una etiqueta desmaqueta un parrafo, perder el texto borra
#: una clausula.
ALLOWED_TAGS = {
    'p', 'br', 'hr',
    'h2', 'h3', 'h4',
    'b', 'strong', 'i', 'em', 'u',
    'ul', 'ol', 'li',
    'dl', 'dt', 'dd',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'a', 'code', 'blockquote', 'div', 'span', 'figure',
}

#: Atributos que sobreviven, por etiqueta. Todo lo demas se cae, y eso incluye
#: cualquier `on*`: no hay lista negra de manejadores de eventos porque no
#: hace falta ninguna — lo que no esta aqui no pasa.
ALLOWED_ATTRS = {
    'a': {'href', 'title'},
    'div': {'class'},
    'span': {'class'},
    'table': {'class'},
    'th': {'colspan', 'rowspan', 'scope'},
    'td': {'colspan', 'rowspan'},
    'figure': {'class'},
}

#: Etiquetas sin cierre.
VOID_TAGS = {'br', 'hr'}

#: Esquemas que puede llevar un enlace. `javascript:` es el que importa, pero
#: la lista es blanca por el mismo motivo que la de atributos: `data:` y
#: `vbscript:` tambien ejecutan, y manana habra otro.
ALLOWED_SCHEMES = ('http://', 'https://', 'mailto:', 'tel:')


def _safe_href(value: str) -> str | None:
    """Un enlace absoluto de esquema conocido, o uno relativo del propio sitio."""
    destino = (value or '').strip()

    if not destino:
        return None

    minuscula = destino.lower()

    if minuscula.startswith(ALLOWED_SCHEMES):
        return destino

    # Relativo dentro del sitio. `//otro.sitio` NO lo es, aunque empiece por
    # barra: es un enlace absoluto sin esquema.
    if destino.startswith('/') and not destino.startswith('//'):
        return destino

    if destino.startswith('#'):
        return destino

    return None


class _Saneador(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.piezas = []
        self._abiertas = []

    def handle_starttag(self, tag, attrs):
        if tag not in ALLOWED_TAGS:
            return

        permitidos = ALLOWED_ATTRS.get(tag, set())
        salida = []

        for nombre, valor in attrs:
            if nombre not in permitidos:
                continue

            if nombre == 'href':
                valor = _safe_href(valor)

                if valor is None:
                    continue

            salida.append(f' {nombre}="{escape(valor or "", quote=True)}"')

        if tag in VOID_TAGS:
            self.piezas.append(f'<{tag}{"".join(salida)} />')
            return

        self._abiertas.append(tag)
        self.piezas.append(f'<{tag}{"".join(salida)}>')

    def handle_startendtag(self, tag, attrs):
        if tag in VOID_TAGS:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS:
            return

        # Solo se cierra lo que se abrio. Un `</p>` suelto que el editor deje
        # colgando no puede cerrar el bloque del que todavia no se ha salido.
        if tag in self._abiertas:
            while self._abiertas:
                abierta = self._abiertas.pop()
                self.piezas.append(f'</{abierta}>')

                if abierta == tag:
                    break

    def handle_data(self, data):
        self.piezas.append(escape(data))

    def close(self):
        super().close()

        while self._abiertas:
            self.piezas.append(f'</{self._abiertas.pop()}>')

    def resultado(self) -> str:
        return ''.join(self.piezas)


def sanitize_legal_html(html: str) -> str:
    """
    El mismo texto, sin nada que el navegador pueda ejecutar.

    Lo que no esta en la lista blanca se cae **conservando su contenido**: el
    texto de un documento legal no puede desaparecer porque llevara una
    etiqueta que aqui no se contempla.
    """
    saneador = _Saneador()
    saneador.feed(html or '')
    saneador.close()

    return saneador.resultado()
