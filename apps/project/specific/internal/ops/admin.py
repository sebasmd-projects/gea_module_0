# apps/project/specific/internal/ops/admin.py
"""
La consola de operaciones, dentro del admin.

Dos pantallas colgando del registro de ejecuciones:

* la **consola**, con los comandos permitidos agrupados por riesgo;
* el **detalle** de cada comando, con su explicacion, sus parametros y el
  boton de ejecutar.

El acceso esta cerrado a superusuarios. No a ``is_staff``: el resto del
proyecto deja pasar a staff en casi todo, y esto no es "casi todo" -- es
ejecutar procesos en el servidor. Un permiso de Django tampoco bastaria,
porque se concede desde la propia interfaz y quien lo tenga podria darselo.
"""

from django.contrib import admin, messages
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.common.utils.admin import GeneralAdminModel

from .models import CommandRunModel
from .registry import (KIND_CHOICE, KIND_FLAG, KIND_NUMBER, RISK_DANGEROUS,
                       RISK_LABELS, RISK_READ_ONLY, get_command,
                       grouped_commands)
from .runner import CommandNotAllowed, run

RISK_COLORS = {
    RISK_READ_ONLY: '#1a7f37',
    'WRITES': '#a17f1a',
    RISK_DANGEROUS: '#a11a1a',
}


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')

    if forwarded:
        return forwarded.split(',')[0].strip()

    return request.META.get('REMOTE_ADDR')


@admin.register(CommandRunModel)
class CommandRunModelAdmin(GeneralAdminModel):
    """Historial de ejecuciones, y la consola colgada de el."""

    list_display = (
        'created', 'command', 'status_badge', 'exit_code',
        'duration_seconds', 'run_by',
    )
    list_filter = ('status', 'command')
    search_fields = ('command', 'command_line', 'output')
    date_hierarchy = 'created'
    ordering = ('-created',)

    # El historial es un registro de auditoria: se lee, no se edita.
    readonly_fields = (
        'command', 'arguments', 'command_line', 'status', 'exit_code',
        'duration_seconds', 'output', 'run_by', 'client_ip',
        'created', 'updated',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Borrar el rastro de lo que se ejecuto en produccion vaciaria de
        # sentido el registro.
        return False

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    @admin.display(description=_('Status'))
    def status_badge(self, obj):
        colors = {
            CommandRunModel.StatusChoices.SUCCESS: '#1a7f37',
            CommandRunModel.StatusChoices.FAILED: '#a11a1a',
            CommandRunModel.StatusChoices.TIMED_OUT: '#a17f1a',
            CommandRunModel.StatusChoices.REFUSED: '#6b1a7f',
        }

        return format_html(
            '<b style="color:{}">{}</b>',
            colors.get(obj.status, '#333'),
            obj.get_status_display(),
        )

    # ------------------------------------------------------------------
    # Rutas propias
    # ------------------------------------------------------------------
    def get_urls(self):
        own = [
            path(
                'console/',
                self.admin_site.admin_view(self.console_view),
                name='ops_console',
            ),
            path(
                'console/<str:name>/',
                self.admin_site.admin_view(self.command_view),
                name='ops_command',
            ),
        ]
        return own + super().get_urls()

    def _guard(self, request):
        """Solo superusuarios. Se aborta con 404, no con 403."""
        if not (request.user.is_active and request.user.is_superuser):
            raise Http404

    def _base_context(self, request, **extra):
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'has_permission': True,
        }
        context.update(extra)
        return context

    def console_view(self, request):
        self._guard(request)

        context = self._base_context(
            request,
            title=_('Operations console'),
            groups=grouped_commands(),
            risk_colors=RISK_COLORS,
            recent=CommandRunModel.objects.all()[:10],
        )

        return TemplateResponse(
            request, 'admin/ops/console.html', context
        )

    def command_view(self, request, name):
        self._guard(request)

        command = get_command(name)

        if command is None:
            raise Http404

        result = None

        if request.method == 'POST':
            result = self._execute(request, command)

            if result is None:
                return HttpResponseRedirect(request.path)

        context = self._base_context(
            request,
            title=str(command.title),
            command=command,
            risk_label=RISK_LABELS.get(command.risk, command.risk),
            risk_color=RISK_COLORS.get(command.risk, '#333'),
            result=result,
            flag_kind=KIND_FLAG,
            number_kind=KIND_NUMBER,
            choice_kind=KIND_CHOICE,
            history=CommandRunModel.objects.filter(command=command.name)[:5],
            console_url=reverse('admin:ops_console'),
        )

        return TemplateResponse(
            request, 'admin/ops/command.html', context
        )

    # ------------------------------------------------------------------
    def _execute(self, request, command):
        """Lanza el comando y deja constancia, salga bien o mal."""
        from django.core.exceptions import ValidationError

        # Los peligrosos piden escribir su nombre. Es friccion a proposito:
        # evita el clic por inercia, no a un atacante.
        if command.needs_confirmation:
            typed = (request.POST.get('confirm') or '').strip()

            if typed != command.name:
                messages.error(
                    request,
                    _('Type "%(name)s" to confirm before running it.')
                    % {'name': command.name}
                )
                return None

        values = {}

        for option in command.options:
            if option.kind == KIND_FLAG:
                values[option.name] = bool(request.POST.get(option.name))
            else:
                values[option.name] = request.POST.get(option.name, '')

        try:
            outcome = run(command.name, values)
        except ValidationError as error:
            self._record(request, command, values, '',
                         CommandRunModel.StatusChoices.REFUSED,
                         output='; '.join(error.messages))
            messages.error(request, '; '.join(error.messages))
            return None
        except CommandNotAllowed:
            self._record(request, command, values, '',
                         CommandRunModel.StatusChoices.REFUSED,
                         output='not allowed')
            messages.error(request, _('That command is not allowed.'))
            return None

        if outcome['timed_out']:
            status = CommandRunModel.StatusChoices.TIMED_OUT
        elif outcome['exit_code'] == 0:
            status = CommandRunModel.StatusChoices.SUCCESS
        else:
            status = CommandRunModel.StatusChoices.FAILED

        record = self._record(
            request, command, values, outcome['printable'], status,
            output=outcome['output'],
            exit_code=outcome['exit_code'],
            duration=outcome['duration'],
        )

        if status == CommandRunModel.StatusChoices.SUCCESS:
            messages.success(
                request,
                _('%(title)s finished in %(seconds)s s.')
                % {'title': command.title, 'seconds': outcome['duration']}
            )
        elif status == CommandRunModel.StatusChoices.TIMED_OUT:
            messages.warning(
                request,
                _('%(title)s was cut off after %(seconds)s s. The output '
                  'below is partial, and the command may have kept going.')
                % {'title': command.title, 'seconds': command.timeout}
            )
        else:
            messages.error(
                request,
                _('%(title)s failed with exit code %(code)s.')
                % {'title': command.title, 'code': outcome['exit_code']}
            )

        return record

    def _record(self, request, command, values, printable, status,
                *, output='', exit_code=None, duration=0.0):
        return CommandRunModel.objects.create(
            command=command.name,
            arguments=values,
            command_line=printable,
            status=status,
            exit_code=exit_code,
            duration_seconds=duration,
            output=output,
            run_by=request.user if request.user.is_authenticated else None,
            client_ip=_client_ip(request),
        )
