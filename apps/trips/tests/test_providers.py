import unittest
from datetime import date

import requests

from ..domain.errors import RoutingError, UpstreamUnavailable
from ..providers.open_meteo import OpenMeteoProvider
from ..providers.osrm import OsrmRouter
from ..providers.photon import PhotonGeocoder


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def om_entry(times, wind, gust, rain, showers, snow):
    return {"hourly": {"time": times, "wind_speed_10m": wind, "wind_gusts_10m": gust, "rain": rain, "showers": showers, "snowfall": snow}}


class OpenMeteoTests(unittest.TestCase):
    TIMES = ["2026-10-10T00:00", "2026-10-10T01:00"]

    def test_requests_us_units_and_parses(self):
        entry = om_entry(self.TIMES, [10, 20], [30, 40], [0.1, None], [0.05, 0.0], [0.0, 0.5])
        session = FakeSession(FakeResponse(200, entry))
        p = OpenMeteoProvider(session)
        [series] = p.fetch_hourly([(40.0, -100.0)], date(2026, 10, 10), date(2026, 10, 10))
        params = session.calls[0][1]
        self.assertEqual((params["wind_speed_unit"], params["precipitation_unit"], params["timezone"]), ("mph", "inch", "GMT"))
        self.assertEqual(series.wind_mph, [10.0, 20.0])
        self.assertAlmostEqual(series.rain_in_hr[0], 0.15)  # rain + showers
        self.assertEqual(series.rain_in_hr[1], 0.0)  # None treated as 0
        self.assertEqual(series.snow_in_hr, [0.0, 0.5])
        self.assertEqual(series.start.tzinfo.utcoffset(None).total_seconds(), 0)

    def test_gust_metric(self):
        entry = om_entry(self.TIMES, [10, 20], [30, 40], [0, 0], [0, 0], [0, 0])
        [series] = OpenMeteoProvider(FakeSession(FakeResponse(200, entry)), wind_metric="gust").fetch_hourly([(1, 1)], date(2026, 10, 10), date(2026, 10, 10))
        self.assertEqual(series.wind_mph, [30.0, 40.0])

    def test_batches_large_requests(self):
        entry = om_entry(self.TIMES, [1, 1], [1, 1], [0, 0], [0, 0], [0, 0])
        session = FakeSession(FakeResponse(200, [entry] * 50))
        p = OpenMeteoProvider(session, batch_size=50, concurrency=1)
        # 50 points per request -> 100 points need two calls; second call gets the same canned 50-entry reply
        out = p.fetch_hourly([(40 + i * 0.01, -100.0) for i in range(100)], date(2026, 10, 10), date(2026, 10, 10))
        self.assertEqual(len(out), 100)
        self.assertEqual(len(session.calls), 2)

    def test_errors_become_upstream_unavailable(self):
        with self.assertRaises(UpstreamUnavailable):
            OpenMeteoProvider(FakeSession(requests.ConnectionError("boom"))).fetch_hourly([(1, 1)], date(2026, 10, 10), date(2026, 10, 10))
        with self.assertRaises(UpstreamUnavailable):
            OpenMeteoProvider(FakeSession(FakeResponse(400, {"reason": "out of range"}))).fetch_hourly([(1, 1)], date(2026, 10, 10), date(2026, 10, 10))


OSRM_OK = {
    "code": "Ok",
    "routes": [
        {"distance": 1609.344 * 100, "duration": 5400, "geometry": {"coordinates": [[-100.0, 40.0], [-99.0, 40.5]]}},
        {"distance": 1609.344 * 120, "duration": 6000, "geometry": {"coordinates": [[-100.0, 40.0], [-99.0, 40.2]]}},
    ],
}


class OsrmTests(unittest.TestCase):
    def test_parses_and_swaps_lonlat(self):
        session = FakeSession(FakeResponse(200, OSRM_OK))
        routes = OsrmRouter(session, "http://osrm").routes([(40.0, -100.0), (40.5, -99.0)], alternatives=3)
        self.assertEqual(routes[0].coords[0], (40.0, -100.0))
        self.assertAlmostEqual(routes[0].distance_miles, 100)
        self.assertEqual(len(routes), 2)
        url, params = session.calls[0]
        self.assertIn("-100.000000,40.000000;-99.000000,40.500000", url)
        self.assertEqual(params["alternatives"], "3")

    def test_falls_back_to_boolean_alternatives(self):
        session = FakeSession(FakeResponse(400, {"message": "bad alternatives"}), FakeResponse(200, OSRM_OK))
        OsrmRouter(session, "http://osrm").routes([(40.0, -100.0), (40.5, -99.0)], alternatives=3)
        self.assertEqual([c[1]["alternatives"] for c in session.calls], ["3", "true"])

    def test_no_route(self):
        with self.assertRaises(RoutingError):
            OsrmRouter(FakeSession(FakeResponse(200, {"code": "NoRoute"})), "http://osrm").routes([(0, 0), (1, 1)])

    def test_network_failure(self):
        with self.assertRaises(UpstreamUnavailable):
            OsrmRouter(FakeSession(requests.Timeout("slow")), "http://osrm").routes([(0, 0), (1, 1)])


class PhotonTests(unittest.TestCase):
    def test_label_and_dedupe(self):
        feats = {
            "features": [
                {"geometry": {"coordinates": [-87.63, 41.88]}, "properties": {"name": "Chicago", "state": "Illinois", "country": "United States"}},
                {"geometry": {"coordinates": [-87.63, 41.88]}, "properties": {"name": "Chicago", "state": "Illinois", "country": "United States"}},
                {"geometry": {"coordinates": [-96.8, 32.78]}, "properties": {"name": "Dallas", "city": "Dallas", "state": "Texas", "country": "United States"}},
            ]
        }
        places = PhotonGeocoder(FakeSession(FakeResponse(200, feats)), "http://photon").search("chi")
        self.assertEqual([p.label for p in places], ["Chicago, Illinois, United States", "Dallas, Texas, United States"])
        self.assertEqual((places[0].lat, places[0].lon), (41.88, -87.63))


if __name__ == "__main__":
    unittest.main()
