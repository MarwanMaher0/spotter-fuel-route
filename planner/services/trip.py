"""Plan a trip: locate both ends, fetch one route, pick the cheapest fuel stops."""

import time
from dataclasses import dataclass

from django.conf import settings

from .geocoding import Location, resolve_location
from .optimizer import Candidate, FuelPlan, plan_fuel_stops
from .routing import Route, get_route
from .stations import get_station_index


class ExternalCalls:
    """Counts requests made to third-party APIs while serving one request."""

    def __init__(self):
        self.made = []

    def record(self, name: str):
        self.made.append(name)


@dataclass
class FuelStop:
    station: object  # planner.models.FuelStation
    mile: float
    off_route_miles: float
    gallons: float
    cost: float
    fuel_on_arrival_gallons: float


@dataclass
class TripPlan:
    start: Location
    finish: Location
    route: Route
    plan: FuelPlan
    stops: list
    stations_considered: int
    start_fuel_mode: str
    stop_cost: float
    external_calls: list
    elapsed_ms: float


def plan_trip(start_text, finish_text, start_fuel_fraction=None, stop_cost=None) -> TripPlan:
    """Plan one trip.

    start_fuel_fraction  tank level at the start, 0-1. None (the default) means
                         the truck leaves with only enough fuel to reach the
                         first station on the route, so the reported total is
                         the cost of fuel for the whole trip.
    stop_cost            dollars per fuel stop, weighed against fuel savings
    """
    began = time.perf_counter()
    calls = ExternalCalls()
    if stop_cost is None:
        stop_cost = settings.FUEL_STOP_COST_USD

    start = resolve_location(start_text, calls)
    finish = resolve_location(finish_text, calls)
    route = get_route(start, finish, calls)

    hits = get_station_index().along_route(route)
    by_id = {station.pk: (station, off_route) for station, _, off_route in hits}
    candidates = [Candidate(station.pk, mile, float(station.price)) for station, mile, _ in hits]

    max_range = settings.TRUCK_RANGE_MILES
    if start_fuel_fraction is not None:
        start_fuel, start_fuel_mode = start_fuel_fraction * max_range, "given"
    elif candidates:
        first_station = min(c.mile for c in candidates)
        start_fuel = min(max_range, first_station + settings.START_RESERVE_MILES)
        start_fuel_mode = "reach_first_station"
    else:
        # No station anywhere near the route: the trip has to fit in one tank.
        start_fuel, start_fuel_mode = max_range, "full_no_stations"
    plan = plan_fuel_stops(
        candidates,
        route.distance_miles,
        max_range=max_range,
        mpg=settings.TRUCK_MPG,
        start_fuel=start_fuel,
        stop_cost=stop_cost,
    )

    stops = []
    for purchase in plan.purchases:
        station, off_route = by_id[purchase.candidate.station_id]
        stops.append(
            FuelStop(
                station=station,
                mile=purchase.candidate.mile,
                off_route_miles=off_route,
                gallons=purchase.gallons,
                cost=purchase.cost,
                fuel_on_arrival_gallons=purchase.fuel_on_arrival_gallons,
            )
        )

    return TripPlan(
        start=start,
        finish=finish,
        route=route,
        plan=plan,
        stops=stops,
        stations_considered=len(candidates),
        start_fuel_mode=start_fuel_mode,
        stop_cost=stop_cost,
        external_calls=calls.made,
        elapsed_ms=(time.perf_counter() - began) * 1000,
    )


def warm_up():
    """Load the place and station indexes before the first request needs them."""
    from .places import get_place_index

    get_place_index()
    get_station_index()
