"""Plain value objects shared across layers. No Django / HTTP imports here."""
from __future__ import annotations

from dataclasses import dataclass

Coord = tuple[float, float]  # (lat, lon)


@dataclass(frozen=True)
class Place:
    label: str
    lat: float
    lon: float

    @property
    def coord(self) -> Coord:
        return (self.lat, self.lon)


@dataclass(frozen=True)
class RawRoute:
    """A route exactly as a routing provider returned it."""

    coords: list[Coord]
    distance_miles: float
    duration_s: float


@dataclass(frozen=True)
class WeatherSample:
    """Weather at one place and time, in the units used by the risk rules."""

    wind_mph: float
    rain_in_hr: float
    snow_in_hr: float
