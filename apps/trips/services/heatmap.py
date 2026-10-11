"""Weather heatmap along the trip corridor for the next 0-48 hours.

The server samples a ribbon of points around every route (centre line plus a
line on each side), fetches hourly weather once, classifies risk for every hour,
and returns it all in one payload so the client can scrub the slider without
any further network calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..domain import geometry as geo
from ..domain.errors import InvalidRequest
from ..domain.models import Coord
from ..domain.risk import RiskLevel, assess
from ..domain.sampling import corridor_spacing
from .weather import WeatherService, WeatherWindow


@dataclass(frozen=True)
class HeatmapRequest:
    paths: list[list[Coord]]
    departure: datetime
    load_weight_lbs: int
    hours: int = 48


@dataclass
class HeatPoint:
    lat: float
    lon: float
    wind_mph: list[float]
    rain_in_hr: list[float]
    snow_in_hr: list[float]
    levels: dict[str, list[int]]  # overall / wind / rain / snow


@dataclass
class HeatmapResult:
    start: datetime
    hours: int
    points: list[HeatPoint]
    hourly_max_level: list[int]


class HeatmapService:
    def __init__(
        self,
        weather: WeatherService,
        max_points: int = 240,
        corridor_half_width_miles: float = 15.0,
        forecast_horizon_days: int = 15,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._weather = weather
        self._max_points = max_points
        self._half_width = corridor_half_width_miles
        self._horizon = forecast_horizon_days
        self._clock = clock

    def build(self, req: HeatmapRequest) -> HeatmapResult:
        start = req.departure.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        now = self._clock()
        if start < now - timedelta(hours=25):
            raise InvalidRequest("Departure time is too far in the past to forecast.")
        available = int((now + timedelta(days=self._horizon) - start).total_seconds() // 3600)
        hours = min(req.hours, available)
        if hours < 1:
            raise InvalidRequest("Departure is beyond the forecast range.")

        coords = self._corridor_points(req.paths)
        window = WeatherWindow.for_trip(start, start + timedelta(hours=hours))
        series = self._weather.fetch(coords, window)

        points: list[HeatPoint] = []
        hourly_max = [0] * (hours + 1)
        for (lat, lon), hourly in zip(coords, series):
            wind, rain, snow = [], [], []
            levels = {"overall": [], "wind": [], "rain": [], "snow": []}
            for h in range(hours + 1):
                s = hourly.sample(start + timedelta(hours=h))
                a = assess(s, req.load_weight_lbs)
                wind.append(round(s.wind_mph, 1))
                rain.append(round(s.rain_in_hr, 3))
                snow.append(round(s.snow_in_hr, 3))
                levels["overall"].append(int(a.overall))
                levels["wind"].append(int(a.wind))
                levels["rain"].append(int(a.rain))
                levels["snow"].append(int(a.snow))
                hourly_max[h] = max(hourly_max[h], int(a.overall))
            points.append(HeatPoint(round(lat, 4), round(lon, 4), wind, rain, snow, levels))
        return HeatmapResult(start, hours, points, hourly_max)

    # ------------------------------------------------------------------
    def _corridor_points(self, paths: list[list[Coord]]) -> list[Coord]:
        cums = [geo.cumulative_miles(p) for p in paths]
        offsets = (-self._half_width, 0.0, self._half_width)
        spacing = corridor_spacing(sum(c[-1] for c in cums), len(offsets), self._max_points)

        seen: set[tuple[int, int]] = set()
        out: list[Coord] = []
        for path, cum in zip(paths, cums):
            total = cum[-1]
            marks = [0.0]
            m = spacing
            while m < total:
                marks.append(m)
                m += spacing
            marks.append(total)
            for mark in marks:
                for off in offsets:
                    p = geo.offset_perpendicular(path, cum, mark, off)
                    key = (math.floor(p[0] / 0.05), math.floor(p[1] / 0.05))
                    if key not in seen:
                        seen.add(key)
                        out.append(p)

        if len(out) > self._max_points:
            stride = math.ceil(len(out) / self._max_points)
            out = out[::stride]
        return out
