"""Turn a user's start/finish text into a coordinate inside the USA.

Accepted inputs, cheapest first:
  "41.8781,-87.6298"        coordinates, used as given
  "Chicago, IL"             city + state code or name, resolved offline from
                            the Census Gazetteer (no API call)
  anything else             one Nominatim (OpenStreetMap) search, counted as
                            an external call
"""

import re
from dataclasses import dataclass

import requests
from django.conf import settings

from .places import get_place_index
from .stations import US_STATES

_COORDINATES = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_COUNTRY_SUFFIX = re.compile(r",\s*(usa|us|united states( of america)?)\s*$", re.IGNORECASE)

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "district of columbia": "DC",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID", "illinois": "IL",
    "indiana": "IN", "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}


class LocationError(ValueError):
    pass


@dataclass(frozen=True)
class Location:
    query: str
    label: str
    lat: float
    lon: float
    source: str  # "coordinates" | "census_gazetteer" | "nominatim"


def resolve_location(text: str, calls) -> Location:
    text = (text or "").strip()
    if not text:
        raise LocationError("Location is empty.")

    match = _COORDINATES.match(text)
    if match:
        lat, lon = float(match.group(1)), float(match.group(2))
        _ensure_in_usa(text, lat, lon)
        return Location(text, f"{lat:.5f}, {lon:.5f}", lat, lon, "coordinates")

    place = _lookup_city_state(text)
    if place is not None:
        return Location(text, f"{place.name}, {place.state}", place.lat, place.lon, "census_gazetteer")

    return _nominatim(text, calls)


def _lookup_city_state(text):
    cleaned = _COUNTRY_SUFFIX.sub("", text)
    if "," not in cleaned:
        return None
    city, state = (part.strip() for part in cleaned.rsplit(",", 1))
    state = STATE_NAMES.get(state.lower(), state.upper())
    if state not in US_STATES:
        raise LocationError(f"'{text}': '{state}' is not a US state.")
    return get_place_index().lookup(city, state)


def _nominatim(text, calls) -> Location:
    calls.record("nominatim.search")
    try:
        response = requests.get(
            settings.NOMINATIM_URL,
            params={"q": text, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            timeout=settings.NOMINATIM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        hits = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise LocationError(f"Could not geocode '{text}': {exc}") from exc
    if not hits:
        raise LocationError(f"Could not find '{text}' in the USA. Try 'City, ST' or 'lat,lon'.")
    lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
    _ensure_in_usa(text, lat, lon)
    return Location(text, hits[0].get("display_name", text), lat, lon, "nominatim")


def _ensure_in_usa(text, lat, lon):
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LocationError(f"'{text}' is not a valid latitude,longitude pair.")
    if get_place_index().miles_to_nearest_place(lat, lon) > settings.MAX_MILES_FROM_US_PLACE:
        raise LocationError(f"'{text}' is outside the USA.")
