"""Weather lookups with grid-snapping and caching in front of a provider."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, Sequence

from ..domain.models import Coord
from ..domain.weather import HourlySeries
from ..providers.base import WeatherProvider


class Cache(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def set(self, key: str, value: Any, timeout: int | None = None) -> None: ...


@dataclass(frozen=True)
class WeatherWindow:
    """Whole UTC days of hourly data to request.

    Route analysis and the heatmap both derive their window from the departure,
    so they share cache entries whenever the trip ends inside the 48 h heatmap span.
    """

    start_date: date
    end_date: date

    @classmethod
    def for_trip(cls, departure: datetime, latest_eta: datetime) -> "WeatherWindow":
        dep = departure.astimezone(timezone.utc)
        end = max(dep + timedelta(hours=49), latest_eta.astimezone(timezone.utc) + timedelta(hours=1))
        return cls(dep.date(), end.date())


class WeatherService:
    def __init__(self, provider: WeatherProvider, cache: Cache, grid_deg: float = 0.05, ttl_s: int = 1800, namespace: str = "wx1"):
        self._provider = provider
        self._cache = cache
        self._grid = grid_deg
        self._ttl = ttl_s
        self._ns = namespace

    def _snap(self, c: Coord) -> Coord:
        g = self._grid
        return (round(round(c[0] / g) * g, 4), round(round(c[1] / g) * g, 4))

    def _key(self, c: Coord, w: WeatherWindow) -> str:
        return f"{self._ns}:{c[0]:.4f}:{c[1]:.4f}:{w.start_date}:{w.end_date}"

    def fetch(self, points: Sequence[Coord], window: WeatherWindow) -> list[HourlySeries]:
        """Hourly series for each point (same order). Points that snap to the same
        grid cell are fetched once; results are cached for `ttl_s`."""
        snapped = [self._snap(p) for p in points]
        found: dict[Coord, HourlySeries] = {}
        missing: list[Coord] = []
        for c in dict.fromkeys(snapped):  # unique, order-preserving
            hit = self._cache.get(self._key(c, window))
            if hit is not None:
                found[c] = hit
            else:
                missing.append(c)

        if missing:
            fetched = self._provider.fetch_hourly(missing, window.start_date, window.end_date)
            for c, series in zip(missing, fetched):
                found[c] = series
                self._cache.set(self._key(c, window), series, self._ttl)

        return [found[c] for c in snapped]
