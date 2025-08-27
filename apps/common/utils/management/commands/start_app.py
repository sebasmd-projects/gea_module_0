import os
from pathlib import Path
from django.core.management.commands.startapp import Command as StartAppCommand


class Command(StartAppCommand):
    def handle(self, *args, **options):
        # Ejecuta el comando original
        super().handle(*args, **options)

        # Nombre de la app (si no se da, Django lo solicita)
        app_name = args[0] if args else options.get("name")
        if not app_name:
            self.stderr.write(self.style.ERROR("Please provide an app name"))
            return

        # Determinar el path de la app y convertirlo al módulo completo
        app_path = Path(app_name).resolve()
        project_root = Path().resolve()  # Raíz del proyecto
        module_path = app_path.relative_to(project_root).as_posix().replace("/", ".")

        # Modifica apps.py
        apps_path = app_path / "apps.py"
        if apps_path.exists():
            with open(apps_path, "r") as file:
                lines = file.readlines()

            updated_lines = []
            for line in lines:
                if "name =" in line:
                    updated_lines.append(f"    name = '{module_path}'\n")
                else:
                    updated_lines.append(line)

            with open(apps_path, "w") as file:
                file.writelines(updated_lines)

        # Crea urls.py
        urls_path = app_path / "urls.py"
        if not urls_path.exists():
            with open(urls_path, "w") as file:
                file.write(
                    "from django.urls import path\n\n"
                    f"app_name = '{module_path}'\n\n"
                    "urlpatterns = []\n"
                )

        # Crea el folder "locale"
        locale_path = app_path / "locale"
        locale_path.mkdir(exist_ok=True)

        # Modifica models.py
        models_path = app_path / "models.py"
        if models_path.exists():
            with open(models_path, "w") as file:
                file.write(
                    "from django.db import models\n"
                    "from django.utils.translation import gettext_lazy as _\n\n"
                    "from apps.common.utils.models import TimeStampedModel\n"
                )

        self.stdout.write(self.style.SUCCESS(f"Customized app '{module_path}' created successfully!"))
