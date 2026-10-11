"""Domain objects -> JSON-ready dicts (the public API contract)."""
from __future__ import annotations

from datetime import datetime, timezone

from ..domain.models import Place
from ..domain.results import AnalysisResult, Checkpoint, RouteAnalysis
from ..domain.risk import RiskLevel
from ..services.heatmap import HeatmapResult


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _place(p: Place) -> dict:
    return {"label": p.label, "lat": round(p.lat, 5), "lon": round(p.lon, 5)}


def _coords(path) -> list[list[float]]:
    return [[round(lat, 5), round(lon, 5)] for lat, lon in path]


def _checkpoint(c: Checkpoint) -> dict:
    return {
        "index": c.index,
        "mile": round(c.mile, 1),
        "lat": round(c.coord[0], 5),
        "lon": round(c.coord[1], 5),
        "eta": iso(c.eta),
        "weather": {
            "wind_mph": round(c.weather.wind_mph, 1),
            "rain_in_hr": round(c.weather.rain_in_hr, 3),
            "snow_in_hr": round(c.weather.snow_in_hr, 3),
        },
        "risk": {
            "overall": int(c.risk.overall),
            "wind": int(c.risk.wind),
            "rain": int(c.risk.rain),
            "snow": int(c.risk.snow),
            "reasons": list(c.risk.reasons),
        },
    }


def _route(r: RouteAnalysis) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "rank": r.rank,
        "recommended": r.recommended,
        "summary": {
            "distance_miles": round(r.distance_miles, 1),
            "duration_s": round(r.duration_s),
            "departure": iso(r.departure),
            "arrival": iso(r.arrival),
            "checkpoint_interval_miles": r.interval_miles,
            "checkpoint_count": len(r.checkpoints),
            "max_level": int(r.max_level),
            "avg_risk": round(r.avg_risk, 2),
            "miles_by_level": {lvl.name.lower(): round(r.miles_by_level[lvl], 1) for lvl in RiskLevel},
        },
        "geometry": _coords(r.geometry),
        "risk_segments": [
            {"level": int(s.level), "from_mile": round(s.from_mile, 1), "to_mile": round(s.to_mile, 1), "path": _coords(s.path)}
            for s in r.risk_segments
        ],
        "checkpoints": [_checkpoint(c) for c in r.checkpoints],
    }


def analysis(result: AnalysisResult) -> dict:
    rec = result.recommendation
    return {
        "origin": _place(result.origin),
        "destination": _place(result.destination),
        "departure": iso(result.departure),
        "load_weight_lbs": result.load_weight_lbs,
        "routes": [_route(r) for r in result.routes],
        "recommendation": {
            "route_id": rec.route_id,
            "headline": rec.headline,
            "reasons": rec.reasons,
            "warnings": rec.warnings,
        },
        "warnings": result.warnings,
    }


def heatmap(result: HeatmapResult) -> dict:
    return {
        "start_time": iso(result.start),
        "hours": result.hours,
        "hourly_max_level": result.hourly_max_level,
        "points": [
            {
                "lat": p.lat,
                "lon": p.lon,
                "wind_mph": p.wind_mph,
                "rain_in_hr": p.rain_in_hr,
                "snow_in_hr": p.snow_in_hr,
                "levels": p.levels,
            }
            for p in result.points
        ],
    }
