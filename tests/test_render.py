import unittest
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from heatmap import render

SVG = "{http://www.w3.org/2000/svg}"


def span(first, last):
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


def cells(svg):
    """(date, class) for every day cell; only day cells carry a tooltip."""
    found = []
    for rect in ET.fromstring(svg).iter(SVG + "rect"):
        title = rect.find(SVG + "title")
        if title is not None:
            found.append((date.fromisoformat(title.text[:10]), rect.get("class")))
    return found


class ThresholdTest(unittest.TestCase):
    def test_nice(self):
        self.assertEqual([render.nice(value) for value in (394, 484, 816, 1234, 37, 3)], [400, 500, 800, 1000, 35, 3])

    def test_thresholds(self):
        self.assertEqual(render.thresholds(range(1, 1001)), (250, 500, 900))
        self.assertEqual(render.thresholds([0, 0]), (1, 2, 3))

    def test_thresholds_always_increase(self):
        self.assertEqual(render.thresholds([500] * 100), (500, 550, 600))

    def test_level(self):
        cuts = (400, 500, 800)
        self.assertEqual([render.level(value, cuts) for value in (None, 0, 1, 399, 400, 799, 800, 5000)], [0, 0, 1, 1, 2, 3, 4, 4])


class RenderTest(unittest.TestCase):
    last = date(2026, 9, 29)

    def setUp(self):
        self.series = {day.isoformat(): 100 + day.toordinal() % 7 * 150 for day in span(date(2024, 3, 5), self.last)}

    def test_one_cell_per_day_through_the_latest(self):
        found = cells(render.render(self.series))
        self.assertEqual(sorted(day for day, _ in found), span(date(2024, 1, 1), self.last))
        empty = {day for day, name in found if name == "l0"}
        self.assertEqual(empty, set(span(date(2024, 1, 1), date(2024, 3, 4))))

    def test_well_formed_and_sized(self):
        root = ET.fromstring(render.render(self.series, title="A & B <x>"))
        self.assertEqual(root.get("width"), "808")
        self.assertEqual(root.get("viewBox"), f"0 0 808 {root.get('height')}")
        self.assertIn("A & B <x>", root.get("aria-label"))

    def test_years(self):
        found = cells(render.render(self.series, years=1))
        self.assertEqual({day.year for day, _ in found}, {2026})
        self.assertLess(len(render.render(self.series, years=1)), len(render.render(self.series)))

    def test_fixed_levels(self):
        found = dict(cells(render.render({"2026-09-28": 450, "2026-09-29": 900}, levels=(100, 200, 1000))))
        self.assertEqual((found[date(2026, 9, 28)], found[date(2026, 9, 29)]), ("l3", "l3"))

    def test_tiles_leave_out_the_latest_day(self):
        series = {day.isoformat(): 600 for day in span(self.last - timedelta(days=400), self.last)}
        series[self.last.isoformat()] = 0  # the Shortcut ran just after midnight
        self.assertEqual(
            render.tiles(series, self.last),
            [
                ("近一年累计", "219,000", ""),
                ("近一年日均", "600", ""),
                ("近一年最高", "600", "9月28日"),
                ("近 30 天日均", "600", "环比 +0%"),
            ],
        )

    def test_trend_uses_a_real_minus_sign(self):
        series = {day.isoformat(): 500 for day in span(self.last - timedelta(days=60), self.last)}
        for day in span(self.last - timedelta(days=30), self.last):
            series[day.isoformat()] = 400
        self.assertEqual(render.tiles(series, self.last)[3][2], "环比 −20%")

    def test_empty_history(self):
        root = ET.fromstring(render.render({}, today=self.last))
        self.assertIn("近一年累计 —", root.get("aria-label"))
        self.assertEqual([day for day, _ in cells(render.render({}, today=self.last))], span(date(2026, 1, 1), self.last))


if __name__ == "__main__":
    unittest.main()
