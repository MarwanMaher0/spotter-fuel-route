"""Django settings for the fuel route planner."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# Routes are cached on disk so a repeated trip makes no external call, even
# after a server restart.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / ".cache",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# OpenAPI schema at /api/schema/, interactive Swagger UI at /api/docs/.
SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel Route Planner API",
    "DESCRIPTION": "Cheapest fuel stops for a truck trip between two places in the USA.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_SETTINGS": {
        "displayRequestDuration": True,
        "defaultModelsExpandDepth": -1,
        "tryItOutEnabled": True,
    },
}

# --- Data files -------------------------------------------------------------
FUEL_PRICES_CSV = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
PLACES_CSV = BASE_DIR / "data" / "us_places.csv"
GEOCODE_OVERRIDES_CSV = BASE_DIR / "data" / "geocode_overrides.csv"
US_BOUNDARY_JSON = BASE_DIR / "data" / "us_boundary.json"

# --- External services ------------------------------------------------------
OSRM_BASE_URL = os.environ.get("OSRM_BASE_URL", "https://router.project-osrm.org")
OSRM_TIMEOUT_SECONDS = 20
NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
NOMINATIM_TIMEOUT_SECONDS = 10
HTTP_USER_AGENT = "spotter-fuel-route/1.0"
ROUTE_CACHE_SECONDS = 7 * 24 * 3600

# --- Vehicle and matching ---------------------------------------------------
TRUCK_RANGE_MILES = 500.0
TRUCK_MPG = 10.0
# Unless the request gives a tank level, the truck leaves with just enough fuel
# to reach the first station on its route (plus this reserve) and buys the rest.
START_RESERVE_MILES = 1.0
# What one fuel stop costs in time off the road. The optimizer weighs it against
# fuel savings so it does not stop twice in ten miles to save a few cents.
FUEL_STOP_COST_USD = 25.0
FUEL_CORRIDOR_MILES = 10.0  # station town centre within this distance of the road
NEAR_ROUTE_MILES = 3.0  # this close, a station counts whatever highway it names
HIGHWAY_MATCH_WINDOW_MILES = 25.0
ROUTE_SAMPLE_MILES = 0.5
US_BORDER_TOLERANCE_MILES = 0.3  # the outline is generalised and stops at the shore
ROUTE_SIMPLIFY_DEGREES = 0.001  # ~100 m; only affects the geometry returned
