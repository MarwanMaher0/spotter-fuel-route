import json
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RoutePlanRequestSerializer, trip_to_dict
from .services.geocoding import LocationError
from .services.optimizer import NoFeasiblePlan
from .services.routing import RoutingError
from .services.trip import plan_trip


def _plan_or_error(params):
    """Validate input and plan the trip. Returns (trip, request_data, error_response)."""
    serializer = RoutePlanRequestSerializer(data=params)
    if not serializer.is_valid():
        return None, None, Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    try:
        trip = plan_trip(
            data["start"], data["finish"],
            start_fuel_fraction=data["start_fuel_percent"] / 100,
            stop_cost=data["stop_cost_usd"],
        )
    except LocationError as exc:
        return None, data, Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except RoutingError as exc:
        return None, data, Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    except NoFeasiblePlan as exc:
        return None, data, Response(
            {"error": str(exc), "gap_start_mile": round(exc.gap_start_mile, 1),
             "gap_end_mile": round(exc.gap_end_mile, 1)},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return trip, data, None


class RoutePlanView(APIView):
    """Plan fuel stops for a truck trip between two places in the USA.

    GET  /api/route/?start=Chicago, IL&finish=Denver, CO
    POST /api/route/  {"start": "Chicago, IL", "finish": "Denver, CO"}

    Optional: start_fuel_percent (0-100, default 100), stop_cost_usd (default 25),
    include_geometry (default true).
    """

    def get(self, request):
        return self._respond(request, request.query_params)

    def post(self, request):
        return self._respond(request, request.data)

    def _respond(self, request, params):
        trip, data, error = _plan_or_error(params)
        if error:
            return error
        query = urlencode({
            "start": data["start"],
            "finish": data["finish"],
            "start_fuel_percent": data["start_fuel_percent"],
            "stop_cost_usd": data["stop_cost_usd"],
        })
        map_url = request.build_absolute_uri(f"{reverse('route-map')}?{query}")
        return Response(trip_to_dict(trip, map_url=map_url, include_geometry=data["include_geometry"]))


class RouteMapView(APIView):
    """The same plan drawn on an OpenStreetMap map (Leaflet)."""

    def get(self, request):
        trip, _, error = _plan_or_error(request.query_params)
        if error:
            return error
        payload = trip_to_dict(trip)
        return render(request, "planner/map.html", {"trip": payload, "trip_json": json.dumps(payload)})
