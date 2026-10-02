import numpy as np
from django.test import SimpleTestCase

from planner.services.geocoding import LocationError, resolve_location
from planner.services.geometry import cumulative_miles, decode_polyline, resample, simplify
from planner.services.places import normalize_place_name
from planner.services.routing import highway_refs
from planner.services.trip import ExternalCalls

from .helpers import encode_polyline


class GeometryTests(SimpleTestCase):
    def test_decodes_reference_polyline(self):
        # Example from Google's polyline algorithm documentation (precision 5).
        coords = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
        np.testing.assert_allclose(coords, [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]])

    def test_encode_decode_round_trip(self):
        coords = [(41.87811, -87.62980), (39.73915, -104.98470)]
        np.testing.assert_allclose(decode_polyline(encode_polyline(coords)), coords, atol=1e-6)

    def test_resample_spacing_and_endpoint(self):
        coords = np.array([[40.0, -100.0], [40.0, -99.0]])
        points, marks = resample(coords, cumulative_miles(coords), spacing=5)
        self.assertAlmostEqual(marks[-1], cumulative_miles(coords)[-1])
        self.assertTrue(np.all(np.diff(marks) <= 5 + 1e-9))
        np.testing.assert_allclose(points[-1], coords[-1])

    def test_simplify_keeps_shape_end_points(self):
        coords = np.column_stack((np.linspace(40, 41, 1000), np.linspace(-100, -99, 1000)))
        simplified = simplify(coords, 0.001)
        self.assertEqual(len(simplified), 2)
        np.testing.assert_allclose(simplified[[0, -1]], coords[[0, -1]])


class NameMatchingTests(SimpleTestCase):
    def test_normalize(self):
        self.assertEqual(normalize_place_name("St. Louis city", strip_suffix=True), normalize_place_name("Saint Louis"))
        self.assertEqual(normalize_place_name("McCalla CDP", strip_suffix=True), normalize_place_name("Mc Calla"))
        self.assertEqual(normalize_place_name("Kansas City city", strip_suffix=True), normalize_place_name("Kansas City"))

    def test_highway_refs(self):
        self.assertEqual(highway_refs("I-44, EXIT 283 & US-69"), {"I-44", "US-69"})
        self.assertEqual(highway_refs("I 80; US 6"), {"I-80", "US-6"})
        self.assertEqual(highway_refs("HWY 83 & SR-21"), frozenset())


class ResolveLocationTests(SimpleTestCase):
    def test_city_state_resolves_offline(self):
        calls = ExternalCalls()
        loc = resolve_location("Chicago, IL", calls)
        self.assertEqual(loc.source, "census_gazetteer")
        self.assertAlmostEqual(loc.lat, 41.84, delta=0.2)
        self.assertEqual(calls.made, [])

    def test_state_name_and_country_suffix(self):
        loc = resolve_location("Denver, Colorado, USA", ExternalCalls())
        self.assertEqual(loc.source, "census_gazetteer")
        self.assertAlmostEqual(loc.lon, -104.9, delta=0.2)

    def test_coordinates(self):
        loc = resolve_location("35.4676,-97.5164", ExternalCalls())
        self.assertEqual((loc.lat, loc.lon, loc.source), (35.4676, -97.5164, "coordinates"))

    def test_rejects_points_outside_usa(self):
        with self.assertRaises(LocationError):
            resolve_location("48.8566,2.3522", ExternalCalls())  # Paris
        with self.assertRaises(LocationError):
            resolve_location("Toronto, ON", ExternalCalls())
