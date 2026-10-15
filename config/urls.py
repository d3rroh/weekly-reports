from django.contrib import admin
from django.urls import include, path

from apps.core import views as core_views
from apps.reviews.views import analysis

urlpatterns = [
    path("", analysis.dashboard, name="dashboard"),
    path("accounts/", include("apps.accounts.urls")),
    path("settings/", core_views.settings_view, name="settings"),
    path("settings/audit/", core_views.audit_log, name="audit_log"),
    path("django-admin/", admin.site.urls),
    path("", include("apps.reviews.urls")),
]

handler403 = "apps.core.errors.forbidden"
handler404 = "apps.core.errors.not_found"
