import zoneinfo

from django import forms

from .models import AppSettings


class AppSettingsForm(forms.ModelForm):
    business_timezone = forms.ChoiceField(
        choices=[(tz, tz) for tz in sorted(zoneinfo.available_timezones())],
        help_text="Changing the timezone does not change the dates of existing reports.",
    )

    class Meta:
        model = AppSettings
        fields = [
            "organisation_name", "business_timezone", "include_management_comments_default",
            "show_leadership_in_presentation", "allow_incomplete_submission",
        ]
