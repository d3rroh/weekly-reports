from django.contrib import admin

from . import models


@admin.register(models.ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ("code", "start_date", "end_date", "presentation_date")
    readonly_fields = ("code", "end_date", "presentation_date")


@admin.register(models.WeeklyReview)
class WeeklyReviewAdmin(admin.ModelAdmin):
    list_display = ("period", "status", "author", "submitted_at", "is_restricted")
    list_filter = ("status",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.Commitment)
class CommitmentAdmin(admin.ModelAdmin):
    list_display = ("description", "status", "due_date", "source_review")
    list_filter = ("status",)
