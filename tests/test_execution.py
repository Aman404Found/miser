import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from miser.execution import CommandSupervisor, check_argv
from miser.ledger import Ledger
from miser.workspace import Workspace


class ExecutionTests(unittest.TestCase):
    """Unit fixtures only; these never stand in for product benchmark numbers."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.ledger = Ledger(Path(self.temp.name) / "ledger.json",
                             mode="unit-test-fixture", benchmark=False)
        self.workspace = Workspace(self.repo)

    def supervisor(self, approval=lambda command: True, allowlist=None):
        return CommandSupervisor(self.workspace, self.ledger, approval_callback=approval,
                                 allowlist=allowlist, timeout=20)

    def test_allowlisted_command_runs_with_real_exit_status(self):
        runner = self.supervisor()
        result = runner.run(["python3", "-m", "unittest", "--help"])
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(result["timed_out"])
        self.assertIn("unittest", result["output"].lower())

    def test_nonzero_exit_status_is_preserved(self):
        result = self.supervisor().run(["python3", "-m", "unittest", "nonexistent_module_xyz"])
        self.assertEqual(result["exit_code"], 1)

    def test_shell_metacharacters_are_refused_before_approval(self):
        calls = []
        with self.assertRaises(ValueError) as caught:
            check_argv(["git", "status; rm -rf /"])
        self.assertIn("metacharacter", str(caught.exception))
        with self.assertRaises(ValueError):
            check_argv(["git", "diff", "|", "cat"])
        self.assertEqual(calls, [])

    def test_unlisted_binary_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            check_argv(["rm", "-rf", "build"])
        self.assertIn("allowlist", str(caught.exception))

    def test_approval_refusal_prevents_execution(self):
        runner = self.supervisor(approval=lambda command: False)
        with self.assertRaises(ValueError) as caught:
            runner.run(["python3", "-m", "unittest", "--help"])
        self.assertIn("rejected", str(caught.exception))
        self.assertEqual(runner.runs, 0)

    def test_missing_approval_channel_refuses(self):
        runner = CommandSupervisor(self.workspace, self.ledger, approval_callback=None)
        with self.assertRaises(ValueError):
            runner.run(["python3", "-m", "unittest", "--help"])

    def test_always_suppresses_repeat_prompt_for_exact_argv(self):
        seen = []

        def approval(command):
            seen.append(command)
            return "always"

        runner = self.supervisor(approval=approval)
        runner.run(["python3", "-m", "unittest", "--help"])
        runner.run(["python3", "-m", "unittest", "--help"])
        self.assertEqual(len(seen), 1)

    def test_background_start_status_and_stop(self):
        (self.repo / "fixture_sleep.py").write_text(
            "import time\nprint('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
        runner = self.supervisor(allowlist=(("python3", "fixture_sleep.py"),))
        started = runner.run(["python3", "fixture_sleep.py"], background=True)
        self.assertTrue(started["running"])
        try:
            self.assertTrue((self.repo / ".miser" / "jobs").is_dir())
            deadline = time.monotonic() + 5
            status = runner.status(started["job_id"])
            while "started" not in status["output"] and time.monotonic() < deadline:
                time.sleep(0.05)
                status = runner.status(started["job_id"])
            self.assertTrue(status["running"])
            self.assertIn("started", status["output"])
        finally:
            stopped = runner.stop(started["job_id"])
        self.assertFalse(stopped["running"])
        self.assertIsNotNone(stopped["exit_code"])


if __name__ == "__main__":
    unittest.main()
