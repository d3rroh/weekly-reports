from decimal import Decimal

from django.test import SimpleTestCase

from apps.reviews.forms import MetricsForm
from apps.reviews.services.metrics import METRICS_BY_KEY, Trend, compare

RT, SLA, MC, CSAT = (METRICS_BY_KEY[k] for k in ("response_time", "sla", "missed_calls", "csat"))


class ComparisonTests(SimpleTestCase):
    def test_response_time_decrease_is_improvement(self):
        c = compare(RT, Decimal("12.5"), Decimal("15"))
        self.assertEqual(c.absolute_change, Decimal("-2.5"))
        self.assertEqual(c.relative_change_pct, Decimal("-16.7"))
        self.assertEqual(c.direction, "down")
        self.assertEqual(c.trend, Trend.IMPROVED)

    def test_response_time_increase_is_deterioration(self):
        self.assertEqual(compare(RT, Decimal("20"), Decimal("15")).trend, Trend.DETERIORATED)

    def test_sla_percentage_points_and_relative_change(self):
        c = compare(SLA, Decimal("94"), Decimal("90"))
        self.assertEqual(c.absolute_change, Decimal("4"))  # percentage points
        self.assertEqual(c.change_unit, "pp")
        self.assertEqual(c.relative_change_pct, Decimal("4.4"))  # relative %
        self.assertEqual(c.trend, Trend.IMPROVED)

    def test_csat_drop_is_deterioration(self):
        c = compare(CSAT, Decimal("88.5"), Decimal("91"))
        self.assertEqual(c.absolute_change, Decimal("-2.5"))
        self.assertEqual(c.trend, Trend.DETERIORATED)

    def test_missed_calls(self):
        c = compare(MC, 30, 40)
        self.assertEqual(c.absolute_change, Decimal("-10"))
        self.assertEqual(c.relative_change_pct, Decimal("-25.0"))
        self.assertEqual(c.trend, Trend.IMPROVED)

    def test_zero_denominator_gives_no_percentage(self):
        c = compare(MC, 5, 0)
        self.assertEqual(c.absolute_change, Decimal("5"))
        self.assertIsNone(c.relative_change_pct)
        self.assertEqual(c.trend, Trend.DETERIORATED)

    def test_unchanged(self):
        c = compare(SLA, Decimal("95"), Decimal("95.00"))
        self.assertEqual(c.trend, Trend.UNCHANGED)
        self.assertEqual(c.direction, "flat")
        self.assertEqual(c.relative_change_pct, Decimal("0.0"))

    def test_missing_previous_is_not_zero(self):
        c = compare(MC, 12, None, previous_exists=False)
        self.assertIsNone(c.absolute_change)
        self.assertIsNone(c.relative_change_pct)
        self.assertEqual(c.trend, Trend.NOT_AVAILABLE)
        self.assertFalse(c.previous_exists)

    def test_missing_current(self):
        c = compare(CSAT, None, Decimal("90"))
        self.assertIsNone(c.absolute_change)
        self.assertEqual(c.trend, Trend.NOT_AVAILABLE)

    def test_zero_values_are_real_values(self):
        c = compare(MC, 0, 0)
        self.assertEqual(c.absolute_change, Decimal("0"))
        self.assertIsNone(c.relative_change_pct)
        self.assertEqual(c.trend, Trend.UNCHANGED)


class MetricValidationTests(SimpleTestCase):
    def form(self, **values):
        data = {f"metrics-{k}": v for k, v in values.items()}
        return MetricsForm(data, prefix="metrics")

    def test_valid_values(self):
        f = self.form(avg_response_minutes="3.75", sla_compliance_pct="100", missed_calls="0", csat_pct="0")
        self.assertTrue(f.is_valid(), f.errors)
        self.assertEqual(f.cleaned_data["avg_response_minutes"], Decimal("3.75"))
        self.assertEqual(f.cleaned_data["missed_calls"], 0)

    def test_blank_values_stay_missing(self):
        f = self.form(avg_response_minutes="", sla_compliance_pct="", missed_calls="", csat_pct="")
        self.assertTrue(f.is_valid())
        self.assertTrue(all(v is None for v in f.cleaned_data.values()))

    def test_out_of_range_rejected(self):
        f = self.form(avg_response_minutes="-1", sla_compliance_pct="100.5", missed_calls="-3", csat_pct="-0.1")
        self.assertFalse(f.is_valid())
        self.assertEqual(set(f.errors), {"avg_response_minutes", "sla_compliance_pct", "missed_calls", "csat_pct"})

    def test_missed_calls_must_be_whole_number(self):
        f = self.form(missed_calls="2.5")
        self.assertFalse(f.is_valid())
        self.assertIn("missed_calls", f.errors)

    def test_non_numeric_rejected(self):
        f = self.form(sla_compliance_pct="ninety")
        self.assertFalse(f.is_valid())
