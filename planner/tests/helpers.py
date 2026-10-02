"""Builders for a fake OSRM response, so API tests never touch the network."""

from unittest import mock

import numpy as np


def encode_polyline(coords, precision=6):
    factor = 10**precision
    out, prev_lat, prev_lon = [], 0, 0
    for lat, lon in coords:
        lat_i, lon_i = int(round(lat * factor)), int(round(lon * factor))
        for delta in (lat_i - prev_lat, lon_i - prev_lon):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lon = lat_i, lon_i
    return "".join(out)


def straight_route_payload(start, end, points=400, ref="I 80"):
    """OSRM-shaped JSON for a straight drive from start to end (lat, lon)."""
    from planner.services.geometry import haversine_miles

    lats = np.linspace(start[0], end[0], points)
    lons = np.linspace(start[1], end[1], points)
    meters = float(haversine_miles(start[0], start[1], end[0], end[1])) * 1609.344
    return {
        "code": "Ok",
        "routes": [{
            "geometry": encode_polyline(zip(lats, lons)),
            "distance": meters,
            "duration": meters / 29.0,
            "legs": [{"steps": [{"distance": meters, "ref": ref}]}],
        }],
    }


def mock_osrm(payload, status_code=200):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = payload
    return mock.patch("planner.services.routing.requests.get", return_value=response)
