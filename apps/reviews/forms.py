from datetime import date

from django import forms

from apps.core import periods

from .models import Comment, Commitment, Priority
from .questions import QUESTIONS_BY_NUMBER
from .services.metrics import METRIC_CHOICES

TEXT_MAX = 10000


def textarea(rows=3):
    return forms.Textarea(attrs={"rows": rows})


class NewReviewForm(forms.Form):
    period_start = forms.DateField(
        label="Reporting period",
        help_text="Choose a period, or pick any date to use the Wednesday–Tuesday period containing it.",
    )

    def clean_period_start(self):
        day = self.cleaned_data["period_start"]
        return periods.period_start_for(day)


class MetricsForm(forms.Form):
    avg_response_minutes = forms.DecimalField(
        label="Avg response time (min)", min_value=0, max_digits=9, decimal_places=2, required=False,
        help_text="Minutes. Decimals allowed.",
    )
    sla_compliance_pct = forms.DecimalField(
        label="SLA compliance (%)", min_value=0, max_value=100, max_digits=5, decimal_places=2, required=False,
        help_text="Percentage, 0–100.",
    )
    missed_calls = forms.IntegerField(
        label="Total missed calls", min_value=0, required=False, help_text="Whole number.",
    )
    csat_pct = forms.DecimalField(
        label="CSAT (%)", min_value=0, max_value=100, max_digits=5, decimal_places=2, required=False,
        help_text="Percentage, 0–100.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        if instance is not None:
            kwargs.setdefault("initial", {name: getattr(instance, name) for name in self.base_fields})
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update({"inputmode": "decimal" if name != "missed_calls" else "numeric",
                                       "autocomplete": "off"})
            if name == "missed_calls":
                field.widget.attrs["step"] = "1"
            else:
                field.widget.attrs["step"] = "0.01"


class ReviewMetaForm(forms.Form):
    executive_summary = forms.CharField(
        label="Summary for management", required=False, max_length=TEXT_MAX, widget=textarea(4),
        help_text="Short summary shown at the top of the presentation.",
    )
    include_management_comments = forms.BooleanField(
        required=False, label="Show Management Report comments in the presentation",
    )
    is_restricted = forms.BooleanField(
        required=False, label="Restrict this report to users with confidential access",
    )


class PriorityForm(forms.Form):
    description = forms.CharField(label="Priority", max_length=500, required=False)
    expected_outcome = forms.CharField(label="Expected outcome", required=False, max_length=TEXT_MAX,
                                       widget=textarea(2))
    actual_result = forms.CharField(label="Actual result", required=False, max_length=TEXT_MAX, widget=textarea(2))
    delivery_status = forms.ChoiceField(
        label="Delivery status", required=False, choices=[("", "— Select —")] + list(Priority.Delivery.choices)
    )
    notes = forms.CharField(label="Supporting notes", required=False, max_length=TEXT_MAX, widget=textarea(2))

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("description", "").strip():
            others = [k for k in ("expected_outcome", "actual_result", "delivery_status", "notes")
                      if str(cleaned.get(k) or "").strip()]
            if others:
                self.add_error("description", "Describe the priority before adding its details.")
        return cleaned


def question_form_class(number):
    q = QUESTIONS_BY_NUMBER[number]
    attrs = {
        sf.key: forms.CharField(label=sf.label, required=False, max_length=TEXT_MAX, help_text=sf.help,
                                widget=textarea(sf.rows))
        for sf in q.fields
    }
    return type(f"Question{number}Form", (forms.Form,), attrs)


class CommitmentDefinitionForm(forms.Form):
    description = forms.CharField(label="Outcome", max_length=500, required=False)
    success_criteria = forms.CharField(label="Measurable success criteria", required=False, max_length=TEXT_MAX,
                                       widget=textarea(2))
    owner = forms.CharField(label="Owner (optional)", max_length=150, required=False)
    due_date = forms.DateField(label="Due date", required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, earliest_due=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.earliest_due = earliest_due

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("description", "").strip():
            if str(cleaned.get("success_criteria") or "").strip() or str(cleaned.get("owner") or "").strip():
                self.add_error("description", "Describe the outcome before adding success criteria.")
        due = cleaned.get("due_date")
        if due and self.earliest_due and due < self.earliest_due:
            self.add_error("due_date", f"Due date cannot be before {self.earliest_due:%-d %b %Y}.")
        return cleaned


class CommitmentProgressForm(forms.Form):
    status = forms.ChoiceField(choices=Commitment.Status.choices)
    progress_notes = forms.CharField(label="Progress notes", required=False, max_length=TEXT_MAX, widget=textarea(2))
    incomplete_explanation = forms.CharField(
        label="Explanation if not completed / blocked", required=False, max_length=TEXT_MAX, widget=textarea(2)
    )
    completion_evidence = forms.CharField(
        label="Completion evidence", required=False, max_length=TEXT_MAX, widget=textarea(2),
        help_text="Required when marking Completed: link or describe the evidence of delivery.",
    )
    completed_on = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(label="Update note (recorded in history)", required=False, max_length=2000)

    def clean_completed_on(self):
        value = self.cleaned_data.get("completed_on")
        if value and value > periods.local_today():
            raise forms.ValidationError("Completion date cannot be in the future.")
        return value


class CommentForm(forms.ModelForm):
    target = forms.ChoiceField(label="Linked to", required=True)

    class Meta:
        model = Comment
        fields = ["category", "visibility", "text"]
        widgets = {"text": textarea(4)}

    def __init__(self, *args, commitments=(), allowed_questions=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("report", "Overall report")]
        choices += [(f"metric:{k}", f"Metric — {label}") for k, label in METRIC_CHOICES]
        choices += [(f"question:{n}", f"Question {n}") for n in allowed_questions]
        choices += [(f"commitment:{c.pk}", f"Commitment — {c.description[:60]}") for c in commitments]
        self.fields["target"].choices = choices
        self.fields["category"].widget.attrs["data-suggest"] = "1"
        self.fields["text"].max_length = TEXT_MAX
        self._commitments = {c.pk: c for c in commitments}
        self._questions = set(allowed_questions)
        inst = self.instance
        if inst.pk and not self.is_bound:
            if inst.target_type == Comment.Target.METRIC:
                self.initial["target"] = f"metric:{inst.metric}"
            elif inst.target_type == Comment.Target.QUESTION:
                self.initial["target"] = f"question:{inst.question}"
            elif inst.target_type == Comment.Target.COMMITMENT:
                self.initial["target"] = f"commitment:{inst.commitment_id}"
            else:
                self.initial["target"] = "report"

    def clean_text(self):
        text = self.cleaned_data["text"].strip()
        if not text:
            raise forms.ValidationError("Comment text is required.")
        return text

    def clean_target(self):
        raw = self.cleaned_data["target"]
        kind, _, value = raw.partition(":")
        result = {"target_type": "report", "metric": "", "question": None, "commitment": None}
        if kind == "metric" and value in dict(METRIC_CHOICES):
            result.update(target_type="metric", metric=value)
        elif kind == "question" and value.isdigit() and int(value) in self._questions:
            result.update(target_type="question", question=int(value))
        elif kind == "commitment" and value.isdigit() and int(value) in self._commitments:
            result.update(target_type="commitment", commitment=self._commitments[int(value)])
        elif kind != "report":
            raise forms.ValidationError("Select a valid item to link this comment to.")
        return result

    def save(self, commit=True):
        target = self.cleaned_data["target"]
        for key, value in target.items():
            setattr(self.instance, key, value)
        return super().save(commit=commit)


class ReopenForm(forms.Form):
    reason = forms.CharField(max_length=2000, widget=textarea(3), label="Reason for correction")


class DateRangeForm(forms.Form):
    RANGE_CHOICES = [("8", "Last 8 weeks"), ("12", "Last 12 weeks"), ("26", "Last 26 weeks"),
                     ("52", "Last 52 weeks"), ("custom", "Custom range")]
    range = forms.ChoiceField(choices=RANGE_CHOICES, required=False, initial="12")
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    def resolve(self, default_weeks=12):
        """Return (first_period_start, last_period_start)."""
        latest = periods.latest_completed_period()
        data = self.cleaned_data if self.is_valid() else {}
        choice = data.get("range") or str(default_weeks)
        if choice == "custom" and data.get("start") and data.get("end"):
            a, b = sorted([data["start"], data["end"]])
            return periods.period_start_for(a), periods.period_start_for(b)
        weeks = int(choice) if choice.isdigit() else default_weeks
        weeks = max(2, min(weeks, 260))
        from datetime import timedelta
        return latest.start - timedelta(days=7 * (weeks - 1)), latest.start


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
