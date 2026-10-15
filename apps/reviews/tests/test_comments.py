from django.urls import reverse

from apps.reviews.models import Comment, CommentRevision
from apps.reviews.services import access, workflow

from .helpers import BaseTestCase, full_answers, make_review, timedelta, P_START


class CommentTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.review = make_review(self.reviewer)
        self.add_url = reverse("reviews:comment_add", args=[self.review.code])

    def test_create_comment_linked_to_metric(self):
        self.login(self.reviewer)
        resp = self.client.post(self.add_url, {"target": "metric:sla", "category": "sla", "visibility": "management",
                                               "text": "SLA dipped during the outage"})
        self.assertEqual(resp.status_code, 302)
        c = Comment.objects.get()
        self.assertEqual((c.target_type, c.metric, c.author), ("metric", "sla", self.reviewer))
        self.assertEqual(c.review.period.code, "WR-2026-10-07")

    def test_create_comment_linked_to_question_and_commitment(self):
        workflow.commitment_service.save_definition(self.review, 1, {"description": "Hire", "success_criteria": "1"},
                                                    self.reviewer)
        commitment = self.review.commitments.get()
        self.login(self.reviewer)
        self.client.post(self.add_url, {"target": "question:5", "category": "root_causes",
                                        "visibility": "internal", "text": "Same bug thrice"})
        self.client.post(self.add_url, {"target": f"commitment:{commitment.pk}", "category": "commitments",
                                        "visibility": "management", "text": "On track"})
        self.assertEqual(Comment.objects.filter(target_type="question", question=5).count(), 1)
        self.assertEqual(Comment.objects.get(target_type="commitment").commitment, commitment)

    def test_invalid_target_rejected(self):
        self.login(self.reviewer)
        resp = self.client.post(self.add_url, {"target": "metric:bogus", "category": "other",
                                               "visibility": "management", "text": "x"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(Comment.objects.count(), 0)

    def test_reviewer_cannot_link_to_confidential_question(self):
        self.login(self.reviewer)
        resp = self.client.post(self.add_url, {"target": "question:7", "category": "leadership",
                                               "visibility": "management", "text": "x"})
        self.assertEqual(resp.status_code, 422)

    def test_empty_text_rejected(self):
        self.login(self.reviewer)
        self.client.post(self.add_url, {"target": "report", "category": "overall", "visibility": "management",
                                        "text": "   "})
        self.assertEqual(Comment.objects.count(), 0)

    def test_edit_keeps_revision_history(self):
        c = self.add_comment(self.review, self.reviewer, text="Original")
        self.login(self.reviewer)
        self.client.post(reverse("reviews:comment_edit", args=[c.pk]),
                         {"target": "report", "category": "overall", "visibility": "management", "text": "Edited"})
        c.refresh_from_db()
        self.assertEqual(c.text, "Edited")
        self.assertEqual(CommentRevision.objects.get(comment=c).text, "Original")

    def test_other_reviewer_cannot_edit_or_delete(self):
        other = self.add_comment(self.review, self.confidential)
        self.login(self.reviewer)
        self.assertEqual(self.client.post(reverse("reviews:comment_edit", args=[other.pk]), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("reviews:comment_delete", args=[other.pk]),
                                          {"confirm": "1"}).status_code, 403)

    def test_delete_requires_confirmation_and_soft_deletes(self):
        c = self.add_comment(self.review, self.reviewer)
        self.login(self.reviewer)
        self.client.post(reverse("reviews:comment_delete", args=[c.pk]))
        c.refresh_from_db()
        self.assertIsNone(c.deleted_at)
        self.client.post(reverse("reviews:comment_delete", args=[c.pk]), {"confirm": "1"})
        c.refresh_from_db()
        self.assertIsNotNone(c.deleted_at)
        self.assertTrue(CommentRevision.objects.filter(comment=c, action="delete").exists())
        self.assertNotIn(c, access.visible_comments(self.admin))

    def test_internal_comments_hidden_from_other_non_confidential_users(self):
        internal = self.add_comment(self.review, self.confidential, visibility="internal", text="PRIVATE-NOTE")
        own_internal = self.add_comment(self.review, self.reviewer, visibility="internal", text="MY-NOTE")
        visible = set(access.visible_comments(self.reviewer, self.review.comments.all()))
        self.assertNotIn(internal, visible)
        self.assertIn(own_internal, visible)
        self.assertIn(internal, set(access.visible_comments(self.confidential, self.review.comments.all())))
        self.login(self.reviewer)
        page = self.client.get(reverse("reviews:edit", args=[self.review.code])).content.decode()
        self.assertNotIn("PRIVATE-NOTE", page)
        self.assertIn("MY-NOTE", page)
        listing = self.client.get(reverse("reviews:comments")).content.decode()
        self.assertNotIn("PRIVATE-NOTE", listing)

    def test_comments_on_confidential_questions_hidden(self):
        self.add_comment(self.review, self.confidential, target_type="question", question=7, text="Q7-MGMT")
        self.login(self.reviewer)
        page = self.client.get(reverse("reviews:edit", args=[self.review.code])).content.decode()
        self.assertNotIn("Q7-MGMT", page)

    def test_comments_not_copied_into_next_report(self):
        self.add_comment(self.review, self.reviewer, text="Week one")
        nxt = make_review(self.reviewer, P_START + timedelta(days=7))
        self.assertEqual(nxt.comments.count(), 0)

    def test_historical_comments_shown_on_reopened_report(self):
        self.add_comment(self.review, self.reviewer, text="HISTORIC-COMMENT")
        self.login(self.confidential)
        self.client.post(reverse("reviews:save", args=[self.review.code]), full_answers())
        self.client.post(reverse("reviews:status", args=[self.review.code]),
                         {"action": "submit", "confirm_incomplete": "1"})
        self.client.force_login(self.admin)
        self.client.post(reverse("reviews:status", args=[self.review.code]), {"action": "reopen", "reason": "x"})
        page = self.client.get(reverse("reviews:edit", args=[self.review.code])).content.decode()
        self.assertIn("HISTORIC-COMMENT", page)

    def test_comments_locked_on_submitted_report_except_for_correctors(self):
        c = self.add_comment(self.review, self.reviewer)
        self.review.status = "submitted"
        self.review.save()
        self.login(self.reviewer)
        self.assertEqual(self.client.post(self.add_url, {"target": "report", "category": "overall",
                                                         "visibility": "management", "text": "x"}).status_code, 403)
        self.assertEqual(self.client.post(reverse("reviews:comment_edit", args=[c.pk]), {}).status_code, 403)
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("reviews:comment_edit", args=[c.pk]),
                                {"target": "report", "category": "overall", "visibility": "management",
                                 "text": "Corrected"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(CommentRevision.objects.get(comment=c).review_status, "submitted")

    def test_comment_counts(self):
        self.add_comment(self.review, self.reviewer, target_type="metric", metric="csat")
        self.add_comment(self.review, self.reviewer, target_type="metric", metric="csat")
        self.add_comment(self.review, self.reviewer, target_type="question", question=4)
        counts = workflow.comment_counts(access.visible_comments(self.reviewer, self.review.comments.all()))
        self.assertEqual(counts["metric"]["csat"], 2)
        self.assertEqual(counts["question"][4], 1)
