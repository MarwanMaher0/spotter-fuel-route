import csv
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from planner.models import FuelStation
from planner.services.places import get_place_index, normalize_place_name
from planner.services.routing import highway_refs
from planner.services.stations import US_STATES, reset_station_index


class Command(BaseCommand):
    help = "Load the fuel price CSV into the database, with a coordinate for every station."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=str(settings.FUEL_PRICES_CSV), help="Fuel price CSV path")

    def handle(self, *args, **options):
        places = get_place_index()
        overrides = self._read_overrides()

        cheapest = {}
        skipped_country = 0
        for row in self._read_rows(options["csv"]):
            if row["state"] not in US_STATES:
                skipped_country += 1  # Canadian provinces: outside the USA
                continue
            current = cheapest.get(row["opis_id"])
            if current is None or row["price"] < current["price"]:
                cheapest[row["opis_id"]] = row

        stations, unlocated = [], []
        for row in cheapest.values():
            place = places.lookup(row["city"], row["state"])
            if place is not None:
                lat, lon, source = place.lat, place.lon, FuelStation.GeocodeSource.CENSUS
            elif (row["state"], normalize_place_name(row["city"])) in overrides:
                lat, lon = overrides[(row["state"], normalize_place_name(row["city"]))]
                source = FuelStation.GeocodeSource.OSM
            else:
                unlocated.append(f"{row['city']}, {row['state']}")
                continue
            stations.append(
                FuelStation(
                    opis_id=row["opis_id"],
                    name=row["name"],
                    address=row["address"],
                    city=row["city"],
                    state=row["state"],
                    rack_id=row["rack_id"],
                    price=row["price"],
                    lat=lat,
                    lon=lon,
                    geocode_source=source,
                    highways=" ".join(sorted(highway_refs(row["address"]))),
                )
            )

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(stations, batch_size=1000)
        reset_station_index()

        self.stdout.write(self.style.SUCCESS(f"Loaded {len(stations)} US stations."))
        self.stdout.write(f"Skipped {skipped_country} rows outside the USA.")
        if unlocated:
            self.stdout.write(self.style.WARNING(
                f"{len(unlocated)} stations have no coordinate and were skipped: "
                + ", ".join(sorted(set(unlocated))[:20])
            ))

    def _read_rows(self, path):
        with open(path, newline="", encoding="utf-8") as fh:
            for raw in csv.DictReader(fh):
                yield {
                    "opis_id": int(raw["OPIS Truckstop ID"]),
                    "name": raw["Truckstop Name"].strip(),
                    "address": raw["Address"].strip(),
                    "city": raw["City"].strip(),
                    "state": raw["State"].strip().upper(),
                    "rack_id": int(raw["Rack ID"]) if raw["Rack ID"].strip() else None,
                    "price": Decimal(raw["Retail Price"].strip()),
                }

    def _read_overrides(self):
        try:
            fh = open(settings.GEOCODE_OVERRIDES_CSV, newline="", encoding="utf-8")
        except FileNotFoundError:
            return {}
        with fh:
            return {
                (row["state"], normalize_place_name(row["city"])): (float(row["lat"]), float(row["lon"]))
                for row in csv.DictReader(fh)
            }
