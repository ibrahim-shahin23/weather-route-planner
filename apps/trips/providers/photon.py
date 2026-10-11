"""Geocoding via Photon (OpenStreetMap data, built for type-ahead search)."""
from __future__ import annotations

import requests

from ..domain.errors import UpstreamUnavailable
from ..domain.models import Place
from .base import GeocodingProvider

# minLon, minLat, maxLon, maxLat: North America, matching the mph / inches units.
NORTH_AMERICA_BBOX = "-170,15,-50,72"


class PhotonGeocoder(GeocodingProvider):
    def __init__(self, session: requests.Session, base_url: str, timeout: float = 8.0, bbox: str | None = NORTH_AMERICA_BBOX):
        self._session = session
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._bbox = bbox

    def search(self, query: str, limit: int = 5) -> list[Place]:
        params = {"q": query, "limit": limit, "lang": "en"}
        if self._bbox:
            params["bbox"] = self._bbox
        try:
            resp = self._session.get(f"{self._base}/api/", params=params, timeout=self._timeout)
            resp.raise_for_status()
            features = resp.json().get("features", [])
        except (requests.RequestException, ValueError) as exc:
            raise UpstreamUnavailable(f"Geocoding service is unavailable: {exc}") from exc

        places: list[Place] = []
        seen: set[str] = set()
        for f in features:
            try:
                lon, lat = f["geometry"]["coordinates"]
                label = self._label(f.get("properties", {}))
            except (KeyError, ValueError, TypeError):
                continue
            if not label or label in seen:
                continue
            seen.add(label)
            places.append(Place(label=label, lat=float(lat), lon=float(lon)))
        return places

    @staticmethod
    def _label(p: dict) -> str:
        street = " ".join(x for x in (p.get("housenumber"), p.get("street")) if x)
        parts = [p.get("name"), street, p.get("city") or p.get("town") or p.get("village") or p.get("county"), p.get("state"), p.get("country")]
        out: list[str] = []
        for part in parts:
            if part and part not in out:
                out.append(part)
        return ", ".join(out)
