# apps/common/utils/netintel.py
"""
Qué se puede decir de una IP **sin salir a la red**.

De dónde viene esto: mirando la tabla de bloqueos se ve a simple vista que
muchas de las IP que caen en la trampa pertenecen a rangos de proveedores
cloud. Y eso, por sí solo, ya es una señal: una persona navegando desde su
casa o su oficina sale por una IP residencial o corporativa. Un servidor de
AWS, Hetzner o DigitalOcean pidiendo ``/wp-login.php`` no es nadie
equivocándose de URL --es un proceso, y un proceso que busca instalaciones
vulnerables--. Distinguir esas dos cosas cambia lo que se hace con la fila.

La regla de oro de este módulo: **no hace peticiones**
------------------------------------------------------
Se llama desde el middleware, o sea dentro de una petición y con
``ATOMIC_REQUESTS`` puesto: cada milisegundo aquí es una transacción abierta
esperando. Una consulta a un servicio de reputación de IP metería una llamada
de red en el camino crítico de **todas** las peticiones, dependería de que ese
servicio esté vivo, y de paso le contaría a un tercero quién visita el sitio.

Así que se resuelve con lo que hay en el disco:

* **Datacenter/cloud**, con una tabla de prefijos que viaja en el repositorio.
  No pretende ser exhaustiva --las listas completas son cientos de miles de
  prefijos y cambian cada semana-- sino cubrir a los proveedores desde los que
  de verdad llega el escaneo automatizado. Un falso negativo aquí no rompe
  nada: la fila se queda sin la etiqueta y el bloqueo funciona igual.
* **País**, sólo si el operador ha configurado una base GeoLite2 en
  ``GEOIP_PATH``. Si no la hay, el campo se queda vacío y no pasa nada. No se
  añade la dependencia ni el fichero al repositorio: MaxMind tiene su propia
  licencia y su propio registro, y esto tiene que funcionar sin ellos.

Lo que **no** hace, y conviene no pedírselo
-------------------------------------------
No es atribución. Que una IP esté en un rango de OVH dice que hay una máquina
alquilada, no quién la alquiló; y una VPN comercial sale por rangos idénticos.
Por eso la etiqueta se guarda como un dato más de la fila y **no decide nada
por sí sola**: sirve para ordenar la tabla y para saber a qué se está mirando.
Bloquear a todo un proveedor cloud dejaría fuera de paso a integraciones
legítimas, a monitorizaciones y a media oficina detrás de una VPN.
"""

import ipaddress
import logging
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

#: Prefijos por operador. No es la lista completa de nadie --eso son cientos de
#: miles de entradas que cambian cada semana-- sino los rangos grandes y
#: estables desde los que llega el escaneo. Ampliarla es añadir una línea.
#:
#: Orden: se recorre entera y gana el prefijo **más específico**, no el
#: primero. Con solapamientos (un /12 de un operador dentro de un /8 heredado)
#: quedarse con el primero daría el dueño equivocado según cómo esté ordenada
#: la tabla, que es la clase de error que nadie mira.
DATACENTER_NETWORKS = {
    'Amazon AWS': [
        '3.0.0.0/8', '13.32.0.0/12', '13.48.0.0/12', '15.164.0.0/14',
        '16.12.0.0/14', '18.0.0.0/8', '23.20.0.0/14', '34.192.0.0/10',
        '35.152.0.0/13', '44.192.0.0/10', '52.0.0.0/8', '54.0.0.0/8',
        '99.77.0.0/16', '107.20.0.0/14', '172.96.0.0/12', '184.72.0.0/13',
        '204.236.0.0/14',
    ],
    'Google Cloud': [
        '34.0.0.0/10', '34.64.0.0/10', '35.184.0.0/13', '35.192.0.0/12',
        '35.208.0.0/12', '35.224.0.0/12', '35.240.0.0/13', '104.154.0.0/15',
        '104.196.0.0/14', '130.211.0.0/16', '146.148.0.0/17', '199.192.112.0/22',
    ],
    'Microsoft Azure': [
        '13.64.0.0/11', '20.0.0.0/8', '40.64.0.0/10', '51.4.0.0/15',
        '51.104.0.0/13', '52.224.0.0/11', '65.52.0.0/14', '104.40.0.0/13',
        '137.116.0.0/15', '138.91.0.0/16', '168.61.0.0/16', '191.232.0.0/13',
    ],
    'DigitalOcean': [
        '45.55.0.0/16', '104.131.0.0/16', '104.236.0.0/16', '138.68.0.0/16',
        '138.197.0.0/16', '139.59.0.0/16', '142.93.0.0/16', '143.110.0.0/16',
        '146.190.0.0/16', '157.230.0.0/16', '159.65.0.0/16', '159.89.0.0/16',
        '161.35.0.0/16', '164.90.0.0/16', '165.22.0.0/16', '167.71.0.0/16',
        '167.99.0.0/16', '174.138.0.0/16', '178.62.0.0/16', '188.166.0.0/16',
        '206.189.0.0/16', '207.154.0.0/16', '209.97.0.0/16',
    ],
    'Hetzner': [
        '5.9.0.0/16', '78.46.0.0/15', '88.99.0.0/16', '94.130.0.0/16',
        '95.216.0.0/15', '116.202.0.0/15', '128.140.0.0/17', '135.181.0.0/16',
        '138.201.0.0/16', '142.132.0.0/17', '144.76.0.0/16', '148.251.0.0/16',
        '159.69.0.0/16', '162.55.0.0/16', '167.235.0.0/16', '168.119.0.0/16',
        '176.9.0.0/16', '178.63.0.0/16', '188.34.0.0/16', '188.40.0.0/16',
        '195.201.0.0/16', '213.133.96.0/19', '213.239.192.0/18',
    ],
    'OVH': [
        '5.39.0.0/17', '5.135.0.0/16', '5.196.0.0/16', '37.59.0.0/16',
        '46.105.0.0/16', '51.68.0.0/16', '51.75.0.0/16', '51.83.0.0/16',
        '51.89.0.0/16', '51.91.0.0/16', '51.178.0.0/16', '51.195.0.0/16',
        '54.36.0.0/16', '87.98.128.0/17', '91.121.0.0/16', '135.125.0.0/16',
        '137.74.0.0/16', '139.99.0.0/16', '141.94.0.0/16', '145.239.0.0/16',
        '146.59.0.0/16', '147.135.0.0/16', '149.202.0.0/16', '151.80.0.0/16',
        '164.132.0.0/16', '167.114.0.0/16', '176.31.0.0/16', '178.32.0.0/15',
        '188.165.0.0/16', '192.99.0.0/16', '198.27.64.0/18', '213.32.0.0/17',
        '213.186.32.0/19', '217.182.0.0/16',
    ],
    'Linode / Akamai': [
        '45.33.0.0/17', '45.56.64.0/18', '45.79.0.0/16', '50.116.0.0/18',
        '66.175.208.0/20', '69.164.192.0/18', '72.14.176.0/20',
        '96.126.96.0/19', '104.200.16.0/20', '106.187.32.0/19',
        '139.144.0.0/16', '139.162.0.0/16', '143.42.0.0/16', '170.187.0.0/16',
        '172.104.0.0/15', '173.230.128.0/19', '173.255.192.0/18',
        '176.58.96.0/19', '178.79.128.0/17', '192.46.208.0/20',
        '192.155.80.0/20', '194.195.208.0/20', '198.58.96.0/19',
        '213.168.248.0/21',
    ],
    'Vultr': [
        '45.32.0.0/16', '45.63.0.0/16', '45.76.0.0/16', '45.77.0.0/16',
        '64.176.0.0/16', '66.42.32.0/19', '70.34.192.0/18', '78.141.192.0/18',
        '95.179.128.0/17', '104.156.224.0/19', '107.191.32.0/19',
        '108.61.0.0/16', '136.244.64.0/18', '139.180.128.0/17',
        '140.82.0.0/18', '141.164.32.0/19', '144.202.0.0/16', '149.28.0.0/16',
        '155.138.128.0/17', '158.247.192.0/18', '199.247.0.0/18',
        '207.148.0.0/18', '208.167.224.0/19', '209.222.0.0/19',
    ],
    'Oracle Cloud': [
        '129.146.0.0/16', '129.148.0.0/16', '129.153.0.0/16', '129.159.0.0/16',
        '130.61.0.0/16', '132.145.0.0/16', '138.2.0.0/16', '140.238.0.0/16',
        '141.147.0.0/16', '143.47.0.0/16', '144.24.0.0/16', '146.235.0.0/16',
        '150.136.0.0/16', '152.67.0.0/16', '158.101.0.0/16', '168.138.0.0/16',
        '193.122.0.0/16',
    ],
    'Alibaba Cloud': [
        '8.208.0.0/12', '47.52.0.0/14', '47.74.0.0/15', '47.88.0.0/14',
        '47.235.0.0/16', '47.236.0.0/14', '47.240.0.0/14', '47.244.0.0/15',
        '47.250.0.0/15', '47.254.0.0/16', '112.124.0.0/14', '120.24.0.0/14',
        '120.76.0.0/14', '121.196.0.0/14', '182.92.0.0/16',
    ],
    'Tencent Cloud': [
        '43.128.0.0/12', '49.51.0.0/16', '101.32.0.0/16', '119.28.0.0/16',
        '124.156.0.0/16', '129.226.0.0/16', '150.109.0.0/16', '170.106.0.0/16',
    ],
    'Scaleway': [
        '51.15.0.0/16', '51.158.0.0/16', '62.210.0.0/16', '163.172.0.0/16',
        '195.154.0.0/16', '212.47.224.0/19', '212.83.128.0/19', '212.129.0.0/18',
    ],
    'Contabo': [
        '5.189.128.0/17', '62.171.128.0/17', '75.119.128.0/17', '84.46.240.0/20',
        '144.91.64.0/18', '154.12.224.0/19', '158.220.80.0/20',
        '161.97.64.0/18', '167.86.64.0/18', '173.212.192.0/18',
        '173.249.0.0/18', '178.238.224.0/19', '194.163.128.0/17',
        '207.180.192.0/18', '213.136.64.0/18',
    ],
    'Cloudflare': [
        '103.21.244.0/22', '103.22.200.0/22', '104.16.0.0/13', '104.24.0.0/14',
        '141.101.64.0/18', '162.158.0.0/15', '172.64.0.0/13', '173.245.48.0/20',
        '188.114.96.0/20', '190.93.240.0/20', '197.234.240.0/22',
        '198.41.128.0/17',
    ],
}


@lru_cache(maxsize=1)
def _compiled_networks():
    """
    La tabla de arriba, ya compilada y ordenada de más específica a menos.

    Se compila una sola vez por proceso: son unos cientos de objetos
    ``ip_network`` y construirlos en cada petición sería tirar CPU. Y se
    ordena por longitud de prefijo para que el más específico gane, que es lo
    que evita que el dueño dependa del orden en que estén escritas.
    """
    compiled = []

    for owner, prefixes in DATACENTER_NETWORKS.items():
        for prefix in prefixes:
            try:
                compiled.append((ipaddress.ip_network(prefix), owner))
            except ValueError:
                logger.warning('netintel: prefijo mal escrito: %s', prefix)

    compiled.sort(key=lambda item: item[0].prefixlen, reverse=True)

    return compiled


def network_owner(ip: str):
    """
    El operador del rango, o ``None`` si no está en la tabla.

    ``None`` no significa «residencial»: significa «no lo sé». La tabla cubre
    a los proveedores desde los que llega el escaneo, no a todo internet.
    """
    if not ip:
        return None

    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None

    for network, owner in _compiled_networks():
        if address.version == network.version and address in network:
            return owner

    return None


def country_code(ip: str):
    """
    El país de la IP en dos letras, o ``None``.

    Sólo contesta si el operador ha configurado una base GeoLite2
    (``GEOIP_PATH``). No se añade el fichero al repositorio ni la dependencia:
    MaxMind tiene su licencia y su registro, y todo esto tiene que funcionar
    sin ellos. Sin base, el campo se queda vacío y la fila sigue siendo útil.

    Nunca lanza: esto se llama desde el middleware, y un fallo mirando el país
    no puede tumbar una petición.
    """
    if not ip or not getattr(settings, 'GEOIP_PATH', None):
        return None

    reader = _geoip()

    if reader is None:
        return None

    try:
        return reader.country_code(ip) or None
    except Exception:  # noqa: BLE001
        # Una IP privada, o una que no está en la base. No es un error.
        logger.debug('netintel: no se pudo resolver el pais de %s', ip)
        return None


@lru_cache(maxsize=1)
def _geoip():
    """El lector de GeoIP2, abierto una vez por proceso, o ``None``."""
    try:
        from django.contrib.gis.geoip2 import GeoIP2

        return GeoIP2()
    except Exception:  # noqa: BLE001
        logger.info(
            'netintel: GEOIP_PATH configurado pero la base no se pudo abrir; '
            'el pais de los bloqueos se quedara vacio'
        )
        return None


def describe(ip: str) -> dict:
    """
    Lo que se sabe de una IP, para guardarlo en la fila del bloqueo.

    Returns:
        dict: ``network_owner`` (str|None), ``is_datacenter`` (bool) y
        ``country`` (str|None).
    """
    owner = network_owner(ip)

    return {
        'network_owner': owner,
        'is_datacenter': owner is not None,
        'country': country_code(ip),
    }
