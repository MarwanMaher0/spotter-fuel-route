# Fuel Route Planner API

A Django REST API that takes a start and finish anywhere in the USA and returns
the driving route, where to buy fuel along it, and what the fuel will cost. The
truck has a 500-mile range and does 10 miles per gallon. Prices come from the
supplied `fuel-prices-for-be-assessment.csv`.

- **One external call per new trip.** Routing is a single OSRM request. Both
  ends are geocoded offline, and repeated trips come from a cache (0 calls).
- **Fast.** A new cross-country trip takes about 0.5–1 s, almost all of it the
  OSRM request. A repeated trip takes 20–150 ms. Planning itself takes under
  15 ms.
- **Cheapest fuel, without silly stops.** It uses a provably optimal refuelling
  algorithm plus a per-stop cost, so it won't stop twice in ten miles to save
  two cents.

```
GET /api/route/?start=Chicago, IL&finish=Dallas, TX
```

![New York to Los Angeles](docs/map-new-york-los-angeles.png)

## Quick start

Requires Python 3.12+ (Django 6.1).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_stations        # loads 6,626 US stations, about 2 s
python manage.py runserver
```

Then open http://127.0.0.1:8000/api/route/map/?start=New%20York,%20NY&finish=Los%20Angeles,%20CA
or import `postman/fuel-route.postman_collection.json` into Postman.

Run the tests with `python manage.py test`. They don't touch the network.

## API

### `GET /api/route/` or `POST /api/route/`

| Parameter | Default | Meaning |
|---|---|---|
| `start`, `finish` | required | `"City, ST"`, `"City, State"`, `"lat,lon"`, or a free-text US address |
| `start_fuel_percent` | `100` | Tank level when the truck leaves (0–100) |
| `stop_cost_usd` | `25` | What one fuel stop costs in time off the road. `0` gives the pure cheapest-fuel plan |
| `include_geometry` | `true` | Include the route line as GeoJSON |

GET takes query parameters. POST takes the same fields as a JSON body.

Response, trimmed (`include_geometry=false`):

```json
{
  "start":  {"query": "Chicago, IL", "resolved_as": "Chicago city, IL", "lat": 41.83705, "lon": -87.68494, "source": "census_gazetteer"},
  "finish": {"query": "Dallas, TX",  "resolved_as": "Dallas city, TX",  "lat": 32.79333, "lon": -96.76651, "source": "census_gazetteer"},
  "route":  {"distance_miles": 961.5, "duration_hours": 17.04},
  "fuel_stops": [
    {"stop": 1, "mile": 477.5, "name": "SHELL", "address": "I-55, EXIT 48", "city": "Osceola", "state": "AR",
     "opis_id": 64617, "price_per_gallon": 2.999, "gallons": 46.15, "cost_usd": 138.4,
     "fuel_on_arrival_gallons": 2.25, "approx_miles_off_route": 3.3, "lat": 35.69022, "lon": -89.98829}
  ],
  "summary": {
    "total_fuel_cost_usd": 138.4, "gallons_purchased": 46.15, "number_of_stops": 1,
    "trip_gallons_burned": 96.15, "start_fuel_gallons": 50.0, "average_price_paid_per_gallon": 2.999,
    "assumptions": {"mpg": 10.0, "max_range_miles": 500.0, "tank_gallons": 50.0, "stop_cost_usd": 25.0, "arrives_with_empty_tank": true}
  },
  "map_url": "http://127.0.0.1:8000/api/route/map/?start=Chicago%2C+IL&finish=Dallas%2C+TX&start_fuel_percent=100&stop_cost_usd=25.0",
  "meta": {"external_api_calls": 0, "route_from_cache": true, "stations_considered": 161, "compute_ms": 8.8}
}
```

`meta.external_api_calls` reports how many third-party requests this call made.

Errors:

| Status | When |
|---|---|
| 400 | Bad input, or a location outside the USA |
| 422 | No station within range somewhere on the route; the response includes the gap |
| 502 | The routing service failed |

### `GET /api/route/map/`

Takes the same parameters and returns the plan drawn on an OpenStreetMap map
(Leaflet), with a stop table. Every JSON response links to it in `map_url`.

## How it works

```
start, finish ──► geocode offline (Census Gazetteer) ──► 0 API calls
                         │
                         ▼
              OSRM route (cached on disk) ───────────► 1 API call per new trip
                         │
                         ▼
     match stations to the route (KD-tree, 10-mile corridor, highway check)
                         │
                         ▼
     choose stops (DP: fuel cost + cost per stop) ──► buy amounts (exact greedy)
```

1. **Station coordinates.** The price list has a town and state but no
   coordinates. `load_stations` matches each town against the US Census
   Gazetteer (49k places, shipped in `data/us_places.csv`), which covers 97.4%
   of stations. The remaining 128 unincorporated towns, such as Breezewood PA,
   were geocoded once with Nominatim and committed in
   `data/geocode_overrides.csv`. Every US station has a coordinate, and the API
   never geocodes a station at request time. The 620 Canadian rows are skipped.
   Rows that repeat an OPIS ID keep the cheapest price.
2. **Endpoints.** `"City, ST"` resolves from the same Gazetteer, so the common
   case costs no API call. Free-text addresses fall back to one Nominatim
   search. Points more than 40 miles from any US town are rejected as outside
   the USA.
3. **Route.** OSRM returns the full geometry, the length, and the highway of
   every step in one call (`overview=full&geometries=polyline6&steps=true`).
   The parsed route is cached for 7 days in Django's file cache, keyed by both
   coordinates.
4. **Stations along the route.** The route is resampled every 0.5 miles and
   loaded into a KD-tree. All 6,626 stations are queried at once, taking a few
   milliseconds. A station is a candidate if its town centre is within 10 miles
   of the road. Station positions are town-level, so the corridor is generous.
   To compensate, a station whose address names an interstate must be on a
   highway the route uses near that point, unless it is within 3 miles. This
   stops a station on I-35 from being picked for an I-80 trip that passes
   through the same town. It removes 10–20% of false candidates.
5. **Where to stop and how much to buy** (`planner/services/optimizer.py`):
   - With `stop_cost_usd=0`, this is the classic fixed-route gas station
     problem, solved by the greedy of Khuller, Malekian & Mestre ("To fill or
     not to fill", 2007). If a cheaper station is within a full tank, buy just
     enough to reach it. Otherwise, if the destination is within reach, buy
     just enough to finish. Otherwise fill up and go to the cheapest reachable
     station. This is optimal when fuel use is linear in distance. A partly
     full starting tank is modelled as a free virtual station behind the
     origin, so the proof still applies.
   - The pure optimum is impractical, though. On Miami to Seattle it makes 20
     stops, one of them for 0.1 gallons. So a dynamic program over (station,
     fuel level in whole miles) first chooses *where* to stop, minimising fuel
     cost plus `stop_cost_usd` per stop. The running-minimum trick keeps each
     station O(tank size), about 10 ms per route. The exact greedy then
     decides *how much* to buy at those stops.
   - The effect at the default $25 per stop:

     | Trip | Cheapest fuel only | With $25/stop |
     |---|---|---|
     | New York → Los Angeles | 14 stops, $700.07 | 6 stops, $705.63 |
     | Chicago → Dallas | 4 stops, $133.22 | 1 stop, $138.40 |
     | Miami → Seattle | 20 stops, $849.65 | 7 stops, $861.62 |

## Assumptions

- The truck leaves with a full tank (50 gallons = 500 miles) and arrives empty.
  The total is the money spent at the recommended stops. Set
  `start_fuel_percent` to plan from a different tank level. At 0, the truck
  must fuel up at the origin.
- Fuel use is a constant 10 mpg, and price is the CSV retail price.
- A station's position is its town centre, so `approx_miles_off_route` is
  approximate. The address, which is usually an interstate exit, tells the
  driver where it is.
- The detour to a station is not added to the route length.

## Project layout

```
config/                     settings, URLs, WSGI (warms the indexes at startup)
planner/
  models.py                 FuelStation
  views.py                  RoutePlanView (GET/POST), RouteMapView (HTML map)
  serializers.py            request validation, response shape
  services/
    geocoding.py            "City, ST" / "lat,lon" / free text → coordinate
    places.py               offline Census Gazetteer lookup
    routing.py              OSRM client, route cache, highway spans
    stations.py             in-memory station index (numpy + KD-tree)
    optimizer.py            greedy + stop-cost DP
    trip.py                 orchestrates one request
    geometry.py             polyline decode, haversine, resample, simplify
  management/commands/load_stations.py
  tests/                    optimizer vs brute force, geocoding, API (OSRM mocked)
scripts/                    one-off builders for data/us_places.csv and data/geocode_overrides.csv
data/                       fuel prices CSV, Census places, geocode overrides
postman/                    Postman collection
```

## Tests

`python manage.py test` runs 28 tests. The optimizer is checked against two
independent brute-force solvers on random routes: a Dijkstra over (station,
fuel), and an exhaustive search over every set of stops for the stop-cost
version. API tests mock OSRM and check the external-call count, caching, error
codes and the map page.

## Configuration

Settings live in `config/settings.py`. `OSRM_BASE_URL` and `NOMINATIM_URL` can
be overridden from the environment, for example to point at a self-hosted OSRM
for production traffic, since the public demo server is rate-limited.
`TRUCK_RANGE_MILES`, `TRUCK_MPG`, `FUEL_CORRIDOR_MILES` and
`FUEL_STOP_COST_USD` are plain settings.

## Data sources

- Fuel prices: the provided assessment CSV.
- Routing: [OSRM](https://project-osrm.org/) public server (OpenStreetMap data).
- Places: [US Census Bureau 2024 Gazetteer](https://www.census.gov/geographies/reference-files/time-series/geo/gazetteer-files.html) (public domain).
- Fallback geocoding and map tiles: OpenStreetMap / Nominatim.
