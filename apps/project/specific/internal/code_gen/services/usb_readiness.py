"""
Si un resumen esta listo para llevarselo en un USB, y si no, por que no.

Por que hay una puerta antes de exportar
----------------------------------------
Un USB sale de aqui y ya no vuelve. No se actualiza, no avisa y no se puede
retirar: lo que se grabe es lo que un titular le enseñara a un banco, a un
notario o a un comprador dentro de dos años. Exportar un resumen a medias
--sellado pero sin confirmar en la cadena, o con un anclaje que ya no cubre el
master hash actual-- es repartir un dossier que **parece** prueba y no lo es.
Y el que lo recibe no tiene forma de notarlo, porque el soporte no dice nada.

De ahi que esto no sea un aviso sino una condicion: sin las cinco en verde no
se genera el paquete.

Por que cinco comprobaciones y no una
-------------------------------------
Porque «no esta listo» tiene cinco causas distintas y cada una se arregla de
una manera. Un boton apagado sin explicacion manda a quien lo pulsa a
preguntar por el chat interno; una lista que dice cual falta y que hacer, no.
Es la misma razon por la que la franja de aprobacion de un documento legal
distingue tres estados en vez de deshabilitarse.

Que cuenta como verde
---------------------
1. **Activo** — `is_active`. El borrado es logico en este proyecto, y un
   resumen retirado no se reparte.
2. **Sellado y cuadrando** — hay master hash, los bytes guardados lo producen
   y esos bytes siguen describiendo a los miembros de ahora. Las tres cosas:
   un sello que ya no cuadra con sus miembros es peor que no tenerlo.
3. **Con papel emitido** — el PDF del resumen existe, esta certificado y su
   copia publica esta en disco. Sin el no hay nada que enseñar, y con el campo
   puesto pero el fichero fuera se grabaria un PDF de cero bytes sin decirlo.
4. **En la cadena de bloques** — un anclaje de OpenTimestamps **confirmado**
   que cubre el master hash de ahora. Un OTS pendiente es un compromiso, no un
   bloque: no acredita fecha todavia (lo dice `anchoring.summary_anchor_state`
   al descartar los no confirmados). Y una TSA sola no es «blockchain»: vale,
   pero es otra cosa y caduca con su certificado.
5. **Sin errores** — ningun anclaje fallido, y todos los miembros certificados
   con su copia publica en disco. Lo que no esta en disco no se puede copiar,
   y descubrirlo a mitad del ZIP deja un paquete incompleto sin decirlo.
"""

from dataclasses import dataclass

from django.utils.translation import gettext_lazy as _

from ..models import AnchorStatusChoices, AnchorTypeChoices
from .anchoring import summary_anchor_state


@dataclass(frozen=True)
class Check:
    """Una de las condiciones, con lo que hacer si no se cumple."""

    key: str
    label: str
    ok: bool
    detail: str = ''


def _copy_on_disk(campo) -> bool:
    """
    Que el archivo **este**, no que el campo tenga un nombre escrito.

    `bool(FieldFile)` solo mira si hay nombre en la columna, y el nombre
    sobrevive a que el fichero se haya movido, borrado o restaurado a medias.
    Descubrirlo a mitad del ZIP deja un PDF de cero bytes dentro del dossier,
    sin decirlo: la puerta existe justo para que eso no llegue a un USB.
    """
    if not campo:
        return False

    try:
        return campo.storage.exists(campo.name)
    except (NotImplementedError, OSError):
        # Un almacenamiento que no sepa contestar no es motivo para bloquear:
        # el nombre esta puesto y la copia se intentara leer.
        return True


def _members_ok(summary):
    """Cada miembro certificado y con su copia publica en disco."""
    faltan = []

    for member in summary.ordered_members():
        documento = member.document

        # Con `%` y no con f-string: `xgettext` no entra en las expresiones de
        # una f-string, asi que un `_()` escrito ahi dentro se traduce en
        # tiempo de ejecucion pero **nunca llega al catalogo**, y la frase sale
        # en ingles sin que nada falle ni avise.
        if not documento.is_certified:
            faltan.append('%s: %s' % (member.code, _('not certified')))
            continue

        if not documento.public_copy_file:
            faltan.append('%s: %s' % (member.code, _('no public copy')))
        elif not _copy_on_disk(documento.public_copy_file):
            faltan.append(
                '%s: %s' % (member.code, _('its public copy is not on disk')))

    return faltan


def export_checks(summary) -> list:
    """
    Las cinco condiciones, en el orden en que se arreglan.

    Se devuelven **todas**, cumplidas y no cumplidas: quien mira la pantalla
    tiene que ver el conjunto, no solo el primer fallo. Arreglar uno y
    descubrir el siguiente, de uno en uno, es la peor forma de enterarse.
    """
    state = summary_anchor_state(summary)
    master = state['master']

    sealed = bool(
        master['sealed']
        and master['stored_matches_payload']
        and master['payload_matches_members']
    )

    if not master['sealed']:
        sealed_detail = _('It has no master hash yet: seal it first.')
    elif not master['stored_matches_payload']:
        sealed_detail = _(
            'The stored payload does not produce the stored hash. Do not '
            'export this: something rewrote one of the two.'
        )
    elif not master['payload_matches_members']:
        sealed_detail = _(
            'The sealed payload no longer describes the current members. '
            'Seal it again so the hash covers what the summary holds today.'
        )
    else:
        sealed_detail = ''

    documento = summary.summary_document

    # Tambien que su copia publica este en disco: es el papel que se entrega, y
    # sin el el dossier llevaria un PDF vacio sin avisar.
    issued = bool(
        documento
        and documento.is_certified
        and _copy_on_disk(documento.public_copy_file)
    )

    if not documento or not documento.is_certified:
        issued_detail = _(
            'There is no certified PDF for the summary. Issue it: it is the '
            'paper that goes on the device.'
        )
    elif not issued:
        issued_detail = _(
            'The summary PDF is certified, but its public copy is not on '
            'disk. Issue it again: what is not on disk cannot be copied.'
        )
    else:
        issued_detail = ''

    anclajes = state['anchors']

    en_cadena = any(
        item['type'] == AnchorTypeChoices.OPENTIMESTAMPS
        and item['valid']
        and item['covers_current_master_hash']
        and item.get('confirmed', False)
        for item in anclajes
    )

    if en_cadena:
        chain_detail = ''
    elif any(item['type'] == AnchorTypeChoices.OPENTIMESTAMPS
             for item in anclajes):
        chain_detail = _(
            'The OpenTimestamps proof is still pending: there is a commitment '
            'but no block yet. It matures on its own — the scheduled task '
            'upgrades it every 15 minutes, and it usually takes a few hours.'
        )
    else:
        chain_detail = _(
            'It has never been sent to OpenTimestamps. Send it from the '
            'anchoring page.'
        )

    fallidos = summary.anchors.filter(
        status=AnchorStatusChoices.FAILED).count()
    faltan = _members_ok(summary)
    sin_errores = not fallidos and not faltan

    if fallidos and faltan:
        errors_detail = _(
            '%(anchors)s failed anchor(s), and: %(members)s'
        ) % {'anchors': fallidos, 'members': '; '.join(str(x) for x in faltan)}
    elif fallidos:
        errors_detail = _('%(anchors)s failed anchor(s).') % {
            'anchors': fallidos}
    elif faltan:
        errors_detail = '; '.join(str(x) for x in faltan)
    else:
        errors_detail = ''

    return [
        Check(
            key='active',
            label=_('Active'),
            ok=bool(summary.is_active),
            detail='' if summary.is_active else _(
                'The summary is withdrawn. A withdrawn summary is not handed '
                'out.'
            ),
        ),
        Check(
            key='sealed',
            label=_('Sealed, and the seal still matches'),
            ok=sealed,
            detail=sealed_detail,
        ),
        Check(
            key='issued',
            label=_('Summary document issued'),
            ok=issued,
            detail=issued_detail,
        ),
        Check(
            key='chain',
            label=_('Confirmed on the blockchain'),
            ok=en_cadena,
            detail=chain_detail,
        ),
        Check(
            key='clean',
            label=_('No errors'),
            ok=sin_errores,
            detail=errors_detail,
        ),
    ]


@dataclass(frozen=True)
class ExportState:
    """
    Las cinco condiciones ya calculadas, para pintarlas sin repetir el trabajo.

    Existe porque la pantalla necesita las tres cosas a la vez --si se puede,
    que falta y la lista entera-- y calcularlas por separado repetiria la
    verificacion del sello y la lectura de las pruebas de anclaje una vez por
    pregunta. Se calcula **sin salir a la red**: leer una prueba `.ots` es
    parsearla, no consultar la cadena.
    """

    checks: tuple

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def blocking(self) -> tuple:
        return tuple(check for check in self.checks if not check.ok)


def export_state(summary) -> ExportState:
    """Las cinco condiciones, en una sola pasada."""
    return ExportState(checks=tuple(export_checks(summary)))


def can_export(summary) -> bool:
    """Verde en las cinco. Es la unica puerta, y no se puede rodear."""
    return export_state(summary).ok


def blocking_reasons(summary) -> list:
    """Lo que falta, para decirlo en un mensaje."""
    return list(export_state(summary).blocking)
