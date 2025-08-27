import logging
import os
from datetime import datetime
from logging import Logger
from typing import List

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

logger: Logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Delete all migration files and folders except __init__.py, and custom apps.
    """
    help = 'Delete all migration files and folders except __init__.py, and custom apps'

    def add_arguments(self, parser: CommandParser) -> None:
        """
        Add arguments to the command line parser.

        Args:
            parser (ArgumentParser): Command line argument parser.
        """
        parser.add_argument(
            '-sp', '--skippermanent', type=str,
            dest='skippermanent', help='Skip permanent app migrations'
        )
        parser.add_argument(
            '-s', '--skip', type=str,
            help='Skip app migrations'
        )

    def handle(self, *args, **options):
        """
        Handle the command execution.

        Args:
            *args: Additional arguments.
            **options: Command options.
        """

        current_time: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.warning(f"Current Time: {current_time}")

        skip_permanent: str = options.get('skippermanent', None)
        skip_current: str = options.get('skip', None)

        skip_apps: list = self.get_skip_apps(skip_permanent)

        deleted_files: list = []
        exceptions: list = []
        deleted_folders: list = []

        if skip_current and skip_current not in skip_apps:
            skip_apps.append(skip_current)

        for app_path in settings.ALL_CUSTOM_APPS:
            app_name: str = app_path.split('.')[-1]

            if app_name in skip_apps:
                continue

            migration_dir: str = os.path.join(
                settings.BASE_DIR, app_path.replace(
                    '.', os.path.sep
                ), 'migrations'
            )

            try:
                self.delete_pycache(app_name, deleted_folders, migration_dir)

                deleted_files.extend(
                    self.delete_migration_files(
                        deleted_files, migration_dir, app_name
                    )
                )
            except FileNotFoundError as e:
                exceptions.append(str(e))

        self.print_results(
            deleted_folders,
            deleted_files,
            exceptions
        )

    def delete_pycache(self, app_name: str, deleted_folders: List[tuple], migration_dir: str) -> None:
        """
        Delete __pycache__ directories.

        Args:
            app_name (str): Name of the app.
            deleted_folders (List[tuple]): List of deleted folders.
            migration_dir (str): Directory path for migrations.
        """
        pycache_dir = os.path.join(migration_dir, '__pycache__')
        if os.path.exists(pycache_dir):
            for item in os.listdir(pycache_dir):
                pycache_item = os.path.join(pycache_dir, item)
                if os.path.isfile(pycache_item):
                    os.remove(pycache_item)
                elif os.path.isdir(pycache_item):
                    os.rmdir(pycache_item)
            os.rmdir(pycache_dir)
            deleted_folders.append((app_name, '__pycache__'))

    def delete_migration_files(self, deleted_files: list, migration_dir: str, app_name: str) -> List[tuple]:
        """
        Delete migration files.

        Args:
            deleted_files (list): List of deleted files.
            migration_dir (str): Directory path for migrations.
            app_name (str): Name of the app.

        Returns:
            List[tuple]: List of deleted files.
        """
        for filename in os.listdir(migration_dir):
            if filename != '__init__.py' and filename.endswith('.py'):
                migration_file = os.path.join(migration_dir, filename)
                os.remove(migration_file)
                deleted_files.append((app_name, filename))
        return deleted_files

    def get_skip_apps(self, app_name: str = None) -> List[str]:
        """
        Get list of apps to skip migration deletion.

        Args:
            app_name (str, optional): Name of the app to skip. Defaults to None.

        Returns:
            List[str]: List of app names to skip.
        """
        utils_data_path: str = getattr(settings, 'UTILS_DATA_PATH', None)
        skip_apps: list = []

        if utils_data_path:
            apps_names_file_path: str = os.path.join(
                settings.BASE_DIR, utils_data_path, 'skip_apps.txt')
            try:
                with open(apps_names_file_path, 'r') as apps_names_file:
                    skip_apps = apps_names_file.read().split(',')

                if app_name and app_name not in skip_apps:
                    skip_apps.append(app_name)
                    with open(apps_names_file_path, 'w') as apps_names_file:
                        apps_names_file.write(','.join(skip_apps))
            except FileNotFoundError:
                logger.error(f"File '{apps_names_file_path}' not found.")
        else:
            logger.warning("No utils path provided in settings.")

        return skip_apps

    def print_results(self, deleted_folders: List[tuple], deleted_files: List[tuple], exceptions: List[str]) -> None:
        """
        Print deletion results.

        Args:
            deleted_folders (List[tuple]): List of deleted folders.
            deleted_files (List[tuple]): List of deleted files.
            exceptions (List[str]): List of exceptions.
        """
        deleted_items = list(set(deleted_folders + deleted_files))

        if deleted_items:
            self.print_deleted(
                deleted_items, 'DELETED'
            )
        else:
            logger.error(
                'No folders or files found or they have already been deleted'
            )

        if exceptions:
            self.print_exceptions(exceptions)

    def print_deleted(self, items: List[tuple], action: str) -> None:
        """
        Print deleted items.

        Args:
            items (List[tuple]): List of items to print.
            action (str): Action performed on items.
        """
        for app_name, name in items:
            logger.warning(f'\n{app_name}\n{name} {action}')

    def print_exceptions(self, exceptions: List[str]) -> None:
        """
        Print exceptions.

        Args:
            exceptions (List[str]): List of exceptions to print.
        """
        logger.error("\nExceptions:")
        for exception in exceptions:
            logger.error(f"- {exception}")
