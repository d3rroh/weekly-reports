import zoneinfo

from django.utils import timezone


class BusinessTimezoneMiddleware:
    """Activate the configured business timezone for every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .models import AppSettings

        try:
            timezone.activate(zoneinfo.ZoneInfo(AppSettings.load().business_timezone))
        except Exception:
            timezone.deactivate()
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()


class SecurityHeadersMiddleware:
    """Strict Content-Security-Policy: all scripts and styles are local files."""

    CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            response.setdefault("Cache-Control", "no-store")
        return response
