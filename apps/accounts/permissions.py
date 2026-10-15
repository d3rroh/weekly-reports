"""Server-side authorization helpers shared by every view."""
from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.core.audit import log_event


def deny(request, reason, obj=None):
    log_event(request, "permission_denied", obj=obj, message=reason)
    raise PermissionDenied(reason)


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_app_admin:
            deny(request, f"Administrator access required for {request.path}")
        return view(request, *args, **kwargs)

    return wrapper


def editor_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.may_edit_reports:
            deny(request, f"Edit permission required for {request.path}")
        return view(request, *args, **kwargs)

    return wrapper
