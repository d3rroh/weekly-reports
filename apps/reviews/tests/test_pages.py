"""Render every page to catch template errors and empty-state handling."""
from datetime import timedelta

from django.urls import reverse

from apps.reviews.services import commitments as svc

from .helpers import P_START, BaseTestCase, full_answers, make_review


class EmptyStateTests(BaseTestCase):
    def test_dashboard_empty_state_has_no_fabricated_figures(self):
        self.login(self.reviewer)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "No reports yet")
        self.assertNotContains(resp, "chart-data")

    def test_pages_render_with_no_data(self):
        self.login(self.admin)
        for name in ("dashboard", "reviews:list", "reviews:new", "reviews:history", "reviews:compare",
                     "reviews:trends", "reviews:comments", "reviews:commitments", "settings", "audit_log",
                     "accounts:user_list", "accounts:user_create", "accounts:password_change"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class PopulatedPageTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.prev = make_review(self.admin, P_START - timedelta(days=7))
        self.login(self.admin)
        self.client.post(reverse("reviews:save", args=[self.prev.code]), full_answers())
        self.client.post(reverse("reviews:status", args=[self.prev.code]),
                         {"action": "submit", "confirm_incomplete": "1"})
        self.review = make_review(self.admin)
        self.client.post(reverse("reviews:save", args=[self.review.code]), full_answers())
        self.add_comment(self.review, self.admin, text="hello")

    def test_all_pages_render(self):
        c = self.prev.commitments.first()
        urls = [
            reverse("dashboard"), reverse("reviews:list"), reverse("reviews:history"),
            reverse("reviews:history") + "?status=submitted&from=2026-01-01&to=2026-12-31&date=2026-10-10",
            reverse("reviews:compare") + f"?a={self.review.code}",
            reverse("reviews:compare") + f"?a={self.prev.code}&b={self.review.code}",
            reverse("reviews:trends"), reverse("reviews:trends") + "?range=custom&start=2026-01-01&end=2026-12-31",
            reverse("reviews:trends_data"), reverse("reviews:comments") + "?category=overall",
            reverse("reviews:commitments"), reverse("reviews:commitments") + "?view=all",
            reverse("reviews:commitment_detail", args=[c.pk]),
            reverse("reviews:edit", args=[self.review.code]), reverse("reviews:edit", args=[self.prev.code]),
            reverse("reviews:present", args=[self.review.code]),
            reverse("reviews:present", args=[self.prev.code]) + "?comments=0&leadership=0",
            reverse("reviews:revision", args=[self.prev.code, 1]),
            reverse("reviews:comment_edit", args=[self.review.comments.first().pk]),
            reverse("settings") , reverse("audit_log"),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)

    def test_editor_shows_follow_through_and_comparison(self):
        resp = self.client.get(reverse("reviews:edit", args=[self.review.code]))
        self.assertContains(resp, "Follow-through on previous commitments")
        self.assertContains(resp, "Outcome 1")
        self.assertContains(resp, "No change")  # identical figures both weeks

    def test_trends_series_uses_saved_records_with_gaps(self):
        resp = self.client.get(reverse("reviews:trends_data") + "?range=8")
        points = resp.json()["points"]
        self.assertEqual(len(points), 8)
        with_reports = [p for p in points if p["has_report"]]
        self.assertEqual({p["code"] for p in with_reports}, {self.prev.code, self.review.code})
        self.assertTrue(all(v is None for p in points if not p["has_report"] for v in p["values"].values()))
        self.assertEqual(with_reports[-1]["values"]["missed_calls"], 10)

    def test_dashboard_with_data(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "chart-data")
        self.assertContains(resp, "Preparation checklist")

    def test_historical_report_unchanged_after_commitment_update(self):
        c = self.prev.commitments.get(position=1)
        svc.update_progress(c, self.admin, status="completed", completion_evidence="Proof")
        page = self.client.get(reverse("reviews:present", args=[self.review.code])).content.decode()
        self.assertIn("Completed", page)
