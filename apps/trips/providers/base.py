"""Provider interfaces. Services depend on these, never on a vendor directly, so
swapping OSRM for GraphHopper/Valhalla or Open-Meteo for another source is a new
class plus one line in `container.py`."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Sequence

from ..domain.models import Coord, Place, RawRoute
from ..domain.weather import HourlySeries


class GeocodingProvider(ABC):
    @abstractmethod
    def search(self, query: str, limit: int = 5) -> list[Place]: ...


class RoutingProvider(ABC):
    @abstractmethod
    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RawRoute]:
        """Driving routes through `waypoints` (origin, optional vias, destination).
        `alternatives` > 0 asks for up to that many alternative routes."""


class WeatherProvider(ABC):
    @abstractmethod
    def fetch_hourly(self, points: Sequence[Coord], start_date: date, end_date: date) -> list[HourlySeries]:
        """Hourly series (UTC) per point, same order as `points`, covering
        00:00 UTC on `start_date` through 23:00 UTC on `end_date`."""
