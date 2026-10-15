from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from apps.core import periods

from .questions import QUESTION_CHOICES

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Reporting periods
# ---------------------------------------------------------------------------
class ReportingPeriod(models.Model):
    code = models.CharField(max_length=20, unique=True, help_text="Stable identifier, e.g. WR-2026-10-07.")
    start_date = models.DateField(unique=True)
    end_date = models.DateField(unique=True)
    presentation_date = models.DateField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date=F("start_date") + timedelta(days=6)),
                name="period_exactly_seven_days",
            ),
            models.CheckConstraint(
                condition=Q(presentation_date=F("end_date") + timedelta(days=1)),
                name="period_presented_day_after_end",
            ),
        ]

    def __str__(self):
        return f"{self.code} ({self.label})"

    def clean(self):
        if self.start_date and self.start_date.weekday() != periods.WEDNESDAY:
            raise ValidationError("Reporting periods must start on a Wednesday.")

    def save(self, *args, **kwargs):
        bounds = periods.bounds_for_start(self.start_date)
        self.end_date = bounds.end
        self.presentation_date = bounds.presentation_date
        self.code = bounds.code
        super().save(*args, **kwargs)

    @classmethod
    def for_start(cls, start):
        """Get or create the period starting on `start` (a Wednesday)."""
        bounds = periods.bounds_for_start(start)
        obj, _ = cls.objects.get_or_create(
            start_date=bounds.start,
            defaults={"end_date": bounds.end, "presentation_date": bounds.presentation_date, "code": bounds.code},
        )
        return obj

    @property
    def bounds(self):
        return periods.PeriodBounds(self.start_date, self.end_date)

    @property
    def label(self):
        return periods.format_range(self.start_date, self.end_date)

    @property
    def previous_bounds(self):
        return self.bounds.previous

    @property
    def state(self):
        return periods.period_state(self.start_date, self.end_date)

    @property
    def state_label(self):
        return periods.PeriodState.LABELS[self.state]

    @property
    def is_complete(self):
        return self.state == periods.PeriodState.COMPLETED


# ---------------------------------------------------------------------------
# Weekly reviews
# ---------------------------------------------------------------------------
class WeeklyReview(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        READY = "ready", "Ready for Review"
        SUBMITTED = "submitted", "Submitted"

    period = models.OneToOneField(ReportingPeriod, on_delete=models.PROTECT, related_name="review")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="authored_reviews")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    executive_summary = models.TextField(blank=True, default="")
    is_restricted = models.BooleanField(
        default=False, help_text="Only users with confidential access can open this report."
    )
    include_management_comments = models.BooleanField(default=True)

    # Checklist acknowledgements
    comparison_reviewed_at = models.DateTimeField(null=True, blank=True)
    previous_commitments_reviewed_at = models.DateTimeField(null=True, blank=True)
    comments_reviewed_at = models.DateTimeField(null=True, blank=True)
    preview_checked_at = models.DateTimeField(null=True, blank=True)

    ready_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_incomplete = models.BooleanField(default=False)
    reopened_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-period__start_date"]

    def __str__(self):
        return f"Weekly review {self.period.code}"

    @property
    def code(self):
        return self.period.code

    @property
    def is_submitted(self):
        return self.status == self.Status.SUBMITTED

    def previous_review(self):
        return (
            WeeklyReview.objects.select_related("period", "metrics")
            .filter(period__start_date=self.period.start_date - timedelta(days=7))
            .first()
        )


class WeeklyMetrics(models.Model):
    """Manually entered figures. NULL means 'not entered' — never zero."""

    review = models.OneToOneField(WeeklyReview, on_delete=models.CASCADE, related_name="metrics")
    avg_response_minutes = models.DecimalField(
        "Average support response time (minutes)", max_digits=9, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    sla_compliance_pct = models.DecimalField(
        "SLA compliance (%)", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    missed_calls = models.PositiveIntegerField("Total missed calls", null=True, blank=True)
    csat_pct = models.DecimalField(
        "CSAT (%)", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "weekly metrics"
        constraints = [
            models.CheckConstraint(condition=Q(avg_response_minutes__gte=0) | Q(avg_response_minutes__isnull=True),
                                   name="metrics_response_non_negative"),
            models.CheckConstraint(condition=Q(sla_compliance_pct__gte=0, sla_compliance_pct__lte=100)
                                   | Q(sla_compliance_pct__isnull=True), name="metrics_sla_range"),
            models.CheckConstraint(condition=Q(csat_pct__gte=0, csat_pct__lte=100) | Q(csat_pct__isnull=True),
                                   name="metrics_csat_range"),
        ]

    def __str__(self):
        return f"Metrics for {self.review.period.code}"


# ---------------------------------------------------------------------------
# Question responses
# ---------------------------------------------------------------------------
class ReviewResponse(models.Model):
    """Answer to one of the 12 management questions.

    `answer` holds the structured sub-fields defined for the question in
    questions.py (e.g. {"friction_points": "...", "impact": "..."}).
    """

    review = models.ForeignKey(WeeklyReview, on_delete=models.CASCADE, related_name="responses")
    question = models.PositiveSmallIntegerField(choices=QUESTION_CHOICES)
    answer = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["question"]
        constraints = [
            models.UniqueConstraint(fields=["review", "question"], name="one_response_per_question"),
            models.CheckConstraint(condition=Q(question__gte=1, question__lte=12), name="question_1_to_12"),
        ]

    def __str__(self):
        return f"Q{self.question} for {self.review.period.code}"


class Priority(models.Model):
    """Question 1: last week's top priorities and what shipped."""

    class Delivery(models.TextChoices):
        SHIPPED = "shipped", "Shipped"
        PARTIAL = "partial", "Partially shipped"
        NOT_SHIPPED = "not_shipped", "Not shipped"
        DEFERRED = "deferred", "Deferred"

    review = models.ForeignKey(WeeklyReview, on_delete=models.CASCADE, related_name="priorities")
    position = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])
    description = models.CharField(max_length=500)
    expected_outcome = models.TextField(blank=True, default="")
    actual_result = models.TextField(blank=True, default="")
    delivery_status = models.CharField(max_length=20, choices=Delivery.choices, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    source_commitment = models.ForeignKey(
        "Commitment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["position"]
        verbose_name_plural = "priorities"
        constraints = [
            models.UniqueConstraint(fields=["review", "position"], name="one_priority_per_position"),
            models.CheckConstraint(condition=Q(position__gte=1, position__lte=3), name="priority_position_1_to_3"),
        ]

    def __str__(self):
        return f"Priority {self.position}: {self.description[:60]}"


# ---------------------------------------------------------------------------
# Commitments (Question 10) and tracking history
# ---------------------------------------------------------------------------
class Commitment(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        BLOCKED = "blocked", "Blocked"

    source_review = models.ForeignKey(WeeklyReview, on_delete=models.PROTECT, related_name="commitments")
    position = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(3)])
    description = models.CharField("Outcome", max_length=500)
    success_criteria = models.TextField("Measurable success criteria")
    owner = models.CharField(max_length=150, blank=True, default="")
    target_period = models.ForeignKey(ReportingPeriod, on_delete=models.PROTECT, related_name="targeted_commitments")
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_STARTED, db_index=True)
    progress_notes = models.TextField(blank=True, default="")
    incomplete_explanation = models.TextField(blank=True, default="")
    completion_evidence = models.TextField(blank=True, default="")
    completed_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["source_review__period__start_date", "position"]
        constraints = [
            models.UniqueConstraint(fields=["source_review", "position"], name="one_commitment_per_position"),
            models.CheckConstraint(condition=Q(position__gte=1, position__lte=3), name="commitment_position_1_to_3"),
            models.CheckConstraint(
                condition=~Q(status="completed") | Q(completed_on__isnull=False),
                name="completed_commitment_has_date",
            ),
        ]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return f"{self.source_review.period.code} outcome {self.position}: {self.description[:60]}"

    @property
    def is_open(self):
        return self.status != self.Status.COMPLETED

    def is_overdue(self, today=None):
        today = today or periods.local_today()
        return self.is_open and self.due_date < today

    def status_as_of(self, moment):
        """Status recorded in history at `moment` (used for submitted reports)."""
        entry = self.history.filter(changed_at__lte=moment).order_by("-changed_at", "-id").first()
        return entry.to_status if entry else self.Status.NOT_STARTED


class CommitmentHistory(models.Model):
    commitment = models.ForeignKey(Commitment, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, choices=Commitment.Status.choices, blank=True, default="")
    to_status = models.CharField(max_length=20, choices=Commitment.Status.choices)
    note = models.TextField(blank=True, default="")
    review = models.ForeignKey(
        WeeklyReview, null=True, blank=True, on_delete=models.SET_NULL, related_name="commitment_updates",
        help_text="The weekly review in which this update was recorded, if any.",
    )
    changed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-changed_at", "-id"]
        verbose_name_plural = "commitment history"

    @property
    def from_label(self):
        return Commitment.Status(self.from_status).label if self.from_status else "—"

    @property
    def to_label(self):
        return Commitment.Status(self.to_status).label


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
class Comment(models.Model):
    class Category(models.TextChoices):
        OVERALL = "overall", "Overall weekly report"
        RESPONSE_TIME = "response_time", "Support response time"
        SLA = "sla", "SLA compliance"
        MISSED_CALLS = "missed_calls", "Missed calls"
        CSAT = "csat", "CSAT / customer satisfaction"
        OUTCOMES = "outcomes", "Weekly outcomes"
        EXECUTION = "execution", "Support execution"
        ROOT_CAUSES = "root_causes", "Recurring issues and root causes"
        LEADERSHIP = "leadership", "Leadership and team capacity"
        COMMITMENTS = "commitments", "Next-week commitments"
        OTHER = "other", "Other"

    class Visibility(models.TextChoices):
        MANAGEMENT = "management", "Management Report"
        INTERNAL = "internal", "Internal Only"

    class Target(models.TextChoices):
        REPORT = "report", "Overall report"
        METRIC = "metric", "Metric"
        QUESTION = "question", "Question"
        COMMITMENT = "commitment", "Commitment"

    review = models.ForeignKey(WeeklyReview, on_delete=models.PROTECT, related_name="comments")
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.OVERALL)
    text = models.TextField()
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.MANAGEMENT)
    target_type = models.CharField(max_length=20, choices=Target.choices, default=Target.REPORT)
    metric = models.CharField(max_length=30, blank=True, default="")
    question = models.PositiveSmallIntegerField(null=True, blank=True, choices=QUESTION_CHOICES)
    commitment = models.ForeignKey(Commitment, null=True, blank=True, on_delete=models.PROTECT, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name="comments")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["review", "category"]),
            models.Index(fields=["review", "target_type", "metric"]),
            models.Index(fields=["review", "target_type", "question"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(target_type="report", metric="", question__isnull=True, commitment__isnull=True)
                    | Q(target_type="metric", question__isnull=True, commitment__isnull=True) & ~Q(metric="")
                    | Q(target_type="question", metric="", question__isnull=False, commitment__isnull=True)
                    | Q(target_type="commitment", metric="", question__isnull=True, commitment__isnull=False)
                ),
                name="comment_target_consistent",
            )
        ]

    def __str__(self):
        return f"Comment #{self.pk} on {self.review.period.code}"

    @property
    def is_internal(self):
        return self.visibility == self.Visibility.INTERNAL

    @property
    def target_label(self):
        from .services.metrics import METRICS_BY_KEY

        if self.target_type == self.Target.METRIC:
            m = METRICS_BY_KEY.get(self.metric)
            return m.label if m else self.metric
        if self.target_type == self.Target.QUESTION:
            return f"Question {self.question}"
        if self.target_type == self.Target.COMMITMENT and self.commitment_id:
            return f"Commitment: {self.commitment.description[:50]}"
        return "Overall report"


class CommentRevision(models.Model):
    """Previous state of a comment, captured before each edit or deletion."""

    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, related_name="revisions")
    text = models.TextField()
    category = models.CharField(max_length=30)
    visibility = models.CharField(max_length=20)
    action = models.CharField(max_length=10, choices=[("edit", "Edited"), ("delete", "Deleted")])
    review_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]


# ---------------------------------------------------------------------------
# Snapshots of submitted reports
# ---------------------------------------------------------------------------
class ReportRevision(models.Model):
    class Kind(models.TextChoices):
        SUBMISSION = "submission", "Submission"
        REOPEN = "reopen", "Reopened for correction"

    review = models.ForeignKey(WeeklyReview, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    reason = models.TextField(blank=True, default="")
    snapshot = models.JSONField()
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        constraints = [models.UniqueConstraint(fields=["review", "number"], name="unique_revision_number")]
