"""Cheapest refuelling plan along a fixed route.

Distances are in miles and fuel is measured in "miles of range" until the very
end, so the tank is simply a number between 0 and max_range. Gallons and
dollars are derived once a plan exists.

The algorithm is the classic greedy for the fixed-route gas station problem
(Khuller, Malekian & Mestre, "To fill or not to fill", 2007), which is optimal
when consumption is linear in distance:

  At a station with price p and fuel f:
    1. If a cheaper station is reachable on a full tank, buy only enough to
       reach the nearest such station, and go there.
    2. Otherwise, if the destination is reachable on a full tank, buy only
       enough to reach it.
    3. Otherwise, fill the tank and go to the cheapest station reachable.

The truck usually starts with some fuel and no pump at the origin. That is
modelled as a free virtual station placed (max_range - start_fuel) miles before
the origin: filling up there and driving to the origin leaves exactly
start_fuel in the tank, so the greedy and its optimality proof apply unchanged.

Cheapest fuel alone is not what a driver wants: it happily stops twice in ten
miles to save 2 cents a gallon on one gallon. So plan_fuel_stops first lets a
dynamic program choose WHERE to stop, minimising fuel cost plus a fixed cost
per stop (time off the road), and then runs the exact greedy on those stations
to decide HOW MUCH to buy. With stop_cost=0 the result is the pure cheapest
plan.
"""

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Candidate:
    """A fuel station projected onto the route."""

    station_id: int
    mile: float  # distance from the origin along the route
    price: float  # dollars per gallon


@dataclass(frozen=True)
class Purchase:
    candidate: Candidate
    gallons: float
    cost: float
    fuel_on_arrival_gallons: float


@dataclass
class FuelPlan:
    purchases: list = field(default_factory=list)
    route_miles: float = 0.0
    mpg: float = 10.0
    start_fuel_gallons: float = 0.0

    @property
    def total_cost(self) -> float:
        return sum(p.cost for p in self.purchases)

    @property
    def gallons_purchased(self) -> float:
        return sum(p.gallons for p in self.purchases)

    @property
    def trip_gallons(self) -> float:
        return self.route_miles / self.mpg

    @property
    def fuel_at_arrival_gallons(self) -> float:
        return max(0.0, self.start_fuel_gallons + self.gallons_purchased - self.trip_gallons)


class NoFeasiblePlan(Exception):
    """The route has a stretch longer than the tank range with no station."""

    def __init__(self, gap_start_mile, gap_end_mile, max_range):
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        super().__init__(
            f"No fuel station between mile {gap_start_mile:.0f} and mile "
            f"{gap_end_mile:.0f}; the truck's range is {max_range:.0f} miles."
        )


_EPS = 1e-9


def plan_fuel_stops(candidates, route_miles, *, max_range=500.0, mpg=10.0, start_fuel=None, stop_cost=0.0):
    """Return the cheapest FuelPlan for a route.

    candidates   iterable of Candidate (any order; off-route ones already removed)
    route_miles  total route length
    max_range    miles on a full tank
    mpg          miles per gallon
    start_fuel   miles of fuel in the tank at the origin (default: full tank)
    stop_cost    dollars charged per fuel stop when choosing where to stop
                 (not included in the returned fuel cost)
    """
    start_fuel = max_range if start_fuel is None else start_fuel
    if not 0 <= start_fuel <= max_range:
        raise ValueError("start_fuel must be between 0 and max_range")

    stations = sorted(
        (c for c in candidates if -_EPS <= c.mile <= route_miles + _EPS),
        key=lambda c: (c.mile, c.price),
    )
    _check_reachable(stations, route_miles, max_range, start_fuel)

    if stop_cost > 0 and stations:
        chosen = _choose_stops(stations, route_miles, max_range, mpg, start_fuel, stop_cost)
        if chosen is not None:
            _check_reachable(chosen, route_miles, max_range, start_fuel)  # guaranteed by the DP margins
            stations = chosen
        # else: only possible when a stretch is within 0.2 miles of the range;
        # plan with every station, ignoring the stop cost.

    return _greedy(stations, route_miles, max_range, mpg, start_fuel)


def _greedy(stations, route_miles, max_range, mpg, start_fuel):
    """Exact cheapest purchases using only `stations` (sorted, reachable)."""
    # Index -1 is the virtual origin station (price 0, see module docstring).
    origin = Candidate(station_id=-1, mile=start_fuel - max_range, price=0.0)
    points = [origin] + stations
    destination = route_miles

    purchases = []
    i, fuel = 0, 0.0
    while True:
        here = points[i]
        horizon = here.mile + max_range

        next_cheaper = None
        cheapest = None
        for j in range(i + 1, len(points)):
            other = points[j]
            if other.mile > horizon + _EPS:
                break
            if next_cheaper is None and other.price < here.price:
                next_cheaper = j
                break
            if cheapest is None or other.price <= points[cheapest].price:
                cheapest = j  # ties go to the farther station: fewer stops

        if next_cheaper is not None:
            target, target_mile = next_cheaper, points[next_cheaper].mile
            buy = max(0.0, (target_mile - here.mile) - fuel)
        elif destination <= horizon + _EPS:
            target, target_mile = None, destination
            buy = max(0.0, (destination - here.mile) - fuel)
        else:
            target, target_mile = cheapest, points[cheapest].mile
            buy = max_range - fuel

        if i > 0 and buy > _EPS:
            gallons = buy / mpg
            purchases.append(
                Purchase(
                    candidate=here,
                    gallons=gallons,
                    cost=gallons * here.price,
                    fuel_on_arrival_gallons=fuel / mpg,
                )
            )
        fuel = fuel + buy - (target_mile - here.mile)
        if target is None:
            break
        i = target

    return FuelPlan(
        purchases=purchases,
        route_miles=route_miles,
        mpg=mpg,
        start_fuel_gallons=start_fuel / mpg,
    )


def _choose_stops(stations, route_miles, max_range, mpg, start_fuel, stop_cost, resolution=0.1):
    """Pick the stations to stop at, minimising fuel cost + stop_cost per stop.

    Dynamic program over (station, fuel in the tank), with fuel counted in
    steps of `resolution` miles. Walking the stations in route order, the
    cost-so-far for every fuel level is shifted down by the distance driven; at
    a station the truck may also stop, pay stop_cost, and buy up to any higher
    level. "Best level to buy up from" is a running minimum, so each station
    costs O(tank size) numpy work and a whole route takes a few milliseconds.

    Rounding positions to the grid can misjudge any stretch by less than one
    step (the errors telescope). The tank, the starting fuel and the final leg
    are therefore each given one step of margin, which makes every plan the DP
    accepts truly feasible; the price is that a stretch within 0.1-0.2 miles of
    the full range counts as too long.

    Returns the chosen stations (the greedy then computes exact amounts), or
    None if no plan fits inside the margins.
    """
    capacity = int(np.floor(max_range / resolution + _EPS)) - 1
    levels = np.arange(capacity + 1)
    cost = np.full(capacity + 1, np.inf)
    start_level = min(int(np.floor(start_fuel / resolution + _EPS)) - 1, capacity)
    if start_level < 0:
        return None
    cost[start_level] = 0.0

    grid = [round(station.mile / resolution) for station in stations]
    position = 0
    choices = []  # per station: fuel level bought up from, or -1 for "no stop"
    for station, here in zip(stations, grid):
        cost = _drive(cost, here - position)
        position = here

        per_step = station.price / mpg * resolution
        adjusted = cost - levels * per_step
        best = np.minimum.accumulate(adjusted)
        best_from = np.maximum.accumulate(np.where(adjusted == best, levels, -1))
        stop = best + levels * per_step + stop_cost

        stopping = stop < cost
        cost = np.where(stopping, stop, cost)
        choices.append(np.where(stopping, best_from, -1).astype(np.int32))

    remaining = int(np.ceil(route_miles / resolution - position - _EPS)) + 1
    if remaining > capacity or not np.isfinite(cost[remaining:]).any():
        return None
    level = remaining + int(np.argmin(cost[remaining:]))

    chosen = []
    for index in range(len(stations) - 1, -1, -1):
        bought_from = choices[index][level]
        if bought_from >= 0:
            chosen.append(stations[index])
            level = int(bought_from)
        if index > 0:
            level += grid[index] - grid[index - 1]
    chosen.reverse()
    return chosen


def _drive(cost, miles):
    """Cost-by-fuel-level after driving `miles`: level f becomes f - miles."""
    if miles <= 0:
        return cost
    shifted = np.full_like(cost, np.inf)
    if miles < len(cost):
        shifted[: len(cost) - miles] = cost[miles:]
    return shifted


def _check_reachable(stations, route_miles, max_range, start_fuel):
    """Raise NoFeasiblePlan if some stretch of road is longer than the tank."""
    last_mile, reach = 0.0, start_fuel
    for station in stations:
        if station.mile > reach + _EPS:
            raise NoFeasiblePlan(last_mile, station.mile, max_range)
        last_mile, reach = station.mile, station.mile + max_range
    if route_miles > reach + _EPS:
        raise NoFeasiblePlan(last_mile, route_miles, max_range)
