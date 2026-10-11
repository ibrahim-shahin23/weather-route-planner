"""Input validation. Output shaping lives in presenters.py."""
from rest_framework import serializers

from ..domain.sampling import ALLOWED_INTERVALS
from ..services.analysis import AnalysisRequest, LocationRef
from ..services.heatmap import HeatmapRequest

MAX_LOAD_LBS = 150_000


class LocationSerializer(serializers.Serializer):
    query = serializers.CharField(required=False, max_length=200, trim_whitespace=True)
    label = serializers.CharField(required=False, allow_blank=True, max_length=250)
    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lon = serializers.FloatField(required=False, min_value=-180, max_value=180)

    def validate(self, attrs):
        has_lat, has_lon = "lat" in attrs, "lon" in attrs
        if has_lat != has_lon:
            raise serializers.ValidationError("Provide both lat and lon.")
        if not has_lat and not attrs.get("query"):
            raise serializers.ValidationError("Provide a place name or coordinates.")
        return attrs


class AnalyzeRequestSerializer(serializers.Serializer):
    origin = LocationSerializer()
    destination = LocationSerializer()
    departure = serializers.DateTimeField()
    load_weight_lbs = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LBS)
    sample_interval_miles = serializers.IntegerField(required=False, allow_null=True)

    def validate_sample_interval_miles(self, value):
        if value is not None and value not in ALLOWED_INTERVALS:
            raise serializers.ValidationError(f"Choose one of {list(ALLOWED_INTERVALS)} miles, or leave empty for automatic.")
        return value

    def to_domain(self) -> AnalysisRequest:
        d = self.validated_data

        def ref(data: dict) -> LocationRef:
            return LocationRef(data.get("query"), data.get("lat"), data.get("lon"), data.get("label") or None)

        return AnalysisRequest(
            origin=ref(d["origin"]),
            destination=ref(d["destination"]),
            departure=d["departure"],
            load_weight_lbs=d["load_weight_lbs"],
            sample_interval_miles=d.get("sample_interval_miles"),
        )


class _CoordPair(serializers.ListField):
    child = serializers.FloatField()

    def __init__(self, **kwargs):
        super().__init__(min_length=2, max_length=2, **kwargs)

    def to_internal_value(self, data):
        lat, lon = super().to_internal_value(data)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise serializers.ValidationError("Coordinate out of range.")
        return (lat, lon)


class HeatmapRequestSerializer(serializers.Serializer):
    routes = serializers.ListField(
        child=serializers.ListField(child=_CoordPair(), min_length=2, max_length=8000),
        min_length=1,
        max_length=3,
    )
    departure = serializers.DateTimeField()
    load_weight_lbs = serializers.IntegerField(min_value=0, max_value=MAX_LOAD_LBS)
    hours = serializers.IntegerField(required=False, min_value=1, max_value=48, default=48)

    def to_domain(self) -> HeatmapRequest:
        d = self.validated_data
        return HeatmapRequest(
            paths=[list(map(tuple, r)) for r in d["routes"]],
            departure=d["departure"],
            load_weight_lbs=d["load_weight_lbs"],
            hours=d["hours"],
        )
