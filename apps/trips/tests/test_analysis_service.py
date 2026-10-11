import unittest
from datetime import timedelta

from ..domain.errors import GeocodingError, InvalidRequest
from ..domain.models import Place
from ..domain.risk import RiskLevel
from ..services.analysis import AnalysisRequest, AnalysisService, AnalysisSettings, LocationRef
from ..services.heatmap import HeatmapRequest, HeatmapService
from ..services.route_finder import RouteFinder
from ..services.weather import WeatherService
from .helpers import NOW, DictCache, FakeGeocoder, FakeRouter, FakeWeather, straight_route

A = (40.0, -100.0)
B = (40.0, -98.0)  # roughly 106 miles east


def build(routes, weather_fn=None, detour=None, places=None):
    weather_provider = FakeWeather(weather_fn) if weather_fn else FakeWeather()
    weather = WeatherService(weather_provider, DictCache())
    router = FakeRouter(routes, detour)
    service = AnalysisService(
        FakeGeocoder(places), RouteFinder(router), weather,
        AnalysisSettings(truck_duration_multiplier=1.0), clock=lambda: NOW,
    )
    return service, weather_provider, router, weather


def request(load=30_000, interval=25, departure=None):
    return AnalysisRequest(
        LocationRef(lat=A[0], lon=A[1], label="A"),
        LocationRef(lat=B[0], lon=B[1], label="B"),
        departure or NOW + timedelta(hours=1),
        load,
        interval,
    )


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.r1 = straight_route(A, B, 2 * 3600)
        self.r2 = straight_route(A, B, 3 * 3600, bulge=0.4)
        self.r3 = straight_route(A, B, 4 * 3600, bulge=-0.4)

    def test_checkpoints_etas_and_calm_weather(self):
        svc, *_ = build([self.r1, self.r2, self.r3])
        res = svc.analyze(request())
        self.assertEqual(len(res.routes), 3)
        r = res.routes[0]
        miles = r.distance_miles
        self.assertEqual(r.checkpoints[0].mile, 0)
        self.assertAlmostEqual(r.checkpoints[-1].mile, miles, places=3)
        self.assertEqual(r.checkpoints[-1].eta - r.checkpoints[0].eta, timedelta(hours=2))
        mid = next(c for c in r.checkpoints if c.mile == 50)
        self.assertAlmostEqual((mid.eta - r.departure).total_seconds(), 2 * 3600 * 50 / miles, delta=1)
        self.assertEqual(r.max_level, RiskLevel.LOW)
        self.assertAlmostEqual(sum(r.miles_by_level), miles, places=3)

    def test_weather_is_sampled_at_eta_not_departure(self):
        dep = NOW + timedelta(hours=1)

        def storm_after_two_hours(lat, lon, t):  # strong wind only from dep+2h onward
            return (60.0, 0, 0) if t >= dep + timedelta(hours=2) else (5.0, 0, 0)

        svc, *_ = build([self.r1], storm_after_two_hours)
        res = svc.analyze(request(departure=dep))
        cps = res.routes[0].checkpoints
        self.assertEqual(cps[0].risk.overall, RiskLevel.LOW)
        self.assertEqual(cps[-1].risk.overall, RiskLevel.NO_TRAVEL)  # arrives exactly at dep+2h

    def test_load_rules_applied_per_checkpoint(self):
        svc, *_ = build([self.r1], lambda *_: (50.0, 0, 0))
        heavy = svc.analyze(request(load=35_000)).routes[0]
        light = svc.analyze(request(load=20_000)).routes[0]
        self.assertEqual(heavy.max_level, RiskLevel.NO_TRAVEL)
        self.assertEqual(light.max_level, RiskLevel.SEVERE)

    def test_recommends_route_with_less_severe_weather_even_if_slower(self):
        # Route 1 (fast, lat 40.0) is stormy; the bowed routes (lat > 40.1 mid-route) are calm.
        def wx(lat, lon, t):
            return (50.0, 0, 0) if abs(lat - 40.0) < 0.1 else (5.0, 0, 0)

        svc, *_ = build([self.r1, self.r2, self.r3], wx)
        res = svc.analyze(request(load=10_000))
        self.assertEqual(res.recommendation.route_id, "route-2")
        self.assertTrue(next(r for r in res.routes if r.id == "route-2").recommended)

    def test_one_batched_weather_call_and_dedupe(self):
        svc, provider, _, _ = build([self.r1, self.r2, self.r3])
        svc.analyze(request())
        self.assertEqual(provider.calls, 1)

    def test_risk_segments_cover_route(self):
        svc, *_ = build([self.r1], lambda lat, lon, t: (40.0, 0, 0) if lon > -99 else (5.0, 0, 0))
        r = svc.analyze(request(load=10_000)).routes[0]
        levels = [s.level for s in r.risk_segments]
        self.assertEqual(levels, [RiskLevel.LOW, RiskLevel.HIGH])
        self.assertAlmostEqual(r.risk_segments[0].from_mile, 0)
        self.assertAlmostEqual(r.risk_segments[-1].to_mile, r.distance_miles, places=3)

    def test_detours_fill_missing_alternatives(self):
        def detour(waypoints):
            via = waypoints[1]
            return straight_route(A, B, 3 * 3600, bulge=via[0] - 40.0)

        svc, _, router, _ = build([self.r1], detour=detour)
        res = svc.analyze(request())
        self.assertEqual(len(res.routes), 3)
        self.assertTrue(any(len(w) == 3 for w, _ in router.calls))

    def test_warns_when_fewer_than_three_routes(self):
        svc, *_ = build([self.r1], detour=lambda w: self.r1)  # detours identical to base -> rejected
        res = svc.analyze(request())
        self.assertEqual(len(res.routes), 1)
        self.assertTrue(res.warnings)

    def test_text_location_is_geocoded(self):
        places = {"denver": Place("Denver, CO", 39.74, -104.99)}
        svc, *_ = build([self.r1], places=places)
        req = AnalysisRequest(LocationRef(query="Denver"), LocationRef(lat=B[0], lon=B[1]), NOW + timedelta(hours=1), 10_000, 25)
        self.assertEqual(svc.analyze(req).origin.label, "Denver, CO")
        bad = AnalysisRequest(LocationRef(query="Nowhere"), LocationRef(lat=B[0], lon=B[1]), NOW, 10_000, 25)
        with self.assertRaises(GeocodingError):
            svc.analyze(bad)

    def test_rejects_past_and_far_future_departures(self):
        svc, *_ = build([self.r1])
        with self.assertRaises(InvalidRequest):
            svc.analyze(request(departure=NOW - timedelta(days=3)))
        with self.assertRaises(InvalidRequest):
            svc.analyze(request(departure=NOW + timedelta(days=20)))


class HeatmapTests(unittest.TestCase):
    def test_hourly_levels_and_shape(self):
        weather = WeatherService(FakeWeather(lambda lat, lon, t: (40.0, 0, 0) if t.hour >= 18 else (5.0, 0, 0)), DictCache())
        svc = HeatmapService(weather, max_points=60, clock=lambda: NOW)
        route = straight_route(A, B, 7200)
        dep = NOW.replace(hour=16, minute=30)
        res = svc.build(HeatmapRequest([route.coords], dep, load_weight_lbs=45_000, hours=48))
        self.assertEqual(res.hours, 48)
        self.assertEqual(res.start.hour, 16)
        self.assertLessEqual(len(res.points), 60)
        p = res.points[0]
        self.assertEqual(len(p.levels["overall"]), 49)
        self.assertEqual(p.levels["overall"][0], RiskLevel.LOW)
        self.assertEqual(p.levels["overall"][2], RiskLevel.SEVERE)  # 18:00, 40 mph, >40k lb
        self.assertEqual(res.hourly_max_level[2], RiskLevel.SEVERE)

    def test_clamps_hours_to_forecast_horizon(self):
        weather = WeatherService(FakeWeather(), DictCache())
        svc = HeatmapService(weather, clock=lambda: NOW, forecast_horizon_days=15)
        route = straight_route(A, B, 7200)
        res = svc.build(HeatmapRequest([route.coords], NOW + timedelta(days=14, hours=20), 10_000, 48))
        self.assertEqual(res.hours, 4)


if __name__ == "__main__":
    unittest.main()
