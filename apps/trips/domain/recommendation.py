"""Route ranking and the human-readable explanation of the choice.

Order of preference (from the brief):
    1. fewest Severe miles
    2. fewest High miles
    3. lowest average risk
    4. shortest travel time

One deliberate addition: "No Travel" miles outrank everything. No Travel is
strictly worse than Severe, so a route with zero Severe miles but a No Travel
stretch must never beat a route that is merely Severe.

Values are rounded before comparing (whole miles, 0.05 risk) so that
sub-mile differences from sampling do not override a clearly shorter route.
"""
from __future__ import annotations

from typing import Sequence

from .results import Recommendation, RouteAnalysis


def _key(r: RouteAnalysis) -> tuple:
    return (
        round(r.no_travel_miles),
        round(r.severe_miles),
        round(r.high_miles),
        round(r.avg_risk * 20) / 20,  # 0.05 steps
        r.duration_s,
    )


_CRITERIA = (
    ("No Travel miles", 0, "{:.0f} mi"),
    ("Severe miles", 1, "{:.0f} mi"),
    ("High-risk miles", 2, "{:.0f} mi"),
    ("average risk", 3, "{:.2f}"),
)


def rank_routes(routes: Sequence[RouteAnalysis]) -> list[RouteAnalysis]:
    ordered = sorted(routes, key=_key)
    for i, r in enumerate(ordered, start=1):
        r.rank = i
        r.recommended = i == 1
    return ordered


def _fmt_duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def recommend(ranked: Sequence[RouteAnalysis]) -> Recommendation:
    """`ranked` must come from `rank_routes` (best first)."""
    best = ranked[0]
    reasons: list[str] = []
    warnings: list[str] = []

    if len(ranked) == 1:
        reasons.append("Only one route was available for this trip.")
    else:
        runner = ranked[1]
        kb, kr = _key(best), _key(runner)
        for label, idx, fmt in _CRITERIA:
            if kb[idx] < kr[idx]:
                reasons.append(
                    f"Lowest {label}: {fmt.format(kb[idx])} vs {fmt.format(kr[idx])} on {runner.name}."
                )
                break
        else:
            if kb[:4] == kr[:4]:
                reasons.append(f"Weather exposure is equal to {runner.name}, so the shorter drive wins.")
        fastest = min(ranked, key=lambda r: r.duration_s)
        if fastest.id == best.id:
            reasons.append("It is also the fastest option.")
        else:
            extra = best.duration_s - fastest.duration_s
            reasons.append(f"Costs {_fmt_duration(extra)} more than the fastest route ({fastest.name}).")

    if best.no_travel_miles >= 0.5:
        warnings.append(
            f"Every route has No Travel conditions at this departure time "
            f"(best case {best.no_travel_miles:.0f} mi). Consider delaying departure."
        )
        headline = f"No safe route at this time. {best.name} is the least bad."
    elif best.severe_miles >= 0.5:
        warnings.append(f"{best.name} still has {best.severe_miles:.0f} mi of Severe conditions.")
        headline = f"{best.name} is the safest option, with caution."
    else:
        headline = f"{best.name} is the safest option."
    return Recommendation(best.id, headline, reasons, warnings)
