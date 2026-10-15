"""Commitment definition, follow-through and status history."""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q

from apps.core import periods
from apps.core.audit import log_event

from ..models import Commitment, CommitmentHistory, ReportingPeriod


def target_period_for(review):
    """Commitments made in a review target the period that starts on its presentation day."""
    return ReportingPeriod.for_start(review.period.start_date + timedelta(days=7))


def own_commitments(review):
    return list(review.commitments.select_related("target_period").order_by("position"))


def previous_commitments(review):
    """Commitments to follow through when preparing `review`.

    Returns those defined in the immediately preceding report, plus any
    older commitments that are still not completed.
    """
    prev_start = review.period.start_date - timedelta(days=7)
    return list(
        Commitment.objects.select_related("source_review__period", "target_period")
        .filter(source_review__period__start_date__lt=review.period.start_date)
        .filter(Q(source_review__period__start_date=prev_start) | ~Q(status=Commitment.Status.COMPLETED))
        .order_by("-source_review__period__start_date", "position")
    )


def relevant_commitments(review):
    return own_commitments(review) + previous_commitments(review)


def outstanding_commitments(today=None, before=None):
    """Open commitments whose due date has passed (or whose target period has ended)."""
    today = today or periods.local_today()
    qs = Commitment.objects.select_related("source_review__period", "target_period").exclude(
        status=Commitment.Status.COMPLETED
    )
    qs = qs.filter(due_date__lt=today)
    return qs.order_by("due_date", "position")


@transaction.atomic
def save_definition(review, position, data, user, request=None):
    """Create or update the definition of a Question 10 outcome."""
    commitment = review.commitments.filter(position=position).first()
    if commitment is None:
        target = target_period_for(review)
        commitment = Commitment.objects.create(
            source_review=review, position=position, target_period=target,
            due_date=data.get("due_date") or target.end_date,
            description=data["description"], success_criteria=data.get("success_criteria", ""),
            owner=data.get("owner", ""), created_by=user,
        )
        CommitmentHistory.objects.create(
            commitment=commitment, from_status="", to_status=commitment.status,
            note="Outcome defined", review=review, changed_by=user,
        )
        log_event(request, "commitment_created", obj=commitment, review=review,
                  message=f"Outcome {position} defined")
        return commitment
    changed = []
    for name in ("description", "success_criteria", "owner", "due_date"):
        if name in data and data[name] is not None and getattr(commitment, name) != data[name]:
            setattr(commitment, name, data[name])
            changed.append(name)
    if changed:
        commitment.save()
        log_event(request, "commitment_updated", obj=commitment, review=review,
                  message=f"Outcome {position} definition updated", data={"fields": changed})
    return commitment


class CommitmentUpdateError(ValueError):
    pass


@transaction.atomic
def update_progress(commitment, user, *, status, progress_notes=None, completion_evidence=None,
                    incomplete_explanation=None, completed_on=None, note="", review=None, request=None):
    """Update status/progress. Every status change is recorded in history.

    A commitment is only ever completed by an explicit user action with
    evidence — never inferred from metric movement.
    """
    commitment = Commitment.objects.select_for_update().get(pk=commitment.pk)
    if status not in Commitment.Status.values:
        raise CommitmentUpdateError("Unknown status.")
    evidence = completion_evidence if completion_evidence is not None else commitment.completion_evidence
    explanation = incomplete_explanation if incomplete_explanation is not None else commitment.incomplete_explanation
    if status == Commitment.Status.COMPLETED and not (evidence or "").strip():
        raise CommitmentUpdateError("Completion evidence is required to mark an outcome as completed.")
    if status == Commitment.Status.BLOCKED and not (explanation or note or "").strip():
        raise CommitmentUpdateError("Explain what is blocking this outcome.")

    old_status = commitment.status
    if progress_notes is not None:
        commitment.progress_notes = progress_notes
    commitment.completion_evidence = evidence
    commitment.incomplete_explanation = explanation
    if status == Commitment.Status.COMPLETED:
        commitment.completed_on = completed_on or commitment.completed_on or periods.local_today()
    else:
        commitment.completed_on = None
    commitment.status = status
    commitment.save()

    if old_status != status or note.strip():
        CommitmentHistory.objects.create(
            commitment=commitment, from_status=old_status, to_status=status,
            note=note.strip(), review=review, changed_by=user,
        )
    log_event(request, "commitment_status" if old_status != status else "commitment_progress",
              obj=commitment, review=review,
              message=f"{commitment.get_status_display()}" if old_status == status
              else f"{Commitment.Status(old_status).label} → {commitment.get_status_display()}")
    return commitment
