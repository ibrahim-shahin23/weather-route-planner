"""HTTP-level tests. Run with `DJANGO_DEBUG=1 python manage.py test` (needs Django)."""
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from rest_framework.test import APIClient

from ..services.analysis import AnalysisService, AnalysisSettings
from ..services.geocoding import CachingGeocoder
from ..services.heatmap import HeatmapService
from ..services.route_finder import RouteFinder
from ..services.weather import WeatherService
from .helpers import NOW, DictCache, FakeGeocoder, FakeRouter, FakeWeather, straight_route

A, B = (40.0, -100.0), (40.0, -98.0)


def fake_container():
    weather = WeatherService(FakeWeather(), DictCache())
    routes = [straight_route(A, B, 7200), straight_route(A, B, 9000, bulge=0.4), straight_route(A, B, 10800, bulge=-0.4)]
    analysis = AnalysisService(FakeGeocoder(), RouteFinder(FakeRouter(routes)), weather, AnalysisSettings(1.0), clock=lambda: NOW)
    heatmap = HeatmapService(weather, max_points=40, clock=lambda: NOW)
    return SimpleNamespace(geocoder=CachingGeocoder(FakeGeocoder(), DictCache()), analysis=analysis, heatmap=heatmap)


class ApiTests(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("apps.trips.container.get_container", return_value=fake_container())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = APIClient()
        self.body = {
            "origin": {"lat": A[0], "lon": A[1], "label": "A"},
            "destination": {"lat": B[0], "lon": B[1], "label": "B"},
            "departure": (NOW + timedelta(hours=2)).isoformat(),
            "load_weight_lbs": 42000,
            "sample_interval_miles": 25,
        }

    def test_health(self):
        self.assertEqual(self.client.get("/api/health/").json(), {"status": "ok"})

    def test_risk_rules(self):
        self.assertEqual(len(self.client.get("/api/risk-rules/").json()["thresholds"]), 3)

    def test_analyze_contract(self):
        res = self.client.post("/api/routes/analyze/", self.body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(len(data["routes"]), 3)
        route = data["routes"][0]
        for key in ("summary", "geometry", "risk_segments", "checkpoints", "recommended", "rank"):
            self.assertIn(key, route)
        self.assertEqual(route["checkpoints"][0]["mile"], 0)
        self.assertIn(data["recommendation"]["route_id"], [r["id"] for r in data["routes"]])
        self.assertEqual(sum(r["recommended"] for r in data["routes"]), 1)

    def test_validation_errors_use_envelope(self):
        bad = {**self.body, "load_weight_lbs": -5, "sample_interval_miles": 7}
        res = self.client.post("/api/routes/analyze/", bad, format="json")
        self.assertEqual(res.status_code, 400)
        err = res.json()["error"]
        self.assertEqual(err["code"], "validation_error")
        self.assertIn("load_weight_lbs", err["fields"])
        self.assertIn("sample_interval_miles", err["fields"])

    def test_domain_errors_map_to_status(self):
        body = {**self.body, "origin": {"query": "nowhere"}}
        res = self.client.post("/api/routes/analyze/", body, format="json")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["error"]["code"], "geocoding_failed")

    def test_heatmap_contract(self):
        route = straight_route(A, B, 7200, points=50)
        body = {
            "routes": [[list(c) for c in route.coords]],
            "departure": (NOW + timedelta(hours=2)).isoformat(),
            "load_weight_lbs": 42000,
        }
        res = self.client.post("/api/heatmap/", body, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["hours"], 48)
        self.assertEqual(len(data["hourly_max_level"]), 49)
        self.assertEqual(len(data["points"][0]["levels"]["overall"]), 49)

    def test_geocode_short_query_returns_empty(self):
        self.assertEqual(self.client.get("/api/geocode/?q=a").json(), {"results": []})
