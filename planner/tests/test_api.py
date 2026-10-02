from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from planner.models import FuelStation
from planner.services.stations import reset_station_index

from .helpers import mock_osrm, straight_route_payload

# Chicago, IL -> Omaha, NE is about 430 miles as the crow flies; with the tank
# half full the truck has to stop once.
CHICAGO = (41.83755, -87.68184)
OMAHA = (41.26131, -96.04551)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class RoutePlanApiTests(TestCase):
    def setUp(self):
        cache.clear()
        reset_station_index()
        self.addCleanup(reset_station_index)
        self.client = APIClient()
        self.payload = straight_route_payload(CHICAGO, OMAHA)
        # Stations sitting on the straight line (interpolated by fraction of the way).
        for opis, fraction, price, address in [
            (1, 0.30, 3.40, "I-80, EXIT 100"),
            (2, 0.45, 2.90, "I-80, EXIT 200"),
            (3, 0.60, 3.10, "I-80, EXIT 300"),
            (4, 0.50, 1.50, "I-35, EXIT 9"),  # cheap but on another interstate, 6 mi off
        ]:
            lat = CHICAGO[0] + (OMAHA[0] - CHICAGO[0]) * fraction
            lon = CHICAGO[1] + (OMAHA[1] - CHICAGO[1]) * fraction
            if opis == 4:
                lat += 0.09  # ~6 miles north of the road
            FuelStation.objects.create(
                opis_id=opis, name=f"STATION {opis}", address=address, city="Town", state="IA",
                price=price, lat=lat, lon=lon, geocode_source="census",
                highways=address.split(",")[0],
            )

    def get(self, **params):
        return self.client.get("/api/route/", params, HTTP_ACCEPT="application/json")

    def test_plans_cheapest_stop_with_one_routing_call(self):
        with mock_osrm(self.payload) as osrm:
            response = self.get(start="Chicago, IL", finish="Omaha, NE", start_fuel_percent=50)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(osrm.call_count, 1)
        body = response.json()

        [stop] = body["fuel_stops"]
        self.assertEqual(stop["opis_id"], 2)  # cheapest on-route station; the I-35 one is excluded
        miles = body["route"]["distance_miles"]
        # Half tank = 250 miles; buy exactly what is missing to reach Omaha.
        expected_gallons = (miles - 250) / 10
        self.assertAlmostEqual(stop["gallons"], round(expected_gallons, 2), delta=0.1)
        self.assertAlmostEqual(body["summary"]["total_fuel_cost_usd"], stop["cost_usd"], places=2)
        self.assertEqual(body["meta"]["external_api_calls"], 1)
        self.assertEqual(body["route"]["geometry"]["type"], "LineString")
        self.assertIn("/api/route/map/?", body["map_url"])

    def test_repeat_request_is_served_from_cache(self):
        with mock_osrm(self.payload) as osrm:
            self.get(start="Chicago, IL", finish="Omaha, NE")
            response = self.get(start="Chicago, IL", finish="Omaha, NE")
        self.assertEqual(osrm.call_count, 1)
        self.assertEqual(response.json()["meta"]["external_api_calls"], 0)
        self.assertTrue(response.json()["meta"]["route_from_cache"])

    def test_post_json_body(self):
        with mock_osrm(self.payload):
            response = self.client.post(
                "/api/route/", {"start": "Chicago, IL", "finish": "Omaha, NE"}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fuel_stops"], [])  # a full tank covers 430 miles

    def test_validation_errors(self):
        self.assertEqual(self.get(start="Chicago, IL").status_code, 400)
        self.assertEqual(self.get(start="Chicago, IL", finish="Omaha, NE", start_fuel_percent=150).status_code, 400)
        response = self.get(start="Paris, France", finish="Omaha, NE")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a US state", response.json()["error"])

    def test_unreachable_stretch_returns_422(self):
        FuelStation.objects.all().delete()
        reset_station_index()
        with mock_osrm(self.payload):
            response = self.get(start="Chicago, IL", finish="Omaha, NE", start_fuel_percent=10)
        self.assertEqual(response.status_code, 422)
        self.assertIn("gap_start_mile", response.json())

    def test_routing_failure_returns_502(self):
        with mock_osrm({"code": "NoRoute", "message": "Impossible route"}, status_code=400):
            response = self.get(start="Chicago, IL", finish="Omaha, NE")
        self.assertEqual(response.status_code, 502)

    def test_map_page_renders(self):
        with mock_osrm(self.payload):
            response = self.client.get("/api/route/map/", {"start": "Chicago, IL", "finish": "Omaha, NE", "start_fuel_percent": 50})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "leaflet")
        self.assertContains(response, "STATION 2")
