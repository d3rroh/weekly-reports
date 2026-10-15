from django.conf import settings

from .models import AppSettings


def _sidebar_period(request):
    """Compact status of this Wednesday's report for the sidebar."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    from apps.core import periods
    from apps.reviews.models import WeeklyReview
    from apps.reviews.services import workflow

    latest = periods.latest_completed_period()
    review = WeeklyReview.objects.select_related("period", "metrics").filter(period__start_date=latest.start).first()
    if review and review.is_restricted and not user.may_view_confidential:
        review = None
    return {
        "bounds": latest,
        "label": periods.format_range(latest.start, latest.end),
        "review": review,
        "percent": workflow.checklist(review)["percent"] if review else 0,
    }


def app_context(request):
    match = getattr(request, "resolver_match", None)
    return {
        "APP_NAME": settings.APP_NAME,
        "app_settings": AppSettings.load(),
        "nav_active": match.url_name if match is not None else None,
        "sidebar_period": _sidebar_period(request),
    }
