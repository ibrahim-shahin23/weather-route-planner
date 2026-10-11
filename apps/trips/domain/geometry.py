"""Geodesy helpers. Pure functions on (lat, lon) tuples, distances in miles."""
from __future__ import annotations

import math
from bisect import bisect_left
from typing import Sequence

from .models import Coord

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(a: Coord, b: Coord) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(coords: Sequence[Coord]) -> list[float]:
    """cum[i] = distance along the path from coords[0] to coords[i]."""
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_miles(coords[i - 1], coords[i]))
    return cum


def point_at(coords: Sequence[Coord], cum: Sequence[float], miles: float) -> Coord:
    """Point `miles` along the path (clamped to the ends)."""
    if miles <= 0:
        return coords[0]
    if miles >= cum[-1]:
        return coords[-1]
    i = bisect_left(cum, miles)
    seg = cum[i] - cum[i - 1]
    if seg <= 0:
        return coords[i]
    f = (miles - cum[i - 1]) / seg
    a, b = coords[i - 1], coords[i]
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def slice_path(coords: Sequence[Coord], cum: Sequence[float], start: float, end: float) -> list[Coord]:
    """Sub-path between two distances along the path (inclusive of both ends)."""
    start = max(0.0, start)
    end = min(cum[-1], end)
    out = [point_at(coords, cum, start)]
    lo = bisect_left(cum, start)
    hi = bisect_left(cum, end)
    for i in range(lo, hi):
        if cum[i] > start:
            out.append(coords[i])
    out.append(point_at(coords, cum, end))
    return out


def sample_along(coords: Sequence[Coord], cum: Sequence[float], step_miles: float) -> list[Coord]:
    """Evenly spaced points along a path, always including the first and last."""
    total = cum[-1]
    pts = [coords[0]]
    d = step_miles
    while d < total:
        pts.append(point_at(coords, cum, d))
        d += step_miles
    pts.append(coords[-1])
    return pts


def _planar(p: Coord, lat0: float) -> tuple[float, float]:
    return (p[1] * math.cos(math.radians(lat0)), p[0])


def _seg_distance(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def simplify(coords: Sequence[Coord], tolerance_deg: float = 0.0004) -> list[Coord]:
    """Ramer-Douglas-Peucker (iterative). ~0.0004 deg is roughly 45 m."""
    n = len(coords)
    if n < 3:
        return list(coords)
    lat0 = coords[0][0]
    pts = [_planar(c, lat0) for c in coords]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        dmax, idx = 0.0, -1
        for i in range(s + 1, e):
            d = _seg_distance(pts[i], pts[s], pts[e])
            if d > dmax:
                dmax, idx = d, i
        if idx != -1 and dmax > tolerance_deg:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [c for c, k in zip(coords, keep) if k]


def bearing_deg(a: Coord, b: Coord) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination_point(origin: Coord, bearing: float, miles: float) -> Coord:
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    brg = math.radians(bearing)
    ang = miles / EARTH_RADIUS_MILES
    lat2 = math.asin(math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0)


def offset_perpendicular(coords: Sequence[Coord], cum: Sequence[float], miles: float, offset_miles: float) -> Coord:
    """Point at `miles` along the path, shifted sideways (positive = right of travel)."""
    here = point_at(coords, cum, miles)
    if offset_miles == 0:
        return here
    behind = point_at(coords, cum, max(0.0, miles - 2.0))
    ahead = point_at(coords, cum, min(cum[-1], miles + 2.0))
    heading = bearing_deg(behind, ahead) if behind != ahead else 0.0
    side = 90.0 if offset_miles > 0 else -90.0
    return destination_point(here, (heading + side) % 360.0, abs(offset_miles))


# --- route similarity -------------------------------------------------------

def _cell(p: Coord, size: float) -> tuple[int, int]:
    return (int(math.floor(p[0] / size)), int(math.floor(p[1] / size)))


def cell_set(coords: Sequence[Coord], cum: Sequence[float], size_deg: float = 0.02) -> set[tuple[int, int]]:
    """Grid cells touched by a path, sampled each mile so long segments are not skipped."""
    return {_cell(p, size_deg) for p in sample_along(coords, cum, 1.0)}


def diverging_miles(
    coords: Sequence[Coord], cum: Sequence[float], reference_cells: set[tuple[int, int]], size_deg: float = 0.02
) -> float:
    """Approximate miles of `coords` that are NOT near the reference path."""
    far = 0
    for p in sample_along(coords, cum, 1.0):
        cx, cy = _cell(p, size_deg)
        near = any((cx + dx, cy + dy) in reference_cells for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        if not near:
            far += 1
    return float(far)
