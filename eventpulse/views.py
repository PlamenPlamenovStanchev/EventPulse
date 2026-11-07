from django.shortcuts import render


def not_found(request, exception):
    """Render the branded not-found page for unresolved URLs."""
    return render(request, '404.html', status=404)
