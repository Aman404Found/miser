import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from miser.agent import run_agent
from miser.client import StreamInterrupted
from miser.ledger import Ledger, estimate_tokens, receipt
from miser.tools import SCHEMAS, ToolRunner
from miser.workspace import Workspace


def response(name=None, arguments=None, usage=True):
    message = {"role": "assistant", "content": None}
    if name:
        message["tool_calls"] = [{"id": "fixture-call", "type": "function",
                                  "function": {"name": name, "arguments": json.dumps(arguments or {})}}]
    else:
        message["content"] = "I think this is done."
    result = {"choices": [{"message": message}], "model": "unit-test-fixture"}
    if usage:
        result["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    return result


class ScriptedClient:
    """Protocol fixture only, never used to produce product benchmark numbers."""
    def __init__(self):
        self.calls = 0
        self.message_lengths = []

    def complete(self, messages, tools, max_tokens):
        self.calls += 1
        self.message_lengths.append(len(messages))
        if self.calls == 1:
            return response("zoom", {"path": "pricing.py", "level": 2})
        if self.calls == 2:
            version = json.loads(messages[-1]["content"])["version"]
            return response("edit", {"path": "pricing.py", "old": "price * discount_percent / 100",
                                     "new": "price * (1 - discount_percent / 100)", "expected_version": version})
        return response("run_tests")


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        fixtures = Path(__file__).resolve().parent.parent / "examples" / "python_bug"
        shutil.copytree(fixtures, self.repo)
        self.ledger = Ledger(self.root / "ledger.json", mode="unit-test-fixture", benchmark=False)
        self.workspace = Workspace(self.repo)
        self.runner = ToolRunner(self.workspace, self.ledger,
                                 [sys.executable, "-m", "unittest", "discover", "-s", "."])

    def test_real_patch_and_tests_with_scripted_protocol(self):
        client = ScriptedClient()
        status = run_agent("Fix discount", client, self.runner, self.ledger)
        self.assertEqual(status, "tests_passed")
        self.assertEqual(client.calls, 2)  # host verifies edits without a third model request
        self.assertEqual(self.ledger.total_tokens, 240)
        test_events = [e for e in self.ledger.data["events"] if e["kind"] == "tests"]
        self.assertFalse(test_events[0]["passed"])
        self.assertTrue(test_events[-1]["passed"])
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["total_tokens"], 240)  # tool estimates are not added
        self.assertTrue(bill["usage_complete"])

    def test_missing_usage_stops_without_edit(self):
        class NoUsage:
            def complete(self, *args, **kwargs):
                return response("list_files", usage=False)
        with self.assertRaisesRegex(ValueError, "valid usage"):
            run_agent("Fix", NoUsage(), self.runner, self.ledger)
        self.assertEqual(self.ledger.data["status"], "error")
        self.assertFalse(receipt(self.ledger.data)["usage_complete"])
        self.assertEqual(self.workspace.modified, set())

    def test_network_failure_marks_usage_unknown(self):
        class Offline:
            def complete(self, *args, **kwargs):
                raise RuntimeError("Service unavailable")
        with self.assertRaises(RuntimeError):
            run_agent("Fix", Offline(), self.runner, self.ledger)
        self.assertFalse(receipt(self.ledger.data)["usage_complete"])

    def test_model_cannot_claim_success_without_acceptance(self):
        class Premature:
            def complete(self, *args, **kwargs):
                return response()
        # A text-only reply is recorded as an answer, never as passing tests.
        self.assertEqual(run_agent("Fix", Premature(), self.runner, self.ledger), "answered")
        self.assertEqual(self.ledger.data["status"], "answered")
        self.assertNotEqual(self.ledger.data["status"], "tests_passed")

    def test_empty_reply_is_incomplete(self):
        class Silent:
            def complete(self, *args, **kwargs):
                result = response()
                result["choices"][0]["message"]["content"] = ""
                return result
        self.assertEqual(run_agent("Fix", Silent(), self.runner, self.ledger), "incomplete")
        self.assertEqual(self.ledger.data["status"], "incomplete")

    def test_length_capped_reply_is_reported_as_truncated(self):
        class LengthCapped:
            def complete(self, *args, **kwargs):
                result = response()
                result["choices"][0]["finish_reason"] = "length"
                return result
        self.assertEqual(run_agent("Fix", LengthCapped(), self.runner, self.ledger), "truncated")
        self.assertEqual(self.ledger.data["status"], "truncated")
        self.assertEqual(self.workspace.modified, set())

    def test_non_coding_task_rejected_without_tests_or_model(self):
        class FailClient:
            def complete(self, *args, **kwargs):
                raise AssertionError("Model should not be called for non-coding requests")
        status = run_agent("hi", FailClient(), self.runner, self.ledger)
        self.assertEqual(status, "rejected_non_coding")
        self.assertEqual(self.runner.test_runs, 0)
        self.assertEqual(self.workspace.modified, set())
        self.assertEqual(self.ledger.data["status"], "rejected_non_coding")

    def test_budget_prevents_model_call(self):
        client = ScriptedClient()
        status = run_agent("Fix", client, self.runner, self.ledger, token_budget=1000)
        self.assertEqual(status, "budget_exhausted")
        self.assertEqual(client.calls, 0)

    @patch("miser.agent.COMPACTION_RATIO", 0.5)
    def test_long_task_compacts_context_below_prompt_budget(self):
        body = "\n".join(f"def step_{i}(value):\n    return value + {i}\n" for i in range(60))
        (self.repo / "big.py").write_text(body, encoding="utf-8")

        class NoisyReader:
            def __init__(self):
                self.prompt_tokens = []

            def complete(self, messages, tools, max_tokens):
                self.prompt_tokens.append(
                    estimate_tokens(json.dumps(messages) + json.dumps(SCHEMAS)))
                result = response("zoom", {"path": "big.py", "level": 2,
                                           "start": 1, "end": 40, "refresh": True})
                result["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                return result

        client = NoisyReader()
        status = run_agent("Inspect big.py", client, self.runner, self.ledger,
                           token_budget=4000, max_steps=12, history_turns=4)
        self.assertEqual(status, "step_limit")
        self.assertEqual(len(client.prompt_tokens), 12)
        self.assertLess(max(client.prompt_tokens), 3500)
        compactions = [e for e in self.ledger.data["events"] if e["kind"] == "compaction"]
        self.assertTrue(compactions)
        # Compaction can shorten a retained turn without dropping the turn.
        self.assertLess(compactions[0]["prompt_tokens_after"], compactions[0]["prompt_tokens_before"])
        self.assertGreater(compactions[0]["prompt_tokens_after"], 0)
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["compactions"], len(compactions))
        self.assertGreater(bill["context_tokens_freed_estimate"], 0)
        self.assertEqual(bill["total_tokens"], 24)

    @patch("miser.agent.COMPACTION_RATIO", 0.5)
    def test_compaction_keeps_latest_snapshot_and_test_status(self):
        body = "\n".join(f"def step_{i}(value):\n    return value + {i}\n" for i in range(60))
        (self.repo / "big.py").write_text(body, encoding="utf-8")

        class Reader:
            def __init__(self):
                self.last_state = None
                self.calls = 0

            def complete(self, messages, tools, max_tokens):
                self.calls += 1
                self.last_state = json.loads(messages[1]["content"])
                result = response("zoom", {"path": "big.py", "level": 2,
                                           "start": 1, "end": 40, "refresh": True})
                result["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
                return result

        client = Reader()
        run_agent("Inspect big.py", client, self.runner, self.ledger,
                  token_budget=4000, max_steps=12)
        memory = client.last_state["working_memory"]
        self.assertEqual(memory["files"][-1]["path"], "big.py")
        self.assertIn("version", memory["files"][-1])
        self.assertEqual(client.last_state["latest_test_result"]["passed"], False)
        self.assertTrue(any(e["kind"] == "compaction" for e in self.ledger.data["events"]))
        self.assertNotIn("latest_tests", memory)  # test output is sent only once
        self.assertNotIn("recent_observations", memory)  # already present in tool history
        self.assertNotIn("return value + 59", json.dumps(memory))

    def test_history_is_bounded_and_step_limit_stops(self):
        class InspectOnly:
            def __init__(self):
                self.lengths = []
            def complete(self, messages, *args, **kwargs):
                self.lengths.append(len(messages))
                return response("list_files")
        client = InspectOnly()
        status = run_agent("Inspect", client, self.runner, self.ledger, max_steps=8, history_turns=2)
        self.assertEqual(status, "step_limit")
        self.assertLessEqual(max(client.lengths), 6)

    def test_acceptance_tests_protected(self):
        result = json.loads(self.runner.invoke("edit", {"path": "test_pricing.py", "old": "x", "new": "y",
                                                        "expected_version": "fake"}))
        self.assertIn("protected", result["error"])

    def test_batch_and_patch_tools_protect_tests_and_record_diffs(self):
        version = json.loads(self.runner.invoke("zoom", {"path": "pricing.py", "level": 2}))["version"]
        protected = json.loads(self.runner.invoke("edit_batch", {"edits": [
            {"path": "pricing.py", "old": "    return price * discount_percent / 100",
             "new": "    return price * (1 - discount_percent / 100)", "expected_version": version}]}))
        self.assertTrue(protected["edited"])
        blocked = json.loads(self.runner.invoke("edit_batch", {"edits": [
            {"path": "test_pricing.py", "old": "x", "new": "y", "expected_version": "fake"}]}))
        self.assertIn("protected", blocked["error"])
        blocked_patch = json.loads(self.runner.invoke("apply_patch", {"patch": (
            "--- a/test_pricing.py\n+++ b/test_pricing.py\n@@ -1 +1 @@\n-import unittest\n+import pytest\n")}))
        self.assertIn("protected", blocked_patch["error"])
        self.assertIn("pricing.py", self.runner.cumulative_diff())
        self.assertIn("+    return price * (1 - discount_percent / 100)", self.runner.cumulative_diff())

    def test_apply_patch_tool_round_trip(self):
        self.runner.invoke("zoom", {"path": "pricing.py", "level": 2})
        # Context lines carry the unified-diff marker space before the source indentation.
        patch = ("--- a/pricing.py\n+++ b/pricing.py\n@@ -3,3 +3,3 @@\n"
                 "     if price < 0 or not 0 <= discount_percent <= 100:\n"
                 "         raise ValueError(\"Invalid price or discount\")\n"
                 "-    return price * discount_percent / 100\n"
                 "+    return price * (1 - discount_percent / 100)\n")
        result = json.loads(self.runner.invoke("apply_patch", {"patch": patch}))
        self.assertEqual(result["files"], ["pricing.py"])
        self.assertTrue(json.loads(self.runner.invoke("run_tests", {}))["passed"])

    def test_schema_covers_retrieval_and_write_tools(self):
        names = {schema["function"]["name"] for schema in SCHEMAS}
        self.assertTrue({"find_files", "read_many", "write_file", "write_todos"} <= names)
        self.assertEqual(len(names), len(SCHEMAS))
        for schema in SCHEMAS:
            self.assertFalse(schema["function"]["parameters"]["additionalProperties"])

    def test_write_file_tool_creates_file_and_protects_tests(self):
        result = json.loads(self.runner.invoke("write_file", {
            "path": "notes.py", "content": "VALUE = 1\n"}))
        self.assertTrue(result["created"])
        self.assertEqual((self.repo / "notes.py").read_text(), "VALUE = 1\n")
        self.assertIn("notes.py", self.runner.cumulative_diff())
        blocked = json.loads(self.runner.invoke("write_file", {
            "path": "tests/test_new.py", "content": "x = 1\n"}))
        self.assertIn("protected", blocked["error"])
        self.assertFalse((self.repo / "tests" / "test_new.py").exists())

    def test_read_many_tool_version_edits_without_zoom(self):
        read = json.loads(self.runner.invoke("read_many", {"reads": [{"path": "pricing.py"}]}))
        entry = read["reads"][0]
        edited = json.loads(self.runner.invoke("edit", {
            "path": "pricing.py", "old": "* discount_percent", "new": "* 0.01 * discount_percent",
            "expected_version": entry["version"]}))
        self.assertTrue(edited["edited"])

    def test_approval_rejection_leaves_file_unchanged(self):
        prompts = []
        runner = ToolRunner(self.workspace, self.ledger,
                            [sys.executable, "-m", "unittest", "discover", "-s", "."],
                            approval_callback=lambda path, diff: prompts.append(path) or False)
        version = json.loads(runner.invoke("zoom", {"path": "pricing.py", "level": 2}))["version"]
        before = self.workspace.text("pricing.py")
        rejected = json.loads(runner.invoke("edit", {
            "path": "pricing.py", "old": "* discount_percent", "new": "* 0.01 * discount_percent",
            "expected_version": version}))
        self.assertIn("rejected", rejected["error"])
        self.assertEqual(prompts, ["pricing.py"])
        self.assertEqual(self.workspace.text("pricing.py"), before)

    def test_timeout_is_failed_and_logged(self):
        runner = ToolRunner(self.workspace, self.ledger,
                            [sys.executable, "-c", "import time; time.sleep(5)"], test_timeout=1)
        result = runner.run_tests()
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["passed"])

    def test_timeout_kills_child_when_group_kill_is_unavailable(self):
        # A host without POSIX process groups (or a group that already exited) must
        # still terminate the direct child instead of raising out of the timeout path.
        sleep = [sys.executable, "-c", "import time; time.sleep(5)"]
        runner = ToolRunner(self.workspace, self.ledger, sleep, test_timeout=1)
        with patch("miser.tools.os.killpg", side_effect=ProcessLookupError("no such group")):
            result = runner.run_tests()
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["passed"])
        runner = ToolRunner(self.workspace, self.ledger, sleep, test_timeout=1)
        with patch("miser.tools.os.killpg", None), patch("miser.tools.os.getpgid", None):
            result = runner.run_tests()
        self.assertTrue(result["timed_out"])
        self.assertFalse(result["passed"])

    def test_unusable_architect_usage_does_not_abort_task(self):
        class NoUsageArchitect:
            def __init__(self):
                self.calls = 0

            def complete(self, messages, tools, max_tokens):
                self.calls += 1
                result = response()
                result.pop("usage")
                return result

        architect = NoUsageArchitect()
        status = run_agent("Fix discount", ScriptedClient(), self.runner, self.ledger,
                           architect_client=architect)
        self.assertEqual(status, "tests_passed")
        self.assertEqual(architect.calls, 1)
        errors = [e for e in self.ledger.data["events"] if e["kind"] == "model_error"]
        self.assertEqual([e["role"] for e in errors], ["architect"])
        self.assertFalse(errors[0]["usage_known"])
        self.assertFalse(receipt(self.ledger.data)["usage_complete"])

    def test_test_output_is_bounded(self):
        runner = ToolRunner(self.workspace, self.ledger,
                            [sys.executable, "-c", "print('x' * 20000)"])
        result = runner.run_tests()
        self.assertTrue(result["output_truncated"])
        self.assertLessEqual(len(result["output"]), 8000)

    def test_model_cannot_override_test_command(self):
        result = json.loads(self.runner.invoke("run_tests", {"command": "echo passed"}))
        self.assertIn("no arguments", result["error"])

    def test_streamed_turns_emit_tokens_and_activity(self):
        class StreamingClient(ScriptedClient):
            supports_streaming = True

            def complete(self, messages, tools, max_tokens=1024, stream=False, on_token=None):
                if stream and on_token:
                    for piece in ("Inspecting ", "pricing.py.\n"):
                        on_token(piece)
                return super().complete(messages, tools, max_tokens)

        tokens, events = [], []
        status = run_agent("Fix discount", StreamingClient(), self.runner, self.ledger,
                           on_token=tokens.append, activity=events.append)
        self.assertEqual(status, "tests_passed")
        self.assertIn("Inspecting ", tokens)
        self.assertTrue(any(event.get("baseline") for event in events
                            if event["type"] == "tests"))
        self.assertTrue(any(event.get("state") == "result" for event in events
                            if event["type"] == "tool"))

    def test_interrupted_stream_stops_instead_of_resending(self):
        class BrokenStream(ScriptedClient):
            supports_streaming = True

            def __init__(self):
                super().__init__()
                self.stream_attempts = 0

            def complete(self, messages, tools, max_tokens=1024, stream=False, on_token=None):
                if stream:
                    self.stream_attempts += 1
                    on_token("partial")
                    raise StreamInterrupted("connection cut")
                raise AssertionError("a partial stream must never be resent")

        client = BrokenStream()
        status = run_agent("Fix discount", client, self.runner, self.ledger,
                           on_token=lambda chunk: None)
        self.assertEqual(status, "stream_interrupted")
        self.assertEqual(client.stream_attempts, 1)
        self.assertEqual(self.ledger.data["status"], "stream_interrupted")
        self.assertFalse(receipt(self.ledger.data)["usage_complete"])


if __name__ == "__main__":
    unittest.main()

