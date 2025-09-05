from django.core.management.base import BaseCommand
from apps.common.utils.models import GeaDailyUniqueCode


class Command(BaseCommand):
    help = "Genera (si no existe) y envía el código GEA del día."

    def handle(self, *args, **options):
        obj = GeaDailyUniqueCode.send_today(
            kind=GeaDailyUniqueCode.KindChoices.GENERAL
        )
        obj_buyer = GeaDailyUniqueCode.send_today(
            kind=GeaDailyUniqueCode.KindChoices.BUYER
        )
        
        self.stdout.write(
            self.style.SUCCESS(
                f"GEA code for BUYER {obj_buyer.valid_on}: {obj_buyer.code} sent to {obj_buyer.sent_to}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"GEA code for GENERAL {obj.valid_on}: {obj.code} sent to {obj.sent_to}"
            )
        )
