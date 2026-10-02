"""Is a coordinate inside the USA? Point-in-polygon on the Census land outline."""

import json
from functools import lru_cache

import numpy as np
from django.conf import settings

from .geometry import EARTH_RADIUS_MILES


class UsBoundary:
    def __init__(self, rings):
        starts, ends = [], []
        for ring in rings:
            points = np.asarray(ring, dtype=float)  # (lon, lat)
            starts.append(points)
            ends.append(np.roll(points, -1, axis=0))
        self._a = np.concatenate(starts)
        self._b = np.concatenate(ends)

    def contains(self, lat: float, lon: float, tolerance_miles: float = 0.0) -> bool:
        """Inside the outline, or within tolerance_miles of its edge.

        The outline is generalised (1:5M) and stops at the shoreline, so a
        point on a dock or a riverbank can land just outside it; a small
        tolerance keeps those without letting in Tijuana or Vancouver.
        """
        if self._inside(lat, lon):
            return True
        return tolerance_miles > 0 and self._distance_to_edge(lat, lon) <= tolerance_miles

    def _inside(self, lat, lon):
        (ax, ay), (bx, by) = self._a.T, self._b.T
        crosses = (ay > lat) != (by > lat)
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = ax + (lat - ay) * (bx - ax) / (by - ay)
        return bool(np.count_nonzero(crosses & (lon < x_at)) % 2)

    def _distance_to_edge(self, lat, lon):
        # Local equirectangular projection around the point, in miles.
        scale = np.radians(1) * EARTH_RADIUS_MILES
        kx = scale * np.cos(np.radians(lat))
        ax, ay = (self._a[:, 0] - lon) * kx, (self._a[:, 1] - lat) * scale
        bx, by = (self._b[:, 0] - lon) * kx, (self._b[:, 1] - lat) * scale
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.clip(np.where(length2 > 0, -(ax * dx + ay * dy) / length2, 0.0), 0.0, 1.0)
        return float(np.min(np.hypot(ax + t * dx, ay + t * dy)))


@lru_cache(maxsize=1)
def get_us_boundary() -> UsBoundary:
    with open(settings.US_BOUNDARY_JSON, encoding="utf-8") as fh:
        return UsBoundary(json.load(fh)["rings"])
