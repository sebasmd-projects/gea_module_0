# apps/project/specific/internal/ops/models.py
"""
Registro de lo que se ha ejecutado desde la consola de operaciones.

Una pagina que lanza comandos en el servidor tiene que dejar constancia de
quien lanzo que y con que resultado. Sin esto, la consola seria una via para
tocar produccion sin rastro, que es exactamente lo contrario de lo que hace
falta en una plataforma que se dedica a acreditar integridad.

El registro se guarda **siempre**, tambien cuando el comando falla o se corta
por tiempo: un intento fallido es justo el que interesa mirar despues.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.utils.models import TimeStampedModel


class CommandRunModel(TimeStampedModel):
    """Una ejecucion, con su salida completa."""

    class StatusChoices(models.TextChoices):
        SUCCESS = 'SUCCESS', _('Finished')
        FAILED = 'FAILED', _('Failed')
        TIMED_OUT = 'TIMED_OUT', _('Cut off by timeout')
        REFUSED = 'REFUSED', _('Refused')

    command = models.CharField(
        _('Command'),
        max_length=100,
        db_index=True
    )

    arguments = models.JSONField(
        _('Arguments'),
        default=dict,
        blank=True,
        help_text=_('The values as they were filled in the form.')
    )

    command_line = models.TextField(
        _('Command line'),
        blank=True,
        default='',
        help_text=_('What was actually run, argument by argument.')
    )

    status = models.CharField(
        _('Status'),
        max_length=20,
        choices=StatusChoices.choices,
        db_index=True
    )

    exit_code = models.IntegerField(
        _('Exit code'),
        blank=True,
        null=True
    )

    duration_seconds = models.FloatField(
        _('Duration (s)'),
        default=0.0
    )

    output = models.TextField(
        _('Output'),
        blank=True,
        default=''
    )

    run_by = models.ForeignKey(
        'users.UserModel',
        on_delete=models.SET_NULL,
        related_name='ops_command_runs',
        verbose_name=_('Run by'),
        blank=True,
        null=True
    )

    # Se guarda para poder atar una ejecucion a una sesion concreta si algun
    # dia hay que reconstruir que paso.
    client_ip = models.GenericIPAddressField(
        _('Client IP'),
        blank=True,
        null=True
    )

    def __str__(self) -> str:
        return f'{self.command} · {self.get_status_display()}'

    @property
    def succeeded(self) -> bool:
        return self.status == self.StatusChoices.SUCCESS

    class Meta:
        db_table = 'apps_ops_command_run'
        verbose_name = _('Command run')
        verbose_name_plural = _('Command runs')
        ordering = ['-created']
        indexes = [
            models.Index(fields=['command', '-created']),
            models.Index(fields=['status']),
        ]
