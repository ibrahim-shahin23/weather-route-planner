"""Checkpoint placement along a route."""
from __future__ import annotations

import math

ALLOWED_INTERVALS = (10, 25, 50)


def resolve_interval(requested: int | None, total_miles: float) -> int:
    """Use the requested 10/25/50 mile spacing, or pick one from the trip length
    so short trips get fine detail and cross-country trips stay fast."""
    if requested is not None:
        if requested not in ALLOWED_INTERVALS:
            raise ValueError(f"interval must be one of {ALLOWED_INTERVALS}")
        return requested
    if total_miles <= 150:
        return 10
    if total_miles <= 500:
        return 25
    return 50


def checkpoint_miles(total_miles: float, interval: float) -> list[float]:
    """Positions (miles from origin) of checkpoints: the origin, every `interval`
    miles, and always the destination."""
    if total_miles <= 0:
        return [0.0]
    marks = [0.0]
    k = 1
    while k * interval < total_miles - 0.5:
        marks.append(float(k * interval))
        k += 1
    marks.append(total_miles)
    return marks


def coverage(marks: list[float]) -> list[tuple[float, float]]:
    """The stretch of road each checkpoint is responsible for: from the midpoint
    with the previous checkpoint to the midpoint with the next one."""
    out = []
    for i, m in enumerate(marks):
        start = 0.0 if i == 0 else (marks[i - 1] + m) / 2
        end = marks[-1] if i == len(marks) - 1 else (m + marks[i + 1]) / 2
        out.append((start, end))
    return out


def corridor_spacing(total_path_miles: float, lateral_lines: int, max_points: int, min_spacing: float = 10.0) -> float:
    """Spacing for heatmap sampling that keeps the point count under budget."""
    needed = total_path_miles * lateral_lines / max(1, max_points)
    return max(min_spacing, math.ceil(needed))
