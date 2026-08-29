# apps/project/specific/internal/code_gen/services/jcs.py
"""
Canonicalizacion JSON segun RFC 8785 (JCS).

Por que hace falta: ``{"a":1,"b":2}`` y ``{"b":2,"a":1}`` son el mismo objeto
pero dan SHA-256 distintos. Si el master hash va a anclarse en una TSA o en
Bitcoin, la regla para pasar de objeto a bytes tiene que estar fijada y ser
reproducible por un tercero anos despues.

Diferencias con ``json.dumps(sort_keys=True)``, que es lo que ya usa el
registro de certificacion:

- JCS ordena las claves por **unidades de codigo UTF-16**, no por puntos de
  codigo. Solo difieren con caracteres fuera del BMP (emoji, por ejemplo).
- JCS fija la serializacion de los numeros con las reglas de ECMAScript.

Aqui se implementa el orden UTF-16 correcto y se **rechazan los flotantes**:
el payload maestro solo lleva cadenas y enteros, y aceptar flotantes obligaria
a reproducir el algoritmo de ECMAScript, que es la parte fragil de JCS. Mejor
fallar ruidosamente que emitir un hash que otro no pueda recalcular.
"""

import json
from typing import Any


class CanonicalizationError(ValueError):
    """El valor no se puede canonicalizar de forma reproducible."""


def _sort_key(key: str):
    """
    Clave de ordenacion por unidades de codigo UTF-16, como exige RFC 8785.

    Para claves ASCII coincide con el orden por puntos de codigo; se hace
    explicito para que siga siendo correcto si alguna vez entra un caracter
    fuera del BMP.
    """
    return key.encode('utf-16-be')


def _check(value: Any, path: str = '$') -> None:
    """Recorre el valor y rechaza lo que no se pueda canonicalizar."""
    if value is None or isinstance(value, (str, bool)):
        return

    if isinstance(value, float):
        raise CanonicalizationError(
            f'{path}: los flotantes no se admiten en el payload canonico; '
            'usa cadenas o enteros.'
        )

    if isinstance(value, int):
        return

    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check(item, f'{path}[{index}]')
        return

    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f'{path}: las claves tienen que ser cadenas.'
                )
            _check(item, f'{path}.{key}')
        return

    raise CanonicalizationError(
        f'{path}: tipo no admitido ({type(value).__name__}).'
    )


def _ordered(value: Any) -> Any:
    """Reconstruye el valor con los diccionarios ya ordenados."""
    if isinstance(value, dict):
        return {
            key: _ordered(value[key])
            for key in sorted(value.keys(), key=_sort_key)
        }

    if isinstance(value, (list, tuple)):
        return [_ordered(item) for item in value]

    return value


def canonicalize(value: Any) -> bytes:
    """
    Serializa un valor a su forma canonica JCS.

    Returns:
        bytes: JSON compacto, claves ordenadas, UTF-8.

    Raises:
        CanonicalizationError: si el valor lleva flotantes, claves no textuales
        o tipos que no se puedan representar de forma estable.
    """
    _check(value)

    return json.dumps(
        _ordered(value),
        ensure_ascii=False,
        separators=(',', ':'),
        allow_nan=False,
    ).encode('utf-8')


def canonical_text(value: Any) -> str:
    """La forma canonica como texto, para mostrarla a un auditor."""
    return canonicalize(value).decode('utf-8')
