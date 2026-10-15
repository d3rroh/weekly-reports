"""Authorization rules for reviews, confidential answers and comments.

Every view calls these functions; templates never decide visibility alone.
"""
from django.db.models import Q

from ..models import Comment, WeeklyReview
from ..questions import CONFIDENTIAL_QUESTIONS


def visible_reviews(user):
    qs = WeeklyReview.objects.select_related("period", "author")
    if not user.may_view_confidential:
        qs = qs.filter(is_restricted=False)
    return qs


def can_view_review(user, review):
    return user.is_authenticated and user.is_active and (not review.is_restricted or user.may_view_confidential)


def can_edit_review(user, review):
    return user.may_edit_reports and not review.is_submitted


def can_change_status(user, review):
    return user.may_edit_reports


def can_reopen(user, review):
    return review.is_submitted and user.may_correct_submitted


def can_view_question(user, number):
    return number not in CONFIDENTIAL_QUESTIONS or user.may_view_confidential


def _confidential_target_q():
    return Q(target_type=Comment.Target.QUESTION, question__in=CONFIDENTIAL_QUESTIONS)


def visible_comments(user, qs=None):
    """Comments this user may read (excludes soft-deleted comments)."""
    qs = (qs if qs is not None else Comment.objects.all()).filter(deleted_at__isnull=True)
    qs = qs.select_related("author", "commitment", "review__period")
    if not user.may_view_confidential:
        qs = qs.exclude(_confidential_target_q())
        qs = qs.filter(Q(visibility=Comment.Visibility.MANAGEMENT) | Q(author=user))
        qs = qs.filter(review__is_restricted=False)
    return qs


def management_comments(review, include_leadership):
    """Comments eligible for management-facing views and exports.

    Internal-only comments are always excluded here, independent of who is
    viewing, so exports can never leak working notes.
    """
    qs = Comment.objects.filter(
        review=review, deleted_at__isnull=True, visibility=Comment.Visibility.MANAGEMENT
    ).select_related("author", "commitment")
    if not include_leadership:
        qs = qs.exclude(_confidential_target_q())
    return qs.order_by("created_at", "id")


def can_add_comment(user, review):
    if not user.may_edit_reports:
        return False
    return not review.is_submitted or user.may_correct_submitted


def can_modify_comment(user, comment):
    if not user.may_edit_reports or comment.deleted_at is not None:
        return False
    if comment.review.is_submitted:
        return user.may_correct_submitted
    return comment.author_id == user.pk or user.is_app_admin
