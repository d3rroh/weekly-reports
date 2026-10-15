"""Historical metric series built only from saved records."""
from datetime import timedelta
from decimal import Decimal

from apps.core import periods

from ..models import WeeklyReview
from .metrics import METRICS, compare


def series(user, first_start, last_start):
    """One entry per reporting period in range; missing periods/values are None."""
    from . import access

    reviews = {
        r.period.start_date: r
        for r in access.visible_reviews(user)
        .select_related("metrics")
        .filter(period__start_date__gte=first_start, period__start_date__lte=last_start)
    }
    points = []
    start = first_start
    while start <= last_start:
        bounds = periods.bounds_for_start(start)
        review = reviews.get(start)
        metrics = getattr(review, "metrics", None) if review else None
        points.append({
            "code": bounds.code,
            "start": bounds.start.isoformat(),
            "end": bounds.end.isoformat(),
            "label": f"{bounds.start:%-d %b}",
            "range": periods.format_range(bounds.start, bounds.end),
            "has_report": review is not None,
            "status": review.get_status_display() if review else None,
            "values": {
                m.key: (float(getattr(metrics, m.field)) if metrics and getattr(metrics, m.field) is not None
                        else None)
                for m in METRICS
            },
        })
        start += timedelta(days=7)
    return points


def summarise(points):
    """Factual summary of observed changes; no causal explanations."""
    out = []
    for m in METRICS:
        vals = [(p, p["values"][m.key]) for p in points if p["values"][m.key] is not None]
        missing = sum(1 for p in points if p["values"][m.key] is None)
        if not vals:
            out.append({"metric": m, "text": "No saved values in this range.", "missing": missing, "latest": None})
            continue
        latest_p, latest_v = vals[-1]
        entry = {"metric": m, "missing": missing, "latest": latest_v, "latest_range": latest_p["range"],
                 "count": len(vals)}
        if len(vals) >= 2:
            first_p, first_v = vals[0]
            prev_p, prev_v = vals[-2]
            cmp = compare(m, Decimal(str(latest_v)), Decimal(str(prev_v)))
            span = compare(m, Decimal(str(latest_v)), Decimal(str(first_v)))
            entry.update(prev=prev_v, prev_range=prev_p["range"], comparison=cmp,
                         first=first_v, first_range=first_p["range"], span=span)
            best = max(vals, key=lambda pv: pv[1]) if m.higher_is_better else min(vals, key=lambda pv: pv[1])
            worst = min(vals, key=lambda pv: pv[1]) if m.higher_is_better else max(vals, key=lambda pv: pv[1])
            entry.update(best=best[1], best_range=best[0]["range"], worst=worst[1], worst_range=worst[0]["range"])
        out.append(entry)
    return out


def latest_reviews(user, limit=12):
    from . import access

    return list(access.visible_reviews(user).select_related("metrics").order_by("-period__start_date")[:limit])


__all__ = ["series", "summarise", "latest_reviews", "WeeklyReview"]
