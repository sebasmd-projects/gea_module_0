"""
Qué motor de base de datos se instala de verdad, según el declarado.

El `.env` declara el motor de Django (`django.db.backends.mysql`). Con MySQL y
MariaDB lo que se instala es el de `app_core/db/mysql`, que es ese mismo con
una diferencia: los UUID se siguen guardando como se guardaron. El porqué
completo está en `app_core/db/mysql/base.py`.

La decisión vive aquí y no suelta en `settings.py` por una razón práctica: así
se puede probar. Repetir la regla en una prueba la deja pasando aunque
`settings.py` haga otra cosa, que es justo lo que no se quiere comprobar.
"""

#: El motor de Django que hay que sustituir, y por cuál.
MYSQL = 'django.db.backends.mysql'
GEA_MYSQL = 'app_core.db.mysql'


def engine_for(declared: str) -> str:
    """
    El motor a instalar para el que se declaró en el `.env`.

    Cualquier otro --PostgreSQL, SQLite-- se queda como está: el cambio es de
    MySQL. En PostgreSQL el UUID es nativo desde siempre y sus columnas se
    escribieron así.
    """
    return GEA_MYSQL if declared == MYSQL else declared
