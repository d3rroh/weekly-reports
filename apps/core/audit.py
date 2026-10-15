"""Audit logging helper. Every important change goes through log_event()."""
import logging

logger = logging.getLogger("apps.audit")

_MISSING = object()


def log_event(request, action, obj=None, review=None, message="", data=None, actor=_MISSING):
    from .models import AuditEvent

    if actor is _MISSING:
        user = getattr(request, "user", None) if request is not None else None
        actor = user if user is not None and user.is_authenticated else None
    if review is None and obj is not None and obj.__class__.__name__ == "WeeklyReview":
        review = obj
    ip = request.META.get("REMOTE_ADDR") if request is not None else None
    try:
        return AuditEvent.objects.create(
            actor=actor,
            action=action,
            object_type=obj.__class__.__name__ if obj is not None else "",
            object_id=str(obj.pk) if obj is not None and obj.pk is not None else "",
            object_repr=str(obj)[:200] if obj is not None else "",
            review=review,
            message=message[:500],
            data=data or {},
            ip_address=ip or None,
        )
    except Exception:  # pragma: no cover - auditing must never break the request
        logger.exception("Failed to write audit event %s", action)
        return None
