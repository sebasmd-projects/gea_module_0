from django.core.management.base import BaseCommand
from apps.common.utils.models import GeaDailyUniqueCode

class Command(BaseCommand):
    help = "Genera (si no existe) y envía el código GEA del día."

    def handle(self, *args, **options):
        obj = GeaDailyUniqueCode.send_today()
        self.stdout.write(self.style.SUCCESS(
            f"GEA code for {obj.valid_on}: {obj.code} sent to {obj.sent_to}"
        ))