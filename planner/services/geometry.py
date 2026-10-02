"""Small geometry helpers. Coordinates are (lat, lon) degrees unless noted."""

import numpy as np

EARTH_RADIUS_MILES = 3958.8


def decode_polyline(encoded: str, precision: int = 6) -> np.ndarray:
    """Decode a Google encoded polyline into an (n, 2) array of (lat, lon)."""
    coords = []
    index = lat = lon = 0
    length = len(encoded)
    while index < length:
        for axis in (0, 1):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        coords.append((lat, lon))
    return np.asarray(coords, dtype=float) / 10**precision


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(a))


def cumulative_miles(coords: np.ndarray) -> np.ndarray:
    """Distance from the first point to every point along a polyline."""
    steps = haversine_miles(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    return np.concatenate(([0.0], np.cumsum(steps)))


def resample(coords: np.ndarray, miles: np.ndarray, spacing: float):
    """Points every `spacing` miles along a polyline, with their mile markers.

    Interstates are drawn with few vertices on straight stretches, so nearest-
    vertex matching would be coarse there; even spacing bounds the error at
    spacing / 2.
    """
    marks = np.arange(0.0, miles[-1], spacing)
    marks = np.append(marks, miles[-1])
    lat = np.interp(marks, miles, coords[:, 0])
    lon = np.interp(marks, miles, coords[:, 1])
    return np.column_stack((lat, lon)), marks


def to_unit_vectors(lat, lon) -> np.ndarray:
    """(lat, lon) degrees -> points on the unit sphere, for KD-tree queries."""
    lat, lon = np.radians(lat), np.radians(lon)
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))


def miles_to_chord(miles: float) -> float:
    return 2 * np.sin(miles / (2 * EARTH_RADIUS_MILES))


def chord_to_miles(chord):
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.clip(chord / 2, 0, 1))


def simplify(coords: np.ndarray, tolerance: float) -> np.ndarray:
    """Ramer-Douglas-Peucker in degree space; keeps the shape, drops the bulk.

    Used only for the geometry we send back, so the response stays small.
    """
    if len(coords) < 3:
        return coords
    keep = np.zeros(len(coords), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(coords) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        start, end = coords[first], coords[last]
        segment = end - start
        points = coords[first + 1 : last] - start
        norm = np.hypot(*segment)
        if norm == 0:
            distances = np.hypot(points[:, 0], points[:, 1])
        else:
            distances = np.abs(segment[0] * points[:, 1] - segment[1] * points[:, 0]) / norm
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            split = first + 1 + worst
            keep[split] = True
            stack.append((first, split))
            stack.append((split, last))
    return coords[keep]
