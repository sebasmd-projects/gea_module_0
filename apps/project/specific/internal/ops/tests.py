# apps/project/specific/internal/ops/tests.py
"""
La consola de operaciones ejecuta procesos en el servidor desde una pagina web.

Casi todo lo que hay aqui comprueba lo que **no** debe poder hacerse. Es el
orden correcto: que la consola funcione es util; que no se pueda usar para
otra cosa es lo que decide si puede existir.

    manage.py test apps.project.specific.internal.ops \\
        --settings=app_core.settings_test
"""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from apps.common.utils.testing import login_with_otp
from apps.project.common.users.models import UserModel

from .models import CommandRunModel
from .registry import COMMANDS_BY_NAME, Command, Option, get_command
from .runner import CommandNotAllowed, build_argv, run

PASSWORD = 'pw-for-tests-123'


class AllowlistTests(TestCase):
    """Lo que no esta declarado no se ejecuta."""

    def test_destructive_commands_are_not_reachable(self):
        """
        Ni los de Django ni los propios del proyecto.

        ``dumpdata`` volcaria la base entera por una pagina web y
        ``delete_migrations`` borra ficheros de todo el repositorio.
        """
        forbidden = (
            'flush', 'sqlflush', 'dumpdata', 'loaddata', 'shell', 'dbshell',
            'delete_migrations', 'rename_migrations', 'createsuperuser',
            'changepassword', 'runserver', 'makemigrations', 'diffsettings',
            'auditlogflush', 'axes_reset_logs', 'axes_reset_failure_logs',
            'two_factor_disable', 'remove_stale_contenttypes',
            'generate_certification_key', 'generate_encryption_key',
            'squashmigrations', 'testserver', 'startapp', 'test',
        )

        for name in forbidden:
            with self.subTest(command=name):
                self.assertIsNone(get_command(name))
                with self.assertRaises(CommandNotAllowed):
                    run(name, {})

    def test_no_entry_runs_a_forbidden_program_either(self):
        """
        La lista blanca es de **programas**, no de nombres de entrada.

        Hay entradas cuyo nombre no coincide con lo que ejecutan --
        ``crontab_add`` lanza ``crontab``, ``git_pull`` lanza ``git`` -- y sin
        esta comprobacion nada impediria declarar una entrada llamada
        ``informe_diario`` que por dentro lanzara ``flush``.
        """
        forbidden = {
            'flush', 'sqlflush', 'dumpdata', 'loaddata', 'shell', 'dbshell',
            'diffsettings', 'delete_migrations', 'rename_migrations',
            'createsuperuser', 'changepassword', 'auditlogflush',
        }

        for name, command in COMMANDS_BY_NAME.items():
            with self.subTest(command=name):
                self.assertNotIn(command.program_name, forbidden)

    def test_makemigrations_can_only_ask_never_write(self):
        """
        La excepcion razonada: ``makemigrations`` esta, pero solo en modo
        pregunta. Lo que lo hace seguro son los argumentos fijos, que el
        operador no puede quitar porque no son opciones.
        """
        command = get_command('makemigrations_check')

        self.assertEqual(command.program_name, 'makemigrations')
        self.assertEqual(command.fixed_args, ('--check', '--dry-run'))

        argv = build_argv(command, {})

        self.assertIn('--check', argv)
        self.assertIn('--dry-run', argv)

    def test_the_pull_can_never_create_a_merge_commit(self):
        """
        ``--ff-only`` es toda la seguridad del pull: sin el, un checkout de
        produccion con algo editado a mano se queda con un merge que nadie ha
        revisado.
        """
        command = get_command('git_pull')

        self.assertIn('--ff-only', build_argv(command, {}))

    def test_an_unknown_command_is_refused(self):
        with self.assertRaises(CommandNotAllowed):
            run('definitely_not_a_command', {})

    def test_only_the_two_declared_binaries_can_run(self):
        """
        Si una entrada pudiera nombrar cualquier ejecutable, la lista blanca
        de comandos no acotaria nada: bastaria con declarar ``bash``.
        """
        from .registry import EXEC_GIT, EXEC_MANAGE

        for name, command in COMMANDS_BY_NAME.items():
            with self.subTest(command=name):
                self.assertIn(command.executable, (EXEC_MANAGE, EXEC_GIT))

    def test_an_unknown_binary_is_refused(self):
        rogue = Command(
            name='rogue', title='x', summary='x', detail='x', example='x',
            executable='bash',
        )

        with self.assertRaises(CommandNotAllowed):
            build_argv(rogue, {})


class ArgumentTests(TestCase):
    """Los parametros se declaran; no se acepta texto libre."""

    def test_the_interpreter_and_manage_py_are_not_user_controlled(self):
        argv = build_argv(get_command('check'), {})

        self.assertTrue(argv[0].endswith(('python', 'python.exe')))
        self.assertTrue(argv[3].endswith('manage.py'))
        self.assertEqual(argv[4], 'check')

    def test_flags_only_appear_when_asked_for(self):
        command = get_command('check')

        self.assertNotIn('--deploy', build_argv(command, {}))
        self.assertIn('--deploy', build_argv(command, {'deploy': True}))

    def test_text_values_must_match_the_declared_pattern(self):
        """El sitio por donde entraria un argumento inventado."""
        command = get_command('check_media')

        hostile = (
            '/home; rm -rf /',
            '--settings=evil',
            '/home/propensi && curl evil.example.com',
            '$(whoami)',
            '`id`',
            '/home\nmalicious',
        )

        for value in hostile:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    build_argv(command, {'find': value})

        # Y una ruta normal sigue pasando.
        argv = build_argv(command, {'find': '/home/propensi'})
        self.assertEqual(argv[-2:], ['--find', '/home/propensi'])

    def test_a_choice_outside_the_list_is_refused(self):
        command = get_command('compilemessages')

        with self.assertRaises(ValidationError):
            build_argv(command, {'locale': '../../etc/passwd'})

        self.assertIn('es', build_argv(command, {'locale': 'es'}))

    def test_a_number_that_is_not_a_number_is_refused(self):
        command = get_command('check_media')

        with self.assertRaises(ValidationError):
            build_argv(command, {'sample': '10; drop table'})

    def test_text_without_a_declared_pattern_is_refused(self):
        """
        Una opcion mal declarada falla cerrada, no abierta.

        Sin esto, olvidarse del patron al anadir un comando abriria un campo
        de texto libre hacia la linea de argumentos.
        """
        sloppy = Command(
            name='check',
            title='x', summary='x', detail='x', example='x',
            options=[Option(flag='--thing', label='x', kind='text')],
        )

        with self.assertRaises(CommandNotAllowed):
            build_argv(sloppy, {'thing': 'anything'})


class AccessTests(TestCase):
    """Solo superusuarios, y no por permiso concedible."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserModel.objects.create_superuser(
            username='ops_root', email='root@example.com', password=PASSWORD,
        )
        cls.staff = UserModel.objects.create_user(
            username='ops_staff', email='staff@example.com', password=PASSWORD,
            user_type=UserModel.UserTypeChoices.BUYER, is_staff=True,
        )
        cls.plain = UserModel.objects.create_user(
            username='ops_plain', email='plain@example.com', password=PASSWORD,
            user_type=UserModel.UserTypeChoices.BUYER,
        )

    def setUp(self):
        self.console = reverse('admin:ops_console')
        self.command = reverse('admin:ops_command', args=['check'])

    def test_a_superuser_gets_in(self):
        login_with_otp(self.client, self.superuser)

        self.assertEqual(self.client.get(self.console).status_code, 200)
        self.assertEqual(self.client.get(self.command).status_code, 200)

    def test_staff_does_not(self):
        """El resto del proyecto deja pasar a staff; esto no."""
        self.client.login(username='ops_staff', password=PASSWORD)

        self.assertNotEqual(self.client.get(self.console).status_code, 200)
        self.assertNotEqual(self.client.get(self.command).status_code, 200)

    def test_an_ordinary_user_does_not(self):
        self.client.login(username='ops_plain', password=PASSWORD)

        self.assertNotEqual(self.client.get(self.console).status_code, 200)

    def test_anonymous_does_not(self):
        self.assertNotEqual(self.client.get(self.console).status_code, 200)

    def test_a_superuser_without_the_second_factor_does_not(self):
        """
        La consola cuelga del admin, y el admin exige segundo factor
        verificado: una sesion autenticada a medias no llega hasta aqui.
        """
        self.client.force_login(self.superuser)

        self.assertNotEqual(self.client.get(self.console).status_code, 200)

    def test_an_unknown_command_page_is_a_404(self):
        login_with_otp(self.client, self.superuser)

        response = self.client.get(
            reverse('admin:ops_command', args=['dumpdata'])
        )
        self.assertEqual(response.status_code, 404)


class ReachableFromThePanelTests(TestCase):
    """
    Que se pueda llegar sin saberse la URL de memoria.

    La consola no es un modelo, asi que el admin no la listaba: habia que
    escribir la ruta a mano. Una herramienta que hay que recordar no la usa
    nadie, y su ausencia del menu hacia pensar que no existia.
    """

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserModel.objects.create_superuser(
            username='ops_link', email='link@example.com', password=PASSWORD,
        )
        cls.staff = UserModel.objects.create_user(
            username='ops_link_staff', email='ls@example.com',
            password=PASSWORD,
            user_type=UserModel.UserTypeChoices.BUYER, is_staff=True,
        )

    def test_the_admin_index_links_to_the_console(self):
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:index'))

        self.assertContains(response, reverse('admin:ops_console'))

    def test_the_run_history_links_to_the_console(self):
        """Son las dos mitades: una lanza, la otra dice que se lanzo."""
        login_with_otp(self.client, self.superuser)

        response = self.client.get(
            reverse('admin:ops_commandrunmodel_changelist')
        )

        self.assertContains(response, reverse('admin:ops_console'))

    def test_the_link_is_not_shown_to_someone_who_cannot_use_it(self):
        """
        Un enlace que lleva a un 404 no es una pista util, es una pista de que
        hay algo ahi.
        """
        login_with_otp(self.client, self.staff)

        response = self.client.get(reverse('admin:index'))

        self.assertNotContains(response, reverse('admin:ops_console'))

    def test_the_console_lists_every_declared_command(self):
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:ops_console'))

        for name in COMMANDS_BY_NAME:
            with self.subTest(command=name):
                self.assertContains(
                    response, reverse('admin:ops_command', args=[name])
                )

    def test_the_console_ships_what_the_search_and_the_filters_need(self):
        """
        Buscar y filtrar pasan por estos tres ganchos. Si un cambio de
        plantilla se lleva uno por delante, la caja de busqueda sigue ahi y
        deja de hacer nada -- que es peor que no tenerla.
        """
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:ops_console'))

        self.assertContains(response, 'id="ops-search"')
        self.assertContains(response, 'data-search=')
        self.assertContains(response, 'data-risk="DANGEROUS"')

    def test_a_command_is_searchable_by_what_it_does(self):
        """No hace falta saber como se llama para encontrarlo."""
        login_with_otp(self.client, self.superuser)

        response = self.client.get(reverse('admin:ops_console'))
        body = response.content.decode().lower()

        # `git_pull` no lleva la palabra "desplegar" en el nombre, pero es lo
        # que alguien escribiria para buscarlo.
        self.assertIn('deploy', body)
        self.assertIn('crontab', body)


class RunningTests(TestCase):
    """Ejecutar de verdad, y dejar constancia."""

    @classmethod
    def setUpTestData(cls):
        cls.superuser = UserModel.objects.create_superuser(
            username='ops_runner', email='runner@example.com',
            password=PASSWORD,
        )

    def setUp(self):
        login_with_otp(self.client, self.superuser)

    def test_running_check_works_and_is_recorded(self):
        response = self.client.post(
            reverse('admin:ops_command', args=['check']), {}
        )

        self.assertEqual(response.status_code, 200)

        record = CommandRunModel.objects.filter(command='check').first()

        self.assertIsNotNone(record)
        self.assertEqual(record.status, CommandRunModel.StatusChoices.SUCCESS)
        self.assertEqual(record.exit_code, 0)
        self.assertEqual(record.run_by_id, self.superuser.pk)
        self.assertIn('System check', record.output)
        # Con dos binarios posibles, la linea tiene que decir cual fue: sin
        # ello `pull --ff-only` y `migrate` se leen igual de sueltos.
        self.assertEqual(record.command_line, 'manage.py check')

    def test_a_dangerous_command_needs_the_typed_confirmation(self):
        url = reverse('admin:ops_command', args=['db_backup'])

        self.client.post(url, {'o': 'backups/'})
        self.assertFalse(CommandRunModel.objects.filter(
            command='db_backup',
            status=CommandRunModel.StatusChoices.SUCCESS,
        ).exists())

        self.client.post(url, {'o': 'backups/', 'confirm': 'wrong'})
        self.assertFalse(CommandRunModel.objects.filter(
            command='db_backup',
            status=CommandRunModel.StatusChoices.SUCCESS,
        ).exists())

    def test_a_refused_argument_is_recorded_too(self):
        """Un intento rechazado es justo el que interesa mirar despues."""
        self.client.post(
            reverse('admin:ops_command', args=['check_media']),
            {'find': '--settings=evil'},
        )

        record = CommandRunModel.objects.filter(command='check_media').first()

        self.assertIsNotNone(record)
        self.assertEqual(record.status, CommandRunModel.StatusChoices.REFUSED)

    def test_the_audit_trail_cannot_be_edited_or_deleted(self):
        from django.contrib import admin

        model_admin = admin.site._registry[CommandRunModel]
        request = type('R', (), {'user': self.superuser})()

        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))


class RegistryTests(TestCase):
    """El registro tiene que estar bien puesto para que lo demas se sostenga."""

    def test_every_text_option_declares_a_pattern(self):
        for name, command in COMMANDS_BY_NAME.items():
            for option in command.options:
                if option.kind == 'text':
                    with self.subTest(command=name, option=option.name):
                        self.assertTrue(
                            option.pattern,
                            'a text option without a pattern is a free-form '
                            'argument into the command line',
                        )

    def test_every_command_explains_itself(self):
        """La consola existe para que no haya que adivinar que hace cada uno."""
        for name, command in COMMANDS_BY_NAME.items():
            with self.subTest(command=name):
                self.assertTrue(str(command.summary))
                self.assertTrue(str(command.detail))
                self.assertTrue(str(command.example))

    def test_every_listed_command_actually_exists(self):
        """
        Una entrada que apunta a un comando inexistente es una tarjeta que
        falla al pulsarla, y no se descubre hasta que alguien la pulsa.
        """
        from django.core.management import get_commands

        from .registry import EXEC_MANAGE

        available = set(get_commands())

        for name, command in COMMANDS_BY_NAME.items():
            if command.executable != EXEC_MANAGE:
                continue

            with self.subTest(command=name):
                self.assertIn(command.program_name, available)

    def test_every_command_is_filed_under_a_known_area(self):
        from .registry import AREA_LABELS

        for name, command in COMMANDS_BY_NAME.items():
            with self.subTest(command=name):
                self.assertIn(command.area, AREA_LABELS)

    def test_every_group_has_something_in_it(self):
        """Un titulo de area sin tarjetas debajo es ruido en la consola."""
        from .registry import grouped_commands

        for area, label, commands in grouped_commands():
            with self.subTest(area=area):
                self.assertTrue(commands)

    def test_the_search_text_finds_a_command_by_what_it_does(self):
        """
        El buscador de la consola mira este texto. Si solo llevara el nombre,
        habria que saber como se llama el comando para encontrarlo -- que es
        justo lo que no sabe quien lo necesita.
        """
        haystack = get_command('sendtestemail').search_text

        for needle in ('email', 'otp', 'mail'):
            with self.subTest(needle=needle):
                self.assertIn(needle, haystack)

    def test_positional_options_are_required_and_patterned(self):
        for name, command in COMMANDS_BY_NAME.items():
            for option in command.options:
                if not option.positional:
                    continue

                with self.subTest(command=name, option=option.name):
                    # Un posicional que falta corre el comando sin el, y
                    # `sqlmigrate` sin app hace otra cosa, no nada.
                    self.assertTrue(option.required)
                    self.assertTrue(option.pattern)


class PositionalArgumentTests(TestCase):
    """Los argumentos que van sueltos, sin bandera delante."""

    def test_a_positional_goes_at_the_end_without_its_flag(self):
        argv = build_argv(get_command('sqlmigrate'), {
            'app_label': 'buyers', 'migration_name': '0012',
        })

        self.assertEqual(argv[-2:], ['buyers', '0012'])
        self.assertNotIn('app_label', argv)

    def test_the_order_of_the_positionals_is_the_declared_one(self):
        """``sqlmigrate 0012 buyers`` no es lo mismo que al reves."""
        command = get_command('sqlmigrate')

        self.assertEqual(
            [option.name for option in command.options],
            ['app_label', 'migration_name'],
        )

    def test_a_missing_required_value_is_refused(self):
        with self.assertRaises(ValidationError):
            build_argv(get_command('sqlmigrate'), {'app_label': 'buyers'})

    def test_a_positional_still_has_to_match_its_pattern(self):
        """
        Es lo unico que separa un posicional de una cadena libre en la linea
        de comandos.
        """
        with self.assertRaises(ValidationError):
            build_argv(get_command('axes_reset_ip'), {'ip': '$(whoami)'})

        with self.assertRaises(ValidationError):
            build_argv(get_command('findstatic'), {
                'staticfile': '../../etc/passwd; rm -rf /',
            })

    def test_a_value_starting_with_a_dash_cannot_pass_as_an_option(self):
        """
        El separador ``--``. El patron ya lo impide, pero apoyarse solo en eso
        deja el argumento a merced de un patron mal escrito.
        """
        argv = build_argv(get_command('findstatic'), {
            'staticfile': 'css/aegis_header.css',
        })

        self.assertIn('--', argv)
        self.assertEqual(argv[-1], 'css/aegis_header.css')
        self.assertLess(argv.index('--'), len(argv) - 1)


class GitCommandTests(TestCase):
    """El otro binario."""

    def test_git_runs_git_and_not_manage_py(self):
        argv = build_argv(get_command('git_status'), {})

        self.assertEqual(argv[0], 'git')
        self.assertEqual(argv[1], 'status')
        self.assertNotIn('manage.py', ' '.join(argv))

    def test_the_printed_line_says_which_program_ran(self):
        """
        Sin el nombre del programa, ``pull --ff-only`` y ``migrate`` se leen
        igual de sueltos en el registro de auditoria.
        """
        from .runner import printable_argv

        command = get_command('git_pull')

        self.assertEqual(
            printable_argv(command, build_argv(command, {})),
            'git pull --ff-only',
        )

    def test_a_manage_command_still_reads_as_manage_py(self):
        from .runner import printable_argv

        command = get_command('check')

        self.assertEqual(
            printable_argv(command, build_argv(command, {'deploy': True})),
            'manage.py check --deploy',
        )
