from django import template
from django.urls import resolve
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def add_class(field, css_class):
    try:
        widget = field.as_widget(attrs={"class": css_class})
        return mark_safe(widget)
    except AttributeError:
        return field


@register.filter
def add_attrs(field, attrs: str):
    """
    Agrega atributos HTML a un campo de formulario.
    La entrada 'attrs' es una cadena con formato 'key1=value1,key2=value2'.

    Ejemplo de uso:
    {{ form.username|add_attrs:"class=form-control,placeholder=Username" }}
    """
    try:
        # Convertir la cadena en un diccionario de atributos
        attr_dict = dict(item.split('=') for item in attrs.split(','))
        widget = field.as_widget(attrs=attr_dict)
        return mark_safe(widget)
    except (AttributeError, ValueError) as e:
        return field


@register.filter
def currency(value):
    try:
        value = float(value)
        entero, decimal = f"{value:,.2f}".split(".")
        return mark_safe(f"$ {entero}.<span style='font-size: 12px;'>{decimal}</span>")
    except (ValueError, TypeError):
        return value


def _current_url_name(request):
    try:
        return resolve(request.path_info).url_name
    except Exception:
        return None


@register.simple_tag(takes_context=True)
def is_active(context, pattern_name):
    """Boolean: True si el url_name actual coincide con pattern_name."""
    try:
        return _current_url_name(context['request']) == pattern_name
    except Exception:
        return False


@register.simple_tag(takes_context=True)
def is_any_active(context, *pattern_names):
    """Boolean: True si el url_name actual está dentro de pattern_names."""
    cur = _current_url_name(context['request'])
    return cur in set(pattern_names)


@register.simple_tag(takes_context=True)
def active_class(context, *pattern_names):
    """Devuelve 'active' si coincide; de lo contrario, cadena vacía."""
    return 'active' if is_any_active(context, *pattern_names) else ''


@register.simple_tag(takes_context=True)
def collapse_open_class(context, *pattern_names):
    """Devuelve 'show' si alguna subruta está activa (para el <div class="collapse">)."""
    return 'show' if is_any_active(context, *pattern_names) else ''


@register.simple_tag(takes_context=True)
def link_collapsed_class(context, *pattern_names):
    """
    Devuelve 'collapsed' para el <a> del acordeón si NO hay subruta activa.
    (SB Admin Pro colapsa cuando no hay hijo activo)
    """
    return '' if is_any_active(context, *pattern_names) else 'collapsed'


@register.simple_tag(takes_context=True)
def aria_expanded(context, *pattern_names):
    """Devuelve 'true' si debe estar expandido; 'false' en caso contrario."""
    return 'true' if is_any_active(context, *pattern_names) else 'false'


@register.filter
def split(value, sep=' '):
    """
    Divide una cadena por el separador dado y devuelve una lista.
    Uso: {{ "a>b>c"|split:">" }}
    """
    if value is None:
        return []
    # Garantiza str y evita separar por '' (vacío)
    s = str(value)
    return s.split(sep) if sep else [s]


@register.filter
def trim(value):
    """
    Quita espacios en blanco al inicio y final.
    Uso: {{ "  texto  "|trim }}
    """
    if value is None:
        return ''
    return str(value).strip()


@register.filter
def messages_as_data(messages):
    """
    Los mensajes de Django como datos, listos para ``json_script``.

    Se entregan al navegador como JSON y no como HTML ya pintado porque el
    aviso se muestra en un toast flotante: un bloque dentro de la página
    aparece arriba del contenido, y quien acaba de pulsar un botón al pie de un
    formulario largo no lo ve.

    Y porque el texto de un mensaje puede venir de un error del servidor o de
    algo que escribió el usuario. Pintado con ``textContent`` desde JSON, no
    hay forma de que se convierta en marcado.

    Uso: {{ messages|messages_as_data|json_script:"djangoMessages" }}
    """
    return [
        {
            'level': message.level_tag or 'info',
            'message': str(message),
        }
        for message in messages
    ]
