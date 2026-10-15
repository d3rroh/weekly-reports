import zoneinfo

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models


def validate_timezone(value):
    if value not in zoneinfo.available_timezones():
        raise ValidationError(f"'{value}' is not a recognised IANA timezone.")


class AppSettings(models.Model):
    """Singleton row holding application-wide configuration."""

    CACHE_KEY = "wor:app-settings"

    organisation_name = models.CharField(max_length=120, blank=True, default="")
    business_timezone = models.CharField(
        max_length=64, default="UTC", validators=[validate_timezone],
        help_text="All reporting periods and timestamps are calculated in this timezone.",
    )
    include_management_comments_default = models.BooleanField(
        default=True, help_text="Show Management Report comments in presentation mode by default."
    )
    show_leadership_in_presentation = models.BooleanField(
        default=True,
        help_text="Include the Leadership & Capacity section in presentations for viewers authorised to see it.",
    )
    allow_incomplete_submission = models.BooleanField(
        default=True,
        help_text="Allow submission of incomplete reports after explicit confirmation.",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        verbose_name = "application settings"
        verbose_name_plural = "application settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def load(cls):
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(
                pk=1, defaults={"business_timezone": settings.TIME_ZONE}
            )
            cache.set(cls.CACHE_KEY, obj, 300)
        return obj


class AuditEvent(models.Model):
    """Append-only record of important actions."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    action = models.CharField(max_length=40, db_index=True)
    object_type = models.CharField(max_length=60, blank=True, default="")
    object_id = models.CharField(max_length=40, blank=True, default="")
    object_repr = models.CharField(max_length=200, blank=True, default="")
    review = models.ForeignKey(
        "reviews.WeeklyReview", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    message = models.CharField(max_length=500, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["object_type", "object_id"])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.object_repr}"
