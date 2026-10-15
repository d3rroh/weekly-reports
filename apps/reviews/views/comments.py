from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import deny
from apps.core.audit import log_event

from ..forms import CommentForm
from ..models import Comment, CommentRevision, WeeklyReview
from ..questions import QUESTIONS
from ..services import access
from ..services import commitments as commitment_service
from .common import get_review_for


def _form_kwargs(user, review):
    return {
        "commitments": commitment_service.relevant_commitments(review),
        "allowed_questions": [q.number for q in QUESTIONS if access.can_view_question(user, q.number)],
    }


def _comments_url(review):
    return reverse("reviews:edit", kwargs={"code": review.code}) + "#comments"


@login_required
@require_POST
def comment_add(request, code):
    review = get_review_for(request, code)
    if not access.can_add_comment(request.user, review):
        deny(request, "Adding comments is not permitted on this report.", obj=review)
    form = CommentForm(request.POST, **_form_kwargs(request.user, review))
    if form.is_valid():
        comment = form.save(commit=False)
        comment.review = review
        comment.author = request.user
        comment.save()
        log_event(request, "comment_created", obj=comment, review=review,
                  message=f"{comment.get_visibility_display()} comment added ({comment.get_category_display()})")
        messages.success(request, "Comment added.")
        return redirect(_comments_url(review))
    from .reviews import _editor_context
    ctx = _editor_context(request, review, comment_form=form)
    ctx["open_tab"] = "comments"
    messages.error(request, "The comment could not be saved. See the errors below.")
    return render(request, "reviews/editor.html", ctx, status=422)


def _get_comment(request, pk):
    comment = get_object_or_404(Comment.objects.select_related("review__period", "author"), pk=pk,
                                deleted_at__isnull=True)
    if not access.visible_comments(request.user, Comment.objects.filter(pk=pk)).exists():
        deny(request, "Comment not visible to this user.", obj=comment)
    if not access.can_modify_comment(request.user, comment):
        deny(request, "Modifying this comment is not permitted.", obj=comment)
    return comment


def _record_revision(comment, user, action):
    CommentRevision.objects.create(
        comment=comment, text=comment.text, category=comment.category, visibility=comment.visibility,
        action=action, review_status=comment.review.status, changed_by=user,
    )


@login_required
def comment_edit(request, pk):
    comment = _get_comment(request, pk)
    review = comment.review
    form = CommentForm(request.POST or None, instance=comment, **_form_kwargs(request.user, review))
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            original = Comment.objects.select_for_update().get(pk=comment.pk)
            _record_revision(original, request.user, "edit")
            form.save()
        log_event(request, "comment_updated", obj=comment, review=review,
                  message="Comment edited" + (" on submitted report" if review.is_submitted else ""),
                  data={"changed": form.changed_data})
        messages.success(request, "Comment updated.")
        return redirect(_comments_url(review))
    return render(request, "reviews/comment_form.html", {
        "form": form, "comment": comment, "review": review, "page_title": "Edit comment",
        "revisions": comment.revisions.select_related("changed_by"),
    })


@login_required
@require_POST
def comment_delete(request, pk):
    comment = _get_comment(request, pk)
    if request.POST.get("confirm") != "1":
        messages.error(request, "Deletion was not confirmed.")
        return redirect(_comments_url(comment.review))
    with transaction.atomic():
        _record_revision(comment, request.user, "delete")
        comment.deleted_at = timezone.now()
        comment.deleted_by = request.user
        comment.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
    log_event(request, "comment_deleted", obj=comment, review=comment.review, message="Comment deleted")
    messages.success(request, "Comment deleted. A copy is retained in the audit history.")
    return redirect(_comments_url(comment.review))


@login_required
def comment_list(request):
    """All comments across reports, filtered by what this user may see."""
    qs = access.visible_comments(request.user).order_by("-review__period__start_date", "created_at")
    category = request.GET.get("category", "")
    visibility = request.GET.get("visibility", "")
    code = request.GET.get("report", "")
    if category in Comment.Category.values:
        qs = qs.filter(category=category)
    if visibility in Comment.Visibility.values:
        qs = qs.filter(visibility=visibility)
    if code:
        qs = qs.filter(review__period__code=code)
    page = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "reviews/comment_list.html", {
        "page": page, "category": category, "visibility": visibility, "report": code,
        "categories": Comment.Category.choices, "visibilities": Comment.Visibility.choices,
        "reports": access.visible_reviews(request.user).order_by("-period__start_date")[:52],
        "page_title": "Comments",
    })


__all__ = ["comment_add", "comment_edit", "comment_delete", "comment_list", "WeeklyReview"]
