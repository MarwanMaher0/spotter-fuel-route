from django.db import models


class FuelStation(models.Model):
    class GeocodeSource(models.TextChoices):
        CENSUS = "census", "US Census Gazetteer (town centre)"
        OSM = "osm", "OpenStreetMap Nominatim (town centre)"

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=8, help_text="Retail $/gallon")
    lat = models.FloatField()
    lon = models.FloatField()
    geocode_source = models.CharField(max_length=10, choices=GeocodeSource.choices)
    highways = models.CharField(
        max_length=100, blank=True, help_text="I-/US- highways named in the address, space separated"
    )

    class Meta:
        ordering = ["state", "city", "name"]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state}) ${self.price:.3f}"
