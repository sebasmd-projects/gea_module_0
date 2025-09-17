from pathlib import Path
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Genera respaldos JSON indentados y sin indentación (con y sin usuarios)."

    def add_arguments(self, parser):
        parser.add_argument(
            "-o", "--output-dir",
            default=".",
            help="Directorio de salida (por defecto: actual).",
        )

    def handle(self, *args, **options):
        output_dir = Path(options["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # Archivos de salida
        files = {
            "h_backup.json": {"users_only": False, "indent": 4},
            "backup.json": {"users_only": False, "indent": None},
            "h_users_backup.json": {"users_only": True, "indent": 4},
            "users_backup.json": {"users_only": True, "indent": None},
        }

        # Exclusiones globales (sistema / terceros que no interesan)
        exclude = [
            "contenttypes",
            "auth.Permission",
            "admin.LogEntry",
            "sessions.Session",
            "axes.AccessAttempt",
            "axes.AccessLog",
            "auditlog.LogEntry",
        ]

        for filename, cfg in files.items():
            output = output_dir / filename
            with output.open("w", encoding="utf-8") as f:
                if cfg["users_only"]:
                    apps = ["users"]
                else:
                    apps = [
                        "core",
                        "utils",
                        "assets",
                        "assets_location",
                        "buyers",
                        "account",
                        "notifications",
                    ]

                call_command(
                    "dumpdata",
                    *apps,
                    use_natural_foreign_keys=False,
                    use_natural_primary_keys=False,
                    exclude=exclude,
                    indent=cfg["indent"],
                    stdout=f,
                )

            self.stdout.write(self.style.SUCCESS(
                f"✔ Backup generado: {output.resolve()}"
            ))
