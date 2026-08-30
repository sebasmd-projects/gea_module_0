# apps/project/specific/internal/code_gen/management/commands/check_anchoring.py
"""
Si este servidor puede anclar en la cadena de bloques, y como comprobarlo.

Sirve para dos preguntas distintas.

**Puede salir de aqui?** El compositor avisa de que el sello se guardo pero el
envio fallo, y ahi se acaba lo que puede contar una pantalla. La causa esta casi
siempre fuera del codigo, y son dos muy distintas que conviene no confundir:

* **La libreria no esta.** Produccion instala con ``pip`` desde
  ``requirements.txt`` -- en cPanel no hay uv, que es solo para local --, asi
  que basta con que una dependencia no llegara a ese fichero, o con que el
  despliegue no volviera a instalar, para que falte. Se arregla instalando
  ``requirements.txt`` en el entorno virtual de la aplicacion. Y para que no
  vuelva a pasar en silencio, ``manage.py check_requirements`` compara las dos
  listas.
* **La red de salida esta cerrada.** En hosting compartido es lo habitual:
  las conexiones salientes hacia terceros se filtran, y entonces no hay nada
  que arreglar en el codigo -- hay que pedirselo al proveedor o anclar desde
  otra maquina.

**Y lo que se mando, quedo?** Esa es otra pregunta, y ``--stamp`` por si solo
no la respondia: enviaba un hash de prueba, decia «aceptado» y tiraba la
prueba, con lo que no habia donde volver a mirar.

Conviene entender por que no basta con enviar. OpenTimestamps **no avisa de
nada**: no hay respuesta diferida, ni correo, ni enlace que llegue luego. Al
enviar, el calendario devuelve al momento una promesa firmada de incluir ese
hash en su proximo arbol; el bloque de Bitcoin llega horas despues. La unica
forma de saber si llego es **guardar esa promesa y volver a preguntar**. Quien
guarda la prueba es quien puede demostrar la fecha, y si se pierde no hay a
quien reclamarla.

Por eso ``--stamp`` guarda ahora la prueba en disco y ``--verify`` la retoma y
pregunta a los calendarios si ya hay bloque. Es exactamente lo que el cron
``upgrade_ots_anchors`` hace cada hora con los anclajes de verdad, en pequeno y
sin tocar la base de datos.

    manage.py check_anchoring            # solo mira: libreria, salida, estado
    manage.py check_anchoring --stamp    # manda un hash de prueba y lo guarda
    manage.py check_anchoring --verify   # vuelve sobre el ultimo y dice si cuajo
"""

import base64
import hashlib
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

TCP_TIMEOUT = 8

SELFTEST_DIR = 'ots_selftest'

# Ventana honesta de maduracion. Los calendarios publican cada hora larga y
# Bitcoin tarda lo que tarda; por debajo de esto, esperar es lo normal.
MATURES_FROM_HOURS = 1
MATURES_TO_HOURS = 6

# Por encima de esto, un pendiente ya no es paciencia: es que algo no corre.
STALE_HOURS = 24

BLOCK_EXPLORER = 'https://blockstream.info/block-height/{height}'


class Command(BaseCommand):
    help = 'Comprueba si este servidor puede anclar en OpenTimestamps.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--stamp',
            action='store_true',
            help=(
                'Ademas de comprobar, envia un hash de prueba de verdad y '
                'guarda la prueba para poder volver sobre ella. Es inofensivo: '
                'el hash es inventado y no queda asociado a ningun documento.'
            ),
        )
        parser.add_argument(
            '--verify',
            action='store_true',
            help=(
                'Retoma el ultimo envio de prueba y pregunta a los calendarios '
                'si ya entro en un bloque de Bitcoin. Se ejecuta horas despues '
                'de --stamp.'
            ),
        )

    def handle(self, *args, **options):
        ok = True

        ok &= self._check_library()
        calendars = self._calendars()
        ok &= self._check_reachability(calendars)
        self._report_real_anchors()

        if options['stamp']:
            ok &= self._check_stamp()

        if options['verify']:
            ok &= self._check_verify()

        self.stdout.write('')

        if ok:
            self.stdout.write(self.style.SUCCESS(
                'Este servidor puede anclar en la cadena de bloques.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                'Este servidor NO puede anclar. Mira los detalles de arriba: '
                'si falla la libreria, reinstala requirements.txt con pip en '
                'el entorno de la aplicacion; si fallan las conexiones, es el '
                'cortafuegos de salida del hosting y hay que pedirselo al '
                'proveedor.'
            ))

        return None

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _check_library(self) -> bool:
        """Que ``opentimestamps`` este instalada y se pueda importar."""
        self._section('1. Libreria')

        try:
            import opentimestamps  # noqa: F401
            from opentimestamps.calendar import RemoteCalendar  # noqa: F401
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   NO disponible: {type(error).__name__}: {error}'
            ))
            self.stdout.write(
                '   Produccion instala con pip desde requirements.txt. Desde '
                'cPanel: Setup Python App -> Run Pip Install apuntando a '
                'requirements.txt, o por SSH activando el entorno de la '
                'aplicacion y "pip install -r requirements.txt".'
            )
            self.stdout.write(
                '   Comprueba antes con "manage.py check_requirements" que la '
                'dependencia este en requirements.txt: si no lo esta, '
                'reinstalar no la traera.'
            )
            return False

        version = getattr(opentimestamps, '__version__', 'sin version')
        self.stdout.write(self.style.SUCCESS(
            f'   opentimestamps disponible ({version}).'
        ))

        return True

    def _calendars(self) -> tuple:
        from ...services.ots import _calendars

        return _calendars()

    def _check_reachability(self, calendars) -> bool:
        """
        Que se pueda abrir una conexion a cada calendario.

        Se prueba el TCP a pelo y no una peticion HTTP porque lo que se quiere
        saber es si el cortafuegos de salida deja pasar, que es la pregunta
        que separa las dos causas.
        """
        self._section('2. Salida a los calendarios (TCP 443)')

        reachable = 0

        for url in calendars:
            host = urlparse(url).hostname
            port = urlparse(url).port or 443

            started = time.monotonic()

            try:
                with socket.create_connection((host, port), TCP_TIMEOUT):
                    pass
            except Exception as error:  # noqa: BLE001
                elapsed = time.monotonic() - started
                self.stdout.write(self.style.ERROR(
                    f'   {host}: sin salida tras {elapsed:.1f}s '
                    f'({type(error).__name__}: {error})'
                ))
                continue

            elapsed = time.monotonic() - started
            reachable += 1

            self.stdout.write(self.style.SUCCESS(
                f'   {host}: alcanzable en {elapsed:.2f}s'
            ))

        if not reachable:
            self.stdout.write(
                '   Ninguno responde. Con que uno solo se alcance basta para '
                'anclar, asi que esto apunta al cortafuegos de salida del '
                'hosting, no a los calendarios.'
            )
            return False

        self.stdout.write(
            f'   {reachable} de {len(calendars)} alcanzables. Con uno basta.'
        )

        return True

    # ------------------------------------------------------------------
    def _report_real_anchors(self):
        """
        Los anclajes de verdad, que es lo que importa de esto.

        El envio de prueba dice si el camino esta abierto; esto dice si las
        cajas selladas estan llegando a un bloque. Un pendiente reciente es lo
        normal. Un pendiente de dias no lo es, y casi siempre significa que el
        cron ``upgrade_ots_anchors`` no esta corriendo: el anclaje se mando
        bien y la prueba se quedo sin madurar en la base de datos.
        """
        self._section('3. Anclajes reales en esta base de datos')

        from ...models import (AnchorStatusChoices, AnchorTypeChoices,
                               CertificationAnchorModel)

        anchors = CertificationAnchorModel.objects.filter(
            anchor_type=AnchorTypeChoices.OPENTIMESTAMPS
        )

        confirmed = anchors.filter(
            status=AnchorStatusChoices.CONFIRMED).count()
        pending = anchors.filter(status=AnchorStatusChoices.PENDING)
        pending_count = pending.count()

        if not confirmed and not pending_count:
            self.stdout.write(
                '   Todavia no se ha anclado ninguna caja desde este servidor.'
            )
            return

        self.stdout.write(
            f'   Confirmados en un bloque: {confirmed}   '
            f'Esperando bloque: {pending_count}'
        )

        oldest = pending.order_by('created').first()

        if oldest is None:
            self.stdout.write(self.style.SUCCESS(
                '   No queda ninguno esperando.'
            ))
            return

        hours = (timezone.now() - oldest.created).total_seconds() / 3600

        if hours > STALE_HOURS:
            self.stdout.write(self.style.WARNING(
                f'   El mas antiguo lleva {hours:.0f} horas esperando, y con '
                f'{MATURES_TO_HOURS} suele bastar. El envio salio bien -- la '
                'prueba esta guardada -- pero nadie la esta madurando: '
                'comprueba que el cron "upgrade_ots_anchors" corra cada hora, '
                'y ejecutalo a mano para ponerte al dia.'
            ))
        else:
            self.stdout.write(
                f'   El mas antiguo lleva {hours:.1f} horas esperando. Es lo '
                f'normal: maduran entre {MATURES_FROM_HOURS} y '
                f'{MATURES_TO_HOURS} horas.'
            )

        self.stdout.write(
            '   El estado de cada caja se ve en su pagina de anclaje, que es '
            'la del QR del resumen y se actualiza sola.'
        )

    # ------------------------------------------------------------------
    def _selftest_dir(self) -> Path:
        return Path(settings.MEDIA_ROOT) / SELFTEST_DIR

    def _protect(self, directory: Path):
        """
        Denegar el acceso web al directorio, porque cuelga de ``MEDIA_ROOT``.

        Ahi el servidor web sirve por defecto y solo se bloquean tres
        subdirectorios por nombre (``deploy/media.htaccess``). Un directorio
        nuevo nace, por tanto, publico. Lo que guarda no es sensible --pruebas
        de hashes inventados que no son de ningun documento--, pero un
        directorio que se crea solo no puede depender de que alguien se acuerde
        de anadirlo a un script de despliegue.
        """
        guard = directory / '.htaccess'

        if guard.exists():
            return

        source = Path(settings.BASE_DIR) / 'deploy' / 'media-protected.htaccess'

        try:
            guard.write_bytes(source.read_bytes())
        except OSError:
            # Sin la plantilla o sin permiso de escritura no se puede hacer
            # mas; no es motivo para no guardar la prueba.
            pass

    def _save_proof(self, digest: str, proof: bytes):
        """
        Guardar la prueba, porque sin ella el envio no se puede comprobar.

        Devuelve la ruta, o ``None`` si no se pudo escribir. No se considera un
        fallo del anclaje: el hash llego igual a los calendarios. Lo que se
        pierde es poder volver sobre el, y por eso en ese caso se imprime la
        prueba en base64 -- son unos cientos de bytes y asi queda al menos en
        la traza de la consola de operaciones.
        """
        stamp = timezone.now().strftime('%Y%m%d-%H%M%S')
        target = self._selftest_dir() / f'{stamp}-{digest[:8]}.ots'

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self._protect(target.parent)
            target.write_bytes(proof)
        except OSError as error:
            self.stdout.write(self.style.WARNING(
                f'   No se pudo guardar la prueba en {target}: {error}'
            ))
            self.stdout.write(
                '   El hash si llego a los calendarios; lo que no vas a poder '
                'es comprobarlo despues con --verify. Copia esto si quieres '
                'conservarlo:'
            )
            self.stdout.write(f'   {base64.b64encode(proof).decode()}')
            return None

        return target

    def _latest_proof(self):
        """El ultimo envio de prueba guardado, que es sobre el que se vuelve."""
        try:
            saved = sorted(self._selftest_dir().glob('*.ots'))
        except OSError:
            return None

        return saved[-1] if saved else None

    def _describe_state(self, state, indent='   ') -> bool:
        """
        Traducir el estado de una prueba a algo que se pueda leer.

        Lo primero es si la prueba vale, y no da igual: una prueba ilegible, o
        que cubra otro hash, tambien llega aqui sin bloque, y contarla como
        «esperando» seria decir que hay un compromiso que no existe. Se
        esperaria indefinidamente algo que no va a llegar nunca.
        """
        if not state['valid']:
            self.stdout.write(self.style.ERROR(
                f'{indent}La prueba no acredita este hash: {state["detail"]}'
            ))
            return False

        if state['confirmed']:
            height = state['bitcoin_block']
            self.stdout.write(self.style.SUCCESS(
                f'{indent}Confirmado en el bloque de Bitcoin {height}.'
            ))
            self.stdout.write(
                f'{indent}Se comprueba en cualquier explorador de bloques, '
                'sin depender de esta plataforma:'
            )
            self.stdout.write(
                f'{indent}   {BLOCK_EXPLORER.format(height=height)}'
            )
            return True

        self.stdout.write(
            f'{indent}Todavia sin bloque. El compromiso existe: estos '
            'calendarios se han comprometido a incluirlo.'
        )

        for uri in state['pending_calendars']:
            self.stdout.write(f'{indent}   {uri}')

        return True

    # ------------------------------------------------------------------
    def _check_stamp(self) -> bool:
        """El envio completo, con un hash de prueba que no es de nadie."""
        self._section('4. Envio de prueba')

        from ...services import ots

        digest = hashlib.sha256(
            f'gea check_anchoring {time.time()}'.encode()
        ).hexdigest()

        self.stdout.write(f'   hash de prueba: {digest}')

        try:
            result = ots.stamp(digest)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   FALLO: {type(error).__name__}: {error}'
            ))
            return False

        proof = result['proof']

        self.stdout.write(self.style.SUCCESS(
            f'   Aceptado por {len(result["calendars"])} calendario(s); '
            f'prueba de {len(proof)} bytes.'
        ))

        for url in result['calendars']:
            self.stdout.write(f'      {url}')

        saved = self._save_proof(digest, proof)

        if saved is not None:
            self.stdout.write(f'   Prueba guardada en {saved}')

        # Lo que acaba de responder el calendario, leido de la propia prueba.
        if not self._describe_state(ots.inspect(proof, digest)):
            return False

        self.stdout.write('')
        self.stdout.write(
            f'   Que esperar: entre {MATURES_FROM_HOURS} y {MATURES_TO_HOURS} '
            'horas. Nadie avisa cuando pase -- OpenTimestamps no manda correos '
            'ni devuelve ningun enlace despues. Hay que volver a preguntar:'
        )
        self.stdout.write(
            '      manage.py check_anchoring --verify'
        )
        self.stdout.write(
            '   (o «Anclaje en cadena de bloques» en la consola de '
            'operaciones, marcando «Comprobar el ultimo envio»).'
        )

        return True

    def _check_verify(self) -> bool:
        """
        Volver sobre el ultimo envio de prueba y decir si ya cuajo.

        Que todavia no haya bloque **no es un fallo**: es el estado normal
        durante las primeras horas. Solo se da por malo si no hay nada
        guardado o si la prueba no se puede leer.
        """
        self._section('5. Comprobacion del ultimo envio de prueba')

        from ...services import ots

        saved = self._latest_proof()

        if saved is None:
            self.stdout.write(self.style.WARNING(
                '   No hay ningun envio de prueba guardado. Manda uno con '
                '--stamp y vuelve dentro de unas horas.'
            ))
            return True

        digest = saved.stem.split('-')[-1]
        proof = saved.read_bytes()

        try:
            detached = ots.deserialize(proof)
        except Exception as error:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f'   No se pudo leer {saved}: {type(error).__name__}: {error}'
            ))
            return False

        # El nombre del fichero solo lleva ocho caracteres del hash; el bueno
        # es el que va dentro de la prueba.
        full_digest = detached.timestamp.msg.hex()

        age = (timezone.now().timestamp() - saved.stat().st_mtime) / 3600

        self.stdout.write(f'   Enviado hace {age:.1f} horas: {saved.name}')
        self.stdout.write(f'   hash: {full_digest}')

        if not full_digest.startswith(digest):
            self.stdout.write(self.style.WARNING(
                '   El nombre del fichero no cuadra con el hash que lleva '
                'dentro. Manda como bueno el de dentro.'
            ))

        try:
            outcome = ots.upgrade(proof)
        except ots.OTSError as error:
            self.stdout.write(self.style.ERROR(
                f'   No se pudo consultar: {error}'
            ))
            return False

        if outcome['upgraded']:
            try:
                saved.write_bytes(outcome['proof'])
            except OSError as error:
                self.stdout.write(self.style.WARNING(
                    f'   Maduro, pero no se pudo reescribir {saved}: {error}'
                ))

        state = ots.inspect(outcome['proof'], full_digest)

        if not self._describe_state(state):
            return False

        if not state['confirmed']:
            if age > STALE_HOURS:
                self.stdout.write(self.style.WARNING(
                    f'   Lleva {age:.0f} horas y aun no hay bloque, cuando con '
                    f'{MATURES_TO_HOURS} suele bastar. El compromiso sigue en '
                    'pie, pero si se repite conviene mirar si los calendarios '
                    'estan respondiendo.'
                ))
            else:
                self.stdout.write(
                    f'   Es lo normal a las {age:.1f} horas. Vuelve a '
                    'ejecutarlo mas tarde.'
                )

        return True
