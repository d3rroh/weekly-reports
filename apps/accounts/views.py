from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.core.audit import log_event

from .forms import ThrottledAuthenticationForm, UserForm
from .models import User
from .permissions import admin_required


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = ThrottledAuthenticationForm
    redirect_authenticated_user = True


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:password_change_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        log_event(self.request, "password_changed", obj=self.request.user, message="Password changed")
        return response


@login_required
@admin_required
def user_list(request):
    users = User.objects.all().order_by("-is_active", "username")
    return render(request, "accounts/user_list.html", {"users": users, "page_title": "User Management"})


@login_required
@admin_required
def user_edit(request, pk=None):
    instance = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=instance, acting_user=request.user)
    if request.method == "POST" and form.is_valid():
        changed = form.changed_data
        user = form.save()
        action = "user_created" if instance is None else "user_updated"
        log_event(
            request, action, obj=user,
            message=f"{'Created' if instance is None else 'Updated'} user {user.username}",
            data={"changed_fields": [f for f in changed if not f.startswith("password")],
                  "password_changed": bool(form.cleaned_data.get("password1"))},
        )
        messages.success(request, f"User {user.username} saved.")
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {
        "form": form, "instance": instance,
        "page_title": "Edit user" if instance else "Add user",
    })
