from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.reviews.models import ReportingPeriod, ReviewResponse, WeeklyMetrics, WeeklyReview


class MetricsSummaryCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="author", password="x")

    def review(self, start, **metrics):
        review = WeeklyReview.objects.create(period=ReportingPeriod.for_start(start), author=self.user)
        if metrics:
            WeeklyMetrics.objects.create(review=review, **metrics)
        return review

    def run_command(self, *args):
        out = StringIO()
        call_command("metrics_summary", *args, stdout=out)
        return out.getvalue()

    def test_compares_with_previous_week(self):
        self.review(date(2026, 10, 7), avg_response_minutes=Decimal("15"), sla_compliance_pct=Decimal("90"),
                    missed_calls=40, csat_pct=Decimal("91"))
        current = self.review(date(2026, 10, 14), avg_response_minutes=Decimal("12.5"),
                              sla_compliance_pct=Decimal("94"), missed_calls=30, csat_pct=Decimal("88.5"))
        ReviewResponse.objects.create(review=current, question=2, answer={"interpretation": "Rota change helped."})

        out = self.run_command("--period", "WR-2026-10-14")

        self.assertIn("**WR-2026-10-07** (7 – 13 Oct 2026)", out)
        self.assertIn("| Average support response time (min) | 15 | 12.5 | -2.5 min (-16.7 %) | Improved |", out)
        self.assertIn("| SLA compliance (%) | 90 % | 94 % | +4 pp | Improved |", out)
        self.assertIn("| Total missed calls | 40 | 30 | -10 (-25 %) | Improved |", out)
        self.assertIn("| CSAT / customer satisfaction (%) | 91 % | 88.5 % | -2.5 pp | Deteriorated |", out)
        self.assertIn("Rota change helped.", out)

    def test_missing_values_are_not_zero(self):
        self.review(date(2026, 10, 14), missed_calls=0)

        out = self.run_command("--period", "WR-2026-10-14")

        self.assertIn("| Total missed calls | No previous data | 0 | No previous data | Not available |", out)
        self.assertIn("| SLA compliance (%) | No previous data | Not available | Not available | Not available |", out)
        self.assertIn("_Not yet entered._", out)

    def test_invalid_period_code(self):
        with self.assertRaises(CommandError):
            self.run_command("--period", "WR-2026-10-15")
