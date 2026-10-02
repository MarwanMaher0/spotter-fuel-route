"""WSGI config. Used by `runserver` and by gunicorn in production."""

import logging
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# Build the in-memory indexes now (~0.6 s) so the first API call is as fast as
# the rest. If the stations are not loaded yet, they load on first use instead.
try:
    from planner.services.trip import warm_up

    warm_up()
except Exception:  # never block startup on a cache warm-up
    logging.getLogger(__name__).warning("Index warm-up skipped", exc_info=True)
