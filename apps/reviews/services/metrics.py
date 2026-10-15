"""Metric definitions and period-over-period comparison logic.

All comparisons are computed from saved records. Missing values are never
treated as zero, and no percentage change is computed against a zero or
missing denominator.
"""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class MetricDef:
    key: str
    field: str
    label: str
    short_label: str
    unit: str  # "min" | "%" | "calls"
    higher_is_better: bool
    is_percentage: bool  # differences expressed in percentage points
    comment_category: str


METRICS = [
    MetricDef("response_time", "avg_response_minutes", "Average support response time", "Response time",
              "min", False, False, "response_time"),
    MetricDef("sla", "sla_compliance_pct", "SLA compliance", "SLA compliance", "%", True, True, "sla"),
    MetricDef("missed_calls", "missed_calls", "Total missed calls", "Missed calls", "calls", False, False,
              "missed_calls"),
    MetricDef("csat", "csat_pct", "CSAT / customer satisfaction", "CSAT", "%", True, True, "csat"),
]
METRICS_BY_KEY = {m.key: m for m in METRICS}
METRIC_CHOICES = [(m.key, m.label) for m in METRICS]


class Trend:
    IMPROVED = "improved"
    DETERIORATED = "deteriorated"
    UNCHANGED = "unchanged"
    NOT_AVAILABLE = "not_available"

    LABELS = {
        IMPROVED: "Improved",
        DETERIORATED: "Deteriorated",
        UNCHANGED: "No change",
        NOT_AVAILABLE: "Not available",
    }


@dataclass
class Comparison:
    metric: MetricDef
    current: Decimal | None
    previous: Decimal | None
    previous_exists: bool  # a previous report exists at all
    absolute_change: Decimal | None
    relative_change_pct: Decimal | None
    direction: str | None  # "up" | "down" | "flat" | None
    trend: str

    @property
    def trend_label(self):
        return Trend.LABELS[self.trend]

    @property
    def change_unit(self):
        return "pp" if self.metric.is_percentage else self.metric.unit

    @property
    def previous_display_missing(self):
        """Text to show when there is no previous value."""
        return "No previous data"

    def as_dict(self):
        def f(v):
            return None if v is None else float(v)

        return {
            "key": self.metric.key,
            "label": self.metric.label,
            "unit": self.metric.unit,
            "current": f(self.current),
            "previous": f(self.previous),
            "absolute_change": f(self.absolute_change),
            "relative_change_pct": f(self.relative_change_pct),
            "direction": self.direction,
            "trend": self.trend,
        }


def _dec(value):
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def compare(metric: MetricDef, current, previous, previous_exists=True) -> Comparison:
    current, previous = _dec(current), _dec(previous)
    absolute = relative = direction = None
    trend = Trend.NOT_AVAILABLE
    if current is not None and previous is not None:
        absolute = current - previous
        if previous != 0:
            relative = (absolute / previous * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if absolute > 0:
            direction = "up"
        elif absolute < 0:
            direction = "down"
        else:
            direction = "flat"
        if absolute == 0:
            trend = Trend.UNCHANGED
        elif (absolute > 0) == metric.higher_is_better:
            trend = Trend.IMPROVED
        else:
            trend = Trend.DETERIORATED
    return Comparison(metric, current, previous, previous_exists, absolute, relative, direction, trend)


def metric_values(metrics_obj):
    """Dict of metric key -> value (or None) from a WeeklyMetrics instance or None."""
    return {m.key: (getattr(metrics_obj, m.field) if metrics_obj is not None else None) for m in METRICS}


def compare_reviews(current_review, previous_review):
    """Comparisons for every metric between two reviews (either may be None)."""
    cur = metric_values(getattr(current_review, "metrics", None) if current_review else None)
    prev = metric_values(getattr(previous_review, "metrics", None) if previous_review else None)
    return [compare(m, cur[m.key], prev[m.key], previous_exists=previous_review is not None) for m in METRICS]


def metrics_complete(metrics_obj):
    return metrics_obj is not None and all(v is not None for v in metric_values(metrics_obj).values())
