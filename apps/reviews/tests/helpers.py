from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.core.models import AppSettings
from apps.reviews.models import Comment, WeeklyMetrics
from apps.reviews.services import workflow

# A known Wednesday-start period: 7–13 Oct 2026, presented Wed 14 Oct 2026.
P_START = date(2026, 10, 7)


def make_user(username, role=User.Role.REVIEWER, **flags):
    user = User.objects.create_user(username=username, password="Str0ng-pass-123!", email=f"{username}@example.com",
                                     role=role, **flags)
    return user


def make_review(user, start=P_START, **metrics):
    review, _ = workflow.create_review(user, start)
    if metrics:
        WeeklyMetrics.objects.filter(review=review).update(**metrics)
        review.refresh_from_db()
    return review


def full_answers():
    """POST data answering every question for a review."""
    from apps.reviews.questions import QUESTIONS

    data = {"meta-present": "1", "meta-executive_summary": "Summary", "meta-include_management_comments": "on"}
    for q in QUESTIONS:
        for sf in q.fields:
            data[f"q{q.number}-{sf.key}"] = f"Answer {q.number} {sf.key}"
    data.update({
        "metrics-avg_response_minutes": "12.5", "metrics-sla_compliance_pct": "94",
        "metrics-missed_calls": "10", "metrics-csat_pct": "91.5",
        "p1-description": "Ship macro library", "p1-actual_result": "Shipped", "p1-delivery_status": "shipped",
    })
    for i in (1, 2, 3):
        data[f"c{i}-description"] = f"Outcome {i}"
        data[f"c{i}-success_criteria"] = f"Criteria {i}"
    return data


class BaseTestCase(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={"business_timezone": "UTC"})
        from django.core.cache import cache
        cache.clear()
        self.admin = make_user("admin", role=User.Role.ADMIN)
        self.reviewer = make_user("reviewer", can_view_confidential=False)
        self.confidential = make_user("lead", can_view_confidential=True)

    def login(self, user):
        self.client.force_login(user)

    def add_comment(self, review, author, visibility=Comment.Visibility.MANAGEMENT, text="A note", **kw):
        return Comment.objects.create(review=review, author=author, visibility=visibility, text=text, **kw)


__all__ = ["BaseTestCase", "make_user", "make_review", "full_answers", "P_START", "Decimal", "timedelta"]
