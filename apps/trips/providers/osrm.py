"""Routing via an OSRM server (the public demo by default; self-host for production)."""
from __future__ import annotations

from typing import Sequence

import requests

from ..domain.errors import RoutingError, UpstreamUnavailable
from ..domain.models import Coord, RawRoute
from .base import RoutingProvider

METERS_PER_MILE = 1609.344


class OsrmRouter(RoutingProvider):
    def __init__(self, session: requests.Session, base_url: str, timeout: float = 25.0, profile: str = "driving"):
        self._session = session
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._profile = profile

    def routes(self, waypoints: Sequence[Coord], alternatives: int = 0) -> list[RawRoute]:
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in waypoints)
        url = f"{self._base}/route/v1/{self._profile}/{coords}"
        payload = self._request(url, alternatives)

        code = payload.get("code")
        if code == "NoRoute":
            raise RoutingError("No drivable route was found between these locations.")
        if code != "Ok":
            raise RoutingError(payload.get("message") or f"Routing failed ({code}).")

        routes = [
            RawRoute(
                coords=[(lat, lon) for lon, lat in r["geometry"]["coordinates"]],
                distance_miles=r["distance"] / METERS_PER_MILE,
                duration_s=float(r["duration"]),
            )
            for r in payload.get("routes", [])
        ]
        if not routes:
            raise RoutingError("No drivable route was found between these locations.")
        return routes

    def _request(self, url: str, alternatives: int) -> dict:
        # Newer OSRM accepts a number of alternatives; older builds only accept
        # true/false, so a 400 on the numeric form falls back to `true`.
        attempts = ["false"] if alternatives <= 0 else [str(alternatives), "true"] if alternatives > 1 else ["true"]
        try:
            for i, alt in enumerate(attempts):
                params = {"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": alt}
                resp = self._session.get(url, params=params, timeout=self._timeout)
                if resp.status_code == 400 and i < len(attempts) - 1:
                    continue
                if resp.status_code in (400, 422):
                    raise RoutingError(resp.json().get("message") or "The routing service rejected this request.")
                resp.raise_for_status()
                return resp.json()
        except RoutingError:
            raise
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamUnavailable(f"Routing service is unavailable: {exc}") from exc
        raise UpstreamUnavailable("Routing service did not respond.")
