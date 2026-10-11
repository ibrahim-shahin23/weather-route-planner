"""Result objects produced by the analysis services."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .models import Coord, Place, WeatherSample
from .risk import RiskAssessment, RiskLevel


@dataclass(frozen=True)
class Checkpoint:
    index: int
    mile: float
    coord: Coord
    eta: datetime
    weather: WeatherSample
    risk: RiskAssessment
    covers_from: float
    covers_to: float


@dataclass(frozen=True)
class RiskSegment:
    """A run of consecutive road with the same risk level (for map colouring)."""

    level: RiskLevel
    from_mile: float
    to_mile: float
    path: list[Coord]


@dataclass
class RouteAnalysis:
    id: str
    name: str
    geometry: list[Coord]
    distance_miles: float
    duration_s: float
    departure: datetime
    arrival: datetime
    interval_miles: int
    checkpoints: list[Checkpoint]
    risk_segments: list[RiskSegment]
    miles_by_level: list[float]  # indexed by RiskLevel value
    avg_risk: float  # mile-weighted mean of level values, 0..4
    max_level: RiskLevel
    rank: int = 0
    recommended: bool = False

    @property
    def no_travel_miles(self) -> float:
        return self.miles_by_level[RiskLevel.NO_TRAVEL]

    @property
    def severe_miles(self) -> float:
        return self.miles_by_level[RiskLevel.SEVERE]

    @property
    def high_miles(self) -> float:
        return self.miles_by_level[RiskLevel.HIGH]


@dataclass(frozen=True)
class Recommendation:
    route_id: str
    headline: str
    reasons: list[str]
    warnings: list[str]


@dataclass
class AnalysisResult:
    origin: Place
    destination: Place
    departure: datetime
    load_weight_lbs: int
    routes: list[RouteAnalysis]
    recommendation: Recommendation
    warnings: list[str] = field(default_factory=list)
