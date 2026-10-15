from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.core.audit import log_event


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log_event(request, "login", actor=user, message=f"{user.username} signed in")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log_event(request, "logout", actor=user, message=f"{user.username} signed out")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")
    log_event(request, "login_failed", actor=None, message=f"Failed sign-in for '{username[:150]}'")
