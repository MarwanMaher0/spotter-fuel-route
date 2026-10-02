"""Geocode the few station towns the Census gazetteer does not list.

About 2.6% of US stations sit in unincorporated communities (Breezewood PA,
Ruther Glen VA, ...). This one-off script resolves them with Nominatim
(OpenStreetMap, 1 request/second per its usage policy) and writes
data/geocode_overrides.csv, which is committed. The API itself never calls a
geocoder for stations.

    python scripts/geocode_missing.py
"""

import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.services.places import PlaceIndex  # noqa: E402
from planner.services.stations import US_STATES  # noqa: E402

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "spotter-fuel-route-assessment/1.0 (one-off station geocoding)"}
OUT = ROOT / "data" / "geocode_overrides.csv"


def nominatim(city, state):
    attempts = [
        {"city": city, "state": state, "country": "us"},
        {"q": f"{city}, {state}, USA"},
    ]
    for params in attempts:
        params.update({"format": "json", "limit": 1, "countrycodes": "us"})
        response = requests.get(NOMINATIM, params=params, headers=HEADERS, timeout=20)
        time.sleep(1.1)
        response.raise_for_status()
        hits = response.json()
        if hits:
            return float(hits[0]["lat"]), float(hits[0]["lon"])
    return None


def main():
    with open(ROOT / "data" / "us_places.csv", newline="", encoding="utf-8") as fh:
        places = PlaceIndex(csv.DictReader(fh))
    with open(ROOT / "data" / "fuel-prices-for-be-assessment.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    missing = sorted({
        (row["City"].strip(), row["State"].strip())
        for row in rows
        if row["State"].strip() in US_STATES and places.lookup(row["City"], row["State"]) is None
    })
    print(f"{len(missing)} towns to geocode")

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["city", "state", "lat", "lon"])
        for city, state in missing:
            hit = nominatim(city, state)
            print(city, state, hit)
            if hit:
                writer.writerow([city, state, f"{hit[0]:.5f}", f"{hit[1]:.5f}"])


if __name__ == "__main__":
    main()
