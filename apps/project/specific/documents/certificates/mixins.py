# apps/project/specific/documents/certificates/mixins.py

import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.core.cache import cache

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
        Si NO estás detrás de un proxy confiable configurado, usa REMOTE_ADDR.
        Si sí lo estás (nginx/cloudflare), idealmente reemplaza esto por una función
        que valide proxies confiables.
        """
        return self.request.META.get("REMOTE_ADDR", "0.0.0.0")

    # ======================
    # OTP core
    # ======================
    def _hash_otp(self, otp: str) -> str:
        return hmac.new(
            key=settings.SECRET_KEY.encode(),
            msg=otp.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

    # NUEVO: llaves de cache
    def _send_rate_key(self, email: str) -> str:
        ip = self._client_ip()
        return f"otp:send:{ip}:{email}"

    def _verify_rate_key(self) -> str:
        ip = self._client_ip()
        # amarra a sesión para no penalizar a todos por la misma IP
        sid = self.request.session.session_key or "nosid"
        return f"otp:verify:{ip}:{sid}"

    def _incr_counter(self, key: str, ttl_seconds: int) -> int:
        """
        contador atómico si cache soporta incr. Fallback seguro.
        """
        try:
            added = cache.add(key, 0, timeout=ttl_seconds)
            # si no existía, quedó en 0, ahora incr a 1
            return cache.incr(key)
        except Exception:
            # fallback no-atómico (menos ideal)
            v = cache.get(key, 0) or 0
            v = int(v) + 1
            cache.set(key, v, timeout=ttl_seconds)
            return v

    def can_send_otp(self, email: str) -> tuple[bool, int]:
        """
        Rate limit real: max N envíos por ventana por ip+email.
        Returns: (allowed, seconds_remaining_estimate)
        """
        email = (email or "").strip().lower()
        key = self._send_rate_key(email)
        ttl = int(self.OTP_SEND_WINDOW.total_seconds())

        count = cache.get(key)
        if count is None:
            cache.set(key, 0, timeout=ttl)
            count = 0

        if int(count) >= self.OTP_MAX_SENDS_PER_WINDOW:
            # aproximación: no tenemos exacto remaining, pero estimamos por TTL restante si backend lo permite
            return False, int(self.OTP_SEND_WINDOW.total_seconds())
        return True, 0

    def record_send_otp(self, email: str) -> None:
        email = (email or "").strip().lower()
        ttl = int(self.OTP_SEND_WINDOW.total_seconds())
        self._incr_counter(self._send_rate_key(email), ttl)

    def can_verify_attempt(self) -> bool:
        ttl = int(self.OTP_VERIFY_WINDOW.total_seconds())
        key = self._verify_rate_key()

        count = cache.get(key)
        if count is None:
            cache.set(key, 0, timeout=ttl)
            count = 0

        return int(count) < self.OTP_MAX_VERIFY_ATTEMPTS_PER_WINDOW

    def record_verify_attempt(self) -> None:
        ttl = int(self.OTP_VERIFY_WINDOW.total_seconds())
        self._incr_counter(self._verify_rate_key(), ttl)

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
        if not self.can_verify_attempt():
            return False

        # registra intento siempre
        self.record_verify_attempt()

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
