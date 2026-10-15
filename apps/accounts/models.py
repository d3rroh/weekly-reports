from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user with a role and explicit permission flags.

    Administrators implicitly hold every permission. Reviewers hold only the
    flags that an administrator grants them.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        REVIEWER = "reviewer", "Reviewer"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.REVIEWER)
    can_edit_reports = models.BooleanField(
        default=True, help_text="Create and edit draft weekly reviews, comments and commitments."
    )
    can_view_confidential = models.BooleanField(
        default=False,
        help_text="View team-performance answers (questions 7 and 8), internal-only comments by other users, "
        "and restricted reports.",
    )
    can_correct_submitted = models.BooleanField(
        default=False, help_text="Reopen and correct submitted reports."
    )

    class Meta:
        ordering = ["username"]

    def save(self, *args, **kwargs):
        if self.is_superuser:
            self.role = self.Role.ADMIN
        super().save(*args, **kwargs)

    # Effective permissions -------------------------------------------------
    @property
    def is_app_admin(self):
        return self.is_active and (self.is_superuser or self.role == self.Role.ADMIN)

    @property
    def may_edit_reports(self):
        return self.is_app_admin or (self.is_active and self.can_edit_reports)

    @property
    def may_view_confidential(self):
        return self.is_app_admin or (self.is_active and self.can_view_confidential)

    @property
    def may_correct_submitted(self):
        return self.is_app_admin or (self.is_active and self.can_correct_submitted)

    @property
    def display_name(self):
        return self.get_full_name() or self.username
