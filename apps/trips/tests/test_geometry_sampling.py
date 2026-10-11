import unittest

from ..domain import geometry as geo
from ..domain.sampling import checkpoint_miles, corridor_spacing, coverage, resolve_interval


class GeometryTests(unittest.TestCase):
    def test_haversine_nyc_la(self):
        d = geo.haversine_miles((40.7128, -74.0060), (34.0522, -118.2437))
        self.assertAlmostEqual(d, 2445, delta=15)

    def test_point_at_and_slice(self):
        coords = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
        cum = geo.cumulative_miles(coords)
        mid = geo.point_at(coords, cum, cum[-1] / 2)
        self.assertAlmostEqual(mid[1], 1.0, places=4)
        self.assertEqual(geo.point_at(coords, cum, -5), coords[0])
        self.assertEqual(geo.point_at(coords, cum, 1e9), coords[-1])
        part = geo.slice_path(coords, cum, cum[-1] * 0.25, cum[-1] * 0.75)
        self.assertAlmostEqual(part[0][1], 0.5, places=3)
        self.assertAlmostEqual(part[-1][1], 1.5, places=3)
        self.assertIn((0.0, 1.0), part)

    def test_simplify_keeps_corners_and_drops_collinear(self):
        line = [(0.0, i * 0.01) for i in range(50)] + [(i * 0.01, 0.49) for i in range(1, 50)]
        out = geo.simplify(line, 0.0005)
        self.assertLess(len(out), 6)
        self.assertEqual(out[0], line[0])
        self.assertEqual(out[-1], line[-1])

    def test_perpendicular_offset_distance(self):
        coords = [(40.0, -100.0), (40.0, -98.0)]
        cum = geo.cumulative_miles(coords)
        p = geo.offset_perpendicular(coords, cum, 50, 15)
        base = geo.point_at(coords, cum, 50)
        self.assertAlmostEqual(geo.haversine_miles(base, p), 15, delta=0.3)
        self.assertLess(p[0], base[0])  # heading east -> right side is south

    def test_diverging_miles(self):
        a = [(0.0, i * 0.01) for i in range(100)]
        b = [(0.0 if i < 30 else 0.5, i * 0.01) for i in range(100)]
        ca = geo.cumulative_miles(a)
        cb = geo.cumulative_miles(b)
        div = geo.diverging_miles(b, cb, geo.cell_set(a, ca))
        self.assertGreater(div, 30)
        self.assertEqual(geo.diverging_miles(a, ca, geo.cell_set(a, ca)), 0.0)


class SamplingTests(unittest.TestCase):
    def test_marks_include_origin_and_destination(self):
        self.assertEqual(checkpoint_miles(100, 25), [0.0, 25.0, 50.0, 75.0, 100])
        self.assertEqual(checkpoint_miles(60, 25), [0.0, 25.0, 50.0, 60])

    def test_destination_not_duplicated_when_close_to_a_mark(self):
        self.assertEqual(checkpoint_miles(100.2, 25), [0.0, 25.0, 50.0, 75.0, 100.2])

    def test_zero_length(self):
        self.assertEqual(checkpoint_miles(0, 10), [0.0])

    def test_coverage_tiles_the_route(self):
        marks = checkpoint_miles(100, 25)
        spans = coverage(marks)
        self.assertEqual(spans[0][0], 0.0)
        self.assertEqual(spans[-1][1], 100)
        for (_, e1), (s2, _) in zip(spans, spans[1:]):
            self.assertAlmostEqual(e1, s2)
        self.assertAlmostEqual(sum(e - s for s, e in spans), 100)

    def test_interval_resolution(self):
        self.assertEqual(resolve_interval(25, 900), 25)
        self.assertEqual(resolve_interval(None, 90), 10)
        self.assertEqual(resolve_interval(None, 300), 25)
        self.assertEqual(resolve_interval(None, 1200), 50)
        with self.assertRaises(ValueError):
            resolve_interval(7, 100)

    def test_corridor_spacing_respects_budget(self):
        self.assertEqual(corridor_spacing(100, 3, 240), 10)
        sp = corridor_spacing(3000, 3, 240)
        self.assertLessEqual(3000 * 3 / sp, 240)


if __name__ == "__main__":
    unittest.main()
