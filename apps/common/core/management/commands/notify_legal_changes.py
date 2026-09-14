"""
Avisa a todo el mundo de que un documento legal cambio.

Por que existe, y por que es lo primero
---------------------------------------
Entrar a la plataforma despues de un cambio cuenta como aceptarlo
(`AcceptanceMethod.CONTINUED_USE`), y eso **solo vale si antes se aviso**.
Aceptacion por conducta sin aviso previo no es aceptacion de nada: es dar por
hecho. Por eso `core.legal.accept_on_login()` se niega a registrar una version
que todavia no lleva `notified_at`, y por eso este comando es el que abre esa
puerta, no la aprobacion.

Por que va por cron y no dentro de la aprobacion
------------------------------------------------
Aprobar es un clic en el admin, y con `ATOMIC_REQUESTS = True` esa peticion es
una transaccion. Mandar cientos de correos ahi dentro la tendria abierta todo
ese rato, y un fallo del servidor de correo a mitad desharia la aprobacion
--que es una escritura nuestra y correcta-- por culpa de algo de fuera. Es la
misma separacion que hay en el anclaje de resumenes: sellar es instantaneo y
nuestro, enviar sale a la red y nunca propaga su fallo (§4-bis.D).

Que se manda
------------
Un correo por persona, con **que documento** cambio y **que** cambio --la nota
de cambio que escribio quien lo redacto--, y el enlace. No se manda el texto
entero: un correo de doce paginas no se lee, y lo que hace falta es que la
persona sepa que tiene que ir a mirar.

    manage.py notify_legal_changes [--dry-run] [--limit N]
"""

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from ...models import LegalDocumentVersionModel, LegalVersionStatus

logger = logging.getLogger(__name__)

#: Cuantos correos por conexion SMTP. Abrir una por mensaje es lento y
#: bastantes proveedores lo cortan; abrir una sola para dos mil tampoco
#: sobrevive. Cincuenta es el termino medio que usan el resto de envios.
TANDA = 50


class Command(BaseCommand):
    help = 'Avisa a los usuarios de los cambios en los documentos legales.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Dice a quien avisaria y de que, sin mandar nada ni marcar.',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Tope de destinatarios por version. 0 es sin tope.',
        )

    def handle(self, *args, **options):
        pendientes = (
            LegalDocumentVersionModel.objects
            .filter(
                status=LegalVersionStatus.APPROVED,
                notify_users=True,
                notified_at__isnull=True,
            )
            .select_related('document')
            .order_by('effective_from')
        )

        if not pendientes.exists():
            self.stdout.write('Sin cambios pendientes de avisar.')
            return

        for version in pendientes:
            self._avisar(version, options)

    # ------------------------------------------------------------------

    def _destinatarios(self, limite):
        """
        A quien se avisa: cuentas activas con correo.

        El correo va cifrado con Fernet, asi que no se puede filtrar por el en
        SQL (`filter(email='')` no encuentra nada nunca — es lo mismo que
        obliga a que exista `email_hash`). Se filtra en Python, que para una
        lista de usuarios de esta plataforma es barato.
        """
        Usuario = get_user_model()
        cuentas = Usuario.objects.filter(is_active=True).order_by('date_joined')

        destinatarios = []

        for cuenta in cuentas.iterator(chunk_size=200):
            correo = (getattr(cuenta, 'email', '') or '').strip()

            if not correo:
                continue

            destinatarios.append((cuenta, correo))

            if limite and len(destinatarios) >= limite:
                break

        return destinatarios

    def _avisar(self, version, options):
        seco = options['dry_run']
        destinatarios = self._destinatarios(options['limit'])
        documento = version.document

        self.stdout.write(
            f'{documento.key} {version.version}: '
            f'{len(destinatarios)} destinatario(s)'
            + (' [en seco]' if seco else '')
        )

        if seco:
            return

        enviados = 0

        for comienzo in range(0, len(destinatarios), TANDA):
            tanda = destinatarios[comienzo:comienzo + TANDA]

            with get_connection() as conexion:
                for cuenta, correo in tanda:
                    if self._enviar(version, cuenta, correo, conexion):
                        enviados += 1

        # Se marca aunque alguno fallara. Reintentar la version entera
        # reenviaria a todos los que si lo recibieron, y un aviso legal
        # duplicado es peor que uno perdido: el que falto sigue en el log, y
        # su aceptacion por uso continuado no se registra hasta que entre.
        version.notified_at = timezone.now()
        version.notified_count = enviados
        version.save(update_fields=['notified_at', 'notified_count', 'updated'])

        self.stdout.write(self.style.SUCCESS(
            f'  avisados {enviados} de {len(destinatarios)}'
        ))

    def _enviar(self, version, cuenta, correo, conexion):
        documento = version.document
        idioma = getattr(cuenta, 'language', None) or 'es'

        try:
            with translation.override(idioma):
                contexto = {
                    'user': cuenta,
                    'document_name': documento.name_for(idioma),
                    'version': version,
                    'change_note': version.change_note_for(idioma),
                    'effective_from': version.effective_from,
                    # Del ajuste y nunca del host de la peticion: aqui no hay
                    # peticion, y `django.contrib.sites` no esta instalado
                    # (invariante 12).
                    'base_url': settings.PUBLIC_BASE_URL.rstrip('/'),
                    'document_key': documento.key,
                }

                asunto = _('%(document)s has changed') % {
                    'document': documento.name_for(idioma)
                }
                cuerpo = render_to_string(
                    'email/legal_change_email.html', contexto
                )

                mensaje = EmailMultiAlternatives(
                    subject=asunto,
                    body=_(
                        'We have updated the %(document)s. You can read it at '
                        '%(url)s'
                    ) % {
                        'document': documento.name_for(idioma),
                        'url': f'{contexto["base_url"]}/{documento.key}/',
                    },
                    to=[correo],
                    connection=conexion,
                )
                mensaje.attach_alternative(cuerpo, 'text/html')
                mensaje.send()

            return True

        except Exception:
            logger.exception(
                'No se pudo avisar del cambio de %s a la cuenta %s',
                documento.key, cuenta.pk,
            )
            return False
