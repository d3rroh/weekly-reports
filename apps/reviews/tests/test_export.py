from datetime import timedelta
from io import BytesIO

from django.urls import reverse
from pypdf import PdfReader

from apps.reviews.models import WeeklyMetrics
from apps.reviews.services import presentation
from apps.reviews.views.reviews import render_pdf_html

from .helpers import P_START, BaseTestCase, Decimal, full_answers, make_review


class ExportTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.prev = make_review(self.confidential, P_START - timedelta(days=7), avg_response_minutes=Decimal("15"),
                                sla_compliance_pct=Decimal("90"), missed_calls=40, csat_pct=Decimal("88"))
        self.review = make_review(self.confidential)
        self.login(self.confidential)
        self.client.post(reverse("reviews:save", args=[self.review.code]), full_answers())
        self.add_comment(self.review, self.confidential, text="MGMT-VISIBLE-COMMENT")
        self.add_comment(self.review, self.confidential, visibility="internal", text="INTERNAL-ONLY-NOTE")
        self.add_comment(self.prev, self.confidential, text="OTHER-WEEK-COMMENT")
        self.review.refresh_from_db()

    def pdf_text(self, query=""):
        resp = self.client.get(reverse("reviews:pdf", args=[self.review.code]) + query)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        reader = PdfReader(BytesIO(resp.content))
        return " ".join(page.extract_text() for page in reader.pages)

    def test_pdf_has_correct_period_and_saved_values(self):
        text = self.pdf_text()
        self.assertIn("7 – 13 Oct 2026", text)
        self.assertIn("Presented Wednesday 14 October 2026", text)
        self.assertIn("12.5 min", text)   # current response time
        self.assertIn("15.0 min", text)   # previous response time
        self.assertIn("94.0%", text)
        self.assertIn("91.5%", text)

    def test_pdf_includes_management_and_excludes_internal_comments(self):
        text = self.pdf_text()
        self.assertIn("MGMT-VISIBLE-COMMENT", text)
        self.assertNotIn("INTERNAL-ONLY-NOTE", text)
        self.assertNotIn("OTHER-WEEK-COMMENT", text)

    def test_comments_can_be_hidden_from_export(self):
        text = self.pdf_text("?comments=0")
        self.assertNotIn("MGMT-VISIBLE-COMMENT", text)

    def test_internal_excluded_even_for_admin_and_html_presentation(self):
        self.login(self.admin)
        html = render_pdf_html(self.review, self.admin)
        self.assertNotIn("INTERNAL-ONLY-NOTE", html)
        page = self.client.get(reverse("reviews:present", args=[self.review.code])).content.decode()
        self.assertNotIn("INTERNAL-ONLY-NOTE", page)
        self.assertIn("MGMT-VISIBLE-COMMENT", page)

    def test_leadership_section_respects_permissions(self):
        ctx = presentation.build_context(self.review, self.reviewer)
        self.assertFalse(ctx["include_leadership"])
        html = render_pdf_html(self.review, self.reviewer, include_leadership=True)
        self.assertNotIn("Answer 7 observations", html)
        html = render_pdf_html(self.review, self.confidential)
        self.assertIn("Answer 7 observations", html)

    def test_export_reflects_saved_data_after_change(self):
        WeeklyMetrics.objects.filter(review=self.review).update(missed_calls=77)
        self.assertIn("77", render_pdf_html(self.review, self.confidential))

    def test_incomplete_report_labelled(self):
        WeeklyMetrics.objects.filter(review=self.review).update(csat_pct=None)
        html = render_pdf_html(self.review, self.confidential)
        self.assertIn("INCOMPLETE", html)

    def test_export_is_audited(self):
        from apps.core.models import AuditEvent
        self.pdf_text()
        self.assertTrue(AuditEvent.objects.filter(action="report_exported", review=self.review).exists())
