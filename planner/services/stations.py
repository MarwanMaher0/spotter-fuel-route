"""In-memory spatial index of fuel stations.

The table is small (about 6,500 US stations), so it is read from the database
once per process and kept as numpy arrays plus a KD-tree. Matching a route
against every station then takes a few milliseconds and no queries.
"""

import threading

import numpy as np
from django.conf import settings
from scipy.spatial import cKDTree

from .geometry import chord_to_miles, miles_to_chord, resample, to_unit_vectors

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)


class StationIndex:
    def __init__(self, stations):
        self.stations = list(stations)
        self.prices = np.array([float(s.price) for s in self.stations])
        self.highways = [frozenset(s.highways.split()) for s in self.stations]
        lat = np.array([s.lat for s in self.stations])
        lon = np.array([s.lon for s in self.stations])
        self._xyz = to_unit_vectors(lat, lon)

    def __len__(self):
        return len(self.stations)

    def along_route(self, route, corridor_miles=None):
        """Stations near the route, as (station, mile_marker, off_route_miles).

        Station coordinates are town-level (the price list has no lat/lon), so
        a generous corridor is used. To avoid suggesting a stop on a different
        interstate that merely passes through the same town, a station whose
        address names an I-/US- highway must be on a highway the route uses
        nearby, unless it is already very close to the route.
        """
        corridor = settings.FUEL_CORRIDOR_MILES if corridor_miles is None else corridor_miles
        if not self.stations:
            return []
        samples, sample_miles = resample(route.coords, route.miles, settings.ROUTE_SAMPLE_MILES)
        tree = cKDTree(to_unit_vectors(samples[:, 0], samples[:, 1]))
        chord, nearest = tree.query(self._xyz, distance_upper_bound=miles_to_chord(corridor))

        hits = []
        for i in np.flatnonzero(np.isfinite(chord)):
            mile = float(sample_miles[nearest[i]])
            off_route = float(chord_to_miles(chord[i]))
            station_highways = self.highways[i]
            if (
                off_route > settings.NEAR_ROUTE_MILES
                and station_highways
                and not station_highways & route.highways_near(mile, settings.HIGHWAY_MATCH_WINDOW_MILES)
            ):
                continue
            hits.append((self.stations[i], mile, off_route))
        return hits


_index = None
_lock = threading.Lock()


def get_station_index() -> StationIndex:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                from planner.models import FuelStation

                index = StationIndex(FuelStation.objects.all())
                if not len(index):
                    # Not loaded yet: don't cache, so `load_stations` takes
                    # effect without restarting the server.
                    return index
                _index = index
    return _index


def reset_station_index():
    global _index
    with _lock:
        _index = None
