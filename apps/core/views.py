from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import redirect, render

from apps.accounts.permissions import admin_required

from .audit import log_event
from .forms import AppSettingsForm
from .models import AppSettings, AuditEvent


@login_required
def settings_view(request):
    obj = AppSettings.load()
    form = AppSettingsForm(request.POST or None, instance=obj) if request.user.is_app_admin else None
    if request.method == "POST":
        if form is None:
            from apps.accounts.permissions import deny
            deny(request, "Only administrators can change application settings.")
        if form.is_valid():
            before = {f: getattr(obj, f) for f in form.changed_data}
            settings_obj = form.save(commit=False)
            settings_obj.updated_by = request.user
            settings_obj.save()
            log_event(request, "settings_updated", obj=settings_obj, message="Application settings updated",
                      data={"changed": {f: [str(before[f]), str(form.cleaned_data[f])] for f in form.changed_data}})
            messages.success(request, "Settings saved.")
            return redirect("settings")
    return render(request, "core/settings.html", {"form": form, "obj": obj, "page_title": "Settings"})


@login_required
@admin_required
def audit_log(request):
    qs = AuditEvent.objects.select_related("actor", "review")
    action = request.GET.get("action", "")
    if action:
        qs = qs.filter(action=action)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    actions = AuditEvent.objects.order_by().values_list("action", flat=True).distinct()
    return render(request, "core/audit_log.html", {
        "page": page, "actions": sorted(actions), "action": action, "page_title": "Audit Log",
    })
