"""Composition root: the only place that knows which concrete providers are used."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from django.core.cache import cache

from .providers.http import build_session
from .providers.open_meteo import OpenMeteoProvider
from .providers.osrm import OsrmRouter
from .providers.photon import PhotonGeocoder
from .services.analysis import AnalysisService, AnalysisSettings
from .services.geocoding import CachingGeocoder
from .services.heatmap import HeatmapService
from .services.route_finder import RouteFinder
from .services.weather import WeatherService


@dataclass(frozen=True)
class Container:
    geocoder: CachingGeocoder
    analysis: AnalysisService
    heatmap: HeatmapService


@lru_cache(maxsize=1)
def get_container() -> Container:
    session = build_session(settings.HTTP_USER_AGENT)

    geocoder = CachingGeocoder(
        PhotonGeocoder(session, settings.PHOTON_BASE_URL),
        cache,
        ttl_s=24 * 3600,
    )
    router = OsrmRouter(session, settings.OSRM_BASE_URL)
    weather_provider = OpenMeteoProvider(
        session,
        base_url=settings.OPEN_METEO_BASE_URL,
        api_key=settings.OPEN_METEO_API_KEY or None,
        wind_metric=settings.WIND_METRIC,
    )
    weather = WeatherService(
        weather_provider,
        cache,
        grid_deg=settings.WEATHER_GRID_DEG,
        ttl_s=settings.WEATHER_CACHE_TTL_S,
        namespace=f"wx-{settings.WIND_METRIC}",
    )
    analysis = AnalysisService(
        geocoder,
        RouteFinder(router, target=3),
        weather,
        AnalysisSettings(truck_duration_multiplier=settings.TRUCK_DURATION_MULTIPLIER),
    )
    heatmap = HeatmapService(
        weather,
        max_points=settings.HEATMAP_MAX_POINTS,
        corridor_half_width_miles=settings.HEATMAP_CORRIDOR_HALF_WIDTH_MILES,
    )
    return Container(geocoder, analysis, heatmap)
