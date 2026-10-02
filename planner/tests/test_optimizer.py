import heapq
import itertools
import random

from django.test import SimpleTestCase

from planner.services.optimizer import Candidate, NoFeasiblePlan, plan_fuel_stops


def stations(*pairs):
    return [Candidate(station_id=i, mile=mile, price=price) for i, (mile, price) in enumerate(pairs)]


def brute_force_cost(cands, route_miles, max_range, mpg, start_fuel):
    """Dijkstra over (station, whole miles of fuel): slow but obviously correct."""
    points = sorted(cands, key=lambda c: c.mile)
    # state: (cost, index of next point to reach, fuel at current position, position)
    best = {}
    heap = [(0.0, 0, start_fuel, 0)]
    while heap:
        cost, i, fuel, pos = heapq.heappop(heap)
        if best.get((i, fuel), float("inf")) <= cost:
            continue
        best[(i, fuel)] = cost
        if i == len(points):
            if fuel >= route_miles - pos:
                return cost
            continue
        station = points[i]
        drive = station.mile - pos
        if fuel < drive:
            continue
        arrive = fuel - drive
        # Option 1: buy any whole number of miles here, then head on.
        for buy in range(0, max_range - arrive + 1):
            heapq.heappush(heap, (cost + buy / mpg * station.price, i + 1, arrive + buy, station.mile))
    return None


class GreedyOptimizerTests(SimpleTestCase):
    def test_no_stop_when_start_tank_covers_trip(self):
        plan = plan_fuel_stops(stations((100, 3.0)), 400, max_range=500, mpg=10)
        self.assertEqual(plan.purchases, [])
        self.assertEqual(plan.total_cost, 0)

    def test_buys_only_what_is_needed_to_finish(self):
        plan = plan_fuel_stops(stations((300, 3.0)), 700, max_range=500, mpg=10)
        [purchase] = plan.purchases
        # Arrives with 200 miles of fuel, needs 400 more: 200 miles = 20 gallons.
        self.assertAlmostEqual(purchase.gallons, 20)
        self.assertAlmostEqual(plan.total_cost, 60)

    def test_waits_for_cheaper_station_ahead(self):
        plan = plan_fuel_stops(stations((100, 4.0), (450, 3.0)), 900, max_range=500, mpg=10)
        self.assertEqual([p.candidate.mile for p in plan.purchases], [450])
        # Arrives at 450 with 50 miles left, needs 450 more: 400 miles = 40 gallons.
        self.assertAlmostEqual(plan.total_cost, 40 * 3.0)

    def test_fills_up_where_cheap_before_expensive_stretch(self):
        plan = plan_fuel_stops(
            stations((10, 2.0), (400, 5.0), (800, 5.0)), 1200, max_range=500, mpg=10, start_fuel=50
        )
        first = plan.purchases[0]
        self.assertEqual(first.candidate.mile, 10)
        self.assertAlmostEqual(first.gallons, 50 - 4)  # fill the tank: arrived with 40 miles = 4 gal

    def test_empty_start_requires_station_at_origin(self):
        with self.assertRaises(NoFeasiblePlan):
            plan_fuel_stops(stations((5, 3.0)), 300, max_range=500, mpg=10, start_fuel=0)
        plan = plan_fuel_stops(stations((0, 3.0)), 300, max_range=500, mpg=10, start_fuel=0)
        self.assertAlmostEqual(plan.gallons_purchased, 30)

    def test_gap_longer_than_range_is_reported(self):
        with self.assertRaises(NoFeasiblePlan) as caught:
            plan_fuel_stops(stations((400, 3.0), (950, 3.0)), 1200, max_range=500, mpg=10)
        self.assertEqual(caught.exception.gap_start_mile, 400)
        self.assertEqual(caught.exception.gap_end_mile, 950)

    def test_ignores_stations_beyond_the_route(self):
        plan = plan_fuel_stops(stations((600, 1.0), (300, 3.0)), 550, max_range=500, mpg=10)
        self.assertEqual([p.candidate.mile for p in plan.purchases], [300])

    def test_matches_brute_force_on_random_routes(self):
        rng = random.Random(7)
        for _ in range(60):
            route = rng.randint(150, 420)
            cands = stations(*[(rng.randint(0, route), round(rng.uniform(2.5, 4.5), 2)) for _ in range(rng.randint(2, 7))])
            start_fuel = rng.randint(20, 100)
            try:
                plan = plan_fuel_stops(cands, route, max_range=100, mpg=10, start_fuel=start_fuel, stop_cost=0)
            except NoFeasiblePlan:
                self.assertIsNone(brute_force_cost(cands, route, 100, 10, start_fuel))
                continue
            expected = brute_force_cost(cands, route, 100, 10, start_fuel)
            self.assertAlmostEqual(plan.total_cost, expected, places=6)


class StopCostTests(SimpleTestCase):
    def test_skips_tiny_top_ups(self):
        # Low tank: pure cheapest buys 1 gallon at mile 40 just to reach a
        # station 2 cents cheaper 20 miles later. Not worth a second stop.
        cands = stations((40, 3.02), (60, 3.00))
        cheapest = plan_fuel_stops(cands, 520, max_range=500, mpg=10, start_fuel=50, stop_cost=0)
        practical = plan_fuel_stops(cands, 520, max_range=500, mpg=10, start_fuel=50, stop_cost=25)
        self.assertEqual([round(p.gallons, 2) for p in cheapest.purchases], [1.0, 46.0])
        self.assertEqual([round(p.gallons, 2) for p in practical.purchases], [47.0])
        self.assertLess(practical.total_cost - cheapest.total_cost, 1)

    def test_never_beats_cheapest_fuel(self):
        rng = random.Random(11)
        for _ in range(40):
            route = rng.randint(600, 2000)
            cands = stations(*[(rng.uniform(0, route), rng.uniform(2.6, 4.2)) for _ in range(rng.randint(20, 60))])
            try:
                cheapest = plan_fuel_stops(cands, route, stop_cost=0)
            except NoFeasiblePlan:
                continue
            practical = plan_fuel_stops(cands, route, stop_cost=25)
            self.assertGreaterEqual(practical.total_cost + 1e-6, cheapest.total_cost)
            self.assertLessEqual(len(practical.purchases), len(cheapest.purchases))

    def test_matches_exhaustive_search_over_stop_sets(self):
        rng = random.Random(5)
        checked = 0
        while checked < 40:
            route = round(rng.uniform(200, 380), 3)
            cands = stations(*[(round(rng.uniform(0, route), 3), round(rng.uniform(2.5, 4.5), 3))
                               for _ in range(rng.randint(3, 8))])
            if _near_range_limit(cands, route, max_range=100, start_fuel=60):
                continue  # the DP is deliberately conservative within 0.2 mi of the range
            try:
                plan = plan_fuel_stops(cands, route, max_range=100, mpg=10, start_fuel=60, stop_cost=4)
            except NoFeasiblePlan:
                continue
            checked += 1
            best = float("inf")
            for size in range(len(cands) + 1):
                for subset in itertools.combinations(cands, size):
                    try:
                        sub = plan_fuel_stops(subset, route, max_range=100, mpg=10, start_fuel=60, stop_cost=0)
                    except NoFeasiblePlan:
                        continue
                    best = min(best, sub.total_cost + 4 * len(sub.purchases))
            self.assertAlmostEqual(plan.total_cost + 4 * len(plan.purchases), best, places=6)

    def test_dp_choice_is_always_feasible_on_half_mile_grid(self):
        # Real routes put stations on a 0.5-mile grid. Rounding those to whole
        # miles once let the DP accept a 500.5-mile stretch; the margins must
        # make every accepted choice pass the exact check.
        from planner.services.optimizer import _check_reachable, _choose_stops

        rng = random.Random(3)
        accepted = 0
        for _ in range(300):
            route = rng.randint(1200, 3000) + 0.5 * rng.randint(0, 1)
            marks = sorted({0.5 * rng.randint(0, int(route * 2)) for _ in range(rng.randint(8, 25))})
            cands = stations(*[(m, round(rng.uniform(2.8, 3.4), 3)) for m in marks])
            start = 0.5 * rng.randint(100, 1000)
            try:
                _check_reachable(cands, route, 500, start)
            except NoFeasiblePlan:
                continue
            chosen = _choose_stops(cands, route, 500, 10, start, 25)
            if chosen is not None:
                accepted += 1
                _check_reachable(chosen, route, 500, start)  # must not raise
        self.assertGreater(accepted, 50)


def _near_range_limit(cands, route, max_range, start_fuel, margin=0.25):
    marks = sorted([0.0, route] + [c.mile for c in cands])
    gaps = [b - a for i, a in enumerate(marks) for b in marks[i + 1:]]
    return any(abs(g - max_range) < margin or abs(g - start_fuel) < margin for g in gaps)
