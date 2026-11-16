from django.http import HttpResponsePermanentRedirect


class CanonicalDomainMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(':')[0].lower()
        if host == 'www.inheritancebox.com':
            return HttpResponsePermanentRedirect(
                f"https://inheritancebox.com{request.get_full_path()}"
            )
        return self.get_response(request)
