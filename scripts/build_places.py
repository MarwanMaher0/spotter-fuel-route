"""Build data/us_places.csv from the US Census Gazetteer files.

The gazetteer lists every US city, town, CDP and county subdivision with an
internal-point latitude/longitude. For large cities that point can be far from
downtown, so data/city_centres.csv (scripts/fix_city_centres.py) replaces it.

We use it as an offline geocoder: fuel stations (city + state in the CSV) and
"City, ST" route endpoints resolve without calling any external API.

Usage (one-off, output is committed to the repo):
    curl -LO https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_place_national.zip
    curl -LO https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_cousubs_national.zip
    unzip 2024_Gaz_place_national.zip && unzip 2024_Gaz_cousubs_national.zip
    python scripts/build_places.py 2024_Gaz_place_national.txt 2024_Gaz_cousubs_national.txt
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from planner.services.places import normalize_place_name  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "data" / "us_places.csv"


def read_gazetteer(path):
    with open(path, encoding="utf-8") as fh:
        header = [h.strip() for h in fh.readline().split("\t")]
        for line in fh:
            row = dict(zip(header, (v.strip() for v in line.split("\t"))))
            yield row


def read_centres():
    """City centres for large places (see scripts/fix_city_centres.py)."""
    path = OUT.parent / "city_centres.csv"
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {(row["state"], row["name"]): (row["lat"], row["lon"]) for row in csv.DictReader(fh)}


def main(place_file, cousub_file):
    best = {}  # (state, key) -> (rank, name, lat, lon)

    def offer(state, raw_name, lat, lon, rank):
        keys = [(normalize_place_name(raw_name, strip_suffix=True), rank)]
        # Consolidated city-counties are filed as "Nashville-Davidson metropolitan
        # government (balance)" or "Macon-Bibb County"; "Boise City city" is how
        # the Census names Boise. Add the everyday name as a low-priority alias.
        everyday = re.split(r"[-/]", raw_name)[0]
        if everyday != raw_name:
            keys.append((normalize_place_name(everyday, strip_suffix=True), rank + 3))
        if raw_name.startswith("Urban "):  # "Urban Honolulu CDP"
            keys.append((normalize_place_name(raw_name[len("Urban "):], strip_suffix=True), rank + 3))
        # Some official names repeat a type word: "Boise City city", "Amite City
        # town", "Moapa Town CDP". People write "Boise", "Amite", "Moapa".
        base = normalize_place_name(raw_name, strip_suffix=True)
        for word in ("city", "town", "village"):
            if base.endswith(word) and len(base) > len(word):
                keys.append((base[: -len(word)], rank + 3))
        for key, key_rank in keys:
            if not key:
                continue
            current = best.get((state, key))
            if current is None or key_rank < current[0]:
                best[(state, key)] = (key_rank, raw_name, lat, lon)

    centres = read_centres()
    for row in read_gazetteer(place_file):
        # Incorporated places (FUNCSTAT A) beat census-designated places.
        rank = 0 if row["FUNCSTAT"] == "A" else 1
        lat, lon = centres.get((row["USPS"], row["NAME"]), (row["INTPTLAT"], row["INTPTLONG"]))
        offer(row["USPS"], row["NAME"], lat, lon, rank)

    for row in read_gazetteer(cousub_file):
        # County subdivisions can be huge (the "Honolulu CCD" reaches Midway),
        # so any real place, even an alias, wins over one.
        offer(row["USPS"], row["NAME"], row["INTPTLAT"], row["INTPTLONG"], 10)

    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["state", "key", "name", "lat", "lon"])
        for (state, key), (_, name, lat, lon) in sorted(best.items()):
            writer.writerow([state, key, name, f"{float(lat):.5f}", f"{float(lon):.5f}"])
    print(f"wrote {len(best)} places to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
