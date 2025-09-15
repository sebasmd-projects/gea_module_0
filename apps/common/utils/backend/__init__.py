from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from apps.common.utils.functions import sha256_hex

UserModel = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    def authenticate(self, request, username: str = None, password: str = None, *args, **kwargs):
        if request is not None:
            username = request.POST.get('auth-username', username)
            password = request.POST.get('auth-password', password)

        if not username or not password:
            return None

        username = username.strip().lower()

        user_query = UserModel.objects.filter(
            email_hash=sha256_hex(
                username
            )
        ) if '@' in username else UserModel.objects.filter(username=username)

        user = user_query.first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
