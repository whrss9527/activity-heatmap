import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from heatmap.__main__ import main


class CliTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.data, self.out = self.folder / "activity.json", self.folder / "out" / "heatmap.svg"
        self.data.write_text(json.dumps({"move": {"2026-09-27": 500}}))
        environment = mock.patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(self.folder / "summary.md")})
        environment.start()
        self.addCleanup(environment.stop)

    def run_cli(self, *args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main([*args, "--data", str(self.data), "--out", str(self.out)])

    def test_sync_merges_draws_and_writes_the_summary(self):
        self.assertEqual(self.run_cli("sync", "--time", "2026-09-28\n2026-09-28", "--value", "300\n5"), 0)
        self.assertEqual(json.loads(self.data.read_text())["move"], {"2026-09-27": 500, "2026-09-28": 305})
        self.assertIn("<svg", self.out.read_text())
        self.assertIn("| 2026-09-28 | 2 |", (self.folder / "summary.md").read_text())

    def test_bad_payload_fails_without_writing(self):
        self.assertEqual(self.run_cli("sync", "--time", "2026-09-28\n2026-09-29", "--value", "300"), 1)
        self.assertEqual(json.loads(self.data.read_text())["move"], {"2026-09-27": 500})
        self.assertFalse(self.out.exists())
        self.assertIn("没法一一对应", (self.folder / "summary.md").read_text())

    def test_render_with_fixed_levels(self):
        self.assertEqual(self.run_cli("render", "--levels", "400,500,800", "--years", "1"), 0)
        self.assertIn("≥ 800", self.out.read_text())

    def test_levels_must_be_three_increasing_numbers(self):
        for bad in ("400,500", "800,500,400", "a,b,c"):
            with self.assertRaises(SystemExit):
                self.run_cli("render", "--levels", bad)


if __name__ == "__main__":
    unittest.main()
