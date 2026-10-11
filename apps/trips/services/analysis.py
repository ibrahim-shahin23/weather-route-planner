"""Route analysis: find routes, place checkpoints, forecast each one at the
truck's ETA, classify risk, and recommend a route."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..domain import geometry as geo
from ..domain.errors import GeocodingError, InvalidRequest
from ..domain.models import Coord, Place, RawRoute
from ..domain.recommendation import rank_routes, recommend
from ..domain.results import AnalysisResult, Checkpoint, RiskSegment, RouteAnalysis
from ..domain.risk import RiskLevel, assess
from ..domain.sampling import checkpoint_miles, coverage, resolve_interval
from ..providers.base import GeocodingProvider
from .route_finder import RouteFinder
from .weather import WeatherService, WeatherWindow


@dataclass(frozen=True)
class LocationRef:
    """Either resolved coordinates or free text to geocode."""

    query: str | None = None
    lat: float | None = None
    lon: float | None = None
    label: str | None = None


@dataclass(frozen=True)
class AnalysisRequest:
    origin: LocationRef
    destination: LocationRef
    departure: datetime
    load_weight_lbs: int
    sample_interval_miles: int | None = None


@dataclass(frozen=True)
class AnalysisSettings:
    truck_duration_multiplier: float = 1.15  # OSRM's car profile is optimistic for loaded trucks
    geometry_tolerance_deg: float = 0.0004
    forecast_horizon_days: int = 15
    past_tolerance_hours: int = 24


@dataclass
class _Plan:
    raw: RawRoute
    coords: list[Coord]
    cum: list[float]
    total: float
    duration_s: float
    interval: int
    marks: list[float]
    points: list[Coord]
    etas: list[datetime]


class AnalysisService:
    def __init__(
        self,
        geocoder: GeocodingProvider,
        route_finder: RouteFinder,
        weather: WeatherService,
        settings: AnalysisSettings = AnalysisSettings(),
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._geocoder = geocoder
        self._finder = route_finder
        self._weather = weather
        self._s = settings
        self._clock = clock

    # ------------------------------------------------------------------
    def analyze(self, req: AnalysisRequest) -> AnalysisResult:
        departure = req.departure.astimezone(timezone.utc)
        now = self._clock()
        if departure < now - timedelta(hours=self._s.past_tolerance_hours):
            raise InvalidRequest("Departure time is too far in the past to forecast.")

        origin = self._resolve(req.origin, "origin")
        destination = self._resolve(req.destination, "destination")

        raw_routes, warnings = self._finder.find(origin.coord, destination.coord)
        plans = [self._plan(raw, departure, req.sample_interval_miles) for raw in raw_routes]

        latest_eta = max(p.etas[-1] for p in plans)
        if latest_eta > now + timedelta(days=self._s.forecast_horizon_days):
            raise InvalidRequest(
                f"Weather forecasts reach about {self._s.forecast_horizon_days} days ahead, "
                "but this trip would arrive after that. Choose an earlier departure."
            )

        # One batched weather call for every checkpoint of every route.
        all_points = [pt for p in plans for pt in p.points]
        series = self._weather.fetch(all_points, WeatherWindow.for_trip(departure, latest_eta))

        routes: list[RouteAnalysis] = []
        offset = 0
        for i, plan in enumerate(plans):
            plan_series = series[offset : offset + len(plan.points)]
            offset += len(plan.points)
            routes.append(self._assemble(i, plan, plan_series, departure, req.load_weight_lbs))

        ranked = rank_routes(routes)
        recommendation = recommend(ranked)
        return AnalysisResult(
            origin=origin,
            destination=destination,
            departure=departure,
            load_weight_lbs=req.load_weight_lbs,
            routes=routes,  # kept in fastest-first order; `rank` marks the recommendation order
            recommendation=recommendation,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    def _resolve(self, ref: LocationRef, role: str) -> Place:
        if ref.lat is not None and ref.lon is not None:
            return Place(ref.label or f"{ref.lat:.4f}, {ref.lon:.4f}", ref.lat, ref.lon)
        if ref.query:
            hits = self._geocoder.search(ref.query, limit=1)
            if hits:
                return hits[0]
        raise GeocodingError(f"Could not find the {role} location. Try a more specific address or pick a suggestion.")

    def _plan(self, raw: RawRoute, departure: datetime, requested_interval: int | None) -> _Plan:
        cum = geo.cumulative_miles(raw.coords)
        total = cum[-1]
        duration = raw.duration_s * self._s.truck_duration_multiplier
        interval = resolve_interval(requested_interval, total)
        marks = checkpoint_miles(total, interval)
        points = [geo.point_at(raw.coords, cum, m) for m in marks]
        etas = [departure + timedelta(seconds=duration * (m / total if total else 0.0)) for m in marks]
        return _Plan(raw, raw.coords, cum, total, duration, interval, marks, points, etas)

    def _assemble(self, index: int, plan: _Plan, series, departure: datetime, load_lbs: int) -> RouteAnalysis:
        spans = coverage(plan.marks)
        checkpoints: list[Checkpoint] = []
        miles_by_level = [0.0] * len(RiskLevel)

        for i, (mark, point, eta, hourly, (c_from, c_to)) in enumerate(zip(plan.marks, plan.points, plan.etas, series, spans)):
            sample = hourly.sample(eta)
            risk = assess(sample, load_lbs)
            checkpoints.append(Checkpoint(i, mark, point, eta, sample, risk, c_from, c_to))
            miles_by_level[risk.overall] += c_to - c_from

        total = plan.total or 1.0
        avg_risk = sum(level * miles for level, miles in enumerate(miles_by_level)) / total
        return RouteAnalysis(
            id=f"route-{index + 1}",
            name=f"Route {chr(ord('A') + index)}",
            geometry=geo.simplify(plan.coords, self._s.geometry_tolerance_deg),
            distance_miles=plan.total,
            duration_s=plan.duration_s,
            departure=departure,
            arrival=plan.etas[-1],
            interval_miles=plan.interval,
            checkpoints=checkpoints,
            risk_segments=self._segments(plan, checkpoints),
            miles_by_level=miles_by_level,
            avg_risk=avg_risk,
            max_level=max(c.risk.overall for c in checkpoints),
        )

    def _segments(self, plan: _Plan, checkpoints: list[Checkpoint]) -> list[RiskSegment]:
        """Merge consecutive same-level checkpoints into coloured map segments."""
        segments: list[RiskSegment] = []
        run_start = 0
        for i in range(1, len(checkpoints) + 1):
            if i == len(checkpoints) or checkpoints[i].risk.overall != checkpoints[run_start].risk.overall:
                first, last = checkpoints[run_start], checkpoints[i - 1]
                path = geo.simplify(geo.slice_path(plan.coords, plan.cum, first.covers_from, last.covers_to), self._s.geometry_tolerance_deg)
                segments.append(RiskSegment(first.risk.overall, first.covers_from, last.covers_to, path))
                run_start = i
        return segments
