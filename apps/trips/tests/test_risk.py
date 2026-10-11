import unittest

from ..domain.models import WeatherSample
from ..domain.risk import RAIN, SNOW, WIND, RiskLevel, assess, describe_rules

L, M, H, S, N = RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.SEVERE, RiskLevel.NO_TRAVEL


class ThresholdTests(unittest.TestCase):
    def test_wind_bands(self):
        cases = [(0, L), (24.9, L), (25, M), (34.9, M), (35, H), (44.9, H), (45, S), (54.9, S), (55, N), (80, N)]
        for value, expected in cases:
            self.assertEqual(WIND.classify(value), expected, f"wind {value}")

    def test_rain_bands(self):
        cases = [(0, L), (0.099, L), (0.10, M), (0.249, M), (0.25, H), (0.499, H), (0.50, S), (1.00, S), (1.001, N)]
        for value, expected in cases:
            self.assertEqual(RAIN.classify(value), expected, f"rain {value}")

    def test_snow_bands(self):
        cases = [(0, L), (0.49, L), (0.5, M), (0.99, M), (1.0, H), (1.99, H), (2.0, S), (3.0, S), (3.01, N)]
        for value, expected in cases:
            self.assertEqual(SNOW.classify(value), expected, f"snow {value}")


class LoadRuleTests(unittest.TestCase):
    def wind(self, mph, load):
        return assess(WeatherSample(mph, 0, 0), load)

    def test_55_mph_blocks_any_load(self):
        self.assertEqual(self.wind(55, 0).overall, N)
        self.assertEqual(self.wind(60, 1_000).overall, N)

    def test_45_to_54_over_30k_is_no_travel(self):
        self.assertEqual(self.wind(50, 30_001).overall, N)
        self.assertEqual(self.wind(50, 30_000).overall, S)  # "over" is strict
        self.assertEqual(self.wind(45, 45_000).overall, N)

    def test_35_to_44_over_40k_is_severe(self):
        self.assertEqual(self.wind(40, 40_001).overall, S)
        self.assertEqual(self.wind(40, 40_000).overall, H)
        self.assertEqual(self.wind(40, 20_000).overall, H)

    def test_load_does_not_affect_rain_or_snow(self):
        a = assess(WeatherSample(0, 0.3, 1.2), 80_000)
        self.assertEqual((a.rain, a.snow), (H, H))

    def test_load_rule_below_threshold_wind_has_no_effect(self):
        self.assertEqual(self.wind(30, 80_000).overall, M)


class OverallTests(unittest.TestCase):
    def test_overall_is_worst_condition(self):
        a = assess(WeatherSample(10, 0.6, 0.6), 10_000)
        self.assertEqual((a.wind, a.rain, a.snow, a.overall), (L, S, M, S))

    def test_reasons_mention_load_rule(self):
        a = assess(WeatherSample(50, 0, 0), 35_000)
        self.assertTrue(any("load rule" in r for r in a.reasons))

    def test_describe_rules_shape(self):
        d = describe_rules()
        self.assertEqual([t["condition"] for t in d["thresholds"]], ["wind", "rain", "snow"])
        self.assertEqual(len(d["levels"]), 5)


if __name__ == "__main__":
    unittest.main()
