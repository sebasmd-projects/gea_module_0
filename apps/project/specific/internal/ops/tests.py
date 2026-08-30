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
            'runserver', 'makemigrations',
        )

        for name in forbidden:
            with self.subTest(command=name):
                self.assertIsNone(get_command(name))
                with self.assertRaises(CommandNotAllowed):
                    run(name, {})

    def test_an_unknown_command_is_refused(self):
        with self.assertRaises(CommandNotAllowed):
            run('definitely_not_a_command', {})


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
        self.assertEqual(record.command_line, 'check')

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
        from django.core.management import get_commands

        available = set(get_commands())

        for name in COMMANDS_BY_NAME:
            with self.subTest(command=name):
                self.assertIn(name, available)
