"""Reporting-period service.

This is the single source of truth for reporting-calendar arithmetic.
A reporting period runs Wednesday 00:00 to Tuesday 23:59:59 (inclusive) in
the configured business timezone, and is presented on the following
Wednesday. Every period contains exactly seven calendar days.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import zoneinfo

from django.utils import timezone

WEDNESDAY = 2  # date.weekday() value
PERIOD_DAYS = 7


def business_tz():
    from .models import AppSettings

    return zoneinfo.ZoneInfo(AppSettings.load().business_timezone)


def local_now(tz=None):
    return timezone.now().astimezone(tz or business_tz())


def local_today(tz=None):
    return local_now(tz).date()


def period_start_for(day: date) -> date:
    """Wednesday that starts the reporting period containing `day`."""
    return day - timedelta(days=(day.weekday() - WEDNESDAY) % 7)


@dataclass(frozen=True)
class PeriodBounds:
    start: date
    end: date

    @property
    def presentation_date(self):
        return self.end + timedelta(days=1)

    @property
    def code(self):
        return period_code(self.start)

    @property
    def previous(self):
        return bounds_for_start(self.start - timedelta(days=PERIOD_DAYS))

    @property
    def next(self):
        return bounds_for_start(self.start + timedelta(days=PERIOD_DAYS))

    def datetimes(self, tz=None):
        return period_datetimes(self.start, self.end, tz)


def bounds_for_start(start: date) -> PeriodBounds:
    if start.weekday() != WEDNESDAY:
        raise ValueError(f"Reporting periods must start on a Wednesday ({start} is not).")
    return PeriodBounds(start, start + timedelta(days=PERIOD_DAYS - 1))


def bounds_for_date(day: date) -> PeriodBounds:
    return bounds_for_start(period_start_for(day))


def period_code(start: date) -> str:
    """Stable identifier, e.g. WR-2026-10-07."""
    return f"WR-{start.isoformat()}"


def parse_code(code: str) -> date:
    if not code.startswith("WR-"):
        raise ValueError("Invalid reporting period identifier.")
    start = date.fromisoformat(code[3:])
    bounds_for_start(start)
    return start


def period_datetimes(start: date, end: date, tz=None):
    """Aware datetimes for the inclusive start and end of a period."""
    tz = tz or business_tz()
    return (
        datetime.combine(start, time.min, tzinfo=tz),
        datetime.combine(end, time(23, 59, 59), tzinfo=tz),
    )


def current_period(now=None, tz=None) -> PeriodBounds:
    """The (in-progress) period containing today."""
    today = (now.astimezone(tz or business_tz()).date() if now else local_today(tz))
    return bounds_for_date(today)


def latest_completed_period(now=None, tz=None) -> PeriodBounds:
    """The most recent fully elapsed period — the one presented this Wednesday."""
    return current_period(now, tz).previous


class PeriodState:
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"
    FUTURE = "future"

    LABELS = {COMPLETED: "Completed", IN_PROGRESS: "In progress", FUTURE: "Future"}


def period_state(start: date, end: date, now=None, tz=None) -> str:
    tz = tz or business_tz()
    now = (now or timezone.now()).astimezone(tz)
    start_dt, end_dt = period_datetimes(start, end, tz)
    if now > end_dt:
        return PeriodState.COMPLETED
    if now >= start_dt:
        return PeriodState.IN_PROGRESS
    return PeriodState.FUTURE


def recent_period_choices(count_back=12, count_forward=2, now=None, tz=None):
    """Periods offered when creating a review, most recent completed first."""
    latest = latest_completed_period(now, tz)
    starts = [latest.start + timedelta(days=PERIOD_DAYS * i) for i in range(count_forward + 1, -count_back, -1)]
    return [bounds_for_start(s) for s in starts]


def format_range(start: date, end: date) -> str:
    if start.year != end.year:
        return f"{start:%-d %b %Y} – {end:%-d %b %Y}"
    if start.month != end.month:
        return f"{start:%-d %b} – {end:%-d %b %Y}"
    return f"{start:%-d} – {end:%-d %b %Y}"
