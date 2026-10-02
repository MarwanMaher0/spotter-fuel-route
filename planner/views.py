import json
from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RoutePlanRequestSerializer, trip_to_dict
from .services.geocoding import GeocodingUnavailable, LocationError
from .services.optimizer import NoFeasiblePlan
from .services.routing import NoRouteFound, RoutingError
from .services.trip import plan_trip


def _plan_or_error(params):
    """Validate input and plan the trip. Returns (trip, request_data, error_response)."""
    serializer = RoutePlanRequestSerializer(data=params)
    if not serializer.is_valid():
        return None, None, Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    try:
        percent = data["start_fuel_percent"]
        trip = plan_trip(
            data["start"], data["finish"],
            start_fuel_fraction=None if percent is None else percent / 100,
            stop_cost=data["stop_cost_usd"],
        )
    except LocationError as exc:
        return None, data, Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except NoRouteFound as exc:
        return None, data, Response({"error": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    except (RoutingError, GeocodingUnavailable) as exc:
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

    Optional: start_fuel_percent (0-100; default: just enough to reach the first
    station), stop_cost_usd (default 25), include_geometry (default true).
    """

    @extend_schema(parameters=[RoutePlanRequestSerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return self._respond(request, request.query_params)

    @extend_schema(request=RoutePlanRequestSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request):
        return self._respond(request, request.data)

    def _respond(self, request, params):
        trip, data, error = _plan_or_error(params)
        if error:
            return error
        params = {"start": data["start"], "finish": data["finish"], "stop_cost_usd": data["stop_cost_usd"]}
        if data["start_fuel_percent"] is not None:
            params["start_fuel_percent"] = data["start_fuel_percent"]
        query = urlencode(params)
        map_url = request.build_absolute_uri(f"{reverse('route-map')}?{query}")
        return Response(trip_to_dict(trip, map_url=map_url, include_geometry=data["include_geometry"]))


class RouteMapView(APIView):
    """The same plan drawn on an OpenStreetMap map (Leaflet)."""

    @extend_schema(exclude=True)
    def get(self, request):
        trip, _, error = _plan_or_error(request.query_params)
        if error:
            return error
        payload = trip_to_dict(trip)
        return render(request, "planner/map.html", {"trip": payload, "trip_json": json.dumps(payload)})
