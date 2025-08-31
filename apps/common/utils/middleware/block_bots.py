import re
from django.http import HttpResponseForbidden

class BlockBadBotsMiddleware:
    """
    Middleware para bloquear bots no deseados como GPTBot, Claude, Perplexity, etc.
    """

    BAD_BOTS = [
        "GPTBot",
        "Google-Extended",
        "ClaudeBot",
        "Claude-User",
        "Claude-SearchBot",
        "PerplexityBot",
        "Perplexity-User",
        "Meta-ExternalAgent",
        "Applebot",
        "Applebot-Extended",
        "facebookexternalhit",
        "ia_archiver",  # Alexa
        "MJ12bot",
        "AhrefsBot",
        "SemrushBot",
        "DotBot",
        "Baiduspider",
        "YandexBot",
        "Sogou",
        "Exabot",
    ]

    BOT_REGEX = re.compile("|".join(BAD_BOTS), re.IGNORECASE)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        if self.BOT_REGEX.search(user_agent):
            return HttpResponseForbidden("Forbidden: bot blocked.")
        return self.get_response(request)
