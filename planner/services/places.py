"""Offline US place lookup built from the Census Gazetteer (data/us_places.csv).

Used for two things:
  * giving every fuel station a coordinate (the CSV only has city + state), and
  * resolving "City, ST" route endpoints without calling a geocoding API.
"""

import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

# Legal/statistical suffixes the Gazetteer appends to names ("Tulsa city",
# "Big Cabin town", "Abanda CDP", "Autaugaville CCD"). Longest first.
_SUFFIXES = sorted(
    [
        "city and borough", "consolidated government (balance)",
        "metropolitan government (balance)", "unified government (balance)",
        "urban county", "(balance)", "charter township", "city", "town", "village",
        "cdp", "ccd",
        "borough", "municipality", "township", "plantation", "comunidad",
        "zona urbana", "gore", "grant", "location", "purchase",
        "unorganized territory", "precinct", "district",
    ],
    key=len,
    reverse=True,
)

_ABBREVIATIONS = {
    "saint": "st", "ste": "st", "sainte": "st",
    "fort": "ft", "mount": "mt", "mountain": "mtn",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "point": "pt", "springs": "spgs", "heights": "hts",
    "junction": "jct", "jct": "jct", "lake": "lk",
}


def normalize_place_name(name: str, strip_suffix: bool = False) -> str:
    """Reduce a place name to a comparison key.

    Gazetteer names carry a type suffix ("St. Louis city"), so they are built
    with strip_suffix=True -> "stlouis". User and CSV input is looked up as
    typed first, because "Kansas City" is a name, not "Kansas" + suffix.
    Spaces are dropped so "Mc Calla" and "McCalla" share a key.
    """
    text = name.lower().strip()
    while strip_suffix:
        # Strip one suffix; go round again only after "(balance)", as in
        # "Indianapolis city (balance)". "Kansas City city" must stay "Kansas City".
        stripped = next((s for s in _SUFFIXES if text.endswith(" " + s)), None)
        if stripped is None:
            break
        text = text[: -len(stripped) - 1].strip()
        if stripped != "(balance)":
            break
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return "".join(_ABBREVIATIONS.get(word, word) for word in text.split())


@dataclass(frozen=True)
class Place:
    name: str
    state: str
    lat: float
    lon: float


class PlaceIndex:
    def __init__(self, rows):
        self._by_key = {}
        for row in rows:
            place = Place(row["name"], row["state"], float(row["lat"]), float(row["lon"]))
            self._by_key[(row["state"], row["key"])] = place

    def lookup(self, city: str, state: str):
        state = state.strip().upper()
        for key in (normalize_place_name(city), normalize_place_name(city, strip_suffix=True)):
            place = self._by_key.get((state, key))
            if place is not None:
                return place
        return None

    def __len__(self):
        return len(self._by_key)


@lru_cache(maxsize=1)
def get_place_index() -> PlaceIndex:
    with open(settings.PLACES_CSV, newline="", encoding="utf-8") as fh:
        return PlaceIndex(csv.DictReader(fh))
