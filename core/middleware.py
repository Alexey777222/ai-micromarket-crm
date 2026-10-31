from django.conf import settings
from django.http import HttpResponseForbidden
from django.utils.cache import patch_cache_control


class PilotSecurityMiddleware:
    """Technical admin is reserved for superusers on the server.

    Owner accounts are regular users with one active organization membership.
    This is not a multi-tenant administration console.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            settings.IS_PRODUCTION
            and request.path.startswith("/admin/")
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            response = HttpResponseForbidden("Техническая панель доступна только администратору.")
        else:
            response = self.get_response(request)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        if not request.path.startswith("/static/"):
            patch_cache_control(response, no_store=True, private=True)
        return response
