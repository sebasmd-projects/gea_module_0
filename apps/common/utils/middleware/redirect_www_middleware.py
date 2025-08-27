from django.http import HttpResponsePermanentRedirect

class RedirectWWWMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host()

        if host.startswith('www.'):
            non_www_host = host[4:]
            url = request.build_absolute_uri(request.get_full_path())
            non_www_url = url.replace(
                f'http://www.{host}', f'http://{non_www_host}'
            )

            return HttpResponsePermanentRedirect(non_www_url)

        response = self.get_response(request)
        return response