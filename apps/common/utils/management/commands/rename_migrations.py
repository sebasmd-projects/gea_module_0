import logging
import os
import random
import string
from logging import Logger
from typing import List

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

logger: Logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Rename migration files by adding a random 4-character suffix to '0001_initial.py'.
    """
    help = "Rename '0001_initial.py' files by appending a random 4-character suffix."

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Add arguments to the command line parser.

        Args:
            parser (CommandParser): Command line argument parser.
        """
        parser.add_argument(
            '-s', '--skip', type=str, help='Skip specific app migrations'
        )

    def handle(self, *args, **options) -> None:
        """
        Handle the command execution.

        Args:
            *args: Additional arguments.
            **options: Command options.
        """
        skip_current: str = options.get('skip', None)
        skip_apps: List[str] = skip_current.split(',') if skip_current else []

        renamed_files: List[tuple] = []
        exceptions: List[str] = []

        for app_path in settings.ALL_CUSTOM_APPS:
            app_name: str = app_path.split('.')[-1]

            if app_name in skip_apps:
                continue

            migration_dir: str = os.path.join(
                settings.BASE_DIR, app_path.replace('.', os.path.sep), 'migrations'
            )

            try:
                renamed_files.extend(self.rename_migration_files(migration_dir, app_name))
            except FileNotFoundError as e:
                exceptions.append(str(e))

        self.print_results(renamed_files, exceptions)

    def rename_migration_files(self, migration_dir: str, app_name: str) -> List[tuple]:
        """
        Rename migration files by adding a random 4-character suffix.

        Args:
            migration_dir (str): Directory path for migrations.
            app_name (str): Name of the app.

        Returns:
            List[tuple]: List of renamed files.
        """
        renamed_files: List[tuple] = []

        if not os.path.exists(migration_dir):
            raise FileNotFoundError(f"Migration directory '{migration_dir}' does not exist.")

        for filename in os.listdir(migration_dir):
            if filename == '0001_initial.py':
                random_suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=4))
                new_filename = f"0001_initial_{random_suffix}.py"
                old_file_path = os.path.join(migration_dir, filename)
                new_file_path = os.path.join(migration_dir, new_filename)
                os.rename(old_file_path, new_file_path)
                renamed_files.append((app_name, filename, new_filename))

        return renamed_files

    def print_results(self, renamed_files: List[tuple], exceptions: List[str]) -> None:
        """
        Print renaming results.

        Args:
            renamed_files (List[tuple]): List of renamed files.
            exceptions (List[str]): List of exceptions.
        """
        if renamed_files:
            logger.info("\nRenamed Files:")
            for app_name, old_name, new_name in renamed_files:
                logger.info(f"{app_name}: {old_name} -> {new_name}")
        else:
            logger.info("No files renamed.")

        if exceptions:
            logger.error("\nExceptions:")
            for exception in exceptions:
                logger.error(f"- {exception}")
