from django import template
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
        return f"$ {value:,.2f}"
    except (ValueError, TypeError):
        return value
