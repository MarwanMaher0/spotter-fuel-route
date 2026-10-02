"""Build data/us_boundary.json (US land outline) from the Census 1:5M KML.

    curl -LO https://www2.census.gov/geo/tiger/GENZ2018/kml/cb_2018_us_nation_5m.zip
    unzip cb_2018_us_nation_5m.zip
    python scripts/build_boundary.py cb_2018_us_nation_5m.kml
"""

import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "us_boundary.json"


def main(kml_file):
    text = Path(kml_file).read_text(encoding="utf-8")
    rings = []
    for block in re.findall(r"<outerBoundaryIs>.*?<coordinates>(.*?)</coordinates>", text, re.S):
        ring = []
        for point in block.split():
            lon, lat = point.split(",")[:2]
            ring.append([round(float(lon), 4), round(float(lat), 4)])
        rings.append(ring)
    OUT.write_text(json.dumps({"source": "US Census cb_2018_us_nation_5m", "rings": rings}, separators=(",", ":")))
    print(f"wrote {len(rings)} rings, {sum(map(len, rings))} points to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
