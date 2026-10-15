from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.accounts.permissions import deny
from apps.core import periods

from ..forms import CommitmentProgressForm
from ..models import Commitment, WeeklyReview
from ..services import access
from ..services import commitments as commitment_service


def _visible_commitments(user):
    qs = Commitment.objects.select_related("source_review__period", "target_period")
    if not user.may_view_confidential:
        qs = qs.filter(source_review__is_restricted=False)
    return qs


@login_required
def tracker(request):
    today = periods.local_today()
    qs = _visible_commitments(request.user)
    status = request.GET.get("status", "")
    view = request.GET.get("view", "open")
    if status in Commitment.Status.values:
        qs = qs.filter(status=status)
    elif view == "open":
        qs = qs.exclude(status=Commitment.Status.COMPLETED)
    rows = list(qs.order_by("due_date", "position"))
    counts = {s: _visible_commitments(request.user).filter(status=s).count() for s in Commitment.Status.values}
    overdue = sum(1 for c in _visible_commitments(request.user).exclude(status=Commitment.Status.COMPLETED)
                  if c.due_date < today)
    return render(request, "reviews/commitments.html", {
        "rows": [{"c": c, "overdue": c.is_overdue(today)} for c in rows],
        "status": status, "view": view, "statuses": Commitment.Status.choices,
        "counts": counts, "overdue": overdue, "page_title": "Commitments Tracker",
    })


def _get_commitment(request, pk):
    c = get_object_or_404(Commitment.objects.select_related("source_review__period", "target_period"), pk=pk)
    if not access.can_view_review(request.user, c.source_review):
        deny(request, "Commitment belongs to a restricted report.", obj=c)
    return c


@login_required
def commitment_detail(request, pk):
    c = _get_commitment(request, pk)
    form = CommitmentProgressForm(prefix=f"cp{c.pk}", initial={
        "status": c.status, "progress_notes": c.progress_notes, "completion_evidence": c.completion_evidence,
        "incomplete_explanation": c.incomplete_explanation, "completed_on": c.completed_on,
    })
    return render(request, "reviews/commitment_detail.html", {
        "c": c, "form": form, "history": c.history.select_related("changed_by", "review__period"),
        "overdue": c.is_overdue(), "can_update": request.user.may_edit_reports,
        "comments": access.visible_comments(request.user, c.comments.all()),
        "page_title": "Commitment",
    })


@login_required
@require_POST
def commitment_update(request, pk):
    c = _get_commitment(request, pk)
    if not request.user.may_edit_reports:
        deny(request, "Updating commitments requires edit permission.", obj=c)
    review = None
    code = request.POST.get("review")
    if code:
        review = WeeklyReview.objects.filter(period__code=code).select_related("period").first()
        if review and not access.can_view_review(request.user, review):
            review = None
    form = CommitmentProgressForm(request.POST, prefix=f"cp{c.pk}")
    if form.is_valid():
        data = form.cleaned_data
        try:
            commitment_service.update_progress(
                c, request.user, status=data["status"], progress_notes=data["progress_notes"],
                completion_evidence=data["completion_evidence"],
                incomplete_explanation=data["incomplete_explanation"], completed_on=data["completed_on"],
                note=data["note"], review=review, request=request,
            )
            messages.success(request, f"Outcome updated: {Commitment.Status(data['status']).label}.")
        except commitment_service.CommitmentUpdateError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Update not saved: " + "; ".join(
            f"{k}: {' '.join(v)}" for k, v in form.errors.items()))
    if review:
        return redirect(reverse("reviews:edit", kwargs={"code": review.code}) + "#follow-through")
    return redirect("reviews:commitment_detail", pk=c.pk)
