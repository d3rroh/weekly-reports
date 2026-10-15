from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.core.models import AuditEvent

from .helpers import BaseTestCase, make_review


class AuthenticationTests(BaseTestCase):
    def test_login_and_logout(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "reviewer", "password": "Str0ng-pass-123!"})
        self.assertRedirects(resp, reverse("dashboard"), fetch_redirect_response=False)
        self.assertTrue(AuditEvent.objects.filter(action="login").exists())
        self.client.post(reverse("accounts:logout"))
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp.url)

    def test_every_page_requires_login(self):
        review = make_review(self.reviewer)
        for url in [reverse("dashboard"), reverse("reviews:list"), reverse("reviews:history"),
                    reverse("reviews:trends"), reverse("reviews:comments"), reverse("reviews:commitments"),
                    reverse("settings"), reverse("reviews:edit", args=[review.code]),
                    reverse("reviews:present", args=[review.code]), reverse("reviews:pdf", args=[review.code])]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/accounts/login/", resp.url)

    @override_settings(LOGIN_THROTTLE_MAX_ATTEMPTS=3)
    def test_login_throttling(self):
        cache.clear()
        for _ in range(3):
            self.client.post(reverse("accounts:login"), {"username": "reviewer", "password": "wrong"})
        resp = self.client.post(reverse("accounts:login"), {"username": "reviewer", "password": "Str0ng-pass-123!"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Too many failed sign-in attempts")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditEvent.objects.filter(action="login_failed").exists())

    def test_password_change(self):
        self.login(self.reviewer)
        resp = self.client.post(reverse("accounts:password_change"), {
            "old_password": "Str0ng-pass-123!", "new_password1": "An0ther-Strong-pw", "new_password2": "An0ther-Strong-pw"})
        self.assertEqual(resp.status_code, 302)
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.check_password("An0ther-Strong-pw"))

    def test_password_reset_sends_email(self):
        from django.core import mail
        self.client.post(reverse("accounts:password_reset"), {"email": "reviewer@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/password/reset/", mail.outbox[0].body)

    def test_csrf_enforced(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        review = make_review(self.reviewer)
        resp = client.post(reverse("reviews:save", args=[review.code]), {"metrics-missed_calls": "1"})
        self.assertEqual(resp.status_code, 403)


class AuthorizationTests(BaseTestCase):
    def test_user_management_admin_only(self):
        self.login(self.reviewer)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(action="permission_denied").exists())
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_admin_creates_user(self):
        self.login(self.admin)
        resp = self.client.post(reverse("accounts:user_create"), {
            "username": "newbie", "email": "n@example.com", "role": "reviewer", "is_active": "on",
            "can_edit_reports": "on", "password1": "Very-secure-pw-1", "password2": "Very-secure-pw-1"})
        self.assertEqual(resp.status_code, 302)
        u = User.objects.get(username="newbie")
        self.assertTrue(u.check_password("Very-secure-pw-1"))
        self.assertFalse(u.may_view_confidential)

    def test_admin_cannot_demote_self(self):
        self.login(self.admin)
        self.client.post(reverse("accounts:user_edit", args=[self.admin.pk]), {
            "username": "admin", "role": "reviewer", "is_active": "on"})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "admin")

    def test_settings_change_admin_only(self):
        self.login(self.reviewer)
        self.assertEqual(self.client.post(reverse("settings"), {"business_timezone": "Asia/Tokyo"}).status_code, 403)
        self.login(self.admin)
        self.client.post(reverse("settings"), {"business_timezone": "Asia/Tokyo",
                                               "include_management_comments_default": "on"})
        from apps.core.models import AppSettings
        self.assertEqual(AppSettings.load().business_timezone, "Asia/Tokyo")

    def test_read_only_reviewer_cannot_edit(self):
        viewer = User.objects.create_user("viewer", password="x-Strong-pass-1", can_edit_reports=False)
        review = make_review(self.reviewer)
        self.login(viewer)
        self.assertEqual(self.client.get(reverse("reviews:edit", args=[review.code])).status_code, 200)
        self.assertEqual(self.client.post(reverse("reviews:save", args=[review.code]), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("reviews:new"), {"period_start": "2026-09-30"}).status_code, 403)

    def test_restricted_report_hidden(self):
        review = make_review(self.confidential)
        review.is_restricted = True
        review.save()
        self.login(self.reviewer)
        self.assertEqual(self.client.get(reverse("reviews:edit", args=[review.code])).status_code, 403)
        self.assertEqual(self.client.get(reverse("reviews:pdf", args=[review.code])).status_code, 403)
        self.assertNotContains(self.client.get(reverse("reviews:list")), review.code)
        self.login(self.confidential)
        self.assertEqual(self.client.get(reverse("reviews:edit", args=[review.code])).status_code, 200)

    def test_team_notes_restricted(self):
        review = make_review(self.confidential)
        review.responses.create(question=7, answer={"observations": "SECRET-PERF-NOTE"})
        self.login(self.reviewer)
        for url in (reverse("reviews:edit", args=[review.code]), reverse("reviews:present", args=[review.code]),
                    reverse("reviews:compare") + f"?a={review.code}&b={review.code}"):
            self.assertNotContains(self.client.get(url), "SECRET-PERF-NOTE")
        self.login(self.confidential)
        self.assertContains(self.client.get(reverse("reviews:edit", args=[review.code])), "SECRET-PERF-NOTE")

    def test_unknown_report_404(self):
        self.login(self.reviewer)
        self.assertEqual(self.client.get(reverse("reviews:edit", args=["WR-2026-10-08"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("reviews:edit", args=["nonsense"])).status_code, 404)

    def test_security_headers(self):
        self.login(self.reviewer)
        resp = self.client.get(reverse("dashboard"))
        self.assertIn("script-src 'self'", resp["Content-Security-Policy"])
        self.assertEqual(resp["X-Frame-Options"], "DENY")
