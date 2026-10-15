from datetime import date, datetime, timedelta
import zoneinfo

from django.test import SimpleTestCase, TestCase

from apps.core import periods
from apps.core.models import AppSettings
from apps.reviews.models import ReportingPeriod


class PeriodArithmeticTests(SimpleTestCase):
    def test_example_from_specification(self):
        # Presented Wednesday 14 Oct 2026 → covers 7–13 Oct; previous 30 Sep – 6 Oct.
        tz = zoneinfo.ZoneInfo("UTC")
        now = datetime(2026, 10, 14, 9, 0, tzinfo=tz)
        latest = periods.latest_completed_period(now, tz)
        self.assertEqual((latest.start, latest.end), (date(2026, 10, 7), date(2026, 10, 13)))
        self.assertEqual(latest.presentation_date, date(2026, 10, 14))
        self.assertEqual((latest.previous.start, latest.previous.end), (date(2026, 9, 30), date(2026, 10, 6)))
        self.assertEqual(periods.current_period(now, tz).start, date(2026, 10, 14))

    def test_every_day_maps_to_wednesday_start_and_seven_days(self):
        day = date(2026, 1, 1)
        for _ in range(800):
            b = periods.bounds_for_date(day)
            self.assertEqual(b.start.weekday(), 2)
            self.assertEqual(b.end.weekday(), 1)
            self.assertEqual((b.end - b.start).days, 6)
            self.assertTrue(b.start <= day <= b.end)
            self.assertEqual(b.previous.end + timedelta(days=1), b.start)
            day += timedelta(days=1)

    def test_tuesday_and_wednesday_boundaries(self):
        self.assertEqual(periods.bounds_for_date(date(2026, 10, 13)).start, date(2026, 10, 7))  # Tuesday
        self.assertEqual(periods.bounds_for_date(date(2026, 10, 14)).start, date(2026, 10, 14))  # Wednesday

    def test_month_end_transition(self):
        b = periods.bounds_for_date(date(2026, 10, 30))
        self.assertEqual((b.start, b.end), (date(2026, 10, 28), date(2026, 11, 3)))

    def test_year_end_transition(self):
        b = periods.bounds_for_date(date(2027, 1, 1))
        self.assertEqual((b.start, b.end), (date(2026, 12, 30), date(2027, 1, 5)))
        self.assertEqual(b.presentation_date, date(2027, 1, 6))
        self.assertEqual(b.previous.start, date(2026, 12, 23))

    def test_leap_year_february(self):
        b = periods.bounds_for_date(date(2028, 2, 29))
        self.assertEqual((b.start, b.end), (date(2028, 2, 23), date(2028, 2, 29)))

    def test_rejects_non_wednesday_start(self):
        with self.assertRaises(ValueError):
            periods.bounds_for_start(date(2026, 10, 8))

    def test_code_round_trip(self):
        self.assertEqual(periods.period_code(date(2026, 10, 7)), "WR-2026-10-07")
        self.assertEqual(periods.parse_code("WR-2026-10-07"), date(2026, 10, 7))
        with self.assertRaises(ValueError):
            periods.parse_code("WR-2026-10-08")

    def test_timestamp_boundaries_in_timezone(self):
        tz = zoneinfo.ZoneInfo("Africa/Nairobi")
        start, end = periods.period_datetimes(date(2026, 10, 7), date(2026, 10, 13), tz)
        self.assertEqual(start.isoformat(), "2026-10-07T00:00:00+03:00")
        self.assertEqual(end.isoformat(), "2026-10-13T23:59:59+03:00")

    def test_configured_timezone_changes_which_period_is_latest(self):
        # 22:30 UTC on Tuesday 13 Oct is already Wednesday 14 Oct in Nairobi (UTC+3).
        utc_now = datetime(2026, 10, 13, 22, 30, tzinfo=zoneinfo.ZoneInfo("UTC"))
        self.assertEqual(periods.latest_completed_period(utc_now, zoneinfo.ZoneInfo("UTC")).start, date(2026, 9, 30))
        self.assertEqual(periods.latest_completed_period(utc_now, zoneinfo.ZoneInfo("Africa/Nairobi")).start,
                         date(2026, 10, 7))

    def test_period_state(self):
        tz = zoneinfo.ZoneInfo("UTC")
        s, e = date(2026, 10, 7), date(2026, 10, 13)
        self.assertEqual(periods.period_state(s, e, datetime(2026, 10, 6, 23, 59, tzinfo=tz), tz), "future")
        self.assertEqual(periods.period_state(s, e, datetime(2026, 10, 7, 0, 0, tzinfo=tz), tz), "in_progress")
        self.assertEqual(periods.period_state(s, e, datetime(2026, 10, 13, 23, 59, 59, tzinfo=tz), tz), "in_progress")
        self.assertEqual(periods.period_state(s, e, datetime(2026, 10, 14, 0, 0, tzinfo=tz), tz), "completed")

    def test_daylight_saving_week_still_seven_calendar_days(self):
        tz = zoneinfo.ZoneInfo("Europe/London")  # clocks go back 25 Oct 2026
        b = periods.bounds_for_date(date(2026, 10, 25))
        start, end = b.datetimes(tz)
        self.assertEqual((b.end - b.start).days + 1, 7)
        self.assertEqual(start.utcoffset(), timedelta(hours=1))
        self.assertEqual(end.utcoffset(), timedelta(0))


class ReportingPeriodModelTests(TestCase):
    def setUp(self):
        AppSettings.objects.update_or_create(pk=1, defaults={"business_timezone": "UTC"})

    def test_for_start_is_idempotent_and_derives_fields(self):
        a = ReportingPeriod.for_start(date(2026, 10, 7))
        b = ReportingPeriod.for_start(date(2026, 10, 7))
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(a.end_date, date(2026, 10, 13))
        self.assertEqual(a.presentation_date, date(2026, 10, 14))
        self.assertEqual(a.code, "WR-2026-10-07")

    def test_database_rejects_period_not_seven_days(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportingPeriod.objects.bulk_create([ReportingPeriod(
                code="X", start_date=date(2026, 10, 14), end_date=date(2026, 10, 21),
                presentation_date=date(2026, 10, 22))])

    def test_timezone_change_preserves_existing_dates(self):
        p = ReportingPeriod.for_start(date(2026, 10, 7))
        s = AppSettings.load()
        s.business_timezone = "Pacific/Auckland"
        s.save()
        p.refresh_from_db()
        self.assertEqual((p.start_date, p.end_date), (date(2026, 10, 7), date(2026, 10, 13)))
