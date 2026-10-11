"""Caching decorator for any GeocodingProvider (type-ahead repeats queries a lot)."""
from __future__ import annotations

import hashlib

from ..domain.models import Place
from ..providers.base import GeocodingProvider
from .weather import Cache


class CachingGeocoder(GeocodingProvider):
    def __init__(self, inner: GeocodingProvider, cache: Cache, ttl_s: int = 86400):
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_s

    def search(self, query: str, limit: int = 5) -> list[Place]:
        norm = " ".join(query.lower().split())
        key = "geo1:" + hashlib.sha1(f"{norm}|{limit}".encode()).hexdigest()
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        places = self._inner.search(query, limit)
        if places:
            self._cache.set(key, places, self._ttl)
        return places
