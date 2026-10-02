from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def index(request):
    return JsonResponse({
        "service": "Fuel route planner",
        "endpoints": {
            "plan": "/api/route/?start=Chicago, IL&finish=Denver, CO",
            "map": "/api/route/map/?start=Chicago, IL&finish=Denver, CO",
        },
    })


urlpatterns = [
    path("", index),
    path("api/", include("planner.urls")),
    path("admin/", admin.site.urls),
]
