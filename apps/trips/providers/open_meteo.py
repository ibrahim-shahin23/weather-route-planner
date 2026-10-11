"""Hourly weather from Open-Meteo.

Units are requested server-side (mph, inches) so no conversion code is needed.
 - wind: 10 m sustained wind (or gusts, see `wind_metric`)
 - rain: `rain` + `showers`, i.e. liquid precipitation in inches over the previous hour
 - snow: `snowfall`, inches of new snow over the previous hour
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from typing import Sequence

import requests

from ..domain.errors import UpstreamUnavailable
from ..domain.models import Coord
from ..domain.weather import HourlySeries
from .base import WeatherProvider

HOURLY_VARS = "wind_speed_10m,wind_gusts_10m,rain,showers,snowfall"


class OpenMeteoProvider(WeatherProvider):
    def __init__(
        self,
        session: requests.Session,
        base_url: str = "https://api.open-meteo.com/v1/forecast",
        api_key: str | None = None,
        wind_metric: str = "sustained",  # or "gust"
        batch_size: int = 50,
        concurrency: int = 4,
        timeout: float = 25.0,
    ):
        if wind_metric not in ("sustained", "gust"):
            raise ValueError("wind_metric must be 'sustained' or 'gust'")
        self._session = session
        self._url = base_url
        self._key = api_key
        self._wind_metric = wind_metric
        self._batch = batch_size
        self._workers = concurrency
        self._timeout = timeout

    def fetch_hourly(self, points: Sequence[Coord], start_date: date, end_date: date) -> list[HourlySeries]:
        if not points:
            return []
        batches = [list(points[i : i + self._batch]) for i in range(0, len(points), self._batch)]
        if len(batches) == 1:
            return self._fetch_batch(batches[0], start_date, end_date)
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            results = list(pool.map(lambda b: self._fetch_batch(b, start_date, end_date), batches))
        return [s for batch in results for s in batch]

    def _fetch_batch(self, batch: list[Coord], start_date: date, end_date: date) -> list[HourlySeries]:
        params = {
            "latitude": ",".join(f"{lat:.4f}" for lat, _ in batch),
            "longitude": ",".join(f"{lon:.4f}" for _, lon in batch),
            "hourly": HOURLY_VARS,
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "GMT",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        }
        if self._key:
            params["apikey"] = self._key
        try:
            resp = self._session.get(self._url, params=params, timeout=self._timeout)
            if resp.status_code == 400:
                reason = resp.json().get("reason", "bad request")
                raise UpstreamUnavailable(f"Weather forecast unavailable for this time range: {reason}")
            resp.raise_for_status()
            payload = resp.json()
        except UpstreamUnavailable:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamUnavailable(f"Weather service is unavailable: {exc}") from exc

        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) != len(batch):
            raise UpstreamUnavailable("Weather service returned an unexpected number of locations.")
        return [self._parse(e) for e in entries]

    def _parse(self, entry: dict) -> HourlySeries:
        h = entry.get("hourly") or {}
        times = h.get("time") or []
        if not times:
            raise UpstreamUnavailable("Weather service returned no hourly data.")
        n = len(times)

        def col(name: str) -> list[float]:
            raw = h.get(name) or [None] * n
            return [float(v) if v is not None else 0.0 for v in raw]

        wind = col("wind_gusts_10m" if self._wind_metric == "gust" else "wind_speed_10m")
        rain = [r + s for r, s in zip(col("rain"), col("showers"))]
        snow = col("snowfall")
        start = datetime.fromisoformat(times[0]).replace(tzinfo=timezone.utc)
        return HourlySeries(start=start, wind_mph=wind, rain_in_hr=rain, snow_in_hr=snow)
