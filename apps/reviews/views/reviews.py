from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from apps.accounts.permissions import deny, editor_required
from apps.core import periods
from apps.core.audit import log_event

from ..forms import CommentForm, CommitmentProgressForm, NewReviewForm, ReopenForm
from ..models import Comment, ReportRevision, WeeklyReview
from ..questions import CONFIDENTIAL_QUESTIONS, QUESTIONS, questions_by_section
from ..services import access, editor, presentation, workflow
from ..services import commitments as commitment_service
from ..services.metrics import METRICS, compare_reviews
from .common import get_review_for, is_ajax


# ---------------------------------------------------------------------------
# List and creation
# ---------------------------------------------------------------------------
@login_required
def review_list(request):
    qs = access.visible_reviews(request.user).select_related("metrics", "submitted_by")
    status = request.GET.get("status", "")
    if status in WeeklyReview.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs.order_by("-period__start_date"), 25).get_page(request.GET.get("page"))
    rows = [{"review": r, "checklist": workflow.checklist(r)} for r in page]
    return render(request, "reviews/review_list.html", {
        "page": page, "rows": rows, "status": status, "statuses": WeeklyReview.Status.choices,
        "page_title": "Weekly Reviews",
    })


@login_required
@editor_required
def review_new(request):
    latest = periods.latest_completed_period()
    existing = set(
        WeeklyReview.objects.filter(
            period__start_date__in=[b.start for b in periods.recent_period_choices()]
        ).values_list("period__start_date", flat=True)
    )
    choices = []
    for b in periods.recent_period_choices():
        choices.append({
            "bounds": b,
            "label": periods.format_range(b.start, b.end),
            "state": periods.PeriodState.LABELS[periods.period_state(b.start, b.end)],
            "exists": b.start in existing,
            "is_default": b.start == latest.start,
        })
    form = NewReviewForm(request.POST or None, initial={"period_start": latest.start})
    if request.method == "POST" and form.is_valid():
        review, created = workflow.create_review(request.user, form.cleaned_data["period_start"], request)
        if created:
            messages.success(request, f"Draft created for {review.period.label}.")
        else:
            if not access.can_view_review(request.user, review):
                deny(request, "A restricted report already exists for this period.", obj=review)
            messages.info(request, f"A report already exists for {review.period.label}. Opened the existing report.")
        return redirect("reviews:edit", code=review.code)
    return render(request, "reviews/review_new.html", {
        "form": form, "choices": choices, "latest": latest, "page_title": "New Weekly Review",
    })


# ---------------------------------------------------------------------------
# Editor
# ---------------------------------------------------------------------------
def _editor_context(request, review, forms=None, comment_form=None, errors=None):
    user = request.user
    can_edit = access.can_edit_review(user, review)
    forms = forms or editor.build_forms(review, user)
    if not can_edit:
        _disable(forms)
    previous = review.previous_review()
    comparisons = compare_reviews(review, previous)
    state = workflow.checklist(review)
    prev_commitments = commitment_service.previous_commitments(review)
    own_commitments = commitment_service.own_commitments(review)
    today = periods.local_today()

    all_comments = list(access.visible_comments(user, review.comments.all()))
    counts = workflow.comment_counts(all_comments)
    category = request.GET.get("category", "")
    shown_comments = [c for c in all_comments if not category or c.category == category]

    allowed_questions = [q.number for q in QUESTIONS if access.can_view_question(user, q.number)]
    comment_form = comment_form or CommentForm(
        commitments=own_commitments + prev_commitments, allowed_questions=allowed_questions,
    )

    sections = []
    for key, title, qs in questions_by_section():
        number, _, name = title.partition(": ")
        sections.append({
            "key": key, "title": title, "number": number, "name": name or title,
            "answered": sum(1 for q in qs if state["questions"][q.number]), "total": len(qs),
            "questions": [{
                "q": q,
                "form": forms["questions"].get(q.number),
                "answered": state["questions"][q.number],
                "comment_count": counts["question"].get(q.number, 0),
                "restricted": not access.can_view_question(user, q.number),
            } for q in qs],
        })

    prev_items = [{
        "obj": c,
        "overdue": c.is_overdue(today),
        "form": CommitmentProgressForm(prefix=f"cp{c.pk}", initial={
            "status": c.status, "progress_notes": c.progress_notes, "completion_evidence": c.completion_evidence,
            "incomplete_explanation": c.incomplete_explanation, "completed_on": c.completed_on,
        }),
        "comment_count": counts["commitment"].get(c.pk, 0),
    } for c in prev_commitments]

    history = {
        "previous": previous,
        "previous_answers": workflow.answers_for(previous) if previous else {},
        "previous_priorities": list(previous.priorities.all()) if previous else [],
        "previous_own_commitments": commitment_service.own_commitments(previous) if previous else [],
        "earlier": list(
            access.visible_reviews(user).select_related("metrics")
            .filter(period__start_date__lt=review.period.start_date).order_by("-period__start_date")[:8]
        ),
        "audit": list(review.audit_events.select_related("actor")[:40]),
        "revisions": list(review.revisions.select_related("created_by")),
    }

    from ..questions import QUESTIONS_BY_NUMBER
    from ..services.metrics import METRICS_BY_KEY

    category_map = {"report": Comment.Category.OVERALL}
    category_map.update({f"metric:{k}": m.comment_category for k, m in METRICS_BY_KEY.items()})
    category_map.update({f"question:{n}": q.comment_category for n, q in QUESTIONS_BY_NUMBER.items()})
    category_map.update({f"commitment:{c.pk}": Comment.Category.COMMITMENTS
                         for c in own_commitments + prev_commitments})

    return {
        "review": review,
        "period": review.period,
        "page_title": f"Weekly Review · {review.period.label}",
        "comment_category_map": category_map,
        "forms": forms,
        "can_edit": can_edit,
        "can_change_status": access.can_change_status(user, review),
        "can_reopen": access.can_reopen(user, review),
        "can_add_comment": access.can_add_comment(user, review),
        "can_view_confidential": user.may_view_confidential,
        "comparisons": [{"c": c, "comment_count": counts["metric"].get(c.metric.key, 0)} for c in comparisons],
        "previous_review": previous,
        "checklist": state,
        "completeness": workflow.data_completeness(review),
        "sections": sections,
        "prev_commitments": prev_items,
        "own_commitments": own_commitments,
        "comments": shown_comments,
        "comment_total": len(all_comments),
        "comment_counts": counts,
        "comment_category": category,
        "comment_categories": Comment.Category.choices,
        "comment_form": comment_form,
        "comment_permissions": {c.pk: access.can_modify_comment(user, c) for c in all_comments},
        "history": history,
        "reopen_form": ReopenForm(),
        "errors": errors or {},
        "metrics_defs": METRICS,
        "confidential_questions": CONFIDENTIAL_QUESTIONS,
        "positions": (1, 2, 3),
    }


def _disable(forms):
    def off(form):
        for f in form.fields.values():
            f.disabled = True
    off(forms["meta"])
    off(forms["metrics"])
    for group in ("priorities", "questions", "commitments"):
        for form in forms[group].values():
            off(form)


@login_required
def review_edit(request, code):
    review = get_review_for(request, code)
    return render(request, "reviews/editor.html", _editor_context(request, review))


@login_required
@require_POST
def review_save(request, code):
    review = get_review_for(request, code, edit=True)
    result = editor.save_details(review, request.user, request.POST, request=request, autosave=is_ajax(request))
    review = get_review_for(request, code)  # fresh copy, including related metrics
    if is_ajax(request):
        state = workflow.checklist(review)
        return JsonResponse({
            "ok": not result["errors"],
            "changed": result["changed"],
            "errors": result["errors"],
            "saved_at": date_format(timezone.localtime(review.updated_at), "j M Y, H:i:s"),
            "checklist": {"percent": state["percent"], "done": state["done"], "total": state["total"],
                          "items": {i.key: i.done for i in state["items"]},
                          "questions": state["questions"]},
        }, status=200 if not result["errors"] else 422)
    if result["errors"]:
        messages.error(request, "Some fields could not be saved. Valid fields were saved; correct the highlighted "
                                "fields and save again.")
        forms = editor.build_forms(review, request.user, request.POST)
        for group in (forms["meta"], forms["metrics"], *forms["priorities"].values(),
                      *forms["questions"].values(), *forms["commitments"].values()):
            group.is_valid()
        return render(request, "reviews/editor.html",
                      _editor_context(request, review, forms=forms, errors=result["errors"]), status=422)
    messages.success(request, "Draft saved." if result["changed"] else "No changes to save.")
    return redirect(reverse("reviews:edit", kwargs={"code": code}) + "#details")


@login_required
@require_POST
def review_acknowledge(request, code):
    review = get_review_for(request, code, edit=True)
    item = request.POST.get("item")
    field = {
        "comparison": "comparison_reviewed_at",
        "prev_commitments": "previous_commitments_reviewed_at",
        "comments": "comments_reviewed_at",
    }.get(item)
    if not field:
        messages.error(request, "Unknown checklist item.")
    else:
        value = None if request.POST.get("undo") else timezone.now()
        setattr(review, field, value)
        review.updated_by = request.user
        review.save(update_fields=[field, "updated_by", "updated_at"])
        log_event(request, "checklist_updated", obj=review, message=f"{item}: {'cleared' if value is None else 'confirmed'}")
    anchor = {"comparison": "metrics", "prev_commitments": "follow-through", "comments": "comments"}.get(item, "")
    return redirect(reverse("reviews:edit", kwargs={"code": code}) + (f"#{anchor}" if anchor else ""))


@login_required
@require_POST
def review_status(request, code):
    review = get_review_for(request, code)
    action = request.POST.get("action")
    user = request.user
    try:
        if action == "reopen":
            if not access.can_reopen(user, review):
                deny(request, "Reopening submitted reports requires correction permission.", obj=review)
            form = ReopenForm(request.POST)
            if not form.is_valid():
                raise workflow.WorkflowError("A reason is required to reopen a submitted report.")
            workflow.reopen(review, user, form.cleaned_data["reason"], request)
            messages.success(request, "Report reopened for correction. The submitted version has been preserved.")
        else:
            if not access.can_change_status(user, review):
                deny(request, "Status change not permitted.", obj=review)
            if action == "ready":
                workflow.mark_ready(review, user, request)
                messages.success(request, "Report marked Ready for Review.")
            elif action == "draft":
                workflow.return_to_draft(review, user, request)
                messages.success(request, "Report returned to Draft.")
            elif action == "submit":
                workflow.submit(review, user, confirm_incomplete=request.POST.get("confirm_incomplete") == "1",
                                request=request)
                messages.success(request, "Report submitted.")
            else:
                messages.error(request, "Unknown action.")
    except workflow.WorkflowError as exc:
        messages.error(request, str(exc))
    return redirect("reviews:edit", code=code)


@login_required
def revision_detail(request, code, number):
    review = get_review_for(request, code)
    revision = get_object_or_404(ReportRevision, review=review, number=number)
    snap = dict(revision.snapshot)
    # Apply the same visibility rules to snapshots as to live data.
    if not request.user.may_view_confidential:
        snap["responses"] = {k: v for k, v in snap.get("responses", {}).items()
                             if int(k) not in CONFIDENTIAL_QUESTIONS}
        snap["comments"] = [c for c in snap.get("comments", [])
                            if c["visibility"] == Comment.Visibility.MANAGEMENT
                            and c.get("question") not in CONFIDENTIAL_QUESTIONS]
    responses = snap.get("responses", {})
    snap_answers = [
        (q, [(sf.label, responses[str(q.number)].get(sf.key)) for sf in q.fields
             if responses[str(q.number)].get(sf.key)])
        for q in QUESTIONS if str(q.number) in responses
    ]
    return render(request, "reviews/revision_detail.html", {
        "review": review, "revision": revision, "snap": snap, "snap_answers": snap_answers,
        "page_title": f"Revision {revision.number}",
        "questions": QUESTIONS, "metrics_defs": METRICS,
    })


# ---------------------------------------------------------------------------
# Presentation and export
# ---------------------------------------------------------------------------
def _flag(request, name):
    value = request.GET.get(name)
    if value is None:
        return None
    return value == "1"


@login_required
def review_present(request, code):
    review = get_review_for(request, code)
    if request.GET.get("preview") == "1" and access.can_edit_review(request.user, review):
        review.preview_checked_at = timezone.now()
        review.save(update_fields=["preview_checked_at", "updated_at"])
    ctx = presentation.build_context(review, request.user, include_comments=_flag(request, "comments"),
                                     include_leadership=_flag(request, "leadership"))
    ctx["page_title"] = f"Presentation · {review.period.label}"
    return render(request, "reviews/present.html", ctx)


def render_pdf_html(review, user, include_comments=None, include_leadership=None):
    ctx = presentation.build_context(review, user, include_comments=include_comments,
                                     include_leadership=include_leadership)
    ctx["generated_at"] = timezone.localtime()
    return render_to_string("reviews/present_pdf.html", ctx)


@login_required
def review_pdf(request, code):
    from io import BytesIO

    from xhtml2pdf import pisa

    review = get_review_for(request, code)
    html = render_pdf_html(review, request.user, _flag(request, "comments"), _flag(request, "leadership"))
    buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=buffer, encoding="utf-8")
    if result.err:
        messages.error(request, "The PDF could not be generated. Use browser printing instead.")
        return redirect("reviews:present", code=code)
    log_event(request, "report_exported", obj=review, message="PDF exported")
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="weekly-review-{review.period.start_date}.pdf"'
    return response
