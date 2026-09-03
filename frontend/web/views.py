from django.conf import settings
from django.shortcuts import render


def index(request):
    """Serve the application shell with the configured FastAPI origin."""
    return render(request, "web/index.html", {"resume_api_url": settings.RESUME_API_URL})
