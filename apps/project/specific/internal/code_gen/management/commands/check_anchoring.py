# apps/project/specific/internal/code_gen/management/commands/check_anchoring.py
"""
Por que el envio a la cadena de bloques no sale de este servidor.

El compositor avisa de que el sello se guardo pero el envio fallo, y ahi se
acaba lo que puede contar una pantalla. La causa esta casi siempre fuera del
codigo, y son dos muy distintas que conviene no confundir:

* **La libreria no esta.** ``opentimestamps`` esta declarada en el proyecto,
  pero un despliegue que no volvio a sincronizar dependencias se queda sin
  ella. Se arregla con ``uv sync``.
* **La red de salida esta cerrada.** En hosting compartido es lo habitual:
  las conexiones salientes hacia terceros se filtran, y entonces no hay nada
  que arreglar en el codigo -- hay que pedirselo al proveedor o anclar desde
  otra maquina.

Esto las separa en diez segundos y sin SSH, porque se ejecuta desde la consola
de operaciones. No manda nada a ningun sitio salvo que se pida ``--stamp``.

    manage.py check_anchoring
    manage.py check_anchoring --stamp
"""

import hashlib
import socket
import time
from urllib.parse import urlparse

from django.core.management.base import BaseCommand

TCP_TIMEOUT = 8


class Command(BaseCommand):
    help = 'Comprueba si este servidor puede anclar en OpenTimestamps.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--stamp',
            action='store_true',
            help=(
                'Ademas de comprobar, envia un hash de prueba de verdad. Es '
                'inofensivo: el hash es inventado y no queda asociado a '
                'ningun documento.'
            ),
        )

    def handle(self, *args, **options):
        ok = True

        ok &= self._check_library()
        calendars = self._calendars()
        ok &= self._check_reachability(calendars)

        if options['stamp']:
            ok &= self._check_stamp()

        self.stdout.write('')

        if ok:
            self.stdout.write(self.style.SUCCESS(
                'Este servidor puede anclar en la cadena de bloques.'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                'Este servidor NO puede anclar. Mira los detalles de arriba: '
                'si falla la libreria, ejecuta "uv sync"; si fallan las '
                'conexiones, es el cortafuegos de salida del hosting y hay '
                'que pedirselo al proveedor.'
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
                '   Se arregla con "uv sync" en el servidor: la dependencia '
                'esta declarada, solo falta instalarla.'
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

    def _check_stamp(self) -> bool:
        """El envio completo, con un hash de prueba que no es de nadie."""
        self._section('3. Envio de prueba')

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

        self.stdout.write(self.style.SUCCESS(
            f'   Aceptado por {len(result["calendars"])} calendario(s); '
            f'prueba de {len(result["proof"])} bytes.'
        ))

        for url in result['calendars']:
            self.stdout.write(f'      {url}')

        return True
