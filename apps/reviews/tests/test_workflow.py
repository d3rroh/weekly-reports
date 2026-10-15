from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse

from apps.core.models import AppSettings, AuditEvent
from apps.reviews.models import Commitment, ReportRevision, ReviewResponse, WeeklyMetrics, WeeklyReview
from apps.reviews.services import workflow

from .helpers import P_START, BaseTestCase, full_answers, make_review


class ReviewCreationTests(BaseTestCase):
    def test_create_draft_with_empty_metrics(self):
        review, created = workflow.create_review(self.reviewer, P_START)
        self.assertTrue(created)
        self.assertEqual(review.status, WeeklyReview.Status.DRAFT)
        self.assertIsNone(review.metrics.missed_calls)
        self.assertTrue(AuditEvent.objects.filter(action="review_created", review=review).exists())

    def test_no_duplicate_review_for_period(self):
        a, _ = workflow.create_review(self.reviewer, P_START)
        b, created = workflow.create_review(self.admin, P_START)
        self.assertFalse(created)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(WeeklyReview.objects.count(), 1)

    def test_new_review_view_snaps_any_date_to_period(self):
        self.login(self.reviewer)
        resp = self.client.post(reverse("reviews:new"), {"period_start": "2026-10-10"})  # a Saturday
        self.assertRedirects(resp, reverse("reviews:edit", args=["WR-2026-10-07"]))

    def test_previous_commitments_prefill_priorities(self):
        prev = make_review(self.reviewer, P_START - timedelta(days=7))
        workflow.commitment_service.save_definition(prev, 1, {"description": "Cut backlog", "success_criteria": "< 20"},
                                                    self.reviewer)
        review = make_review(self.reviewer, P_START)
        p = review.priorities.get()
        self.assertEqual(p.description, "Cut backlog")
        self.assertEqual(p.expected_outcome, "< 20")


class SaveDetailsTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.review = make_review(self.confidential)
        self.login(self.confidential)
        self.url = reverse("reviews:save", args=[self.review.code])

    def test_save_answers_and_metrics(self):
        resp = self.client.post(self.url, full_answers())
        self.assertEqual(resp.status_code, 302)
        m = WeeklyMetrics.objects.get(review=self.review)
        self.assertEqual(m.avg_response_minutes, Decimal("12.50"))
        self.assertEqual(m.missed_calls, 10)
        self.assertEqual(ReviewResponse.objects.filter(review=self.review).count(), 12)
        self.assertEqual(self.review.commitments.count(), 3)
        c = self.review.commitments.get(position=1)
        self.assertEqual(c.target_period.start_date, date(2026, 10, 14))
        self.assertEqual(c.due_date, date(2026, 10, 20))
        self.review = WeeklyReview.objects.get(pk=self.review.pk)
        status = workflow.question_status(self.review)
        self.assertTrue(all(status.values()), status)

    def test_partial_save_keeps_valid_fields_and_reports_errors(self):
        data = {"metrics-avg_response_minutes": "9", "metrics-sla_compliance_pct": "140",
                "metrics-missed_calls": "", "metrics-csat_pct": "", "q3-trends": "Rising volume"}
        resp = self.client.post(self.url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp.status_code, 422)
        payload = resp.json()
        self.assertIn("metrics-sla_compliance_pct", payload["errors"])
        m = WeeklyMetrics.objects.get(review=self.review)
        self.assertEqual(m.avg_response_minutes, Decimal("9"))
        self.assertIsNone(m.sla_compliance_pct)
        self.assertIsNone(m.missed_calls)  # blank stays missing, not zero
        self.assertEqual(self.review.responses.get(question=3).answer["trends"], "Rising volume")

    def test_editing_metrics_resets_comparison_acknowledgement(self):
        self.client.post(reverse("reviews:acknowledge", args=[self.review.code]), {"item": "comparison"})
        self.review.refresh_from_db()
        self.assertIsNotNone(self.review.comparison_reviewed_at)
        self.client.post(self.url, {"metrics-missed_calls": "4"})
        self.review.refresh_from_db()
        self.assertIsNone(self.review.comparison_reviewed_at)

    def test_reviewer_without_confidential_cannot_write_q7(self):
        self.client.force_login(self.reviewer)
        self.client.post(self.url, {"q7-observations": "Injected", "q3-trends": "ok"})
        self.assertFalse(self.review.responses.filter(question=7).exists())
        self.assertTrue(self.review.responses.filter(question=3).exists())

    def test_priority_details_without_description_rejected(self):
        resp = self.client.post(self.url, {"p2-actual_result": "Something"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn("p2-description", resp.json()["errors"])
        self.assertFalse(self.review.priorities.filter(position=2).exists())

    def test_commitment_due_date_cannot_precede_target_period(self):
        resp = self.client.post(self.url, {"c1-description": "X", "c1-due_date": "2026-10-01"},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn("c1-due_date", resp.json()["errors"])


class StatusWorkflowTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.review = make_review(self.confidential)
        self.login(self.confidential)
        self.status_url = reverse("reviews:status", args=[self.review.code])

    def complete(self):
        self.client.post(reverse("reviews:save", args=[self.review.code]), full_answers())
        for item in ("comparison", "comments"):
            self.client.post(reverse("reviews:acknowledge", args=[self.review.code]), {"item": item})
        self.client.get(reverse("reviews:present", args=[self.review.code]) + "?preview=1")
        self.review.refresh_from_db()

    def test_checklist_reaches_100_percent(self):
        self.assertLess(workflow.checklist(self.review)["percent"], 100)
        self.complete()
        state = workflow.checklist(self.review)
        self.assertTrue(state["complete"], [i.key for i in state["outstanding"]])

    def test_incomplete_submission_requires_confirmation(self):
        self.client.post(self.status_url, {"action": "submit"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "draft")
        self.client.post(self.status_url, {"action": "submit", "confirm_incomplete": "1"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "submitted")
        self.assertTrue(self.review.submitted_incomplete)

    def test_incomplete_submission_blocked_when_disabled(self):
        s = AppSettings.load()
        s.allow_incomplete_submission = False
        s.save()
        self.client.post(self.status_url, {"action": "submit", "confirm_incomplete": "1"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "draft")

    def test_full_lifecycle_and_snapshot(self):
        self.complete()
        self.client.post(self.status_url, {"action": "ready"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "ready")
        self.client.post(self.status_url, {"action": "submit"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "submitted")
        self.assertFalse(self.review.submitted_incomplete)
        rev = ReportRevision.objects.get(review=self.review)
        self.assertEqual(rev.snapshot["metrics"]["missed_calls"], "10")
        self.assertEqual(len(rev.snapshot["responses"]), 12)

    def test_submitted_report_is_read_only(self):
        self.complete()
        self.client.post(self.status_url, {"action": "submit"})
        resp = self.client.post(reverse("reviews:save", args=[self.review.code]), {"metrics-missed_calls": "999"})
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(WeeklyMetrics.objects.get(review=self.review).missed_calls, 10)

    def test_reopen_requires_permission_and_reason_and_preserves_history(self):
        self.complete()
        self.client.post(self.status_url, {"action": "submit"})
        resp = self.client.post(self.status_url, {"action": "reopen", "reason": "Fix"})
        self.assertEqual(resp.status_code, 403)  # lead lacks correction permission
        self.client.force_login(self.admin)
        self.client.post(self.status_url, {"action": "reopen", "reason": ""})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "submitted")
        self.client.post(self.status_url, {"action": "reopen", "reason": "CSAT figure was wrong"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, "draft")
        self.assertEqual(self.review.revisions.count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="review_reopened", review=self.review).exists())
        self.client.post(reverse("reviews:save", args=[self.review.code]), {"metrics-csat_pct": "89"})
        self.assertTrue(AuditEvent.objects.filter(action="review_corrected", review=self.review).exists())

    def test_creating_new_report_does_not_touch_previous(self):
        self.complete()
        self.client.post(self.status_url, {"action": "submit"})
        before = ReportRevision.objects.get(review=self.review).snapshot
        nxt = make_review(self.confidential, P_START + timedelta(days=7))
        self.client.post(reverse("reviews:save", args=[nxt.code]), {"metrics-missed_calls": "3"})
        self.review.refresh_from_db()
        self.assertEqual(self.review.metrics.missed_calls, 10)
        self.assertEqual(workflow.snapshot(self.review)["metrics"], before["metrics"])

    def test_comparison_uses_saved_previous_record(self):
        from apps.reviews.services.metrics import compare_reviews
        prev = make_review(self.confidential, P_START - timedelta(days=7), missed_calls=20,
                           sla_compliance_pct=Decimal("90"))
        WeeklyMetrics.objects.filter(review=self.review).update(missed_calls=15, sla_compliance_pct=Decimal("93"))
        self.review.refresh_from_db()
        cmps = {c.metric.key: c for c in compare_reviews(self.review, self.review.previous_review())}
        self.assertEqual(cmps["missed_calls"].absolute_change, -5)
        self.assertEqual(cmps["sla"].absolute_change, Decimal("3"))
        self.assertIsNone(cmps["csat"].previous)
        self.assertTrue(cmps["csat"].previous_exists)
        self.assertEqual(self.review.previous_review().pk, prev.pk)
