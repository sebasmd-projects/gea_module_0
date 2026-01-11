import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare


class OTPSessionMixin:
    OTP_SESSION_KEY = 'document_otp'
    OTP_TTL = timedelta(minutes=10)
    OTP_RESEND_COOLDOWN = timedelta(minutes=1)

    # ======================
    # Session helpers
    # ======================
    def clear_otp_session(self):
        self.request.session.pop(self.OTP_SESSION_KEY, None)

    def get_otp_session(self):
        return self.request.session.get(self.OTP_SESSION_KEY)

    # ======================
    # OTP core
    # ======================
    def _hash_otp(self, otp: str) -> str:
        return hmac.new(
            key=settings.SECRET_KEY.encode(),
            msg=otp.encode(),
            digestmod=hashlib.sha256
        ).hexdigest()

    def set_otp_session(self, email: str, otp: str):
        now = timezone.now()

        self.request.session[self.OTP_SESSION_KEY] = {
            'email': email,
            'otp_hash': self._hash_otp(otp),
            'created_at': now.isoformat(),
            'last_sent_at': now.isoformat(),
            'expires_at': (now + self.OTP_TTL).isoformat(),
            'verified': False,
        }

    def update_otp(self, otp: str):
        data = self.get_otp_session()
        if not data:
            return

        now = timezone.now()
        data.update({
            'otp_hash': self._hash_otp(otp),
            'last_sent_at': now.isoformat(),
            'expires_at': (now + self.OTP_TTL).isoformat(),
            'verified': False,
        })
        self.request.session[self.OTP_SESSION_KEY] = data

    def mark_otp_verified(self):
        data = self.get_otp_session()
        if data:
            data['verified'] = True
            self.request.session[self.OTP_SESSION_KEY] = data

    # ======================
    # Validations
    # ======================
    def is_otp_valid(self, otp: str) -> bool:
        data = self.get_otp_session()
        if not data:
            return False

        if data.get('verified'):
            return False

        try:
            expires_at = timezone.datetime.fromisoformat(
                data['expires_at']
            ).astimezone(timezone.get_current_timezone())
        except Exception:
            return False

        if timezone.now() > expires_at:
            return False

        return constant_time_compare(
            data.get('otp_hash', ''),
            self._hash_otp(otp)
        )

    def reset_otp_flow(self):
        self.clear_otp_session()

    def can_resend_otp(self) -> tuple[bool, int]:
        """
        Returns:
            (allowed, seconds_remaining)
        """
        data = self.get_otp_session()
        if not data:
            return False, 0

        last_sent = timezone.datetime.fromisoformat(
            data['last_sent_at']
        ).astimezone(timezone.get_current_timezone())

        elapsed = timezone.now() - last_sent

        if elapsed >= self.OTP_RESEND_COOLDOWN:
            return True, 0

        remaining = int(
            (self.OTP_RESEND_COOLDOWN - elapsed).total_seconds()
        )
        return False, remaining


class OTPProtectedDocumentMixin:
    """
    Protects document detail views:
    - Authenticated users are allowed
    - Anonymous users must pass OTP verification
    """

    otp_required = True  # extensible

    def has_otp_access(self) -> bool:
        request = self.request

        if request.user.is_authenticated:
            return True

        otp_state = request.session.get('document_otp')

        if not otp_state:
            return False

        return otp_state.get('verified', False)

    def dispatch(self, request, *args, **kwargs):
        if self.otp_required and not self.has_otp_access():
            return redirect(
                reverse('certificates:input_document_verification_aegis')
            )

        return super().dispatch(request, *args, **kwargs)
