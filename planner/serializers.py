from django.conf import settings
from rest_framework import serializers

from .services.geometry import simplify


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="'City, ST', 'lat,lon' or an address in the USA")
    finish = serializers.CharField(max_length=200, help_text="'City, ST', 'lat,lon' or an address in the USA")
    start_fuel_percent = serializers.FloatField(
        min_value=0, max_value=100, default=100, help_text="Tank level at the start; default full"
    )
    stop_cost_usd = serializers.FloatField(
        min_value=0, max_value=1000, required=False,
        help_text="Cost of one fuel stop (time off the road) used to avoid tiny top-ups; 0 = cheapest fuel only",
    )
    include_geometry = serializers.BooleanField(default=True)

    def validate(self, attrs):
        attrs.setdefault("stop_cost_usd", settings.FUEL_STOP_COST_USD)
        return attrs


def trip_to_dict(trip, map_url=None, include_geometry=True):
    plan, route = trip.plan, trip.route
    data = {
        "start": _location(trip.start),
        "finish": _location(trip.finish),
        "route": {
            "distance_miles": round(route.distance_miles, 1),
            "duration_hours": round(route.duration_hours, 2),
        },
        "fuel_stops": [_stop(number, stop) for number, stop in enumerate(trip.stops, start=1)],
        "summary": {
            "total_fuel_cost_usd": round(plan.total_cost, 2),
            "gallons_purchased": round(plan.gallons_purchased, 2),
            "number_of_stops": len(trip.stops),
            "trip_gallons_burned": round(plan.trip_gallons, 2),
            "start_fuel_gallons": round(plan.start_fuel_gallons, 2),
            "average_price_paid_per_gallon": (
                round(plan.total_cost / plan.gallons_purchased, 3) if plan.gallons_purchased else None
            ),
            "assumptions": {
                "mpg": settings.TRUCK_MPG,
                "max_range_miles": settings.TRUCK_RANGE_MILES,
                "tank_gallons": settings.TRUCK_RANGE_MILES / settings.TRUCK_MPG,
                "stop_cost_usd": trip.stop_cost,
                "arrives_with_empty_tank": True,
            },
        },
        "map_url": map_url,
        "meta": {
            "external_api_calls": len(trip.external_calls),
            "external_api_calls_detail": trip.external_calls,
            "route_from_cache": "osrm.route" not in trip.external_calls,
            "stations_considered": trip.stations_considered,
            "compute_ms": round(trip.elapsed_ms, 1),
        },
    }
    if include_geometry:
        data["route"]["geometry"] = route_geojson(route)
    return data


def route_geojson(route):
    """Route line as GeoJSON ([lon, lat] order), simplified to keep the payload small."""
    coords = simplify(route.coords, settings.ROUTE_SIMPLIFY_DEGREES)
    return {
        "type": "LineString",
        "coordinates": [[round(lon, 5), round(lat, 5)] for lat, lon in coords],
    }


def _location(location):
    return {
        "query": location.query,
        "resolved_as": location.label,
        "lat": round(location.lat, 5),
        "lon": round(location.lon, 5),
        "source": location.source,
    }


def _stop(number, stop):
    station = stop.station
    return {
        "stop": number,
        "mile": round(stop.mile, 1),
        "name": station.name,
        "address": station.address,
        "city": station.city,
        "state": station.state,
        "opis_id": station.opis_id,
        "price_per_gallon": round(float(station.price), 3),
        "gallons": round(stop.gallons, 2),
        "cost_usd": round(stop.cost, 2),
        "fuel_on_arrival_gallons": round(stop.fuel_on_arrival_gallons, 2),
        "approx_miles_off_route": round(stop.off_route_miles, 1),
        "lat": round(station.lat, 5),
        "lon": round(station.lon, 5),
    }
