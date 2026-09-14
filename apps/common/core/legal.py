"""
Quien acepto que, y como se deja constancia.

Lo que exige la ley
-------------------
El articulo 9 de la Ley 1581 de 2012 y el 7 del Decreto 1377 de 2013 no piden
saber que el titular acepto: piden **poder demostrarlo**. Y demostrar una
autorizacion son cuatro cosas, no una:

* **quien** — el usuario,
* **cuando** — la fecha y hora,
* **que** — no «los terminos», sino el texto exacto: version y huella,
* **como** — casilla marcada en el alta, o conducta posterior a un aviso.

Las cuatro se guardan en `LegalAcceptanceModel`. La tercera es la que se suele
olvidar y la unica que no se puede reconstruir despues: si el texto se
reescribe y no se guardo su huella, la constancia dice que alguien acepto algo
sin decir el que.

Los dos caminos, que no valen lo mismo
--------------------------------------
1. **En el alta** (`REGISTRATION`): consentimiento expreso. El titular marco
   una casilla teniendo el texto delante.
2. **Al entrar, despues de un aviso** (`CONTINUED_USE`): consentimiento por
   conducta. Mas debil, y por eso se guarda **con su etiqueta propia** en vez
   de mezclarlo con el anterior: el dia que haya que defender una autorizacion,
   lo primero que se pregunta es de cual de las dos se trata.

   Este camino solo se recorre **despues** de que el usuario haya sido avisado
   del cambio (`notify_legal_changes`). Aceptacion por conducta sin aviso
   previo no es aceptacion de nada, y por eso el aviso va primero.

Que pasa mientras no hay nada aprobado
--------------------------------------
Hoy los cuatro documentos son borradores. Se registra igualmente la aceptacion
de lo que el titular **vio**, borrador incluido: lo que no puede pasar es que
alguien marque la casilla y no quede rastro. Por eso un borrador tambien lleva
huella (`LegalDocumentVersionModel.save()`).
"""

import logging

from django.db import IntegrityError, transaction

from .models import (AcceptanceMethod, LegalAcceptanceModel,
                     LegalDocumentModel, LegalAcceptanceModel as Acceptance)

logger = logging.getLogger(__name__)

#: Cuanto del User-Agent se guarda. Lo que identifica al navegador esta al
#: principio; lo que sigue son listas de motores que no aportan nada.
MAX_USER_AGENT = 400


def client_ip(request):
    """
    La IP de quien acepta, mirando primero la cabecera del proxy.

    En produccion la aplicacion va detras del servidor web, asi que
    `REMOTE_ADDR` seria siempre la misma y no serviria como constancia.
    """
    if request is None:
        return None

    reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')

    if reenviada:
        return reenviada.split(',')[0].strip() or None

    return request.META.get('REMOTE_ADDR') or None


def user_agent(request):
    if request is None:
        return ''

    return (request.META.get('HTTP_USER_AGENT') or '')[:MAX_USER_AGENT]


def versions_in_force():
    """
    La version que hay que aceptar de cada documento, hoy.

    Si un documento no tiene nada aprobado se coge su ultimo borrador, que es
    lo que se le enseña al titular: la constancia tiene que recoger lo que
    vio, no lo que nos habria gustado enseñarle.
    """
    versiones = []

    for documento in LegalDocumentModel.objects.filter(is_active=True):
        version = documento.displayed_version()

        if version is not None:
            versiones.append(version)

    return versiones


def pending_for(user):
    """
    Lo que este usuario todavia no ha aceptado.

    Vacio es lo normal: solo deja de estarlo cuando se aprueba una version
    nueva de algo.
    """
    if user is None or not user.is_authenticated:
        return []

    aceptadas = set(
        Acceptance.objects.filter(user=user).values_list('version_id', flat=True)
    )

    return [v for v in versions_in_force() if v.pk not in aceptadas]


def record_acceptance(user, version, method, request=None):
    """
    Deja constancia de una aceptacion. Devuelve la fila, o `None` si ya estaba.

    Es idempotente por `(usuario, version)`: entrar diez veces no son diez
    autorizaciones, es una. La restriccion esta tambien en la base, asi que el
    `IntegrityError` se atrapa en vez de comprobarse antes --comprobar primero
    y escribir despues deja una carrera entre dos peticiones del mismo usuario,
    que con dos pestañas abiertas no es hipotetico.
    """
    if user is None or not user.is_authenticated or version is None:
        return None

    try:
        with transaction.atomic():
            return LegalAcceptanceModel.objects.create(
                user=user,
                version=version,
                content_hash=version.content_hash,
                method=method,
                ip_address=client_ip(request),
                user_agent=user_agent(request),
            )
    except IntegrityError:
        return None


def accept_all_in_force(user, method, request=None):
    """
    Registra la aceptacion de todo lo que este usuario tiene pendiente.

    Se usa en los dos caminos: en el alta con `REGISTRATION` y al entrar con
    `CONTINUED_USE`.
    """
    registradas = []

    for version in pending_for(user):
        fila = record_acceptance(user, version, method, request)

        if fila is not None:
            registradas.append(fila)

    return registradas


def accept_on_registration(user, request=None):
    """La casilla del alta: consentimiento expreso sobre lo que se enseño."""
    return accept_all_in_force(user, AcceptanceMethod.REGISTRATION, request)


def accept_on_login(user, request=None):
    """
    Entrar despues de un cambio: consentimiento por conducta.

    **No se registra lo que el usuario no ha podido ver.** Solo cuenta una
    version que ya fue avisada (`notified_at`) o que no requeria aviso; si se
    aprobo algo hace un minuto y el correo todavia no ha salido, entrar no
    puede valer como aceptarlo. Esa espera es lo unico que separa el
    consentimiento por conducta de darlo por hecho.
    """
    pendientes = [
        version for version in pending_for(user)
        if version.notified_at is not None or not version.notify_users
    ]

    registradas = []

    for version in pendientes:
        fila = record_acceptance(
            user, version, AcceptanceMethod.CONTINUED_USE, request
        )

        if fila is not None:
            registradas.append(fila)

    if registradas:
        logger.info(
            'Aceptacion por uso continuado: usuario=%s versiones=%s',
            user.pk, [str(f.version_id) for f in registradas],
        )

    return registradas
