from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from . import throttle
from .models import User


class ThrottledAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": "Too many failed sign-in attempts. Please wait a few minutes and try again.",
    }

    def clean(self):
        username = self.data.get("username", "")
        ip = throttle.client_ip(self.request) if self.request else ""
        if throttle.is_locked(username, ip):
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            throttle.register_failure(username, ip)
            raise
        throttle.reset(username)
        return cleaned


class UserForm(forms.ModelForm):
    """Administrator form for creating and editing users."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput, required=False, strip=False)
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput, required=False, strip=False)

    class Meta:
        model = User
        fields = [
            "username", "first_name", "last_name", "email", "role", "is_active",
            "can_edit_reports", "can_view_confidential", "can_correct_submitted",
        ]

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.creating = self.instance.pk is None
        if self.creating:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
        else:
            self.fields["password1"].help_text = "Leave blank to keep the current password."

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords do not match.")
            else:
                try:
                    password_validation.validate_password(p1, self.instance)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)
        if self.acting_user and self.instance.pk == self.acting_user.pk:
            if not cleaned.get("is_active") or cleaned.get("role") != User.Role.ADMIN:
                raise forms.ValidationError("You cannot deactivate or demote your own administrator account.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password1"):
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
