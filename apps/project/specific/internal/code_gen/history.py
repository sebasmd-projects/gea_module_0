"""
El historial de codigos, en arbol: cada resumen con los suyos debajo.

Por que no sale de un `ORDER BY`
--------------------------------
Un codigo puede colgar de un resumen de tres maneras distintas: ser el de un
certificado que es **miembro** del resumen, ser el del **documento del propio
resumen** (el AEGIS-6, que no es miembro de si mismo — invariante 15), o no
colgar de nada. Y un mismo certificado puede ser miembro de **mas de un
resumen**: `uniq_document_per_summary` solo impide repetirlo dentro de uno. La
relacion es codigo → documento → pertenencias → resumen, con dos saltos y una
cardinalidad de muchos a muchos en medio, asi que no hay columna por la que
ordenar que produzca el arbol. Hay que armarlo.

Por que se arma sobre el listado entero y se pagina despues
-----------------------------------------------------------
Al reves --paginar primero y agrupar lo que caiga en la pagina-- el resumen que
cruza el corte sale **partido en dos paginas**, con unos miembros en una y el
resto en otra, y el mismo titulo repetido arriba en las dos. Eso es peor que no
agrupar: un arbol a medias se lee como un arbol completo, y lo que se deduce de
el es falso. Aqui la rama entra entera o no entra.

Lo que cuesta es tener la lista en memoria en vez de veinticinco filas. Se paga
a sabiendas: son codigos que se emiten a mano desde una herramienta interna, y
las consultas son **tres** sean cuantos sean --el listado, las pertenencias y
los documentos de resumen--, no una por fila.

El orden
--------
Los nodos salen en el orden en que aparece su codigo mas reciente, que con el
listado ordenado por fecha descendente es gratis: basta con respetar el orden
de insercion en el diccionario. Un resumen sube cuando se le emite un codigo
nuevo, que es lo que se espera de un historial. Dentro del nodo manda el codigo
del miembro (AEGIS-1, AEGIS-2…), porque ahi lo util no es la fecha sino el
orden del propio resumen.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class HistoryRow:
    """Un codigo dentro del arbol."""

    registration: object

    #: El codigo que le toca dentro del resumen ('AEGIS-1'). Vacio en un
    #: codigo suelto y en el documento del propio resumen.
    member_code: str = ''

    #: True para el documento del resumen, que no es miembro sino continente.
    is_summary_document: bool = False


@dataclass
class HistoryNode:
    """
    Una rama: un resumen con sus codigos debajo, o un codigo suelto.

    Las dos formas viven en la misma lista porque comparten el orden --el
    historial es uno solo-- y la plantilla las distingue por `summary`.
    """

    summary: Optional[object] = None
    rows: list = field(default_factory=list)

    @property
    def is_summary(self) -> bool:
        return self.summary is not None

    @property
    def count(self) -> int:
        return len(self.rows)


def _member_sort_key(code: str):
    """
    Ordena AEGIS-2 antes que AEGIS-10.

    Comparados como texto, '10' va antes que '2' y el resumen se lee
    desordenado justo cuando tiene bastantes miembros, que es cuando el orden
    importa. Lo que no acabe en numero se ordena alfabeticamente detras.
    """
    match = re.search(r'(\d+)\s*$', code or '')

    if match:
        return (0, int(match.group(1)), '')

    return (1, 0, (code or '').lower())


def build_history_tree(registrations) -> list:
    """
    Agrupa los codigos por resumen, respetando el orden que traen.

    `registrations` tiene que venir ya filtrado y ordenado (lo normal, por
    fecha descendente): este modulo no decide **que** se ve ni en que orden,
    solo **como** se anida.
    """
    from apps.project.specific.documents.certificates.models import (
        AegisSummaryDocumentModel, AegisSummaryModel)

    registrations = list(registrations)

    document_ids = {
        registration.document_id
        for registration in registrations
        if registration.document_id
    }

    # Pertenencias: un documento puede estar en varios resumenes, asi que el
    # valor es una lista y el codigo va con cada uno (AEGIS-1 en uno no tiene
    # por que ser AEGIS-1 en otro).
    memberships: dict = {}

    if document_ids:
        rows = (
            AegisSummaryDocumentModel.objects
            .filter(document_id__in=document_ids)
            .select_related('summary')
        )

        for membership in rows:
            memberships.setdefault(membership.document_id, []).append(
                (membership.summary, membership.code)
            )

    # Documentos que son el resumen en si, no un miembro suyo.
    summary_documents: dict = {}

    if document_ids:
        summaries = AegisSummaryModel.objects.filter(
            summary_document_id__in=document_ids
        )

        for summary in summaries:
            summary_documents[summary.summary_document_id] = summary

    # Un diccionario conserva el orden de insercion, asi que el nodo queda
    # donde aparecio su codigo mas reciente sin tener que ordenar despues.
    nodes: dict = {}

    for registration in registrations:
        document_id = registration.document_id
        summary = summary_documents.get(document_id) if document_id else None

        if summary is not None:
            node = nodes.setdefault(summary.pk, HistoryNode(summary=summary))
            node.rows.append(
                HistoryRow(
                    registration=registration,
                    is_summary_document=True,
                )
            )
            continue

        belongs_to = memberships.get(document_id) if document_id else None

        if belongs_to:
            for summary, code in belongs_to:
                node = nodes.setdefault(
                    summary.pk, HistoryNode(summary=summary)
                )
                node.rows.append(
                    HistoryRow(registration=registration, member_code=code)
                )
            continue

        # Un codigo suelto es tambien un nodo, no un cajon comun: si todos
        # fueran al mismo saco, ese saco seria siempre el mas grande de la
        # pagina y taparia los resumenes, que es lo que se venia a ver. La
        # clave lleva prefijo porque la de un resumen es un UUID y la de un
        # registro un entero, y dos espacios de claves en el mismo diccionario
        # se pisan el dia que uno de los dos cambie de tipo.
        node = HistoryNode()
        node.rows.append(HistoryRow(registration=registration))
        nodes[f'loose-{registration.pk}'] = node

    result = list(nodes.values())

    for node in result:
        if node.is_summary:
            # Estable: las filas llegan de mas nueva a mas vieja, asi que dos
            # codigos del mismo miembro --una recertificacion-- conservan ese
            # orden dentro de su posicion.
            node.rows.sort(
                key=lambda row: (
                    not row.is_summary_document,
                    _member_sort_key(row.member_code),
                )
            )

    return result
