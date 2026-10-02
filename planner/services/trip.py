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
    stop_cost: float
    external_calls: list
    elapsed_ms: float


def plan_trip(start_text, finish_text, start_fuel_fraction=1.0, stop_cost=None) -> TripPlan:
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
    plan = plan_fuel_stops(
        candidates,
        route.distance_miles,
        max_range=max_range,
        mpg=settings.TRUCK_MPG,
        start_fuel=start_fuel_fraction * max_range,
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
        stop_cost=stop_cost,
        external_calls=calls.made,
        elapsed_ms=(time.perf_counter() - began) * 1000,
    )


def warm_up():
    """Load the place and station indexes before the first request needs them."""
    from .places import get_place_index

    get_place_index()
    get_station_index()
