# apps/common/utils/tests/test_realtime.py
"""
Que la Fase 0 conteste lo que midio, y solo eso.

Este comando decide si la aplicacion se queda en cPanel o hay que mudarla al
VPS -- base de datos, media, estaticos, cron, TLS y una ventana de corte. Un
verde de mas lleva a construir el tiempo real encima de un canal que no
funciona; un rojo de mas lleva a mudar una aplicacion que no hacia falta mudar.
Asi que lo que se comprueba aqui no es que el comando corra: es que **cada
desenlace se cuente como lo que es**.

Tres cosas que salieron de ejecutarlo contra un Redis de verdad, y que por eso
tienen prueba propia.

**Suscribirse no falla donde uno se suscribe.** ``subscribe()`` de redis-py
escribe el comando y no lee la respuesta. Con la ACL de la cache
(``resetchannels``), la primera version daba «SUBSCRIBE: permitido» y el NOPERM
aparecia tres secciones mas abajo disfrazado de otra cosa.

**Un NOPERM no es un servidor inalcanzable.** Son dos averias que se arreglan
en sitios distintos --una linea de ACL, o el cortafuegos-- y la primera version
las confundia: con la ACL de la cache decia «no se llega al Redis», que era
falso, y contaba «se abrieron 0 de 4 conexiones», que acusaba al hosting de lo
que hacia el permiso.

**La quinta pregunta no se mide aqui y no puede dar verde.** Esa conexion sale
del VPS. Un comando de verificacion que da por buena una comprobacion que nunca
ocurrio es peor que no tenerlo.

    manage.py test apps.common.utils.tests.test_realtime \\
        --settings=app_core.settings_test
"""

from io import StringIO
from unittest import mock

import redis
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

FROM_URL = 'redis.Redis.from_url'
MODULE = 'apps.common.utils.management.commands.check_realtime'

REDIS_URL = 'redis://gea:secreto@redis.example.org:6380/0'


def denied(command):
    """Lo que contesta Redis cuando la ACL no deja: NOPERM, con respuesta."""
    return redis.exceptions.NoPermissionError(
        f"this user has no permissions to run the '{command}' command"
    )


def unreachable():
    """Lo que sale cuando no hay servidor al otro lado: no es una respuesta."""
    return redis.exceptions.ConnectionError('Connection refused')


class FakePubSub:
    """
    Una suscripcion que contesta como la de verdad, incluida la parte lenta.

    Lo que la hace util es que ``subscribe()`` **no comprueba nada**: guarda el
    canal y ya. Lo que decide llega por ``get_message``, que es donde redis-py
    lee la respuesta del servidor. Un doble que fallara en ``subscribe()``
    haria pasar la prueba con el codigo que tenia el fallo.
    """

    def __init__(self, cliente, *, allow=True):
        self.cliente = cliente
        self.allow = allow
        self.subscribed = []
        self.pending = []
        self.closed = False

    def subscribe(self, channel):
        self.subscribed.append(channel)

        if self.allow:
            self.pending.append({'type': 'subscribe', 'channel': channel})

    def get_message(self, timeout=0):
        if not self.allow:
            raise denied('subscribe')

        if self.pending:
            return self.pending.pop(0)

        if self.cliente.published is not None:
            entregado = self.cliente.published
            self.cliente.published = None
            return {'type': 'message', 'data': entregado}

        return None

    def close(self):
        self.closed = True


class FakeRedis:
    """Un Redis de mentira que se comporta como el de verdad en lo que importa."""

    def __init__(self, *, pubsub_allowed=True, publish_allowed=True,
                 delivers=True, ping_error=None, ping_calls_before_error=None):
        self.pubsub_allowed = pubsub_allowed
        self.publish_allowed = publish_allowed
        self.delivers = delivers
        self.ping_error = ping_error
        self.ping_calls_before_error = ping_calls_before_error
        self.ping_calls = 0
        self.published = None
        self.pubsubs = []

    def pubsub(self, **kwargs):
        creada = FakePubSub(self, allow=self.pubsub_allowed)
        self.pubsubs.append(creada)
        return creada

    def publish(self, channel, payload):
        if not self.publish_allowed:
            raise denied('publish')

        if self.delivers:
            self.published = payload

        return 1 if self.delivers else 0

    def ping(self):
        self.ping_calls += 1

        if self.ping_error is None:
            return True

        if self.ping_calls_before_error is None:
            raise self.ping_error

        if self.ping_calls > self.ping_calls_before_error:
            raise self.ping_error

        return True

    def close(self):
        pass


def run(client=None, **options):
    """Ejecutar el comando con ese Redis y devolver lo que escribio."""
    salida = StringIO()

    opciones = {'samples': 2, 'connections': 2, 'stdout': salida,
                'stderr': salida}
    opciones.update(options)

    if client is None:
        call_command('check_realtime', **opciones)
    else:
        with mock.patch(FROM_URL, return_value=client):
            call_command('check_realtime', **opciones)

    return salida.getvalue()


@override_settings(REDIS_URL='')
class SinRedisTestCase(SimpleTestCase):
    """Sin Redis configurado no hay respuesta, y eso no es un «no»."""

    def test_no_se_confunde_con_un_canal_roto(self):
        texto = run()

        self.assertIn('no hay Redis configurado', texto)
        self.assertIn('la pregunta no se ha llegado a hacer', texto)

        # Lo que NO puede decir: que el tiempo real no se sostiene. No se ha
        # medido nada, y ese veredicto manda a mudar la aplicacion.
        self.assertNotIn('NO se sostiene', texto)

    def test_la_explicacion_se_da_una_vez(self):
        """
        Tres secciones se quedan sin medir por el mismo motivo.

        Repetir el parrafo entero tres veces hace que se lea cero: en pantalla
        parecen tres averias distintas. Se explica en la primera y las otras
        remiten a ella.
        """
        texto = run()

        self.assertEqual(texto.count('cae en LocMemCache'), 1)
        self.assertEqual(texto.count('Sin REDIS_URL (ver la seccion 1)'), 2)


@override_settings(REDIS_URL=REDIS_URL)
class CanalTestCase(SimpleTestCase):
    """La primera pregunta: ¿sale un mensaje de aqui y vuelve por el canal?"""

    def test_el_canal_completo_sale_bien(self):
        texto = run(FakeRedis())

        self.assertIn('SUBSCRIBE: confirmado por el servidor', texto)
        self.assertIn('PUBLISH: permitido', texto)
        self.assertIn('funciona de punta a punta', texto)

    def test_sin_canales_en_la_acl_se_cuenta_como_denegado(self):
        """
        El fallo que encontro ejecutarlo de verdad.

        ``subscribe()`` no lee la respuesta del servidor, asi que un doble --y
        un Redis-- que niegan el permiso no lo niegan ahi: lo niegan en la
        primera lectura. Si el comando se fiara de que ``subscribe()`` no
        lanzo, esto diria «permitido».
        """
        texto = run(FakeRedis(pubsub_allowed=False))

        self.assertNotIn('SUBSCRIBE: confirmado', texto)
        self.assertIn('NoPermissionError', texto)

        # Y que diga donde se arregla: los canales no los conceden los
        # patrones de clave, van aparte con `&`.
        self.assertIn('`&`', texto)
        self.assertIn('~gea:*', texto)

    def test_publicar_es_otro_permiso(self):
        texto = run(FakeRedis(publish_allowed=False))

        self.assertIn('SUBSCRIBE: confirmado por el servidor', texto)
        self.assertIn('PUBLISH:', texto)
        self.assertIn('permisos distintos', texto)
        self.assertNotIn('funciona de punta a punta', texto)

    def test_publicar_sin_que_llegue_no_es_un_canal(self):
        """
        ``PUBLISH`` no falla cuando nadie escucha: devuelve 0 receptores.

        Comprobar el canal por el valor de retorno daria por bueno un canal que
        nadie puede oir -- dos conexiones contra Redis distintos detras de un
        balanceador, que es justo lo que rompe el tiempo real sin romper la
        cache.
        """
        texto = run(FakeRedis(delivers=False))

        self.assertIn('PUBLISH: permitido (0 receptor/es)', texto)
        self.assertIn('NO volvio por la suscripcion', texto)
        self.assertNotIn('funciona de punta a punta', texto)

    def test_el_canal_lleva_el_prefijo_configurado(self):
        """
        Y sale del ajuste, no de un 'gea' escrito dentro del comando.

        Con otro prefijo configurado, un canal `gea:*` cae fuera del patron
        `&` que se le haya concedido al usuario: el comando estaria midiendo
        un permiso que nadie pidio, y contestaria que no a una pregunta que
        nadie hizo. El ajuste existe como atributo de `settings` justo por
        esto -- antes solo se leia dentro del diccionario de CACHES, asi que
        `getattr(settings, 'REDIS_KEY_PREFIX')` no lo encontraba y el comando
        caia en su propio 'gea' por defecto.
        """
        cliente = FakeRedis()

        with override_settings(REDIS_KEY_PREFIX='otro'):
            run(cliente)

        canales = [c for suscripcion in cliente.pubsubs
                   for c in suscripcion.subscribed]

        self.assertEqual(len(canales), 1)
        self.assertTrue(canales[0].startswith('otro:'), canales[0])


@override_settings(REDIS_URL=REDIS_URL)
class DiagnosticoTestCase(SimpleTestCase):
    """Que el servidor conteste que no, y que no haya servidor, no es lo mismo."""

    def test_noperm_no_se_cuenta_como_servidor_inalcanzable(self):
        texto = run(FakeRedis(ping_error=denied('ping')))

        self.assertIn('contesto que no: es la ACL, no la red', texto)
        self.assertNotIn('No se llega al servidor', texto)

    def test_servidor_caido_no_se_cuenta_como_acl(self):
        texto = run(FakeRedis(ping_error=unreachable()))

        self.assertIn('No se llega al servidor', texto)
        self.assertIn('la cache tampoco esta funcionando', texto)
        self.assertNotIn('es la ACL, no la red', texto)

    def test_noperm_no_acusa_al_hosting_de_cortar_conexiones(self):
        """
        La seccion 3 mide un tope de conexiones simultaneas.

        Un NOPERM ahi no es un tope: la conexion se abrio y lo que fallo fue el
        PING. Contarlo como «se abrieron 0 de 10» manda a hablar con el
        proveedor por algo que se arregla en una linea de la ACL.
        """
        texto = run(FakeRedis(ping_error=denied('ping')))

        self.assertIn('Eso es la ACL y no un tope de conexiones', texto)
        self.assertIn('La conexion se abrio', texto)
        self.assertNotIn('Se abrieron 0 de', texto)
        self.assertNotIn('tope del proveedor', texto)

    def test_un_corte_de_verdad_si_se_cuenta(self):
        """Dos conexiones bien y la tercera cortada: eso si es el tope."""
        cliente = FakeRedis(ping_error=unreachable(),
                            ping_calls_before_error=3)

        texto = run(cliente, connections=4)

        self.assertIn('Se abrieron', texto)
        self.assertIn('tope del proveedor', texto)


@override_settings(REDIS_URL=REDIS_URL)
class LatenciaTestCase(SimpleTestCase):
    """Cada milisegundo es tiempo con una transaccion abierta."""

    def _con_latencia(self, milisegundos, **options):
        """
        Fijar el reloj en vez de dormir.

        Dormir de verdad haria la prueba lenta y, peor, dependiente de la
        maquina: una prueba de latencia que a veces falla en un portatil
        cargado acaba ignorandose.
        """
        paso = milisegundos / 1000
        reloj = [0.0]

        def perf_counter():
            valor = reloj[0]
            reloj[0] += paso
            return valor

        with mock.patch(f'{MODULE}.time.perf_counter', perf_counter):
            return run(FakeRedis(), **options)

    def test_latencia_baja_no_preocupa(self):
        texto = self._con_latencia(5)

        self.assertIn('no se va a notar', texto)

    def test_latencia_media_manda_publicar_tras_el_commit(self):
        texto = self._con_latencia(60)

        self.assertIn('transaction.on_commit', texto)

    def test_latencia_alta_es_un_hallazgo(self):
        texto = self._con_latencia(250)

        self.assertIn('alarga la peticion', texto)
        self.assertIn('publica siempre fuera de la peticion', texto)


@override_settings(REDIS_URL=REDIS_URL)
class SubdominioTestCase(SimpleTestCase):
    """Preguntar por un host que nadie nombro no es contestar."""

    def test_sin_host_no_se_inventa_uno(self):
        texto = run(FakeRedis())

        self.assertIn('No se ha dicho cual es', texto)

        # Y no cuenta como fallo: el veredicto dice que falta preguntarlo, no
        # que este mal.
        self.assertIn('no se ha preguntado', texto)
        self.assertNotIn('Falta el subdominio que lo sirve', texto)

    def test_sin_dns_es_un_fallo_y_dice_cual(self):
        with mock.patch(f'{MODULE}.socket.getaddrinfo',
                        side_effect=OSError('Name or service not known')):
            texto = run(FakeRedis(), realtime_host='rt.example.org')

        self.assertIn('no resuelve', texto)
        self.assertIn('Falta el registro DNS', texto)

    def test_un_certificado_que_no_vale_corta_el_socket(self):
        """
        Y no es un aviso que el usuario pueda aceptar.

        Desde una pagina servida en https, el navegador no ofrece «continuar de
        todos modos» para un WebSocket: corta y ya esta. Decirlo importa porque
        la intuicion de quien lo monta viene de abrir la URL en una pestana,
        donde si se puede seguir.
        """
        import ssl

        with mock.patch(f'{MODULE}.socket.getaddrinfo',
                        return_value=[(0, 0, 0, '', ('203.0.113.7', 443))]), \
                mock.patch(f'{MODULE}.socket.create_connection',
                           side_effect=ssl.SSLCertVerificationError('bad')):
            texto = run(FakeRedis(), realtime_host='rt.example.org')

        self.assertIn('El certificado de rt.example.org no vale', texto)
        self.assertIn('no es un aviso que el usuario pueda aceptar', texto)
        self.assertIn('corta el socket sin preguntar', texto)

    def test_el_nombre_se_limpia_venga_como_venga(self):
        vistos = []

        def getaddrinfo(host, *args, **kwargs):
            vistos.append(host)
            raise OSError('parado aqui a proposito')

        for escrito in ('https://rt.example.org/socket',
                        'rt.example.org:443',
                        '  rt.example.org  '):
            with mock.patch(f'{MODULE}.socket.getaddrinfo', getaddrinfo):
                run(FakeRedis(), realtime_host=escrito)

        self.assertEqual(vistos, ['rt.example.org'] * 3)


@override_settings(REDIS_URL=REDIS_URL)
class BaseDeDatosTestCase(SimpleTestCase):
    """La quinta pregunta: la que no se puede medir desde aqui."""

    def test_no_se_presenta_como_medida(self):
        texto = run(FakeRedis())

        self.assertIn('no se mide aqui', texto)
        self.assertIn('Ejecuta alla el comando', texto)

    def test_un_host_local_es_la_respuesta_a_la_pregunta(self):
        """
        ``DB_HOST=localhost`` es correcto en cPanel y a la vez la respuesta.

        El VPS no puede usar ese valor, y el GRANT a ``'usuario'@'localhost'``
        tampoco sirve para una conexion que llega de fuera. Es lo que se
        descubre tarde, con el worker ya montado.
        """
        texto = run(FakeRedis())

        self.assertIn('apunta a esta misma maquina', texto)
        self.assertIn('Remote MySQL', texto)

    def test_no_imprime_la_contrasena(self):
        """
        La salida de un comando de la consola acaba escrita en CommandRunModel.

        O sea en una tabla, en claro, para quien pueda leerla despues. Es el
        mismo motivo por el que la clave de Safety va por el entorno y nunca
        como ``--key=...``.
        """
        from django.conf import settings as reales

        clave = (reales.DATABASES['default'].get('PASSWORD') or '').strip()

        texto = run(FakeRedis())

        if clave:
            self.assertNotIn(clave, texto)

        self.assertNotIn('PASSWORD', texto)


class RegistroTestCase(SimpleTestCase):
    """Que se pueda ejecutar desde la consola, sin shell."""

    def test_esta_declarado_en_la_consola_de_operaciones(self):
        from apps.project.specific.internal.ops.registry import get_command

        entrada = get_command('check_realtime')

        self.assertIsNotNone(entrada)
        self.assertEqual(entrada.name, 'check_realtime')

    def test_la_opcion_de_texto_lleva_patron(self):
        """
        Sin ``pattern``, el runner se niega a ejecutar, y con razon: un campo
        de texto sin patron es una cadena libre en la linea de comandos.
        """
        from apps.project.specific.internal.ops.registry import (
            KIND_TEXT, get_command,
        )

        entrada = get_command('check_realtime')

        for opcion in entrada.options:
            if opcion.kind == KIND_TEXT:
                self.assertTrue(opcion.pattern, opcion.flag)
