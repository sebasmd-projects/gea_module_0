# apps/common/utils/tests/test_horizontal_scroll.py
"""
Que el panel no se ensanche en el movil.

En «Purchase Orders», en un telefono, la pagina se podia arrastrar de lado y
la barra superior se estiraba con ella: el boton del menu y el del usuario
quedaban fuera de la pantalla. No era una tabla sin contenedor --la tabla
estaba dentro del ``.datatable-container``, que tiene su propio scroll--, era
lo que el kit de Font Awesome mete al lado de cada icono con ``title``: un
``<span class="sr-only">`` con ``position: absolute``.

Un contenedor con scroll solo recorta a los descendientes cuyo bloque
contenedor esta dentro de el, y ni ``.table-responsive`` ni el contenedor de
simple-datatables estaban posicionados. Ese span se escapaba del scroll de la
tabla y ensanchaba la pagina hasta 1068 px; ``overflow-x: hidden`` en el
``body`` lo tapa en escritorio, pero el navegador movil agranda el viewport.

Se mide con un navegador, no aqui: estas pruebas fijan las dos cosas que lo
evitan --la regla de CSS, cargada en todas las paginas, y que el HTML del
panel llegue con las etiquetas cerradas--, que es lo que un cambio descuidado
puede quitar sin que nada mas lo note.

    manage.py test apps.common.utils.tests.test_horizontal_scroll \\
        --settings=app_core.settings_test
"""

import re
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel

CSS = Path(settings.BASE_DIR) / 'public' / 'staticfiles' / 'css' / 'scroll_behavior.css'
RAW = Path(settings.BASE_DIR) / 'templates' / 'raw.html'


def rules_for(selector, css):
    """Las declaraciones de los bloques cuyo selector incluye ``selector``."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    found = []

    for selectors, body in re.findall(r'([^{}]+)\{([^}]*)\}', css):
        names = [s.strip() for s in selectors.split(',')]

        if selector in names:
            found.append(body)

    return ' '.join(found)


class TestScrollContainersClipTheirContent(SimpleTestCase):

    def setUp(self):
        self.css = CSS.read_text(encoding='utf-8')

    def test_the_stylesheet_is_loaded_on_every_page(self):
        self.assertIn("css/scroll_behavior.css", RAW.read_text(encoding='utf-8'))

    def test_scroll_containers_are_the_containing_block(self):
        """
        Sin ``position``, un hijo absoluto se posiciona contra un ancestro de
        fuera y el scroll del contenedor no lo recorta.
        """
        for selector in ('.table-responsive', '.datatable-container'):
            with self.subTest(selector=selector):
                self.assertRegex(
                    rules_for(selector, self.css), r'position:\s*relative'
                )

    def test_the_content_area_clips_whatever_still_escapes(self):
        """
        ``clip`` y no ``hidden``: ``hidden`` lo convierte en contenedor de
        scroll, rompe ``position: sticky`` y deja un segundo scroll vertical.
        """
        self.assertRegex(
            rules_for('#layoutSidenav_content', self.css),
            r'overflow-x:\s*clip',
        )


class TagBalance(HTMLParser):
    """
    Apunta las etiquetas que se cierran sin haberse abierto y las que quedan
    abiertas cuando otra las cierra por arriba.

    Las de cierre opcional (``p``, ``li``, ``td``…) no cuentan: el HTML
    permite omitirlas y no es lo que se busca aqui.
    """

    VOID = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
        'meta', 'source', 'track', 'wbr',
        # SVG: casi siempre autocerrados, y el parser no los distingue.
        'path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'use',
        'stop', 'ellipse',
    }
    OPTIONAL = {
        'p', 'li', 'td', 'th', 'tr', 'option', 'thead', 'tbody', 'tfoot',
        'dt', 'dd',
    }

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return

        if tag not in (name for name, _ in self.stack):
            self.errors.append(f'line {self.getpos()[0]}: stray </{tag}>')
            return

        while self.stack:
            name, line = self.stack.pop()

            if name == tag:
                break

            if name not in self.OPTIONAL:
                self.errors.append(
                    f'line {self.getpos()[0]}: </{tag}> closes '
                    f'<{name}> opened at line {line}'
                )


class TestDashboardPagesCloseTheirTags(TestCase):
    """
    Un ``<div>`` sin cerrar no rompe la pagina a la vista: el navegador lo
    cierra donde puede, y lo que cambia es que bloque contiene a cual. En
    cambiar la contrasena la ``.row`` de las dos contrasenas se quedaba
    abierta y la cerraba el ``</form>``.
    """

    PAGES = (
        'buyers:buyer_index',
        'buyers:buyer_create',
        'buyers:profitability_view',
        'buyers:inventory_view',
        'assets:holder_index',
        'assets:create',
        'assets:add_category',
        'assets_location:add_location',
        'assets_location:add_asset_location',
        'code_gen:code_history',
        'code_gen:code_generate',
        'code_gen:summary_list',
        'code_gen:layout_list',
        'account:change_password',
        'two_factor:profile',
    )

    def setUp(self):
        user = UserModel.objects.create_superuser(
            username='layout', email='layout@example.com', password='pw-123',
        )
        self.client.force_login(user)

    def test_every_tag_is_closed(self):
        for name in self.PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))

                self.assertEqual(response.status_code, 200)

                parser = TagBalance()
                parser.feed(response.content.decode())
                parser.close()

                left_open = [
                    f'<{tag}> opened at line {line}'
                    for tag, line in parser.stack
                    if tag not in TagBalance.OPTIONAL
                ]

                self.assertEqual(parser.errors + left_open, [])
