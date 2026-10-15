"""Simple cache-backed brute-force protection for the login form."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def _key(kind, value):
    digest = hashlib.sha256((value or "").lower().encode()).hexdigest()[:32]
    return f"login-fail:{kind}:{digest}"


def client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def is_locked(username, ip):
    limit = settings.LOGIN_THROTTLE_MAX_ATTEMPTS
    return (
        cache.get(_key("user", username), 0) >= limit
        or cache.get(_key("ip", ip), 0) >= limit * 4
    )


def register_failure(username, ip):
    window = settings.LOGIN_THROTTLE_WINDOW_SECONDS
    for kind, value in (("user", username), ("ip", ip)):
        key = _key(kind, value)
        if cache.add(key, 1, window):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)


def reset(username):
    cache.delete(_key("user", username))
