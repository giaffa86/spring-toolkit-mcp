from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spring_toolkit_mcp.quality import read_jacoco_report, read_surefire_report, run_maven_tests


class QualityTests(unittest.TestCase):
    def test_reads_surefire_report_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "target" / "surefire-reports"
            report_dir.mkdir(parents=True)
            (report_dir / "TEST-com.acme.OrderServiceTest.xml").write_text(
                """<testsuite name="com.acme.OrderServiceTest" tests="2" failures="1" errors="0" skipped="0" time="0.2">
  <testcase classname="com.acme.OrderServiceTest" name="passes" time="0.1"/>
  <testcase classname="com.acme.OrderServiceTest" name="fails" time="0.1">
    <failure message="boom"/>
  </testcase>
</testsuite>
""",
                encoding="utf-8",
            )

            result = read_surefire_report(root)

            self.assertTrue(result["found"])
            self.assertEqual(result["totals"]["tests"], 2)
            self.assertEqual(result["totals"]["failures"], 1)
            self.assertEqual(result["reports"][0]["cases"][1]["status"], "failure")

    def test_reads_jacoco_counters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_dir = root / "target" / "site" / "jacoco"
            report_dir.mkdir(parents=True)
            (report_dir / "jacoco.xml").write_text(
                """<report name="demo">
  <counter type="LINE" missed="2" covered="8"/>
</report>
""",
                encoding="utf-8",
            )

            result = read_jacoco_report(root)

            self.assertTrue(result["found"])
            self.assertEqual(result["counters"][0]["coverage"], 0.8)

    def test_maven_test_runner_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_maven_tests(tmp, test="OrderServiceTest")

            self.assertFalse(result["ran"])
            self.assertIn("SPRING_TOOLKIT_ENABLE_TEST_RUNS", result["message"])


if __name__ == "__main__":
    unittest.main()

