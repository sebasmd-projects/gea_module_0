# apps/common/utils/tests_otp_email.py
"""
El correo con el codigo, que ahora es uno solo para los dos sitios.

Habia dos: el del acceso, con logos y avisos, y el de la verificacion
documental, que era ``send_mail`` con tres lineas de texto plano. El segundo
llega a quien acaba de escanear el QR de un papel, no es usuario de la
plataforma y no tiene por que reconocer el remitente -- justo a quien mas
falta le hace que el mensaje se parezca a algo.

Lo que se fija aqui es lo que, si se rompe, no se nota hasta que alguien
reenvia una captura preguntando si el correo es de verdad:

* que los logos viajan **dentro** del mensaje y no enlazados;
* que va el aviso de que nadie del despacho pide el codigo;
* que los dos sitios usan la misma plantilla, y solo cambia lo suyo.

    manage.py test apps.common.utils.tests_otp_email \\
        --settings=app_core.settings_test
"""

from django.core import mail
from django.test import TestCase

from .otp_email import send_otp_email


class Sent:
    """Lo ultimo que salio, desmontado."""

    def __init__(self, message):
        self.message = message
        self.html = message.alternatives[0][0]
        self.text = message.body
        self.types = [part.get_content_type() for part in message.message().walk()]


def send(**kwargs):
    mail.outbox = []
    send_otp_email(**{
        'to': 'quien@example.com',
        'subject': 'Asunto',
        'instruction': 'Para lo que sea.',
        'code': '123456',
        'minutes': 15,
        **kwargs,
    })
    return Sent(mail.outbox[-1])


class TheLogosTravelInsideTests(TestCase):
    """
    Enlazados no valen.

    Un `<img src="https://...">` lo bloquean Gmail y Outlook hasta que el
    destinatario da permiso: el mensaje llegaria con dos huecos rotos justo
    encima del codigo, que es lo que menos conviene en el correo que autoriza
    una entrada. Y de paso un logo remoto delata cuando se abrio el mensaje.
    """

    def test_they_are_referenced_by_cid(self):
        sent = send()

        self.assertIn('cid:propensiones', sent.html)
        self.assertIn('cid:gea', sent.html)

    def test_nothing_is_loaded_from_the_network(self):
        sent = send()

        self.assertNotIn('<img src="http', sent.html)

    def test_they_are_attached_as_png(self):
        """
        En PNG y no en WebP: los logos del proyecto estan en WebP porque es lo
        que conviene en la web, y Outlook de escritorio no lo pinta.
        """
        sent = send()

        self.assertEqual(sent.types.count('image/png'), 2)

    def test_the_images_are_part_of_the_body(self):
        """
        `related` y no `mixed`: si fueran adjuntos, el destinatario veria dos
        ficheros colgando del mensaje y el cuerpo con dos huecos.
        """
        sent = send()

        self.assertEqual(sent.types[0], 'multipart/related')


class TheMessageSaysWhatItHasToTests(TestCase):

    def test_it_carries_the_code(self):
        sent = send(code='654321')

        self.assertIn('654321', sent.html)

    def test_it_says_how_long_it_lasts(self):
        sent = send(minutes=15)

        self.assertIn('15', sent.html)

    def test_it_says_who_to_contact(self):
        sent = send()

        self.assertIn('info@propensionesabogados.com', sent.html)
        self.assertIn('target="_blank"', sent.html)

    def test_it_warns_that_nobody_will_ask_for_the_code(self):
        """
        Es la frase que corta la estafa mas comun -- una llamada diciendo
        «leeme el codigo que te acaba de llegar». Va en el propio correo y no
        solo en la web, porque es ahi donde se lee en el momento que importa.
        """
        sent = send()

        self.assertIn('Nobody from the firm will ever ask you', sent.html)

    def test_it_carries_the_authors_footer(self):
        sent = send()

        self.assertIn('Sebastian Morales', sent.html)
        self.assertIn('https://wa.me/573002954040', sent.html)

    def test_the_instruction_is_what_the_caller_said(self):
        sent = send(instruction='Para validar las certificaciones.')

        self.assertIn('Para validar las certificaciones.', sent.html)


class TheGreetingTests(TestCase):

    def test_it_uses_the_name_when_there_is_one(self):
        sent = send(greeting_name='Ana')

        self.assertIn('Ana', sent.html)

    def test_it_greets_anyway_when_there_is_not(self):
        """
        La verificacion publica no sabe el nombre de quien consulta y no tiene
        por que preguntarlo. Sin esta rama el correo empezaba con «Hola :».
        """
        sent = send(greeting_name='')

        self.assertNotIn('Hi :', sent.html)
        self.assertNotIn('Hola :', sent.html)


class ThePlainTextHalfIsReadableTests(TestCase):
    """
    La mitad que ven los clientes que no pintan HTML.

    Se genera quitando etiquetas del HTML, y quitarlas no basta: hay que
    deshacer tambien las entidades, o el texto plano llega con `&middot;` y
    `&amp;` escritos tal cual.
    """

    def test_it_carries_the_code(self):
        sent = send(code='654321')

        self.assertIn('654321', sent.text)

    def test_it_has_no_html_entities_left(self):
        sent = send()

        self.assertNotIn('&middot;', sent.text)
        self.assertNotIn('&amp;', sent.text)
        self.assertNotIn('&copy;', sent.text)

    def test_it_has_no_tags_left(self):
        sent = send()

        self.assertNotIn('<', sent.text)
