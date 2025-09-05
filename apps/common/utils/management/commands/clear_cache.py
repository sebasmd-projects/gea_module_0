# apps/common/utils/management/commands/clear_cache.py
from django.core.cache import cache
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Clear default cache backend"

    def handle(self, *args, **options):
        try:
            cache.clear()
            self.stdout.write(self.style.SUCCESS("Cache cleared."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error clearing cache: {e}"))
