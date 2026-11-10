"""Routing/timing diagnostics: scripted providers and measured host operations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from miser import ledger
from miser.agent import run_agent
from miser.terminal import Terminal
from miser.tools import ToolRunner
from miser.workspace import Workspace
from test_agent import response


class LatencyTests(unittest.TestCase):
    def test_duration_totals_exclude_test_tool_duplicates_and_do_not_partition_parallel_wall_time(self):
        events = [
            {"kind": "model", "elapsed_seconds": 4},
            {"kind": "model_error", "elapsed_seconds": 3},
            {"kind": "model_error", "duration_in_model_event": True},
            {"kind": "tests", "elapsed_seconds": 5},
            {"kind": "tool", "name": "run_tests", "elapsed_seconds": 5.1},
            {"kind": "tool", "name": "zoom", "elapsed_seconds": 2},
            {"kind": "tool", "name": "search", "elapsed_seconds": 2},
            {"kind": "task_timing", "elapsed_seconds": 100},
        ]
        result = ledger.timing_summary(events, 10)
        self.assertEqual(result["wall_seconds"], 10)
        self.assertEqual(result["model_seconds"], 7)
        self.assertEqual(result["test_seconds"], 5)
        self.assertEqual(result["tool_seconds_sum"], 4)
        self.assertEqual(result["missing_durations"], 0)
        self.assertIn("overlap", result["note"])
        self.assertGreater(sum(result[key] for key in ("model_seconds", "test_seconds", "tool_seconds_sum")), 10)

    def test_missing_or_invalid_durations_are_reported_not_silently_claimed_complete(self):
        events = [{"kind": "model_error"}, {"kind": "tests", "elapsed_seconds": float("nan")},
                  {"kind": "tool", "elapsed_seconds": -1}, {"kind": "model", "elapsed_seconds": True}]
        self.assertEqual(ledger.timing_summary(events, 1)["missing_durations"], 4)

    def test_interrupted_request_without_completion_reports_unknown_duration(self):
        result = ledger.timing_summary([{"kind": "model_request"}], 3)
        self.assertEqual(result["missing_durations"], 1)

    def test_local_then_conversation_diagnostics_never_reuse_another_tasks_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 1\n")
            events = []
            terminal = Terminal(root, write=lambda _: None,
                                client_factory=lambda _: self.fail("Local action called model"))
            terminal.activity_listener = events.append
            terminal.task("show first line of app.py")
            self.assertEqual(terminal.last_route, "local-read")
            saved = terminal.last_ledger.path.read_bytes()
            data = json.loads(saved)
            self.assertEqual(data["events"][-1]["kind"], "task_timing")
            self.assertEqual(ledger.receipt(data)["test_runs"], 0)
            terminal.task("hello")
            self.assertEqual(terminal.last_route, "conversation")
            self.assertEqual(terminal.last_timing["model_seconds"], 0)
            self.assertEqual(terminal.last_ledger.path.read_bytes(), saved)
            self.assertEqual([event["profile"] for event in events if event["type"] == "route"],
                             ["local-read", "conversation"])

    def test_coding_policy_still_runs_baseline_and_records_timing_without_extra_requests(self):
        class Client:
            calls = 0
            def complete(self, *args, **kwargs):
                self.calls += 1
                return response()
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            terminal = Terminal(directory, model="simulated/timing", write=lambda _: None,
                                test_command=f"{sys.executable} -m unittest discover -s .",
                                client_factory=lambda _: client)
            terminal.task("Fix the bug")
            self.assertEqual(terminal.last_route, "coding")
            bill = ledger.receipt(terminal.last_ledger.data)
            self.assertEqual(bill["test_runs"], 1)
            self.assertEqual(bill["model_calls"], 1)
            self.assertEqual(client.calls, 1)
            self.assertGreaterEqual(terminal.last_timing["test_seconds"], 0)
            self.assertEqual(terminal.last_timing["missing_durations"], 0)

    def test_failed_question_has_measured_model_wait_but_no_success_or_old_ledger(self):
        class Client:
            def complete(self, *args, **kwargs):
                raise RuntimeError("simulated request failure")
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory, model="simulated/timing", write=lambda _: None,
                                client_factory=lambda _: Client())
            terminal.task("how are you?")
            self.assertEqual(terminal.last_route, "question")
            self.assertGreaterEqual(terminal.last_timing["model_seconds"], 0)
            self.assertEqual(terminal.last_timing["test_seconds"], 0)
            self.assertEqual(terminal.session_model_requests, 0)
            self.assertEqual(terminal.session_unknown_usage, 1)
            self.assertIsNone(terminal.last_ledger)

    def test_failed_agent_request_records_duration_without_inventing_usage(self):
        class Client:
            def complete(self, *args, **kwargs):
                raise RuntimeError("simulated failure")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            book = ledger.Ledger(root / "ledger.json")
            runner = ToolRunner(Workspace(root), book, [], profile="inspect")
            with self.assertRaisesRegex(RuntimeError, "simulated"):
                run_agent("Explain app.py", Client(), runner, book)
            failure = next(event for event in book.data["events"] if event["kind"] == "model_error")
            self.assertIn("elapsed_seconds", failure)
            self.assertFalse(ledger.receipt(book.data)["usage_complete"])
            self.assertEqual(ledger.receipt(book.data)["model_calls"], 0)

    def test_timing_command_is_host_only_and_new_session_has_no_old_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            output = []
            terminal = Terminal(directory, write=output.append)
            terminal.slash("/timing")
            self.assertIn("No task timing", "\n".join(output))
            terminal.task("hello")
            output.clear()
            terminal.slash("/timing")
            self.assertIn("conversation", "\n".join(output))
            self.assertIn("Model requests", "\n".join(output))
            self.assertIsNone(Terminal(directory, write=lambda _: None).last_timing)


class ManualCheckPolicyTests(unittest.TestCase):
    def test_manual_checks_skip_baseline_and_post_edit_tests_without_claiming_verified_success(self):
        class Client:
            calls = 0
            def complete(inner, messages, tools, **kwargs):
                inner.calls += 1
                self.assertNotIn('run_tests', {tool['function']['name'] for tool in tools})
                if inner.calls == 1:
                    return response('write_file', {'path': 'essay.txt', 'content': 'A short essay.\n'})
                result = response()
                result['choices'][0]['message']['content'] = 'Created essay.txt; tests were not run.'
                return result
        with tempfile.TemporaryDirectory() as directory:
            client = Client()
            terminal = Terminal(directory, model='simulated/manual', write=lambda _: None,
                                client_factory=lambda _: client)
            terminal.slash('/checks manual')
            statuses = []
            def measured_run(*args, **kwargs):
                status = run_agent(*args, **kwargs)
                statuses.append(status)
                return status
            with patch('miser.tools.ToolRunner.run_tests', side_effect=AssertionError('Must not run tests')), patch(
                    'miser.terminal.run_agent', side_effect=measured_run):
                terminal.task('Create essay.txt with a short essay')
            self.assertEqual(statuses, ['edited_unverified'])
            self.assertEqual((Path(directory) / 'essay.txt').read_text(), 'A short essay.\n')
            self.assertEqual(terminal.last_ledger.data['status'], 'edited_unverified')
            self.assertEqual(ledger.receipt(terminal.last_ledger.data)['test_runs'], 0)
            self.assertEqual(client.calls, 2)
            self.assertEqual(terminal.command, [])
            self.assertEqual(terminal.last_ledger.data['metadata']['test_policy'], 'manual')

    def test_manual_policy_cannot_be_changed_by_a_model_tool_and_required_can_be_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            book = ledger.Ledger(Path(directory) / 'ledger.json')
            runner = ToolRunner(Workspace(directory), book, [], test_policy='manual')
            with self.assertRaisesRegex(ValueError, 'manual'):
                runner.run_tests()
            self.assertIn('error', json.loads(runner.invoke('run_tests', {})))
            terminal = Terminal(directory, write=lambda _: None)
            self.assertEqual(terminal.test_policy, 'required')
            terminal.slash('/checks manual')
            terminal.slash('/checks required')
            self.assertEqual(terminal.test_policy, 'required')
            with self.assertRaises(ValueError):
                terminal.slash('/checks arbitrary')
            self.assertEqual(Terminal(directory, write=lambda _: None).test_policy, 'required')
