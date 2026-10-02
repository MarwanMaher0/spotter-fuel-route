from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def index(request):
    return JsonResponse({
        "service": "Fuel route planner",
        "endpoints": {
            "plan": "/api/route/?start=Chicago, IL&finish=Denver, CO",
            "map": "/api/route/map/?start=Chicago, IL&finish=Denver, CO",
            "docs": "/api/docs/",
        },
    })


urlpatterns = [
    path("", index),
    path("api/", include("planner.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("admin/", admin.site.urls),
]
