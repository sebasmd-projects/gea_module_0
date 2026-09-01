# apps/project/specific/documents/certificates/mixins.py

import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.common.utils.throttling import RateLimit


class OTPSessionMixin:
    OTP_SESSION_KEY = "document_otp"

    OTP_TTL = timedelta(minutes=10)
    OTP_RESEND_COOLDOWN = timedelta(minutes=1)

    # NUEVO: antifuerza bruta
    OTP_MAX_ATTEMPTS = 5
    OTP_LOCKOUT = timedelta(minutes=10)

    # NUEVO: rate limiting real (server-side) para envío
    OTP_SEND_WINDOW = timedelta(minutes=10)
    OTP_MAX_SENDS_PER_WINDOW = 3

    # NUEVO: rate limiting real (server-side) para verificación
    OTP_VERIFY_WINDOW = timedelta(minutes=10)
    OTP_MAX_VERIFY_ATTEMPTS_PER_WINDOW = 10

    # Limite del formulario de identificador.
    #
    # Faltaba: el OTP estaba limitado por todos lados, pero una vez superado
    # se podian teclear codigos publicos sin ningun tope durante los 30
    # minutos que dura el acceso. Y ese formulario es un oraculo -- dice si un
    # codigo existe -- sobre codigos de 4 caracteres (personas) y 12
    # (documentos). Con 4 caracteres el espacio se agota a fuerza bruta en
    # nada; con 12 no, pero un enumerador tampoco tiene por que salir gratis.
    #
    # 20 intentos por cada 10 minutos no lo nota nadie que teclee un codigo de
    # un papel, ni siquiera equivocandose varias veces.
    IDENTIFIER_WINDOW = timedelta(minutes=10)
    IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW = 20

    # ======================
    # Los tres cupos
    # ======================
    # Los tres se llevaban a mano leyendo `cache.get` y comparando. Con
    # `IGNORE_EXCEPTIONS` puesto en la cache, un Redis caido devuelve `None` en
    # lugar de lanzar, `None or 0` es `0`, y los tres dejaban de aplicarse **en
    # silencio**: ni excepcion, ni log, ni sintoma. `RateLimit` detecta la
    # averia por el valor que devuelve `incr` y decide por cupo, no en bloque.

    #: Envio del OTP, por destinatario. Falla cerrado: el correo sale hacia un
    #: buzon ajeno, y quien lo pide elige su IP mientras que quien lo recibe
    #: no. Por eso el `scope` es el correo y no lleva la IP dentro.
    otp_send_throttle = RateLimit(
        'otp_send_to',
        limit=OTP_MAX_SENDS_PER_WINDOW,
        window=int(OTP_SEND_WINDOW.total_seconds()),
    )

    #: Y el mismo envio, por origen. Sin este, el cupo por destinatario se
    #: esquiva cambiando de destinatario: 3 correos a cada direccion de una
    #: lista sigue siendo una lista entera. Numero mayor porque una oficina
    #: entera comparte salida a internet.
    otp_send_ip_throttle = RateLimit(
        'otp_send_from',
        limit=OTP_MAX_SENDS_PER_WINDOW * 5,
        window=int(OTP_SEND_WINDOW.total_seconds()),
    )

    #: Verificacion del codigo recibido. **El unico que falla abierto**, y por
    #: una diferencia real: aqui no se adivina nada de otro. El codigo se
    #: acaba de mandar al buzon de quien teclea, vive 10 minutos, y la sesion
    #: se bloquea a los 5 fallos con un contador que va **en la sesion**, o
    #: sea en la base de datos, que no depende de Redis. Este cupo es la
    #: segunda linea, no la unica; cerrarlo durante una averia dejaria tirado
    #: a quien tiene el codigo correcto delante sin cerrar ninguna puerta que
    #: siga abierta.
    otp_verify_throttle = RateLimit(
        'otp_verify',
        limit=OTP_MAX_VERIFY_ATTEMPTS_PER_WINDOW,
        window=int(OTP_VERIFY_WINDOW.total_seconds()),
        fail_open=True,
        reason='the 5-attempt lockout lives in the session, which is in the DB',
    )

    #: Codigos publicos. Falla cerrado, y es el caso mas claro de todos: este
    #: limite **es** el control -- no hay nada mas entre un desconocido y
    #: recorrer un espacio de 4 caracteres. Y lo que se enumera no se
    #: desenumera cuando vuelve Redis.
    identifier_throttle = RateLimit(
        'identifier_lookup',
        limit=IDENTIFIER_MAX_ATTEMPTS_PER_WINDOW,
        window=int(IDENTIFIER_WINDOW.total_seconds()),
    )

    # ======================
    # Session helpers
    # ======================
    def clear_otp_session(self):
        self.request.session.pop(self.OTP_SESSION_KEY, None)

    def get_otp_session(self):
        return self.request.session.get(self.OTP_SESSION_KEY)

    # ======================
    # Helpers: IP (no confíes en XFF sin proxy confiable)
    # ======================
    def _client_ip(self) -> str:
        """
        La misma respuesta que da el resto del proyecto.

        Aqui habia una segunda implementacion --``REMOTE_ADDR`` a secas-- con
        un comentario que pedia reemplazarla si algun dia habia un proxy. Ya
        existe esa funcion: ``apps.common.utils.client_ip.get_client_ip``, que
        no se cree ``X-Forwarded-For`` salvo que ``TRUSTED_PROXY_DEPTH`` diga
        cuantos saltos hay. Tener dos respuestas a la misma pregunta es
        exactamente lo que rompio la mitigacion anti-escaneo en su dia.
        """
        from apps.common.utils.client_ip import get_client_ip

        return get_client_ip(self.request)

    # ======================
    # OTP core
    # ======================
    def _hash_otp(self, otp: str) -> str:
        return hmac.new(
            key=settings.SECRET_KEY.encode(),
            msg=otp.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

    def spend_otp_send(self, email: str) -> bool:
        """
        Gasta una unidad del cupo de envios y dice si se puede mandar.

        Antes esto eran dos llamadas --``can_send_otp()`` para preguntar y
        ``record_send_otp()`` para anotar despues del envio-- y esa separacion
        era el fallo: entre una y otra hay una peticion HTTP, una plantilla y
        un SMTP. Dos peticiones simultaneas preguntaban las dos antes de que
        ninguna anotara, y las dos pasaban.

        Se anota **antes** de mandar. Un correo que no llega por un fallo del
        SMTP gasta cupo, y esta bien que lo gaste: el reintento tiene su boton
        de reenvio, con su espera aparte.

        Returns:
            bool: ``True`` si el envio puede seguir adelante.
        """
        email = (email or "").strip().lower()

        # Los dos, no el primero que sobre: en corto, uno se quedaria sin
        # contar y el cupo dependeria del orden de evaluacion.
        to_ok = self.otp_send_throttle.consume(self.request, scope=email)
        from_ok = self.otp_send_ip_throttle.consume(self.request)

        return to_ok and from_ok

    def _verify_scope(self) -> str:
        """
        El cupo de verificacion se ata a la sesion, no a la direccion.

        Es la excepcion, y tiene su motivo: aqui no se adivina nada de otro
        --el codigo llego al buzon de quien teclea-- asi que contar por IP
        castigaria a una oficina entera por culpa de uno solo. En los demas
        cupos manda la IP, porque lo que se protege es comun.
        """
        return f'{self._client_ip()}:{self.request.session.session_key or "nosid"}'

    def spend_verify_attempt(self) -> bool:
        return self.otp_verify_throttle.consume(
            self.request, scope=self._verify_scope())

    # ======================
    # Identifier lookups
    # ======================
    def spend_identifier_attempt(self) -> bool:
        """
        Un intento del formulario de codigos publicos.

        Se cuenta por IP --el ``scope`` por defecto-- y no por sesion: la
        sesion la controla quien busca, y tirar la cookie para empezar de cero
        es una linea de script. Lo que se protege aqui no es el secreto de
        nadie en concreto, es el espacio de codigos, que es comun.
        """
        return self.identifier_throttle.consume(self.request)

    def set_otp_session(self, email: str, otp: str, *, purpose: str = "document_verification"):
        now = timezone.now()
        self.request.session[self.OTP_SESSION_KEY] = {
            "email": (email or "").strip().lower(),
            "purpose": purpose,
            "otp_hash": self._hash_otp(otp),
            "created_at": now.isoformat(),
            "last_sent_at": now.isoformat(),
            "expires_at": (now + self.OTP_TTL).isoformat(),
            "verified": False,
            "verified_at": None,
            "attempts": 0,
            "locked_until": None,
        }

    def update_otp(self, otp: str):
        data = self.get_otp_session()
        if not data:
            return

        now = timezone.now()
        data.update({
            "otp_hash": self._hash_otp(otp),
            "last_sent_at": now.isoformat(),
            "expires_at": (now + self.OTP_TTL).isoformat(),
            "verified": False,
            "verified_at": None,
            "attempts": 0,
            "locked_until": None,
        })
        self.request.session[self.OTP_SESSION_KEY] = data

    def mark_otp_verified(self):
        data = self.get_otp_session()
        if not data:
            return

        now = timezone.now()
        data["verified"] = True
        data["verified_at"] = now.isoformat()

        self.request.session[self.OTP_SESSION_KEY] = data

        # rota session key para bajar riesgo de fixation
        self.request.session.cycle_key()

    # ======================
    # Validations
    # ======================
    def _parse_iso_dt(self, value: str):
        try:
            return timezone.datetime.fromisoformat(value).astimezone(timezone.get_current_timezone())
        except Exception:
            return None

    def is_otp_valid(self, otp: str, *, purpose: str = "document_verification") -> bool:
        data = self.get_otp_session()
        if not data:
            return False

        if data.get("verified"):
            return False

        # NUEVO: propósito
        if data.get("purpose") != purpose:
            return False

        # NUEVO: lockout por intentos
        locked_until = data.get("locked_until")
        if locked_until:
            lu = self._parse_iso_dt(locked_until)
            if lu and timezone.now() < lu:
                return False

        expires_at = self._parse_iso_dt(data.get("expires_at", ""))
        if not expires_at or timezone.now() > expires_at:
            return False

        # NUEVO: rate limit real de verificación (server-side)
        if not self.spend_verify_attempt():
            return False

        ok = constant_time_compare(
            data.get("otp_hash", ""),
            self._hash_otp((otp or "").strip())
        )

        if ok:
            return True

        # fallo: incrementa intentos y bloquea si excede
        attempts = int(data.get("attempts", 0) or 0) + 1
        data["attempts"] = attempts
        if attempts >= self.OTP_MAX_ATTEMPTS:
            data["locked_until"] = (timezone.now() + self.OTP_LOCKOUT).isoformat()

        self.request.session[self.OTP_SESSION_KEY] = data
        return False

    def can_resend_otp(self) -> tuple[bool, int]:
        data = self.get_otp_session()
        if not data:
            return False, 0

        last_sent = self._parse_iso_dt(data.get("last_sent_at", ""))
        if not last_sent:
            return True, 0

        elapsed = timezone.now() - last_sent
        if elapsed >= self.OTP_RESEND_COOLDOWN:
            return True, 0

        remaining = int((self.OTP_RESEND_COOLDOWN - elapsed).total_seconds())
        return False, remaining
    
class OTPProtectedDocumentMixin:
    """
    Protects document detail views:
    - Authenticated users are allowed
    - Anonymous users must pass OTP verification
    """

    otp_required = True
    OTP_ACCESS_TTL = timedelta(minutes=30)

    def _parse_iso_dt(self, value: str):
        try:
            return timezone.datetime.fromisoformat(value).astimezone(timezone.get_current_timezone())
        except Exception:
            return None

    def has_otp_access(self) -> bool:
        request = self.request

        if request.user.is_authenticated:
            return True

        otp_state = request.session.get("document_otp")
        if not otp_state:
            return False

        if not otp_state.get("verified", False):
            return False

        verified_at = self._parse_iso_dt(otp_state.get("verified_at", ""))
        if not verified_at:
            return False

        if timezone.now() - verified_at > self.OTP_ACCESS_TTL:
            request.session.pop("document_otp", None)
            return False

        return True

    def dispatch(self, request, *args, **kwargs):
        if self.otp_required and not self.has_otp_access():
            return redirect(
                reverse('certificates:input_document_verification_aegis')
            )

        return super().dispatch(request, *args, **kwargs)
