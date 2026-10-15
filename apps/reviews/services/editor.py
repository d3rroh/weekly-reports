"""Building and saving the Details tab of the report editor.

Saving is *partial*: fields that validate are persisted; fields that fail
validation are reported back and left unchanged. Missing values are stored
as NULL/empty, never coerced to zero.
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.audit import log_event
from apps.core.models import AuditEvent

from ..forms import (
    CommitmentDefinitionForm, MetricsForm, PriorityForm, ReviewMetaForm, question_form_class,
)
from ..models import Commitment, Priority, ReviewResponse, WeeklyMetrics
from ..questions import QUESTIONS
from . import commitments as commitment_service
from . import access

AUDIT_AUTOSAVE_INTERVAL = timedelta(minutes=10)


def build_forms(review, user, data=None):
    """Instantiate every Details-tab form, bound to `data` when given."""
    metrics = getattr(review, "metrics", None) or WeeklyMetrics(review=review)
    priorities = {p.position: p for p in review.priorities.all()}
    commitments = {c.position: c for c in review.commitments.all()}
    answers = {r.question: r.answer for r in review.responses.all()}
    earliest_due = review.period.presentation_date

    forms = {
        "meta": ReviewMetaForm(data, prefix="meta", initial={
            "executive_summary": review.executive_summary,
            "include_management_comments": review.include_management_comments,
            "is_restricted": review.is_restricted,
        }),
        "metrics": MetricsForm(data, prefix="metrics", instance=metrics),
        "priorities": {},
        "questions": {},
        "commitments": {},
    }
    if not user.may_view_confidential:
        forms["meta"].fields["is_restricted"].disabled = True
    for pos in (1, 2, 3):
        p = priorities.get(pos)
        initial = {f: getattr(p, f) for f in ("description", "expected_outcome", "actual_result",
                                              "delivery_status", "notes")} if p else {}
        forms["priorities"][pos] = PriorityForm(data, prefix=f"p{pos}", initial=initial)
        c = commitments.get(pos)
        cinitial = {f: getattr(c, f) for f in ("description", "success_criteria", "owner", "due_date")} if c else {}
        forms["commitments"][pos] = CommitmentDefinitionForm(
            data, prefix=f"c{pos}", initial=cinitial, earliest_due=earliest_due,
        )
    for q in QUESTIONS:
        if access.can_view_question(user, q.number):
            forms["questions"][q.number] = question_form_class(q.number)(
                data, prefix=f"q{q.number}", initial=answers.get(q.number, {}),
            )
    return forms


def _posted(form, data):
    return any(form.add_prefix(name) in data for name in form.fields)


def _valid_values(form):
    """Run validation and return cleaned values for fields without errors."""
    form.is_valid()
    cleaned = getattr(form, "cleaned_data", {})
    return {name: cleaned[name] for name in form.fields if name not in form.errors and name in cleaned}


def _errors(form):
    return {form.add_prefix(name if name != "__all__" else "description"): [str(e) for e in errs]
            for name, errs in form.errors.items()}


@transaction.atomic
def save_details(review, user, data, request=None, autosave=False):
    """Persist the Details tab. Returns {"changed": [...], "errors": {...}}."""
    forms = build_forms(review, user, data)
    changed, errors = [], {}

    # Report metadata -----------------------------------------------------
    meta = forms["meta"]
    if data.get("meta-present"):
        values = _valid_values(meta)
        errors.update(_errors(meta))
        updates = {"executive_summary": values.get("executive_summary", review.executive_summary),
                   "include_management_comments": values.get("include_management_comments", False)}
        if user.may_view_confidential:
            updates["is_restricted"] = values.get("is_restricted", False)
        for key, value in updates.items():
            if getattr(review, key) != value:
                setattr(review, key, value)
                changed.append(key)

    # Metrics ---------------------------------------------------------------
    mform = forms["metrics"]
    if _posted(mform, data):
        values = _valid_values(mform)
        errors.update(_errors(mform))
        metrics, _ = WeeklyMetrics.objects.get_or_create(review=review)
        metric_changed = False
        for key, value in values.items():
            if getattr(metrics, key) != value:
                setattr(metrics, key, value)
                metric_changed = True
                changed.append(f"metrics.{key}")
        if metric_changed:
            metrics.save()
            # Figures changed: the comparison must be re-confirmed.
            if review.comparison_reviewed_at:
                review.comparison_reviewed_at = None
                changed.append("comparison_reviewed_at")

    # Question 1 priorities -------------------------------------------------
    for pos, form in forms["priorities"].items():
        if not _posted(form, data):
            continue
        values = _valid_values(form)
        errors.update(_errors(form))
        if "description" in form.errors:
            continue
        existing = review.priorities.filter(position=pos).first()
        description = values.get("description", "").strip()
        if not description:
            if existing:
                existing.delete()
                changed.append(f"priority.{pos}.deleted")
            continue
        obj = existing or Priority(review=review, position=pos)
        dirty = obj.pk is None
        for key, value in values.items():
            value = value.strip() if isinstance(value, str) else value
            if getattr(obj, key) != value:
                setattr(obj, key, value)
                dirty = True
        if dirty:
            obj.save()
            changed.append(f"priority.{pos}")

    # Question answers -------------------------------------------------------
    existing_responses = {r.question: r for r in review.responses.all()}
    for number, form in forms["questions"].items():
        if not _posted(form, data):
            continue
        values = _valid_values(form)
        errors.update(_errors(form))
        response = existing_responses.get(number)
        answer = dict(response.answer) if response else {}
        for key, value in values.items():
            answer[key] = value.strip()
        if response is None:
            if any(answer.values()):
                ReviewResponse.objects.create(review=review, question=number, answer=answer, updated_by=user)
                changed.append(f"q{number}")
        elif answer != response.answer:
            response.answer = answer
            response.updated_by = user
            response.save()
            changed.append(f"q{number}")

    # Question 10 commitment definitions --------------------------------------
    for pos, form in forms["commitments"].items():
        if not _posted(form, data):
            continue
        values = _valid_values(form)
        errors.update(_errors(form))
        if "description" in form.errors:
            continue
        existing = review.commitments.filter(position=pos).first()
        description = values.get("description", "").strip()
        if not description:
            if existing:
                if _can_delete_commitment(existing):
                    log_event(request, "commitment_deleted", obj=existing, review=review,
                              message=f"Outcome {pos} removed")
                    existing.history.all().delete()
                    existing.delete()
                    changed.append(f"commitment.{pos}.deleted")
                else:
                    errors[form.add_prefix("description")] = [
                        "This outcome has comments or progress updates and cannot be removed. Edit it instead."]
            continue
        payload = {k: (v.strip() if isinstance(v, str) else v) for k, v in values.items()}
        payload["description"] = description
        if "due_date" in payload and payload["due_date"] is None:
            payload.pop("due_date")
        before = None if existing is None else (existing.description, existing.success_criteria,
                                                existing.owner, existing.due_date)
        c = commitment_service.save_definition(review, pos, payload, user, request=request)
        if before != (c.description, c.success_criteria, c.owner, c.due_date):
            changed.append(f"commitment.{pos}")

    if changed:
        review.updated_by = user
        review.save()
        _audit_save(request, review, changed, autosave)
    else:
        # Still record who last touched the draft without altering content.
        pass
    return {"changed": changed, "errors": errors, "saved_at": review.updated_at}


def _can_delete_commitment(commitment):
    return (
        not commitment.comments.exists()
        and commitment.status == Commitment.Status.NOT_STARTED
        and commitment.history.count() <= 1
        and not commitment.progress_notes
    )


def _audit_save(request, review, changed, autosave):
    correction = review.reopened_count > 0
    if autosave and not correction:
        recent = AuditEvent.objects.filter(
            review=review, action="review_updated",
            actor=request.user if request and request.user.is_authenticated else None,
            created_at__gte=timezone.now() - AUDIT_AUTOSAVE_INTERVAL,
        ).exists()
        if recent:
            return
    log_event(request, "review_corrected" if correction else "review_updated", obj=review,
              message="Report corrected after reopening" if correction else
              ("Draft autosaved" if autosave else "Draft saved"),
              data={"changed": changed[:50]})
