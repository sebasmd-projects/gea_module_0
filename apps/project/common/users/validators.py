from django.core import validators
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class UnicodeNameValidator(validators.RegexValidator):
    regex = r'^[A-Za-z\sÀ-ÿ]{3,}$'
    message = _(
        "Please enter a valid name. This value can contain only letters, "
        "min lenght: 3."
    )
    flags = 0

@deconstructible
class UnicodeLastNameValidator(validators.RegexValidator):
    regex = r'^[A-Za-z\sÀ-ÿ]{3,}$'
    message = _(
        "Please enter a valid last name. This value can contain only letters, "
        "min lenght: 3."
    )
    flags = 0
    
@deconstructible
class UnicodeUsernameValidator(validators.RegexValidator):
    regex = r"^[\w.+-]{4,}\Z"
    message = _(
        "Please enter a valid username. This value can contain only letters, "
        "numbers and this characters /./+/-/_"
        "min lenght: 4; no spaces."
    )
    flags = 0
    
