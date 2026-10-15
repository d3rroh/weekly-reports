"""Weekly review lifecycle: creation, completeness, status transitions, snapshots."""
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core import periods
from apps.core.audit import log_event
from apps.core.models import AppSettings

from ..models import (
    Comment, Commitment, Priority, ReportingPeriod, ReportRevision, ReviewResponse, WeeklyMetrics, WeeklyReview,
)
from ..questions import QUESTIONS, QUESTIONS_BY_NUMBER
from . import commitments as commitment_service
from .metrics import METRICS, metric_values, metrics_complete


class WorkflowError(Exception):
    pass


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def create_review(user, start_date, request=None):
    """Create the review for the period starting `start_date`.

    Returns (review, created). Never creates a duplicate for a period.
    """
    bounds = periods.bounds_for_start(start_date)
    existing = WeeklyReview.objects.filter(period__start_date=bounds.start).first()
    if existing:
        return existing, False
    try:
        with transaction.atomic():
            period = ReportingPeriod.for_start(bounds.start)
            review = WeeklyReview.objects.create(
                period=period, author=user, updated_by=user,
                include_management_comments=AppSettings.load().include_management_comments_default,
            )
            WeeklyMetrics.objects.create(review=review)
            _prefill_priorities(review)
    except IntegrityError:
        # Concurrent creation of the same period: return the winner.
        return WeeklyReview.objects.get(period__start_date=bounds.start), False
    log_event(request, "review_created", obj=review, message=f"Review created for {period.label}")
    return review, True


def _prefill_priorities(review):
    """Seed Question 1 with the outcomes committed in the previous report."""
    prev = review.previous_review()
    if not prev:
        return
    for c in prev.commitments.order_by("position")[:3]:
        Priority.objects.create(
            review=review, position=c.position, description=c.description[:500],
            expected_outcome=c.success_criteria, source_commitment=c,
        )


# ---------------------------------------------------------------------------
# Answers and completeness
# ---------------------------------------------------------------------------
def answers_for(review):
    return {r.question: r.answer or {} for r in review.responses.all()}


def _filled(value):
    return bool(str(value or "").strip())


def priority_complete(p):
    return _filled(p.description) and _filled(p.actual_result) and _filled(p.delivery_status)


def commitment_defined(c):
    return _filled(c.description) and _filled(c.success_criteria)


def question_status(review, answers=None, priorities=None, commitments=None, metrics=None):
    """Return {question_number: bool answered}."""
    answers = answers if answers is not None else answers_for(review)
    priorities = priorities if priorities is not None else list(review.priorities.all())
    commitments = commitments if commitments is not None else list(review.commitments.all())
    metrics = metrics if metrics is not None else getattr(review, "metrics", None)
    status = {}
    for q in QUESTIONS:
        answer = answers.get(q.number, {})
        ok = all(_filled(answer.get(k)) for k in q.required_keys)
        if q.kind == "priorities":
            ok = ok and any(priority_complete(p) for p in priorities) and all(
                priority_complete(p) for p in priorities if _filled(p.description))
        elif q.kind == "metrics":
            ok = ok and metrics_complete(metrics)
        elif q.kind == "commitments":
            ok = ok and len([c for c in commitments if commitment_defined(c)]) == 3
        status[q.number] = ok
    return status


@dataclass
class ChecklistItem:
    key: str
    label: str
    done: bool
    detail: str = ""
    anchor: str = ""
    acknowledgeable: bool = False


def checklist(review):
    metrics = getattr(review, "metrics", None)
    qstatus = question_status(review, metrics=metrics)
    answered = sum(qstatus.values())
    own = list(review.commitments.all())
    defined = len([c for c in own if commitment_defined(c)])
    prev_commitments = commitment_service.previous_commitments(review)
    values = metric_values(metrics)
    missing_metrics = [m.short_label for m in METRICS if values[m.key] is None]
    comment_count = review.comments.filter(deleted_at__isnull=True).count()

    items = [
        ChecklistItem("period", "Reporting period selected", True, review.period.label, "details"),
        ChecklistItem(
            "metrics", "Required metric values entered", not missing_metrics,
            "All four entered" if not missing_metrics else "Missing: " + ", ".join(missing_metrics), "metrics",
        ),
        ChecklistItem(
            "comparison", "Previous-period comparison reviewed", review.comparison_reviewed_at is not None,
            "Confirm after checking the comparison table", "metrics", acknowledgeable=True,
        ),
        ChecklistItem(
            "questions", "All 12 questions answered", answered == len(QUESTIONS),
            f"{answered} of {len(QUESTIONS)} answered", "questions",
        ),
        ChecklistItem("outcomes", "Three next-week outcomes defined", defined == 3, f"{defined} of 3 defined", "q10"),
        ChecklistItem(
            "prev_commitments", "Previous commitments reviewed",
            not prev_commitments or review.previous_commitments_reviewed_at is not None,
            "No previous commitments" if not prev_commitments
            else f"{len(prev_commitments)} to review", "follow-through", acknowledgeable=bool(prev_commitments),
        ),
        ChecklistItem(
            "comments", "Relevant comments added",
            comment_count > 0 or review.comments_reviewed_at is not None,
            f"{comment_count} comment(s)" if comment_count else "Add comments or confirm none are needed",
            "comments", acknowledgeable=comment_count == 0,
        ),
        ChecklistItem(
            "preview", "Presentation preview checked", review.preview_checked_at is not None,
            "Open Preview to complete", "preview",
        ),
    ]
    done = sum(1 for i in items if i.done)
    return {
        "items": items,
        "done": done,
        "total": len(items),
        "percent": round(done * 100 / len(items)),
        "complete": done == len(items),
        "questions": qstatus,
        "outstanding": [i for i in items if not i.done],
    }


def data_completeness(review):
    """Whether the figures can be presented as final results."""
    metrics = getattr(review, "metrics", None)
    return {
        "period_complete": review.period.is_complete,
        "metrics_complete": metrics_complete(metrics),
        "is_final": review.period.is_complete and metrics_complete(metrics),
    }


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------
def _locked(review):
    """Re-read the review with a row lock; call inside a transaction."""
    return WeeklyReview.objects.select_for_update().select_related("period").get(pk=review.pk)


@transaction.atomic
def mark_ready(review, user, request=None):
    review = _locked(review)
    if review.status != WeeklyReview.Status.DRAFT:
        raise WorkflowError("Only draft reports can be marked ready for review.")
    review.status = WeeklyReview.Status.READY
    review.ready_at = timezone.now()
    review.updated_by = user
    review.save()
    log_event(request, "review_ready", obj=review, message="Marked ready for review")
    return review


@transaction.atomic
def return_to_draft(review, user, request=None):
    review = _locked(review)
    if review.status != WeeklyReview.Status.READY:
        raise WorkflowError("Only reports that are ready for review can be returned to draft.")
    review.status = WeeklyReview.Status.DRAFT
    review.ready_at = None
    review.updated_by = user
    review.save()
    log_event(request, "review_draft", obj=review, message="Returned to draft")
    return review


@transaction.atomic
def submit(review, user, confirm_incomplete=False, request=None):
    review = _locked(review)
    if review.status == WeeklyReview.Status.SUBMITTED:
        raise WorkflowError("This report has already been submitted.")
    state = checklist(review)
    if not state["complete"]:
        if not AppSettings.load().allow_incomplete_submission:
            raise WorkflowError("This report is incomplete and incomplete submissions are disabled.")
        if not confirm_incomplete:
            raise WorkflowError("This report is incomplete. Confirm that you want to submit it anyway.")
    review.status = WeeklyReview.Status.SUBMITTED
    review.submitted_at = timezone.now()
    review.submitted_by = user
    review.submitted_incomplete = not state["complete"]
    review.updated_by = user
    review.save()
    revision = _record_revision(review, user, ReportRevision.Kind.SUBMISSION, "")
    log_event(request, "review_submitted", obj=review,
              message="Submitted" + (" (incomplete, confirmed)" if review.submitted_incomplete else ""),
              data={"revision": revision.number, "outstanding": [i.key for i in state["outstanding"]]})
    return review


@transaction.atomic
def reopen(review, user, reason, request=None):
    review = _locked(review)
    if review.status != WeeklyReview.Status.SUBMITTED:
        raise WorkflowError("Only submitted reports can be reopened.")
    if not (reason or "").strip():
        raise WorkflowError("A reason is required to reopen a submitted report.")
    _record_revision(review, user, ReportRevision.Kind.REOPEN, reason.strip())
    review.status = WeeklyReview.Status.DRAFT
    review.reopened_count += 1
    review.preview_checked_at = None
    review.updated_by = user
    review.save()
    log_event(request, "review_reopened", obj=review, message="Reopened for correction",
              data={"reason": reason.strip()[:1000]})
    return review


def _record_revision(review, user, kind, reason):
    number = (review.revisions.order_by("-number").values_list("number", flat=True).first() or 0) + 1
    return ReportRevision.objects.create(
        review=review, number=number, kind=kind, reason=reason, snapshot=snapshot(review), created_by=user,
    )


# ---------------------------------------------------------------------------
# Snapshot (full record of a report at a point in time)
# ---------------------------------------------------------------------------
def snapshot(review):
    def s(v):
        return None if v is None else str(v)

    metrics = getattr(review, "metrics", None)
    return {
        "code": review.period.code,
        "start_date": review.period.start_date.isoformat(),
        "end_date": review.period.end_date.isoformat(),
        "presentation_date": review.period.presentation_date.isoformat(),
        "status": review.status,
        "executive_summary": review.executive_summary,
        "metrics": {k: s(v) for k, v in metric_values(metrics).items()},
        "responses": {str(k): v for k, v in answers_for(review).items()},
        "priorities": [
            {"position": p.position, "description": p.description, "expected_outcome": p.expected_outcome,
             "actual_result": p.actual_result, "delivery_status": p.delivery_status, "notes": p.notes}
            for p in review.priorities.all()
        ],
        "commitments": [
            {"id": c.pk, "position": c.position, "description": c.description,
             "success_criteria": c.success_criteria, "owner": c.owner, "due_date": c.due_date.isoformat(),
             "status": c.status}
            for c in review.commitments.all()
        ],
        "previous_commitments": [
            {"id": c.pk, "description": c.description, "status": c.status,
             "progress_notes": c.progress_notes, "completion_evidence": c.completion_evidence,
             "incomplete_explanation": c.incomplete_explanation}
            for c in commitment_service.previous_commitments(review)
        ],
        "comments": [
            {"id": c.pk, "category": c.category, "visibility": c.visibility, "target_type": c.target_type,
             "metric": c.metric, "question": c.question, "commitment": c.commitment_id, "text": c.text,
             "author": c.author.username, "created_at": c.created_at.isoformat()}
            for c in review.comments.filter(deleted_at__isnull=True).select_related("author")
        ],
    }


def question_def(number):
    return QUESTIONS_BY_NUMBER[number]


def open_commitment_count():
    return Commitment.objects.exclude(status=Commitment.Status.COMPLETED).count()


def comment_counts(comments):
    """Counts of the given (already visibility-filtered) comments by target."""
    counts = {"metric": {}, "question": {}, "commitment": {}, "report": 0}
    for c in comments:
        if c.target_type == Comment.Target.METRIC:
            counts["metric"][c.metric] = counts["metric"].get(c.metric, 0) + 1
        elif c.target_type == Comment.Target.QUESTION:
            counts["question"][c.question] = counts["question"].get(c.question, 0) + 1
        elif c.target_type == Comment.Target.COMMITMENT:
            counts["commitment"][c.commitment_id] = counts["commitment"].get(c.commitment_id, 0) + 1
        else:
            counts["report"] += 1
    return counts
