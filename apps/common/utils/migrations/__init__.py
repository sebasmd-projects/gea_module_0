import django.utils.timezone
from django.contrib.postgres.operations import (TrigramExtension,
                                                UnaccentExtension)
from django.db import migrations


class Migration(migrations.Migration):

    operations = [
        UnaccentExtension(),
        TrigramExtension(),
    ]