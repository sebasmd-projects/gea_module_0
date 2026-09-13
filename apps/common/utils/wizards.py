# apps/common/utils/wizards.py
"""
Lo que hay que decirle a `formtools` cuando los pasos cambian a mitad de vuelo.

Desde **django-formtools 2.6**, ``WizardView.get_form_list()`` resuelve las
condiciones **una vez por petición** y se guarda el resultado en
``_resolved_form_list``. Es una optimización razonable --una condición puede
costar una consulta-- pero su invalidación tiene un límite que conviene
entender antes de tropezar con él.

La firma de la caché es::

    (id(self.condition_dict), tuple(sorted(self.condition_dict.items())))

O sea: la **identidad** del diccionario de condiciones y de sus valores. No lo
que esas condiciones *devuelven*. Si una condición es un invocable cuyo
resultado depende de algo de fuera --la sesión, por ejemplo-- puede cambiar de
respuesta sin que la firma se mueva un milímetro, y la caché seguirá sirviendo
la lista vieja. Lo mismo pasa si se reemplaza ``self.form_list`` después de
que la lista ya se resolviera.

Este proyecto hace las dos cosas, en dos sitios y por buenas razones:

* el **asistente de acceso** entra y sale del modo código dentro de la misma
  petición, y ese modo decide si existe el paso ``otp``;
* el **asistente de PQRS** cambia el formulario del paso de titular según sea
  persona natural o jurídica.

Con la caché puesta y sin invalidar, lo primero daba ``KeyError: 'otp'`` --el
asistente ponía como paso actual uno que su propia lista decía que no
existía-- y lo segundo enseñaba el formulario de persona natural en la rama de
persona jurídica, así que la solicitud no llegaba a guardarse.

Nada de esto es un fallo de la biblioteca: es que una condición que cambia
dentro de la misma petición rompe cualquier caché que no lo sepa. La respuesta
es avisarla, que es exactamente lo que ``formtools`` hace en su propio
``post()`` después de guardar los datos de un paso.
"""

#: Los atributos donde `formtools` guarda la lista ya resuelta y su firma.
#:
#: Son privados, sí. La alternativa sería recalcular la lista a mano y
#: sustituirla, que es más frágil: dependería de reproducir la lógica de
#: resolución en vez de sólo pedirle que la repita.
CACHE_ATTRIBUTES = ('_resolved_form_list', '_condition_dict_signature')


def forget_resolved_steps(wizard) -> None:
    """
    Olvida la lista de pasos que el asistente tenga cacheada.

    Llámalo **justo después** de cambiar algo que afecte a qué pasos hay o a
    qué formulario lleva cada uno, y antes de volver a pedir un formulario.

    Es seguro llamarlo de más: si no hay nada cacheado --o si la versión de
    ``formtools`` no cachea nada, como antes de la 2.6-- no hace nada.

    Args:
        wizard: la vista de asistente (``WizardView`` o descendiente).
    """
    for attribute in CACHE_ATTRIBUTES:
        if hasattr(wizard, attribute):
            delattr(wizard, attribute)
