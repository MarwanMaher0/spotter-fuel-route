"""Replace the Census "internal point" of large cities with their centre.

For a big or watery city the Gazetteer's internal point can be far from
downtown: San Francisco's is in the Pacific (the city includes the Farallon
Islands), and Los Angeles' and Orlando's are 10-12 miles out. That matters for
route endpoints. This one-off script asks Nominatim (1 request/second) for the
centre of every place over 50 sq mi of land or 15 sq mi of water and writes
data/city_centres.csv, which scripts/build_places.py applies.

    python scripts/fix_city_centres.py 2024_Gaz_place_national.txt
"""

import csv
import math
import sys
import time
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "city_centres.csv"
HEADERS = {"User-Agent": "spotter-fuel-route-assessment/1.0 (one-off city centres)"}
MAX_SHIFT_MILES = 75  # a bigger jump means Nominatim found a different place


def main(place_file):
    with open(place_file, encoding="utf-8") as fh:
        header = [h.strip() for h in fh.readline().split("\t")]
        rows = [dict(zip(header, (v.strip() for v in line.split("\t")))) for line in fh]
    big = [r for r in rows if float(r["ALAND_SQMI"]) > 50 or float(r["AWATER_SQMI"]) > 15]
    print(f"{len(big)} large places")

    with open(OUT, "w", newline="", encoding="utf-8") as out:
        writer = csv.writer(out)
        writer.writerow(["state", "name", "lat", "lon"])
        for row in big:
            city = row["NAME"].rsplit(" ", 1)[0] if row["NAME"].endswith((" city", " town", " CDP", " village", " municipality")) else row["NAME"]
            params = {"city": city, "state": row["USPS"], "country": "us", "format": "json", "limit": 1}
            try:
                hits = requests.get("https://nominatim.openstreetmap.org/search", params=params,
                                    headers=HEADERS, timeout=20).json()
            except (requests.RequestException, ValueError):
                hits = []
            time.sleep(1.1)
            if not hits:
                continue
            lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
            old_lat, old_lon = float(row["INTPTLAT"]), float(row["INTPTLONG"])
            shift = 69 * math.hypot(lat - old_lat, (lon - old_lon) * math.cos(math.radians(lat)))
            if shift <= MAX_SHIFT_MILES:
                writer.writerow([row["USPS"], row["NAME"], f"{lat:.5f}", f"{lon:.5f}"])
                out.flush()
            print(f"{row['NAME']}, {row['USPS']}: moved {shift:.1f} mi", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
