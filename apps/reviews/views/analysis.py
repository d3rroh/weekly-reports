"""Dashboard, historical reports, comparison and trends."""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import render

from apps.core import periods

from ..forms import DateRangeForm, parse_date
from ..models import Commitment, WeeklyReview
from ..questions import CONFIDENTIAL_QUESTIONS, QUESTIONS
from ..services import access, trends, workflow
from ..services import commitments as commitment_service
from ..services.metrics import METRICS, compare_reviews


def _chart_metrics():
    return [{"key": m.key, "label": m.label, "unit": m.unit, "higher_is_better": m.higher_is_better}
            for m in METRICS]


@login_required
def dashboard(request):
    user = request.user
    latest = periods.latest_completed_period()
    current_inprogress = periods.current_period()
    reviews = access.visible_reviews(user).select_related("metrics")
    review = reviews.filter(period__start_date=latest.start).first()
    any_reviews = reviews.exists()

    ctx = {
        "page_title": "Overview",
        "latest": latest,
        "latest_label": periods.format_range(latest.start, latest.end),
        "previous_label": periods.format_range(latest.previous.start, latest.previous.end),
        "in_progress": current_inprogress,
        "in_progress_label": periods.format_range(current_inprogress.start, current_inprogress.end),
        "review": review,
        "any_reviews": any_reviews,
        "can_edit": user.may_edit_reports,
    }
    if review:
        ctx["comparisons"] = compare_reviews(review, review.previous_review())
        ctx["checklist"] = workflow.checklist(review)
        ctx["completeness"] = workflow.data_completeness(review)
        ctx["upcoming"] = commitment_service.own_commitments(review)
    else:
        # Fall back to the most recent report's commitments.
        last = reviews.order_by("-period__start_date").first()
        ctx["upcoming"] = commitment_service.own_commitments(last) if last else []
        ctx["upcoming_source"] = last

    today = periods.local_today()
    outstanding = [c for c in commitment_service.outstanding_commitments(today)
                   if access.can_view_review(user, c.source_review)]
    ctx["outstanding"] = outstanding[:8]
    ctx["outstanding_total"] = len(outstanding)
    ctx["recent_submitted"] = list(reviews.filter(status=WeeklyReview.Status.SUBMITTED)
                                   .order_by("-period__start_date")[:5])
    observations = []
    for r in reviews.order_by("-period__start_date")[:4]:
        ans = workflow.answers_for(r).get(3, {})
        if ans.get("trends"):
            observations.append({"review": r, "trends": ans.get("trends"), "risks": ans.get("risks", "")})
    ctx["observations"] = observations[:3]
    if any_reviews:
        points = trends.series(user, latest.start - timedelta(days=7 * 11), latest.start)
        ctx["chart_points"] = points
        ctx["chart_metrics"] = _chart_metrics()
        ctx["chart_payload"] = {"points": points, "metrics": ctx["chart_metrics"]}
        if review:
            ctx["metric_rows"] = [
                {"c": c, "spark": [p["values"][c.metric.key] for p in points]} for c in ctx["comparisons"]
            ]
    return render(request, "reviews/dashboard.html", ctx)


@login_required
def history(request):
    qs = access.visible_reviews(request.user).select_related("metrics", "submitted_by")
    status = request.GET.get("status", "")
    date_from = parse_date(request.GET.get("from"))
    date_to = parse_date(request.GET.get("to"))
    on_date = parse_date(request.GET.get("date"))
    if status in WeeklyReview.Status.values:
        qs = qs.filter(status=status)
    if on_date:
        qs = qs.filter(period__start_date=periods.period_start_for(on_date))
    if date_from:
        qs = qs.filter(period__end_date__gte=date_from)
    if date_to:
        qs = qs.filter(period__start_date__lte=date_to)
    page = Paginator(qs.order_by("-period__start_date"), 20).get_page(request.GET.get("page"))
    rows = []
    for r in page:
        own = list(r.commitments.all())
        rows.append({
            "review": r,
            "comparisons": compare_reviews(r, r.previous_review()),
            "commitments_done": sum(1 for c in own if c.status == Commitment.Status.COMPLETED),
            "commitments_total": len(own),
        })
    all_reviews = access.visible_reviews(request.user).order_by("-period__start_date")
    return render(request, "reviews/history.html", {
        "page": page, "rows": rows, "status": status, "statuses": WeeklyReview.Status.choices,
        "date_from": request.GET.get("from", ""), "date_to": request.GET.get("to", ""),
        "on_date": request.GET.get("date", ""),
        "all_reviews": all_reviews[:104], "metrics_defs": METRICS,
        "page_title": "Historical Reports",
    })


@login_required
def compare_view(request):
    user = request.user
    visible = access.visible_reviews(user).select_related("metrics")
    all_reviews = list(visible.order_by("-period__start_date")[:104])
    a_code, b_code = request.GET.get("a", ""), request.GET.get("b", "")
    a = visible.filter(period__code=a_code).first() if a_code else None
    b = visible.filter(period__code=b_code).first() if b_code else None
    if a and not b_code:
        b = a.previous_review()
        if b and not access.can_view_review(user, b):
            b = None
    ctx = {"all_reviews": all_reviews, "a": a, "b": b, "a_code": a_code,
           "b_code": b.code if b else b_code, "page_title": "Compare Reports"}
    if a and b:
        if b.period.start_date > a.period.start_date:
            a, b = b, a
            ctx.update(a=a, b=b)
        ctx["comparisons"] = compare_reviews(a, b)
        a_ans, b_ans = workflow.answers_for(a), workflow.answers_for(b)
        ctx["answer_rows"] = [
            {"q": q, "a": a_ans.get(q.number, {}), "b": b_ans.get(q.number, {})}
            for q in QUESTIONS
            if q.number not in CONFIDENTIAL_QUESTIONS or user.may_view_confidential
        ]
        ctx["a_commitments"] = list(a.commitments.all())
        ctx["b_commitments"] = list(b.commitments.all())
        ctx["gap_weeks"] = (a.period.start_date - b.period.start_date).days // 7
    return render(request, "reviews/compare.html", ctx)


@login_required
def trends_view(request):
    form = DateRangeForm(request.GET or None)
    first, last = form.resolve()
    points = trends.series(request.user, first, last)
    chart_metrics = _chart_metrics()
    return render(request, "reviews/trends.html", {
        "chart_payload": {"points": points, "metrics": chart_metrics},
        "form": form, "points": points, "summary": trends.summarise(points),
        "first_label": periods.format_range(first, first + timedelta(days=6)),
        "last_label": periods.format_range(last, last + timedelta(days=6)),
        "chart_metrics": chart_metrics,
        "page_title": "Performance Trends",
    })


@login_required
def trends_data(request):
    form = DateRangeForm(request.GET or None)
    first, last = form.resolve()
    return JsonResponse({"points": trends.series(request.user, first, last)})
