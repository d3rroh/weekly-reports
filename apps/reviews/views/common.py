from django.http import Http404
from django.shortcuts import get_object_or_404

from apps.accounts.permissions import deny
from apps.core import periods

from ..models import WeeklyReview
from ..services import access


def get_review_for(request, code, edit=False):
    """Load a review by its period code and enforce access rules."""
    try:
        start = periods.parse_code(code)
    except ValueError:
        raise Http404("Unknown reporting period")
    review = get_object_or_404(
        WeeklyReview.objects.select_related("period", "author", "submitted_by", "metrics"),
        period__start_date=start,
    )
    if not access.can_view_review(request.user, review):
        deny(request, f"Restricted report {code}", obj=review)
    if edit and not access.can_edit_review(request.user, review):
        deny(request, f"Edit not permitted on {code}", obj=review)
    return review


def is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"
