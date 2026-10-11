"""Hourly weather series for a single location."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import WeatherSample


@dataclass
class HourlySeries:
    """Hourly values starting at `start` (UTC, aligned to the hour)."""

    start: datetime
    wind_mph: list[float]
    rain_in_hr: list[float]
    snow_in_hr: list[float]

    def __len__(self) -> int:
        return len(self.wind_mph)

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=len(self) - 1)

    def covers(self, when: datetime) -> bool:
        return self.start <= when <= self.end

    def at_hour(self, index: int) -> WeatherSample:
        i = max(0, min(index, len(self) - 1))
        return WeatherSample(self.wind_mph[i], self.rain_in_hr[i], self.snow_in_hr[i])

    def sample(self, when: datetime) -> WeatherSample:
        """Linearly interpolate between the two surrounding hours.

        Times outside the series are clamped to its first / last hour.
        """
        pos = (when - self.start).total_seconds() / 3600.0
        pos = max(0.0, min(pos, len(self) - 1.0))
        lo = int(math.floor(pos))
        hi = min(lo + 1, len(self) - 1)
        f = pos - lo

        def lerp(values: list[float]) -> float:
            return values[lo] + (values[hi] - values[lo]) * f

        return WeatherSample(lerp(self.wind_mph), lerp(self.rain_in_hr), lerp(self.snow_in_hr))
