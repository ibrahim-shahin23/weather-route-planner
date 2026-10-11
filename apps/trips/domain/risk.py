"""Weather risk rules.

Single source of truth for the thresholds and load rules in the brief. The API
exposes `describe_rules()` so the UI legend never drifts from the logic.

Boundary convention
-------------------
The brief's ranges share edges (e.g. rain "0.10-0.25" and "0.25-0.50"). We treat
every band as lower-bound inclusive, so 0.25 in/hr is High. The two "No Travel"
cells are written differently in the brief and we follow them literally:
wind is ">= 55 mph" (inclusive) while rain ">1.00" and snow ">3.0" are exclusive,
so exactly 1.00 in/hr of rain is still Severe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .models import WeatherSample


class RiskLevel(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    RiskLevel.LOW: "Low",
    RiskLevel.MODERATE: "Moderate",
    RiskLevel.HIGH: "High",
    RiskLevel.SEVERE: "Severe",
    RiskLevel.NO_TRAVEL: "No Travel",
}


@dataclass(frozen=True)
class Thresholds:
    """Lower bounds of each band. Below `moderate` is Low."""

    moderate: float
    high: float
    severe: float
    no_travel: float
    no_travel_inclusive: bool
    unit: str

    def classify(self, value: float) -> RiskLevel:
        blocked = value >= self.no_travel if self.no_travel_inclusive else value > self.no_travel
        if blocked:
            return RiskLevel.NO_TRAVEL
        if value >= self.severe:
            return RiskLevel.SEVERE
        if value >= self.high:
            return RiskLevel.HIGH
        if value >= self.moderate:
            return RiskLevel.MODERATE
        return RiskLevel.LOW


WIND = Thresholds(moderate=25, high=35, severe=45, no_travel=55, no_travel_inclusive=True, unit="mph")
RAIN = Thresholds(moderate=0.10, high=0.25, severe=0.50, no_travel=1.00, no_travel_inclusive=False, unit="in/hr")
SNOW = Thresholds(moderate=0.5, high=1.0, severe=2.0, no_travel=3.0, no_travel_inclusive=False, unit="in/hr")

# Load rules (pounds). Both apply to wind only, as in the brief.
NO_TRAVEL_LOAD_IN_SEVERE_WIND_LBS = 30_000  # 45-54 mph and heavier than this -> No Travel
SEVERE_LOAD_IN_HIGH_WIND_LBS = 40_000  # 35-44 mph and heavier than this -> Severe


@dataclass(frozen=True)
class RiskAssessment:
    wind: RiskLevel
    rain: RiskLevel
    snow: RiskLevel
    overall: RiskLevel
    reasons: tuple[str, ...]


def assess_wind(wind_mph: float, load_lbs: float) -> tuple[RiskLevel, str | None]:
    """Wind level including the load rules. Returns (level, load-rule note)."""
    level = WIND.classify(wind_mph)
    if WIND.severe <= wind_mph < WIND.no_travel and load_lbs > NO_TRAVEL_LOAD_IN_SEVERE_WIND_LBS:
        return RiskLevel.NO_TRAVEL, f"load over {NO_TRAVEL_LOAD_IN_SEVERE_WIND_LBS:,} lb in {WIND.severe:g}-54 mph wind"
    if WIND.high <= wind_mph < WIND.severe and load_lbs > SEVERE_LOAD_IN_HIGH_WIND_LBS:
        return max(level, RiskLevel.SEVERE), f"load over {SEVERE_LOAD_IN_HIGH_WIND_LBS:,} lb in {WIND.high:g}-44 mph wind"
    return level, None


def assess(sample: WeatherSample, load_lbs: float) -> RiskAssessment:
    wind, load_note = assess_wind(sample.wind_mph, load_lbs)
    rain = RAIN.classify(sample.rain_in_hr)
    snow = SNOW.classify(sample.snow_in_hr)
    overall = max(wind, rain, snow)

    reasons: list[str] = []
    if wind >= RiskLevel.MODERATE:
        note = f" (load rule: {load_note})" if load_note else ""
        reasons.append(f"Wind {sample.wind_mph:.0f} mph is {wind.label}{note}")
    if rain >= RiskLevel.MODERATE:
        reasons.append(f"Rain {sample.rain_in_hr:.2f} in/hr is {rain.label}")
    if snow >= RiskLevel.MODERATE:
        reasons.append(f"Snow {sample.snow_in_hr:.2f} in/hr is {snow.label}")
    return RiskAssessment(wind, rain, snow, overall, tuple(reasons))


def describe_rules() -> dict:
    """Machine-readable rules for the UI legend."""

    def row(name: str, t: Thresholds) -> dict:
        return {
            "condition": name,
            "unit": t.unit,
            "moderate_from": t.moderate,
            "high_from": t.high,
            "severe_from": t.severe,
            "no_travel": t.no_travel,
            "no_travel_inclusive": t.no_travel_inclusive,
        }

    return {
        "levels": [{"value": int(l), "label": l.label} for l in RiskLevel],
        "thresholds": [row("wind", WIND), row("rain", RAIN), row("snow", SNOW)],
        "load_rules": [
            {"text": "Wind of 55 mph or more is No Travel for any load"},
            {"text": f"Wind 45-54 mph with a load over {NO_TRAVEL_LOAD_IN_SEVERE_WIND_LBS:,} lb is No Travel"},
            {"text": f"Wind 35-44 mph with a load over {SEVERE_LOAD_IN_HIGH_WIND_LBS:,} lb is Severe"},
        ],
    }
