import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from miser.evaluation import GOLDEN_LIMITS, evaluate_fixtures, golden_check, summarize
try:
    from tests.test_agent import ScriptedClient
except ImportError:
    from test_agent import ScriptedClient


class EvaluationTests(unittest.TestCase):
    def test_failed_spend_counts_and_unknown_usage_abstains(self):
        rows = [{"status": status, "receipt": {"usage_complete": True, "total_tokens": tokens}}
                for status, tokens in [("tests_passed", 100), ("step_limit", 200)]]
        self.assertEqual(summarize(rows)["tokens_per_solved_task"], 300)
        rows[1]["receipt"]["usage_complete"] = False
        self.assertIsNone(summarize(rows)["tokens_per_solved_task"])

    def test_fixture_runs_and_writes_report(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "evaluation"
            report = evaluate_fixtures(target, ScriptedClient(), "protocol-fixture",
                                       languages=("python",), progress=None)
            self.assertEqual(report["summary"]["solved"], 1)
            self.assertEqual(report["summary"]["reported_tokens_including_failures"], 240)
            self.assertTrue((target / "report.json").exists())
            self.assertFalse(report["benchmark"])

    def test_golden_task_is_graded_within_thresholds(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "golden"
            report = evaluate_fixtures(target, ScriptedClient(), "protocol-fixture",
                                       languages=("python",), progress=None, golden=True)
            self.assertEqual(report["kind"], "golden-task-evaluation")
            self.assertEqual(report["golden_thresholds"], GOLDEN_LIMITS)
            self.assertEqual(report["summary"]["golden_tasks"], 1)
            self.assertEqual(report["summary"]["golden_tasks_passed"], 1)
            graded = report["runs"][0]["golden"]
            self.assertTrue(graded["solved"])
            self.assertTrue(graded["within_model_calls"])
            self.assertTrue(graded["within_provider_tokens"])
            self.assertTrue((target / "report.json").exists())

    def test_golden_thresholds_reject_expensive_or_unmetered_runs(self):
        expensive = golden_check({"status": "tests_passed",
                                  "receipt": {"usage_complete": True, "model_calls": 5,
                                              "total_tokens": 6000}})
        self.assertFalse(expensive["within_model_calls"])
        self.assertFalse(expensive["within_provider_tokens"])
        unmetered = golden_check({"status": "tests_passed",
                                  "receipt": {"usage_complete": False, "model_calls": 2,
                                              "total_tokens": 100}})
        self.assertFalse(unmetered["usage_complete"])
        summary = summarize([{"status": "tests_passed", "golden": expensive,
                              "receipt": {"usage_complete": True, "total_tokens": 6000}}])
        self.assertEqual(summary["golden_tasks_passed"], 0)

    def test_transport_failure_stops_suite(self):
        class Offline:
            def complete(self, *args, **kwargs):
                raise RuntimeError("offline")
        with tempfile.TemporaryDirectory() as root:
            report = evaluate_fixtures(Path(root) / "evaluation", Offline(), "fixture",
                                       languages=("python",), repeats=2, progress=None)
            self.assertEqual(len(report["runs"]), 1)
            self.assertIn("stopped_early", report)
            self.assertFalse(report["summary"]["usage_complete"])


if __name__ == "__main__":
    unittest.main()

