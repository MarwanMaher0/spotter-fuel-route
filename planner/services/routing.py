"""Driving route from OSRM: one HTTP request per new origin/destination pair.

OSRM (router.project-osrm.org) is free, keyless and returns, in a single call,
the full route geometry, its length and the highway ref of every step. Results
are cached, so asking for the same trip again makes no external call at all.
"""

import re
from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings
from django.core.cache import cache

from .geometry import cumulative_miles, decode_polyline

METERS_PER_MILE = 1609.344
_HIGHWAY_RE = re.compile(r"\b(I|US)[\s-]*(\d+)\b")


class RoutingError(Exception):
    """The routing service failed (HTTP 502)."""


class NoRouteFound(RoutingError):
    """The service works but there is no road between the points (HTTP 422)."""


@dataclass
class Route:
    coords: np.ndarray  # (n, 2) lat, lon
    miles: np.ndarray  # mile marker of every coordinate
    distance_miles: float
    duration_hours: float
    highway_spans: list  # [(start_mile, end_mile, frozenset({"I-80", "US-6"}))]

    def highways_near(self, mile: float, window: float) -> set:
        found = set()
        for start, end, refs in self.highway_spans:
            if start <= mile + window and end >= mile - window:
                found |= refs
        return found


def highway_refs(text: str) -> frozenset:
    """'I 80; US 6' or 'I-44, EXIT 283 & US-69' -> {'I-80', 'US-6'} etc."""
    return frozenset(f"{kind}-{number}" for kind, number in _HIGHWAY_RE.findall(text or ""))


def get_route(start, finish, calls) -> Route:
    key = f"route:{start.lat:.4f},{start.lon:.4f}:{finish.lat:.4f},{finish.lon:.4f}"
    route = cache.get(key)
    if route is None:
        route = fetch_route(start, finish, calls)
        cache.set(key, route, timeout=settings.ROUTE_CACHE_SECONDS)
    return route


def fetch_route(start, finish, calls) -> Route:
    url = (
        f"{settings.OSRM_BASE_URL}/route/v1/driving/"
        f"{start.lon:.6f},{start.lat:.6f};{finish.lon:.6f},{finish.lat:.6f}"
    )
    params = {"overview": "full", "geometries": "polyline6", "steps": "true"}
    calls.record("osrm.route")
    try:
        response = requests.get(url, params=params, timeout=settings.OSRM_TIMEOUT_SECONDS)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RoutingError("Routing service unavailable; please retry.") from exc
    code = payload.get("code")
    if code in ("NoRoute", "NoSegment"):
        raise NoRouteFound("No road route between these points (an island, or water in the way?).")
    if response.status_code != 200 or code != "Ok" or not payload.get("routes"):
        raise RoutingError(f"Routing service error: {payload.get('message') or code or response.status_code}")
    return parse_osrm_route(payload["routes"][0])


def parse_osrm_route(data) -> Route:
    coords = decode_polyline(data["geometry"], precision=6)
    distance_miles = data["distance"] / METERS_PER_MILE
    miles = cumulative_miles(coords)
    if miles[-1] > 0:
        # Our great-circle sum differs from OSRM's road length by a fraction of
        # a percent; scale so mile markers agree with the reported distance.
        miles *= distance_miles / miles[-1]

    spans, mile = [], 0.0
    for leg in data.get("legs", []):
        for step in leg.get("steps", []):
            length = step["distance"] / METERS_PER_MILE
            refs = highway_refs(step.get("ref", ""))
            if refs:
                spans.append((mile, mile + length, refs))
            mile += length

    return Route(
        coords=coords,
        miles=miles,
        distance_miles=distance_miles,
        duration_hours=data["duration"] / 3600,
        highway_spans=spans,
    )
