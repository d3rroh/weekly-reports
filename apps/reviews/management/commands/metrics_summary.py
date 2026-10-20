"""Print the Question 2 metrics comparison as a Markdown table.

    python manage.py metrics_summary                      # latest completed period
    python manage.py metrics_summary --period WR-2026-10-14

Values are read from saved WeeklyMetrics records only. Missing figures are
shown as "Not available" (or "No previous data"), never as zero.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core import periods
from apps.reviews.models import WeeklyReview
from apps.reviews.questions import QUESTIONS
from apps.reviews.services.metrics import compare_reviews


_LABEL_UNITS = {"min": " (min)", "%": " (%)"}


def _num(value):
    return f"{value.normalize():f}"


def _signed(value):
    return ("+" if value > 0 else "") + _num(value)


def _value_cell(comparison, value, missing_text):
    if value is None:
        return missing_text
    return _num(value) + (" %" if comparison.metric.is_percentage else "")


def _change_cell(c):
    if c.absolute_change is None:
        return "No previous data" if c.current is not None and not c.previous_exists else "Not available"
    if c.metric.is_percentage:
        return f"{_signed(c.absolute_change)} pp"
    unit = " min" if c.metric.unit == "min" else ""
    relative = f" ({_signed(c.relative_change_pct)} %)" if c.relative_change_pct is not None else ""
    return f"{_signed(c.absolute_change)}{unit}{relative}"


def render_summary(bounds):
    previous_bounds = bounds.previous
    reviews = {
        r.period.start_date: r
        for r in WeeklyReview.objects.select_related("period", "metrics").filter(
            period__start_date__in=[bounds.start, previous_bounds.start]
        )
    }
    current, previous = reviews.get(bounds.start), reviews.get(previous_bounds.start)
    question = next(q for q in QUESTIONS if q.number == 2)
    interpretation = ""
    if current is not None:
        response = current.responses.filter(question=2).first()
        interpretation = (response.answer.get("interpretation") or "") if response else ""

    lines = [
        f"**Q2. {question.text}**",
        "",
        f"Previous week: **{previous_bounds.code}** ({periods.format_range(previous_bounds.start, previous_bounds.end)})"
        f" · This week: **{bounds.code}** ({periods.format_range(bounds.start, bounds.end)})",
        "",
        "| Metric | Previous week | This week | Change | Trend |",
        "|---|---|---|---|---|",
    ]
    for c in compare_reviews(current, previous):
        prev_missing = "Not available" if previous is not None else "No previous data"
        lines.append(
            f"| {c.metric.label}{_LABEL_UNITS.get(c.metric.unit, '')} | {_value_cell(c, c.previous, prev_missing)} "
            f"| {_value_cell(c, c.current, 'Not available')} | {_change_cell(c)} | {c.trend_label} |"
        )
    lines += ["", "**Interpretation of the movement:**", interpretation.strip() or "_Not yet entered._"]
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Print the Question 2 metrics comparison (this week vs. previous week) as Markdown."

    def add_arguments(self, parser):
        parser.add_argument("--period", help="Reporting period code, e.g. WR-2026-10-14. "
                                             "Defaults to the latest completed period.")

    def handle(self, *args, **options):
        if options["period"]:
            try:
                bounds = periods.bounds_for_start(periods.parse_code(options["period"]))
            except ValueError as exc:
                raise CommandError(str(exc))
        else:
            bounds = periods.latest_completed_period()
        self.stdout.write(render_summary(bounds))
