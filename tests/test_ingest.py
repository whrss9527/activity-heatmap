import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from heatmap import ingest

TZ = ZoneInfo("Asia/Shanghai")


def days(samples):
    return [sample.day.isoformat() for sample in samples]


def values(samples):
    return [sample.value for sample in samples]


class ParseTest(unittest.TestCase):
    def test_one_sample_per_line(self):
        samples = ingest.parse(
            "2026-09-28T08:00:00+08:00\n2026-09-28T09:00:00+08:00\n2026-09-29T00:05:00+08:00", "12.5\n30.25\n1", TZ
        )
        self.assertEqual(days(samples), ["2026-09-28", "2026-09-28", "2026-09-29"])
        self.assertEqual(values(samples), [12.5, 30.25, 1.0])
        self.assertEqual(samples[0].moment, datetime(2026, 9, 28, 8, 0))

    def test_literal_backslash_n(self):
        # GitHubPoster's workflow expanded these through bash $'...'
        samples = ingest.parse(r"2026-09-28\n2026-09-29", r"100\n200", TZ)
        self.assertEqual(days(samples), ["2026-09-28", "2026-09-29"])
        self.assertEqual(values(samples), [100, 200])

    def test_list_written_as_text(self):
        samples = ingest.parse("['2026-09-28', '2026-09-29']", "['100', '200']", TZ)
        self.assertEqual(values(samples), [100, 200])

    def test_comma_separated(self):
        samples = ingest.parse("2026-09-28,2026-09-29", "100,200.5", TZ)
        self.assertEqual(days(samples), ["2026-09-28", "2026-09-29"])
        self.assertEqual(values(samples), [100, 200.5])

    def test_thousands_separators(self):
        self.assertEqual(values(ingest.parse("2026-09-24\n2026-09-25", "1,257\n634", TZ)), [1257, 634])
        self.assertEqual(values(ingest.parse("2026-09-24", "1,257.5", TZ)), [1257.5])

    def test_offsets_become_local_days(self):
        [sample] = ingest.parse("2026-09-27T16:30:00Z", "5", TZ)
        self.assertEqual(sample.day, date(2026, 9, 28))
        self.assertEqual(sample.moment, datetime(2026, 9, 28, 0, 30))

    def test_time_without_offset_keeps_its_date(self):
        [sample] = ingest.parse("2026-09-27 23:30:00", "5", TZ)
        self.assertEqual(sample.day, date(2026, 9, 27))

    def test_other_date_formats(self):
        text = "2026/9/28\n2026年9月28日 08:00\n2026-09-28 08:00:00 +0800\n2026-09-28T08:00:00.000+08:00"
        self.assertEqual(days(ingest.parse(text, "1\n2\n3\n4", TZ)), ["2026-09-28"] * 4)

    def test_units_next_to_values(self):
        self.assertEqual(values(ingest.parse("2026-09-28\n2026-09-29", "12.5 kcal\n30 千卡", TZ)), [12.5, 30])

    def test_windows_line_endings(self):
        self.assertEqual(values(ingest.parse("2026-09-28\r\n2026-09-29\r\n", "1\r\n2\r\n", TZ)), [1, 2])

    def test_nothing_sent(self):
        self.assertEqual(ingest.parse("", "", TZ), [])
        self.assertEqual(ingest.parse(None, None, TZ), [])

    def test_counts_must_match(self):
        with self.assertRaises(ingest.PayloadError):
            ingest.parse("2026-09-28\n2026-09-29", "100", TZ)
        with self.assertRaises(ingest.PayloadError):
            ingest.parse("", "100", TZ)
        with self.assertRaises(ingest.PayloadError):
            ingest.parse("2026-09-28", "", TZ)

    def test_bad_date_or_number(self):
        with self.assertRaises(ingest.PayloadError):
            ingest.parse("2026-13-40", "1", TZ)
        with self.assertRaises(ingest.PayloadError):
            ingest.parse("2026-09-28", "abc", TZ)


class MergeTest(unittest.TestCase):
    def test_sums_each_day_and_replaces_it(self):
        series = {"2026-09-27": 500, "2026-09-28": 1000}
        samples = ingest.parse(
            "2026-09-28T08:00:00+08:00\n2026-09-28T09:30:00+08:00\n2026-09-29T00:10:00+08:00", "300.04\n320\n7", TZ
        )
        changes = ingest.merge(series, samples)
        self.assertEqual(series, {"2026-09-27": 500, "2026-09-28": 620, "2026-09-29": 7})
        self.assertEqual(
            [(change.day.isoformat(), change.samples, change.old, change.new) for change in changes],
            [("2026-09-28", 2, 1000, 620), ("2026-09-29", 1, None, 7)],
        )
        self.assertEqual((changes[0].first, changes[0].last), (datetime(2026, 9, 28, 8, 0), datetime(2026, 9, 28, 9, 30)))

    def test_report(self):
        changes = [
            ingest.Change(date(2026, 9, 24), 24, datetime(2026, 9, 24, 0, 0), datetime(2026, 9, 24, 23, 0), 1257, 634),
            ingest.Change(date(2026, 9, 30), 1, None, None, None, 5),
        ]
        text = ingest.report(changes, date(2026, 9, 29))
        self.assertIn("收到 25 个样本，涉及 2 天", text)
        self.assertIn("| 2026-09-24 | 24 | 00:00–23:00 | 1,257 | 634 | ⚠️ 比原来少 50% |", text)
        self.assertIn("⚠️ 未来的日期", text)
        self.assertIn("没有收到样本", ingest.report([], date(2026, 9, 29)))


class StorageTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "activity.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"move": {}, "stand": {"2026-09-28": 12}}))
            ingest.save(path, {"2026-09-29": 204.38200000000026, "2026-09-28": 907.0})
            text = path.read_text()
            self.assertIn('    "2026-09-28": 907,\n    "2026-09-29": 204.4\n', text)
            self.assertEqual(json.loads(text)["stand"], {"2026-09-28": 12})
            self.assertEqual(ingest.load(path), {"2026-09-28": 907, "2026-09-29": 204.4})
            self.assertEqual(ingest.load(Path(folder) / "missing.json"), {})

    def test_import_fills_only_missing_days(self):
        with tempfile.TemporaryDirectory() as folder:
            legacy = Path(folder) / "apple_history.json"
            legacy.write_text(json.dumps({"move": {"2026-09-27": 39.0, "2026-09-28": 907.0}}))
            series = {"2026-09-28": 950}
            self.assertEqual(ingest.import_legacy(series, legacy), 1)
            self.assertEqual(series, {"2026-09-27": 39, "2026-09-28": 950})


if __name__ == "__main__":
    unittest.main()
