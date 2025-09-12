# apps/common/management/commands/runserver.py
import os
import socket
from django.core.management.commands.runserver import Command as DjangoRunserver

def _get_ipv4() -> str:
    # Obtiene la IPv4 “saliente” de la máquina (con fallback)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no envía datos
            return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"

class Command(DjangoRunserver):
    # por defecto siempre 0.0.0.0:8000
    default_addr = "0.0.0.0"
    default_port = "8000"

    def inner_run(self, *args, **options):
        # Evita imprimir dos veces con el autoreloader
        use_reloader = options.get("use_reloader", True)
        in_child = os.environ.get("RUN_MAIN") == "true"
        if not use_reloader or in_child:
            ip = _get_ipv4()
            url = f"http://{ip}:{self.port}/"
            self.stdout.write(self.style.SUCCESS(f"\n🌐  Click: {url}\n"))
        return super().inner_run(*args, **options)
