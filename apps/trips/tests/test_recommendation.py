import unittest
from datetime import datetime, timezone

from ..domain.recommendation import rank_routes, recommend
from ..domain.results import RouteAnalysis
from ..domain.risk import RiskLevel


def make(rid, minutes, low=100.0, mod=0.0, high=0.0, severe=0.0, no_travel=0.0):
    miles = [low, mod, high, severe, no_travel]
    total = sum(miles)
    avg = sum(i * m for i, m in enumerate(miles)) / total
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    return RouteAnalysis(
        id=rid, name=f"Route {rid}", geometry=[], distance_miles=total, duration_s=minutes * 60,
        departure=now, arrival=now, interval_miles=25, checkpoints=[], risk_segments=[],
        miles_by_level=miles, avg_risk=avg, max_level=RiskLevel.LOW,
    )


class RankingTests(unittest.TestCase):
    def test_fewest_severe_beats_everything_else(self):
        a = make("A", 100, severe=20, low=80)
        b = make("B", 300, severe=0, high=100, low=0)
        self.assertEqual(rank_routes([a, b])[0].id, "B")

    def test_high_miles_break_severe_ties(self):
        a = make("A", 100, high=40, low=60)
        b = make("B", 300, high=10, low=90)
        self.assertEqual(rank_routes([a, b])[0].id, "B")

    def test_average_risk_breaks_high_ties(self):
        a = make("A", 100, mod=50, low=50)
        b = make("B", 300, mod=10, low=90)
        self.assertEqual(rank_routes([a, b])[0].id, "B")

    def test_travel_time_is_last_tiebreaker(self):
        a = make("A", 300)
        b = make("B", 200)
        self.assertEqual(rank_routes([a, b])[0].id, "B")

    def test_no_travel_is_worse_than_severe(self):
        blocked = make("A", 100, no_travel=10, low=90)
        severe = make("B", 300, severe=10, low=90)
        self.assertEqual(rank_routes([blocked, severe])[0].id, "B")

    def test_sub_mile_differences_are_ties(self):
        a = make("A", 300, high=10.2, low=89.8)
        b = make("B", 200, high=10.4, low=89.6)
        self.assertEqual(rank_routes([a, b])[0].id, "B")

    def test_rank_and_flag_assigned(self):
        ordered = rank_routes([make("A", 300, severe=5, low=95), make("B", 200)])
        self.assertEqual([r.rank for r in ordered], [1, 2])
        self.assertEqual([r.recommended for r in ordered], [True, False])


class ExplanationTests(unittest.TestCase):
    def test_reason_names_deciding_criterion(self):
        ranked = rank_routes([make("A", 100, severe=20, low=80), make("B", 150)])
        rec = recommend(ranked)
        self.assertEqual(rec.route_id, "B")
        self.assertTrue(any("Severe miles" in r for r in rec.reasons))
        self.assertTrue(any("more than the fastest" in r for r in rec.reasons))

    def test_warns_when_all_routes_blocked(self):
        ranked = rank_routes([make("A", 100, no_travel=30, low=70), make("B", 100, no_travel=40, low=60)])
        rec = recommend(ranked)
        self.assertTrue(rec.warnings)
        self.assertIn("No safe route", rec.headline)

    def test_single_route(self):
        rec = recommend(rank_routes([make("A", 100)]))
        self.assertEqual(rec.route_id, "A")


if __name__ == "__main__":
    unittest.main()
