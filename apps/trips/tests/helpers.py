"""Test doubles shared by the suite."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..domain import geometry as geo
from ..domain.models import Coord, Place, RawRoute
from ..domain.weather import HourlySeries
from ..providers.base import GeocodingProvider, RoutingProvider, WeatherProvider

UTC = timezone.utc
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


class DictCache:
    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value, timeout=None):
        self.store[key] = value


def straight_route(a: Coord, b: Coord, duration_s: float, points: int = 200, bulge: float = 0.0) -> RawRoute:
    """Straight (optionally bowed) polyline from a to b."""
    coords = []
    for i in range(points + 1):
        f = i / points
        lat = a[0] + (b[0] - a[0]) * f + bulge * (1 - (2 * f - 1) ** 2)
        lon = a[1] + (b[1] - a[1]) * f
        coords.append((lat, lon))
    return RawRoute(coords, geo.cumulative_miles(coords)[-1], duration_s)


class FakeGeocoder(GeocodingProvider):
    def __init__(self, places=None):
        self.places = places or {}

    def search(self, query, limit=5):
        p = self.places.get(query.lower())
        return [p] if p else []


class FakeRouter(RoutingProvider):
    def __init__(self, routes, detour=None):
        self._routes = routes
        self._detour = detour
        self.calls = []

    def routes(self, waypoints, alternatives=0):
        self.calls.append((list(waypoints), alternatives))
        if len(waypoints) > 2 and self._detour:
            return [self._detour(waypoints)]
        return list(self._routes)


class FakeWeather(WeatherProvider):
    """Weather as a function of (lat, lon, datetime) -> (wind, rain, snow)."""

    def __init__(self, fn=lambda lat, lon, t: (5.0, 0.0, 0.0)):
        self.fn = fn
        self.calls = 0
        self.requested_points = 0

    def fetch_hourly(self, points, start_date: date, end_date: date):
        self.calls += 1
        self.requested_points += len(points)
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=UTC)
        hours = int((datetime(end_date.year, end_date.month, end_date.day, tzinfo=UTC) - start).total_seconds() // 3600) + 24
        out = []
        for lat, lon in points:
            wind, rain, snow = [], [], []
            for h in range(hours):
                w, r, s = self.fn(lat, lon, start + timedelta(hours=h))
                wind.append(w)
                rain.append(r)
                snow.append(s)
            out.append(HourlySeries(start, wind, rain, snow))
        return out
