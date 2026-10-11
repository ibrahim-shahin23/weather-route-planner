"""Produce up to three distinct route options between two places.

1. Ask the routing API for alternatives.
2. If it returns fewer than the target (common on open highways), force extra
   options by routing through a via-point nudged sideways of the best route.
   Detours that are not meaningfully different, or are absurdly long, are dropped.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from ..domain import geometry as geo
from ..domain.errors import DomainError
from ..domain.models import Coord, RawRoute
from ..providers.base import RoutingProvider

log = logging.getLogger(__name__)

_VIA_PATTERN = ((0.5, 1), (0.5, -1), (0.3, 1), (0.7, -1), (0.3, -1), (0.7, 1))  # (fraction along route, side)


class RouteFinder:
    def __init__(self, router: RoutingProvider, target: int = 3, max_workers: int = 4):
        self._router = router
        self._target = target
        self._workers = max_workers

    def find(self, origin: Coord, destination: Coord) -> tuple[list[RawRoute], list[str]]:
        routes = list(self._router.routes([origin, destination], alternatives=self._target))[: self._target]
        warnings: list[str] = []

        if len(routes) < self._target:
            routes = self._add_detours(origin, destination, routes)

        routes.sort(key=lambda r: r.duration_s)
        if len(routes) < self._target:
            warnings.append(
                f"Only {len(routes)} distinct route{'s' if len(routes) != 1 else ''} could be found for this trip."
            )
        return routes, warnings

    # ------------------------------------------------------------------
    def _add_detours(self, origin: Coord, destination: Coord, routes: list[RawRoute]) -> list[RawRoute]:
        base = routes[0]
        cum = geo.cumulative_miles(base.coords)
        total = cum[-1]
        sideways = min(60.0, max(8.0, 0.12 * total))
        vias = [geo.offset_perpendicular(base.coords, cum, total * f, side * sideways) for f, side in _VIA_PATTERN]

        def attempt(via: Coord) -> RawRoute | None:
            try:
                return self._router.routes([origin, via, destination], alternatives=0)[0]
            except DomainError as exc:
                log.info("detour via %s failed: %s", via, exc.message)
                return None

        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            candidates = list(pool.map(attempt, vias))

        accepted = list(routes)
        cell_sets = [geo.cell_set(r.coords, geo.cumulative_miles(r.coords)) for r in accepted]
        for cand in candidates:
            if cand is None or len(accepted) >= self._target:
                continue
            if not self._reasonable(cand, base):
                continue
            ccum = geo.cumulative_miles(cand.coords)
            threshold = max(3.0, 0.03 * ccum[-1])
            if all(geo.diverging_miles(cand.coords, ccum, cells) >= threshold for cells in cell_sets):
                accepted.append(cand)
                cell_sets.append(geo.cell_set(cand.coords, ccum))
        return accepted

    @staticmethod
    def _reasonable(candidate: RawRoute, base: RawRoute) -> bool:
        return candidate.distance_miles <= 1.5 * base.distance_miles + 5 and candidate.duration_s <= 1.75 * base.duration_s + 600
