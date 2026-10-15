from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "email", "role", "is_active", "can_edit_reports", "can_view_confidential")
    fieldsets = UserAdmin.fieldsets + (
        ("Weekly review permissions", {"fields": ("role", "can_edit_reports", "can_view_confidential", "can_correct_submitted")}),
    )
