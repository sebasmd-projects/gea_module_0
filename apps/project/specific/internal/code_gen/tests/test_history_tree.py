# apps/project/specific/internal/code_gen/tests/test_history_tree.py
"""
El historial de codigos, agrupado por resumen.

La pagina listaba los codigos en una tabla plana ordenada por fecha, y eso
perdia lo unico que relaciona unos con otros: de que resumen es cada
certificado. Con varios resumenes abiertos a la vez --que es lo normal-- sus
miembros salian intercalados por hora de emision, asi que para saber que hay
dentro de un resumen habia que abrir otra pagina y cotejar a mano.

Lo que se fija aqui:

- **Los miembros cuelgan de su resumen**, con el codigo que les toca dentro
  (AEGIS-1, AEGIS-2…), y el documento del propio resumen sale como continente,
  no como un miembro mas: el master hash cubre a los miembros y nunca a si
  mismo (invariante 15), asi que ponerlo en la misma lista los confundiria.
- **AEGIS-2 va antes que AEGIS-10.** Comparados como texto se ordenan al reves,
  y el desorden aparece justo cuando el resumen tiene bastantes miembros.
- **Un codigo suelto es su propia rama**, no un cajon comun al final: un saco
  con todo lo que no es de nadie seria siempre el mas grande de la pagina.
- **Un certificado que este en dos resumenes sale en los dos.** La base lo
  permite --`uniq_document_per_summary` solo impide repetirlo dentro de uno--
  y esconderlo en uno de los dos haria que ese resumen se leyera incompleto.
- **La cifra de cabecera cuenta codigos, no filas**, por lo mismo: ese
  certificado no se ha emitido dos veces.
- **Se pagina por ramas.** Un resumen entra entero o no entra; partirlo por el
  corte lo repetiria arriba en dos paginas con miembros distintos, y un arbol a
  medias se lee como uno completo.

Nada de aqui sale a internet ni toca archivos.

    manage.py test apps.project.specific.internal.code_gen.tests.test_history_tree \\
        --settings=app_core.settings_test
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.project.common.users.models import UserModel
from apps.project.specific.documents.certificates.models import (
    AegisSummaryDocumentModel, AegisSummaryModel, CertificationStatusChoices,
    DocumentVerificationModel)

from ..history import build_history_tree
from ..models import CodeRegistrationModel

PASSWORD = 'pw-for-tests-123'


class HistoryTreeTestCase(TestCase):
    """El armado del arbol, sin pasar por la vista."""

    def a_document(self, title):
        return DocumentVerificationModel.objects.create(
            document_title=title,
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash=f'{abs(hash(title)):064x}'[:64],
            code_payload=f'GEA-{title}',
        )

    def a_code(self, reference, document=None):
        return CodeRegistrationModel.objects.create(
            reference=reference,
            document=document,
            code_information=f'PAYLOAD-{reference}',
        )

    def listing(self):
        """Como lo pide la vista: por fecha, del mas nuevo al mas viejo."""
        return (
            CodeRegistrationModel.objects
            .select_related('document')
            .order_by('-created')
        )

    def test_los_miembros_cuelgan_de_su_resumen(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')

        first = self.a_document('Certificado 1')
        second = self.a_document('Certificado 2')

        AegisSummaryDocumentModel.objects.create(
            summary=summary, document=first, code='AEGIS-1'
        )
        AegisSummaryDocumentModel.objects.create(
            summary=summary, document=second, code='AEGIS-2'
        )

        self.a_code('UNO', first)
        self.a_code('DOS', second)

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 1, 'los dos codigos son una sola rama')

        node = tree[0]

        self.assertTrue(node.is_summary)
        self.assertEqual(node.summary.pk, summary.pk)
        self.assertEqual(
            [row.member_code for row in node.rows],
            ['AEGIS-1', 'AEGIS-2'],
        )

    def test_el_documento_del_resumen_no_es_un_miembro(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')

        member = self.a_document('Certificado 1')
        AegisSummaryDocumentModel.objects.create(
            summary=summary, document=member, code='AEGIS-1'
        )

        paper = self.a_document('Resumen AEGIS-6')
        summary.summary_document = paper
        summary.save(update_fields=['summary_document'])

        self.a_code('MIEMBRO', member)
        self.a_code('RESUMEN', paper)

        node = build_history_tree(self.listing())[0]

        self.assertEqual(len(node.rows), 2)

        # El continente va primero, y marcado como tal.
        self.assertTrue(node.rows[0].is_summary_document)
        self.assertEqual(node.rows[0].member_code, '')
        self.assertEqual(node.rows[1].member_code, 'AEGIS-1')

    def test_aegis_2_va_antes_que_aegis_10(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')

        # Se dan de alta al reves para que el orden no salga por casualidad.
        for number in (10, 2, 1):
            document = self.a_document(f'Certificado {number}')
            AegisSummaryDocumentModel.objects.create(
                summary=summary, document=document, code=f'AEGIS-{number}'
            )
            self.a_code(f'REF-{number}', document)

        node = build_history_tree(self.listing())[0]

        self.assertEqual(
            [row.member_code for row in node.rows],
            ['AEGIS-1', 'AEGIS-2', 'AEGIS-10'],
        )

    def test_un_codigo_suelto_es_su_propia_rama(self):
        self.a_code('SUELTO-A')
        self.a_code('SUELTO-B')

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 2)
        self.assertFalse(any(node.is_summary for node in tree))
        self.assertEqual(
            [node.rows[0].registration.reference for node in tree],
            ['SUELTO-B', 'SUELTO-A'],
            'el mas reciente primero, como el listado',
        )

    def test_un_certificado_en_dos_resumenes_sale_en_los_dos(self):
        first = AegisSummaryModel.objects.create(title='Resumen X')
        second = AegisSummaryModel.objects.create(title='Resumen Y')

        document = self.a_document('Compartido')

        AegisSummaryDocumentModel.objects.create(
            summary=first, document=document, code='AEGIS-1'
        )
        AegisSummaryDocumentModel.objects.create(
            summary=second, document=document, code='AEGIS-4'
        )

        self.a_code('COMPARTIDO', document)

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 2)
        self.assertEqual(
            sorted(row.member_code for node in tree for row in node.rows),
            ['AEGIS-1', 'AEGIS-4'],
        )

    def test_una_rama_sube_cuando_se_le_emite_un_codigo_nuevo(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')
        member = self.a_document('Certificado 1')
        AegisSummaryDocumentModel.objects.create(
            summary=summary, document=member, code='AEGIS-1'
        )

        self.a_code('ANTIGUO', member)
        self.a_code('SUELTO')

        self.assertEqual(
            [node.is_summary for node in build_history_tree(self.listing())],
            [False, True],
            'el suelto es lo mas reciente',
        )

        # Recertificar al miembro emite otro codigo, y la rama sube.
        self.a_code('NUEVO', member)

        tree = build_history_tree(self.listing())

        self.assertEqual([node.is_summary for node in tree], [True, False])
        self.assertEqual(len(tree[0].rows), 2, 'los dos codigos del miembro')

    def test_no_hace_una_consulta_por_fila(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')

        for number in range(1, 6):
            document = self.a_document(f'Certificado {number}')
            AegisSummaryDocumentModel.objects.create(
                summary=summary, document=document, code=f'AEGIS-{number}'
            )
            self.a_code(f'REF-{number}', document)

        # El listado, las pertenencias y los documentos de resumen: tres, sean
        # cuantas filas sean. Es lo que permite armar el arbol entero antes de
        # paginar sin que el coste crezca con el historial.
        with self.assertNumQueries(3):
            build_history_tree(self.listing())


class HistoryPageTestCase(TestCase):
    """La pagina: que pagine ramas y cuente codigos."""

    def setUp(self):
        self.staff = UserModel.objects.create_user(
            username='ops', email='ops@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.url = reverse('code_gen:code_history')

    def a_summary_with(self, title, members):
        summary = AegisSummaryModel.objects.create(title=title)

        for number in range(1, members + 1):
            document = DocumentVerificationModel.objects.create(
                document_title=f'{title} · {number}',
                issued_at=date(2026, 1, 15),
                certification_status=CertificationStatusChoices.CERTIFIED,
                document_hash=f'{number:064d}'[:64],
            )
            AegisSummaryDocumentModel.objects.create(
                summary=summary, document=document, code=f'AEGIS-{number}'
            )
            CodeRegistrationModel.objects.create(
                reference=f'{title}-{number}', document=document
            )

        return summary

    def test_la_pagina_pinta_el_resumen_y_sus_miembros(self):
        self.a_summary_with('Bonos 1872', members=2)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bonos 1872')
        self.assertContains(response, 'AEGIS-1')
        self.assertContains(response, 'AEGIS-2')

        nodes = response.context['nodes']

        self.assertEqual(len(nodes), 1)
        self.assertEqual(len(nodes[0].rows), 2)

    def test_la_cifra_cuenta_codigos_no_filas(self):
        """Un certificado en dos resumenes no se ha emitido dos veces."""
        first = AegisSummaryModel.objects.create(title='Resumen X')
        second = AegisSummaryModel.objects.create(title='Resumen Y')

        document = DocumentVerificationModel.objects.create(
            document_title='Compartido',
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash='c' * 64,
        )

        AegisSummaryDocumentModel.objects.create(
            summary=first, document=document, code='AEGIS-1'
        )
        AegisSummaryDocumentModel.objects.create(
            summary=second, document=document, code='AEGIS-2'
        )

        CodeRegistrationModel.objects.create(
            reference='COMPARTIDO', document=document
        )

        response = self.client.get(self.url)

        self.assertEqual(response.context['code_count'], 1)
        self.assertEqual(len(response.context['nodes']), 2, 'sale en los dos')

    def test_un_resumen_no_se_parte_entre_paginas(self):
        """
        Lo que se pagina son ramas.

        Con 30 ramas de una fila cada una y el corte en 25, la primera pagina
        lleva 25 ramas enteras. Antes el corte caia sobre las filas, asi que un
        resumen de ocho miembros a caballo del limite salia repetido arriba en
        las dos paginas, con unos miembros en cada una.
        """
        big = self.a_summary_with('Bonos 1872', members=8)

        for number in range(30):
            CodeRegistrationModel.objects.create(reference=f'SUELTO-{number}')

        first_page = self.client.get(self.url)
        nodes = first_page.context['nodes']

        self.assertEqual(len(nodes), 25, 'veinticinco ramas, no veinticinco filas')

        second_page = self.client.get(self.url, {'page': 2})
        every = list(nodes) + list(second_page.context['nodes'])
        summaries = [node for node in every if node.is_summary]

        self.assertEqual(len(summaries), 1, 'el resumen aparece una sola vez')
        self.assertEqual(summaries[0].summary.pk, big.pk)
        self.assertEqual(len(summaries[0].rows), 8, 'y entero')

    def test_la_busqueda_sigue_funcionando(self):
        self.a_summary_with('Bonos 1872', members=2)
        CodeRegistrationModel.objects.create(reference='NADA QUE VER')

        response = self.client.get(self.url, {'q': 'Bonos'})

        self.assertEqual(response.context['code_count'], 2)
        self.assertNotContains(response, 'NADA QUE VER')


class FlatViewTestCase(TestCase):
    """
    El otro modo: una fila por codigo, sin repetir ninguno.

    El arbol repite a proposito el certificado que esta en dos resumenes, asi
    que sus filas dejan de ser los codigos emitidos. Para cuadrar una cuenta
    hace falta la lista de siempre — y para no perder la relacion al dejar de
    agrupar, cada fila dice a que resumenes pertenece.
    """

    def setUp(self):
        self.staff = UserModel.objects.create_user(
            username='ops', email='ops@example.com', password=PASSWORD,
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.url = reverse('code_gen:code_history')

    def a_document(self, title, h):
        return DocumentVerificationModel.objects.create(
            document_title=title,
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash=h * 64,
        )

    def shared_document(self):
        """Un certificado en dos resumenes: el caso que separa los dos modos."""
        first = AegisSummaryModel.objects.create(title='Resumen X')
        second = AegisSummaryModel.objects.create(title='Resumen Y')

        document = self.a_document('Compartido', 'c')

        AegisSummaryDocumentModel.objects.create(
            summary=first, document=document, code='AEGIS-1'
        )
        AegisSummaryDocumentModel.objects.create(
            summary=second, document=document, code='AEGIS-4'
        )

        CodeRegistrationModel.objects.create(
            reference='COMPARTIDO', document=document
        )

        return first, second

    def test_el_arbol_es_el_modo_por_defecto(self):
        self.shared_document()

        response = self.client.get(self.url)

        self.assertTrue(response.context['grouped'])
        self.assertIn('nodes', response.context)

    def test_un_valor_desconocido_cae_en_el_arbol(self):
        """Una URL vieja o manipulada no puede acabar en un error."""
        self.shared_document()

        response = self.client.get(self.url, {'view': 'loquesea'})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['grouped'])

    def test_la_lista_no_repite_el_certificado_compartido(self):
        self.shared_document()

        grouped = self.client.get(self.url)
        flat = self.client.get(self.url, {'view': 'flat'})

        # En arbol son dos ramas de una fila: dos filas para un solo codigo.
        self.assertEqual(
            sum(node.count for node in grouped.context['nodes']), 2
        )

        # En lista, una fila y una sola.
        self.assertFalse(flat.context['grouped'])
        self.assertEqual(len(flat.context['rows']), 1)
        self.assertEqual(flat.context['code_count'], 1)

    def test_la_lista_dice_de_que_resumenes_es_cada_codigo(self):
        """Dejar de agrupar no puede ser perder la relacion."""
        self.shared_document()

        response = self.client.get(self.url, {'view': 'flat'})
        row = response.context['rows'][0]

        self.assertEqual(
            sorted(row.labels),
            ['Resumen X · AEGIS-1', 'Resumen Y · AEGIS-4'],
        )
        self.assertContains(response, 'Resumen X · AEGIS-1')

    def test_el_papel_del_resumen_se_distingue_en_la_lista(self):
        summary = AegisSummaryModel.objects.create(title='Bonos 1872')
        paper = self.a_document('Resumen AEGIS-6', 'f')
        summary.summary_document = paper
        summary.save(update_fields=['summary_document'])

        CodeRegistrationModel.objects.create(
            reference='RESUMEN', document=paper
        )

        row = self.client.get(self.url, {'view': 'flat'}).context['rows'][0]

        self.assertTrue(row.is_summary_document)
        # Lleva su resumen, pero sin codigo de miembro: no es miembro de si
        # mismo (invariante 15).
        self.assertEqual(row.labels, ('Bonos 1872',))

    def test_un_codigo_sin_resumen_no_lleva_etiqueta(self):
        orphan = self.a_document('Certificado sin resumen', 'z')
        CodeRegistrationModel.objects.create(
            reference='HUERFANO', document=orphan
        )
        CodeRegistrationModel.objects.create(reference='SIN DOCUMENTO')

        rows = self.client.get(self.url, {'view': 'flat'}).context['rows']

        self.assertEqual([row.labels for row in rows], [(), ()])

    def test_la_lista_pagina_en_la_base_de_datos(self):
        """
        En lista no hay ramas que partir, asi que no hace falta traerlo todo.

        Es la diferencia de coste entre los dos modos y conviene que este
        fijada: el arbol carga el historial entero para no cortar una rama, y
        esta no tiene por que pagarlo.
        """
        for number in range(30):
            CodeRegistrationModel.objects.create(reference=f'SUELTO-{number}')

        response = self.client.get(self.url, {'view': 'flat'})

        self.assertEqual(len(response.context['rows']), 25)
        self.assertEqual(response.context['code_count'], 30)
        self.assertEqual(response.context['paginator'].num_pages, 2)

        # `object_list` es el QuerySet ya cortado, no una lista en memoria.
        self.assertEqual(len(response.context['object_list']), 25)

    def test_la_busqueda_y_la_paginacion_conservan_el_modo(self):
        """
        Sin esto, buscar desde la lista devolvia al arbol y parecia que el
        interruptor se hubiera soltado solo.
        """
        for number in range(30):
            CodeRegistrationModel.objects.create(reference=f'SUELTO-{number}')

        response = self.client.get(self.url, {'view': 'flat'})

        self.assertContains(response, 'name="view" value="flat"')
        self.assertContains(response, 'view=flat&amp;page=2')

        # Y la pagina 2 sigue en lista.
        second = self.client.get(self.url, {'view': 'flat', 'page': 2})

        self.assertFalse(second.context['grouped'])
        self.assertEqual(len(second.context['rows']), 5)


class SharedMembersTestCase(TestCase):
    """
    Dos resumenes que comparten miembros, y dos que comparten titulo.

    Nada en la base lo impide: `uniq_document_per_summary` solo evita repetir
    un documento **dentro** de un resumen, y el titulo no es unico. Las ramas
    se indexan por el UUID del resumen, no por su nombre, asi que dos que se
    llamen igual no se funden en una — que seria juntar los miembros de dos
    resumenes distintos bajo una sola cabecera.
    """

    def a_document(self, title, h):
        return DocumentVerificationModel.objects.create(
            document_title=title,
            issued_at=date(2026, 1, 15),
            certification_status=CertificationStatusChoices.CERTIFIED,
            document_hash=h * 64,
        )

    def listing(self):
        return (
            CodeRegistrationModel.objects
            .select_related('document')
            .order_by('-created')
        )

    def test_dos_resumenes_con_los_mismos_miembros(self):
        first = AegisSummaryModel.objects.create(title='Bonos — original')
        second = AegisSummaryModel.objects.create(title='Bonos — para el banco')

        for number, letter in ((1, 'a'), (2, 'b')):
            document = self.a_document(f'Certificado {number}', letter)

            for summary in (first, second):
                AegisSummaryDocumentModel.objects.create(
                    summary=summary, document=document,
                    code=f'AEGIS-{number}',
                )

            CodeRegistrationModel.objects.create(
                reference=f'CERT-{number}', document=document
            )

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 2)

        for node in tree:
            self.assertEqual(
                [row.member_code for row in node.rows],
                ['AEGIS-1', 'AEGIS-2'],
                'cada resumen lleva su juego completo',
            )

    def test_dos_resumenes_con_el_mismo_titulo_no_se_funden(self):
        first = AegisSummaryModel.objects.create(title='Repetido')
        second = AegisSummaryModel.objects.create(title='Repetido')

        for summary, number, letter in ((first, 1, 'd'), (second, 2, 'e')):
            document = self.a_document(f'Certificado {number}', letter)
            AegisSummaryDocumentModel.objects.create(
                summary=summary, document=document, code='AEGIS-1'
            )
            CodeRegistrationModel.objects.create(
                reference=f'CERT-{number}', document=document
            )

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 2, 'son dos resumenes, no uno')
        self.assertEqual(
            {node.summary.pk for node in tree}, {first.pk, second.pk}
        )
        # Se distinguen por el codigo publico, que si es unico.
        self.assertNotEqual(
            tree[0].summary.public_code, tree[1].summary.public_code
        )

    def test_un_certificado_que_no_esta_en_ningun_resumen(self):
        """
        Un documento certificado y suelto: ni miembro, ni papel de resumen.

        Estaba cubierto el codigo **sin documento**, que toma otro camino en
        el armado: aqui hay documento, y hay que mirar sus pertenencias para
        descubrir que no tiene ninguna.
        """
        orphan = self.a_document('Certificado sin resumen', 'z')
        CodeRegistrationModel.objects.create(
            reference='HUERFANO', document=orphan
        )

        tree = build_history_tree(self.listing())

        self.assertEqual(len(tree), 1)
        self.assertFalse(tree[0].is_summary)
        self.assertEqual(tree[0].rows[0].registration.reference, 'HUERFANO')
        self.assertEqual(tree[0].rows[0].member_code, '')
