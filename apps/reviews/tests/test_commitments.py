from datetime import date, timedelta

from django.urls import reverse

from apps.reviews.models import Commitment, CommitmentHistory, WeeklyMetrics
from apps.reviews.services import commitments as svc
from apps.reviews.services import workflow

from .helpers import P_START, BaseTestCase, make_review


class CommitmentTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.prev = make_review(self.reviewer, P_START - timedelta(days=7))
        for i in (1, 2, 3):
            svc.save_definition(self.prev, i, {"description": f"Outcome {i}", "success_criteria": f"KPI {i}"},
                                self.reviewer)
        self.c1 = self.prev.commitments.get(position=1)
        self.review = make_review(self.reviewer)

    def test_definition_targets_next_period(self):
        self.assertEqual(self.c1.target_period.start_date, P_START)
        self.assertEqual(self.c1.due_date, date(2026, 10, 13))
        self.assertEqual(self.c1.history.get().to_status, "not_started")

    def test_carry_forward_into_next_report(self):
        carried = svc.previous_commitments(self.review)
        self.assertEqual({c.description for c in carried}, {"Outcome 1", "Outcome 2", "Outcome 3"})

    def test_open_older_commitments_keep_carrying_forward(self):
        svc.update_progress(self.c1, self.reviewer, status="completed", completion_evidence="Dashboard link")
        later = make_review(self.reviewer, P_START + timedelta(days=7))
        carried = {c.description for c in svc.previous_commitments(later)}
        self.assertEqual(carried, {"Outcome 2", "Outcome 3"})  # completed one drops off; open ones remain

    def test_status_update_records_history(self):
        svc.update_progress(self.c1, self.reviewer, status="in_progress", progress_notes="Started", review=self.review)
        svc.update_progress(self.c1, self.reviewer, status="blocked", incomplete_explanation="Waiting on vendor")
        hist = list(CommitmentHistory.objects.filter(commitment=self.c1).order_by("changed_at", "id"))
        self.assertEqual([h.to_status for h in hist], ["not_started", "in_progress", "blocked"])
        self.assertEqual(hist[1].review, self.review)

    def test_completion_requires_evidence(self):
        with self.assertRaises(svc.CommitmentUpdateError):
            svc.update_progress(self.c1, self.reviewer, status="completed")
        c = svc.update_progress(self.c1, self.reviewer, status="completed", completion_evidence="Report #42")
        self.assertEqual(c.status, "completed")
        self.assertIsNotNone(c.completed_on)

    def test_blocked_requires_explanation(self):
        with self.assertRaises(svc.CommitmentUpdateError):
            svc.update_progress(self.c1, self.reviewer, status="blocked")

    def test_reopening_completed_clears_completion_date(self):
        svc.update_progress(self.c1, self.reviewer, status="completed", completion_evidence="x")
        c = svc.update_progress(self.c1, self.reviewer, status="in_progress")
        self.assertIsNone(c.completed_on)

    def test_overdue_detection(self):
        self.assertTrue(self.c1.is_overdue(today=date(2026, 10, 14)))
        self.assertFalse(self.c1.is_overdue(today=date(2026, 10, 13)))
        overdue = svc.outstanding_commitments(today=date(2026, 10, 20))
        self.assertEqual(len(overdue), 3)

    def test_metric_improvement_never_completes_commitment(self):
        WeeklyMetrics.objects.filter(review=self.review).update(missed_calls=0, csat_pct=100)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, "not_started")

    def test_update_view_from_report(self):
        self.login(self.reviewer)
        resp = self.client.post(reverse("reviews:commitment_update", args=[self.c1.pk]), {
            "review": self.review.code, f"cp{self.c1.pk}-status": "completed",
            f"cp{self.c1.pk}-completion_evidence": "https://example.com/proof", f"cp{self.c1.pk}-note": "Done",
        })
        self.assertRedirects(resp, reverse("reviews:edit", args=[self.review.code]) + "#follow-through",
                             fetch_redirect_response=False)
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, "completed")
        self.assertEqual(self.c1.history.first().review, self.review)

    def test_status_as_of_for_submitted_history(self):
        from django.utils import timezone
        moment = timezone.now()
        CommitmentHistory.objects.filter(commitment=self.c1).update(changed_at=moment - timedelta(hours=1))
        h = CommitmentHistory.objects.create(commitment=self.c1, from_status="not_started", to_status="completed")
        CommitmentHistory.objects.filter(pk=h.pk).update(changed_at=moment + timedelta(hours=1))
        self.assertEqual(self.c1.status_as_of(moment), "not_started")

    def test_checklist_requires_previous_commitments_review(self):
        item = {i.key: i for i in workflow.checklist(self.review)["items"]}["prev_commitments"]
        self.assertFalse(item.done)
        self.login(self.reviewer)
        self.client.post(reverse("reviews:acknowledge", args=[self.review.code]), {"item": "prev_commitments"})
        self.review.refresh_from_db()
        item = {i.key: i for i in workflow.checklist(self.review)["items"]}["prev_commitments"]
        self.assertTrue(item.done)

    def test_cannot_remove_commitment_with_progress(self):
        svc.update_progress(self.c1, self.reviewer, status="in_progress")
        self.login(self.reviewer)
        resp = self.client.post(reverse("reviews:save", args=[self.prev.code]),
                                {"c1-description": "", "c1-success_criteria": ""},
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn("c1-description", resp.json()["errors"])
        self.assertTrue(Commitment.objects.filter(pk=self.c1.pk).exists())
