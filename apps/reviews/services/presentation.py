"""Single context builder for presentation mode, print and PDF export.

Both the on-screen presentation and the PDF use this function, so exports
always match the saved data for the selected reporting period.
"""
from apps.core.models import AppSettings

from ..models import Comment
from ..questions import QUESTIONS, QUESTIONS_BY_NUMBER
from . import access, workflow
from . import commitments as commitment_service
from .metrics import compare_reviews


def _answer_blocks(question, answer):
    return [
        {"label": sf.label, "value": (answer or {}).get(sf.key, "").strip()}
        for sf in question.fields
        if (answer or {}).get(sf.key, "").strip()
    ]


def build_context(review, user, include_comments=None, include_leadership=None):
    app_settings = AppSettings.load()
    if include_comments is None:
        include_comments = review.include_management_comments
    leadership_allowed = user.may_view_confidential
    if include_leadership is None:
        include_leadership = app_settings.show_leadership_in_presentation
    include_leadership = bool(include_leadership and leadership_allowed)

    previous = review.previous_review()
    comparisons = compare_reviews(review, previous)
    answers = workflow.answers_for(review)
    completeness = workflow.data_completeness(review)
    state = workflow.checklist(review)

    comments = list(access.management_comments(review, include_leadership)) if include_comments else []
    comments_by_section = {"metrics": {}, "questions": {}, "commitments": {}, "report": []}
    for c in comments:
        if c.target_type == Comment.Target.METRIC:
            comments_by_section["metrics"].setdefault(c.metric, []).append(c)
        elif c.target_type == Comment.Target.QUESTION:
            comments_by_section["questions"].setdefault(c.question, []).append(c)
        elif c.target_type == Comment.Target.COMMITMENT:
            comments_by_section["commitments"].setdefault(c.commitment_id, []).append(c)
        else:
            comments_by_section["report"].append(c)

    # Previous commitments: for submitted reports show status as recorded
    # at submission time, so historical presentations stay consistent.
    prev_commitments = []
    for c in commitment_service.previous_commitments(review):
        status_value = c.status
        if review.is_submitted and review.submitted_at:
            status_value = c.status_as_of(review.submitted_at)
        prev_commitments.append({
            "obj": c,
            "status": status_value,
            "status_label": c.Status(status_value).label,
            "changed_since": status_value != c.status,
            "overdue": status_value != c.Status.COMPLETED and c.due_date < review.period.presentation_date,
            "comments": comments_by_section["commitments"].get(c.pk, []),
        })

    def q(number):
        question = QUESTIONS_BY_NUMBER[number]
        return {
            "q": question,
            "blocks": _answer_blocks(question, answers.get(number)),
            "comments": comments_by_section["questions"].get(number, []),
        }

    own_commitments = [
        {"obj": c, "comments": comments_by_section["commitments"].get(c.pk, [])}
        for c in commitment_service.own_commitments(review)
    ]

    return {
        "review": review,
        "period": review.period,
        "previous_review": previous,
        "previous_bounds": review.period.previous_bounds,
        "comparisons": [
            {"c": cmp, "comments": comments_by_section["metrics"].get(cmp.metric.key, [])} for cmp in comparisons
        ],
        "completeness": completeness,
        "checklist": state,
        "priorities": list(review.priorities.all()),
        "q": {n: q(n) for n in range(1, 13)},
        "include_leadership": include_leadership,
        "leadership_allowed": leadership_allowed,
        "include_comments": include_comments,
        "prev_commitments": prev_commitments,
        "own_commitments": own_commitments,
        "report_comments": comments_by_section["report"],
        "app_settings": app_settings,
        "questions": QUESTIONS,
    }
