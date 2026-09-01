# apps/project/common/pqrs/deadlines.py
"""
Los plazos de la Ley 1581 de 2012, contados en dias habiles.

Esta es la parte del modulo que tiene sustancia. El resto --un formulario, un
correo de acuse-- es trabajo corriente; lo que de verdad se puede hacer mal
aqui es el conteo, porque de el depende si una respuesta llega a tiempo o la
entidad incumple.

Los dos plazos, y de donde salen
--------------------------------
* **Consulta: 10 dias habiles**, prorrogables 5 mas (art. 14).
* **Reclamo: 15 dias habiles**, prorrogables 8 mas (art. 15).

En los dos casos el conteo empieza **al dia siguiente** de la recepcion, no el
mismo dia, y la prorroga se cuenta desde el vencimiento del primer termino.
Hay ademas un tercer plazo que no es de respuesta sino de subsanacion: si el
reclamo llega incompleto se requiere al interesado dentro de los 5 dias, y si
no contesta en 2 meses se entiende que desistio.

Por que no vale ``timedelta(days=15)``
--------------------------------------
Porque "habil" excluye sabados, domingos y **festivos**, y Colombia tiene
dieciocho al ano, la mayoria movibles: la Ley 51 de 1983 traslada buena parte
de ellos al lunes siguiente, y otros --Jueves y Viernes Santo, Ascension,
Corpus Christi, Sagrado Corazon-- dependen de la Pascua, que se calcula con el
algoritmo de Gauss. Contar dias corridos da de menos: un plazo de quince
habiles en Semana Santa son mas de tres semanas de calendario.

Equivocarse aqui no es un detalle de presentacion. Da una fecha de vencimiento
antes de la real --y entonces el panel marca en rojo lo que va a tiempo-- o
despues, que es peor: la solicitud parece dentro de plazo el dia en que ya se
incumplio.
"""

from datetime import date, timedelta

# --- Festivos fijos: (mes, dia) ----------------------------------------
FIXED_HOLIDAYS = (
    (1, 1),    # Ano nuevo
    (5, 1),    # Dia del trabajo
    (7, 20),   # Independencia
    (8, 7),    # Batalla de Boyaca
    (12, 8),   # Inmaculada Concepcion
    (12, 25),  # Navidad
)

# --- Festivos que la Ley 51 de 1983 traslada al lunes siguiente --------
#
# "Ley Emiliani": el festivo no se celebra el dia que cae, sino el lunes
# posterior. Sin esto, un festivo que cae en miercoles se contaria como habil
# el lunes en que de verdad no se trabaja.
MOVED_HOLIDAYS = (
    (1, 6),    # Reyes Magos
    (3, 19),   # San Jose
    (6, 29),   # San Pedro y San Pablo
    (8, 15),   # Asuncion
    (10, 12),  # Dia de la raza
    (11, 1),   # Todos los santos
    (11, 11),  # Independencia de Cartagena
)

# --- Festivos que dependen de la Pascua --------------------------------
#
# El numero es cuantos dias despues del Domingo de Pascua cae. Los tres
# ultimos se trasladan ademas al lunes siguiente.
EASTER_OFFSETS = {
    'jueves_santo': (-3, False),
    'viernes_santo': (-2, False),
    'ascension': (43, True),
    'corpus_christi': (64, True),
    'sagrado_corazon': (71, True),
}


def easter_sunday(year: int) -> date:
    """
    Domingo de Pascua por el algoritmo de Gauss (computus gregoriano).

    Se calcula en vez de tabularse para que el sistema no caduque: una tabla
    de festivos hay que acordarse de ampliarla, y el ano que se olvide los
    plazos empiezan a salir mal en silencio.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)

    return date(year, month, day + 1)


def next_monday(value: date) -> date:
    """El lunes siguiente, o el mismo dia si ya es lunes."""
    return value + timedelta(days=(7 - value.weekday()) % 7)


def holidays(year: int) -> frozenset:
    """Todos los festivos de un ano en Colombia."""
    days = {date(year, month, day) for month, day in FIXED_HOLIDAYS}

    days.update(
        next_monday(date(year, month, day)) for month, day in MOVED_HOLIDAYS
    )

    easter = easter_sunday(year)

    for offset, moves in EASTER_OFFSETS.values():
        holiday = easter + timedelta(days=offset)
        days.add(next_monday(holiday) if moves else holiday)

    return frozenset(days)


def is_business_day(value: date) -> bool:
    """Ni sabado, ni domingo, ni festivo."""
    if value.weekday() >= 5:
        return False

    return value not in holidays(value.year)


def add_business_days(start: date, days: int) -> date:
    """
    La fecha que cae ``days`` dias habiles despues de ``start``.

    El dia de partida **no cuenta**: el articulo 14 dice "contados a partir
    del dia siguiente a la fecha de recibo", asi que una consulta recibida un
    lunes empieza a contar el martes.

    Parameters:
        start (date): el dia de la recepcion.
        days (int): cuantos dias habiles.

    Returns:
        date: el ultimo dia del plazo.
    """
    if days <= 0:
        return start

    current = start
    remaining = days

    while remaining:
        current += timedelta(days=1)

        if is_business_day(current):
            remaining -= 1

    return current


def business_days_between(start: date, end: date) -> int:
    """
    Cuantos dias habiles van de ``start`` a ``end``, sin contar ``start``.

    Negativo si ``end`` es anterior. Sirve para saber cuantos dias quedan --o
    cuantos se lleva de retraso-- sin volver a calcular el plazo entero.
    """
    if end == start:
        return 0

    step = 1 if end > start else -1
    current = start
    count = 0

    while current != end:
        current += timedelta(days=step)

        if is_business_day(current):
            count += step

    return count
