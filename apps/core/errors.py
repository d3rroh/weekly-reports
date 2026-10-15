from django.shortcuts import render


def forbidden(request, exception=None):
    return render(request, "errors/403.html", {"page_title": "Access denied"}, status=403)


def not_found(request, exception=None):
    return render(request, "errors/404.html", {"page_title": "Not found"}, status=404)
