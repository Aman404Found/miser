import json
import shutil
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

from miser.terminal import Terminal, clean
try:
    from tests.test_agent import ScriptedClient, response
except ImportError:
    from test_agent import ScriptedClient, response


class TerminalTests(unittest.TestCase):
    def test_interactive_task_writes_real_patch_and_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=lambda _: None,
                                client_factory=lambda _: ScriptedClient())
            terminal.task("Fix discount")
            self.assertEqual(terminal.last_ledger.data["status"], "tests_passed")
            self.assertIn("price * (1 - discount_percent / 100)", terminal.last_diff)
            saved = terminal.last_ledger.path.parent / "patch.diff"
            self.assertEqual(saved.read_text(), terminal.last_diff)
            self.assertEqual(json.loads(terminal.last_ledger.path.read_text())["status"], "tests_passed")

    def test_session_recovers_from_bad_command_and_handles_exit(self):
        with tempfile.TemporaryDirectory() as root:
            lines = iter(["/budget 2", "/model fixture/model", "/status", "/exit"])
            output = []
            terminal = Terminal(root, read=lambda _: next(lines), write=output.append)
            self.assertEqual(terminal.run(), 0)
            self.assertEqual(terminal.budget, 24000)
            self.assertEqual(terminal.model, "fixture/model")
            self.assertIn("Budget must be at least", "\n".join(output))

    def test_missing_configuration_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, client_factory=lambda _: self.fail("Unexpected model call"))
            with self.assertRaisesRegex(ValueError, "Set /model"):
                terminal.task("Fix something")

    def test_greeting_does_not_launch_agent_or_run_tests(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", test_command="invalid-test-cmd-that-would-fail",
                                write=output.append,
                                client_factory=lambda _: self.fail("Unexpected model call"))
            terminal.handle_input("hi")
            self.assertIn("Hello!", "\n".join(output))
            self.assertIsNone(terminal.last_ledger)
            self.assertEqual(terminal.last_diff, "")

            # Direct terminal.task("hello there") also guarded
            terminal.task("hello there")
            self.assertIsNone(terminal.last_ledger)

    def test_acknowledgement_and_help_handled_without_model(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", test_command="exit 1",
                                write=output.append,
                                client_factory=lambda _: self.fail("Unexpected model call"))
            terminal.handle_input("thanks")
            self.assertIn("welcome", "\n".join(output).lower())
            terminal.handle_input("what can you do")
            self.assertIn("miser", "\n".join(output).lower())
            self.assertIsNone(terminal.last_ledger)

    def test_ambiguous_request_asks_clarifying_question(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", test_command="exit 1",
                                write=output.append,
                                client_factory=lambda _: self.fail("Unexpected model call"))
            terminal.handle_input("pricing")
            self.assertIn("ambiguous", "\n".join(output).lower())
            self.assertIsNone(terminal.last_ledger)

    def test_question_answered_without_tools_or_test_execution(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            class QuestionClient:
                def complete(self, messages, tools=None, max_tokens=1000):
                    assert tools is None, "Question completion must not receive coding tools"
                    return {"choices": [{"message": {"role": "assistant", "content": "It calculates discounts."}}]}
            terminal = Terminal(root, model="fixture/model", test_command="exit 1",
                                write=output.append,
                                client_factory=lambda _: QuestionClient())
            terminal.handle_input("What does discounted_price do?")
            self.assertIn("It calculates discounts.", "\n".join(output))
            self.assertIsNone(terminal.last_ledger)

    def test_multiline_input_reading(self):
        with tempfile.TemporaryDirectory() as root:
            # Test triple quotes
            triple_lines = iter(['"""Fix this bug', 'and preserve tests"""'])
            terminal = Terminal(root, read=lambda _: next(triple_lines))
            result = terminal.read_multiline_input()
            self.assertEqual(result, "Fix this bug\nand preserve tests")

            # Test backslash continuation
            backslash_lines = iter(['Fix this bug \\', 'and make tests pass'])
            terminal = Terminal(root, read=lambda _: next(backslash_lines))
            result = terminal.read_multiline_input()
            self.assertEqual(result, "Fix this bug and make tests pass")

    def test_confirm_mode_and_approval_workflow(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            output = []
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=output.append,
                                read=lambda _: "n", # reject edit
                                client_factory=lambda _: ScriptedClient())
            terminal.slash("/confirm on")
            self.assertTrue(terminal.confirm_edits)
            terminal.task("Fix discount")
            # Edit was rejected, so tests still fail or incomplete
            self.assertNotEqual(terminal.last_ledger.data["status"], "tests_passed")

    def test_undo_restores_original_files(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            output = []
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=output.append,
                                client_factory=lambda _: ScriptedClient())
            terminal.task("Fix discount")
            self.assertEqual(terminal.last_ledger.data["status"], "tests_passed")
            self.assertIn("pricing.py", terminal.workspace.modified)
            # Revert with undo
            terminal.slash("/undo")
            self.assertEqual(len(terminal.workspace.modified), 0)
            orig = (Path(__file__).resolve().parent.parent / "examples/python_bug/pricing.py").read_text()
            self.assertEqual((repo / "pricing.py").read_text(), orig)

    def test_manual_run_executes_tests_without_model(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, test_command=f"{sys.executable} -c 'print(\"hello-test\"); exit(0)'",
                                output_dir=Path(root) / "runs", write=output.append)
            terminal.slash("/run")
            self.assertIn("hello-test", "\n".join(output))

    def test_status_and_model_inspection(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, write=output.append)
            terminal.slash("/status")
            terminal.slash("/model")
            terminal.slash("/test")
            terminal.slash("/budget")
            text = "\n".join(output)
            self.assertIn("Workspace", text)
            self.assertIn("Current model:", text)
            self.assertIn("Current tests:", text)
            self.assertIn("Current budget:", text)

    def test_model_chain_and_architect_slash_commands(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, write=output.append)
            terminal.slash("/model primary/model, backup/model ,primary/model")
            self.assertEqual(terminal.model, "primary/model")
            self.assertEqual(terminal.fallbacks, ["backup/model"])
            terminal.slash("/architect reasoning/model")
            self.assertEqual(terminal.architect_model, "reasoning/model")
            terminal.slash("/architect off")
            self.assertIsNone(terminal.architect_model)
            terminal.slash("/model")
            text = "\n".join(output)
            self.assertIn("Fallbacks: backup/model", text)
            self.assertIn("Architect: off", text)
            with self.assertRaises(ValueError):
                terminal.slash("/model ,,")

    def test_make_client_carries_fallback_chain(self):
        with tempfile.TemporaryDirectory() as root:
            terminal = Terminal(root, model="primary/model", fallbacks=["backup/model"],
                                write=lambda text: None)
            client = terminal.make_client()
            self.assertEqual(client.candidates, ["primary/model", "backup/model"])
            self.assertEqual(client.consume_fallback(), None)

    def test_control_sequences_are_filtered(self):
        self.assertNotIn("\x1b", clean("\x1b[2Jbad\x07"))
        self.assertNotIn("\x07", clean("bad\x07"))

    def test_history_and_autocommit_slash_commands(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, write=output.append)
            terminal.slash("/history")
            self.assertIn("No tasks have been executed", "\n".join(output))

            terminal.slash("/autocommit on")
            self.assertTrue(terminal.auto_commit)
            terminal.slash("/autocommit off")
            self.assertFalse(terminal.auto_commit)

    def test_resume_session_restores_history(self):
        with tempfile.TemporaryDirectory() as root:
            runs_dir = Path(root) / "runs"
            session_dir = runs_dir / "session-12345678"
            session_dir.mkdir(parents=True)
            ledger_data = {
                "status": "tests_passed",
                "metadata": {"task": "Sample resumed task", "repo": root},
                "events": [
                    {"kind": "model", "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "usage_known": True}
                ]
            }
            (session_dir / "ledger.json").write_text(json.dumps(ledger_data))
            (session_dir / "patch.diff").write_text("--- a/f.py\n+++ b/f.py\n@@ -1 +1 @@\n-old\n+new\n")

            output = []
            terminal = Terminal(root, output_dir=runs_dir, resume=True, write=output.append)
            self.assertEqual(terminal.session_tasks_count, 1)
            self.assertEqual(terminal.session_provider_tokens, 150)
            self.assertEqual(len(terminal.task_history), 1)
            self.assertIn("Sample resumed task", terminal.task_history[0]["task"])
            self.assertIn("Resumed 1 prior session task", "\n".join(output))

    def test_question_usage_is_counted_in_the_session(self):
        with tempfile.TemporaryDirectory() as root:
            class UsageClient:
                def complete(self, messages, tools=None, max_tokens=1000):
                    return {"choices": [{"message": {"content": "It applies a discount."}}],
                            "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                                      "total_tokens": 15}}
            terminal = Terminal(root, model="fixture/model", write=lambda _: None,
                                client_factory=lambda _: UsageClient())
            terminal.handle_input("What does discounted_price do?")
            self.assertEqual(terminal.session_provider_tokens, 15)
            self.assertEqual(terminal.session_model_requests, 1)
            self.assertEqual(terminal.session_unknown_usage, 0)

    def test_unmetered_question_is_reported_as_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as root:
            class NoUsageClient:
                def complete(self, messages, tools=None, max_tokens=1000):
                    return {"choices": [{"message": {"content": "Answer."}}]}
            output = []
            terminal = Terminal(root, model="fixture/model", write=output.append,
                                client_factory=lambda _: NoUsageClient())
            terminal.handle_input("What does pricing.py do?")
            terminal.slash("/usage")
            text = "\n".join(output)
            self.assertEqual(terminal.session_unknown_usage, 1)
            self.assertIn("unmetered", text)

    def test_streaming_answer_renders_tokens_before_completion(self):
        with tempfile.TemporaryDirectory() as root:
            class StreamingClient:
                supports_streaming = True

                def complete(self, messages, tools, max_tokens=1024, stream=False, on_token=None):
                    assert tools is None, "Question completion must not receive coding tools"
                    for piece in ("The ", "answer ", "is 42."):
                        on_token(piece)
                    return {"choices": [{"message": {"content": "The answer is 42."}}],
                            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}}
            output = []
            terminal = Terminal(root, model="fixture/model", write=output.append,
                                client_factory=lambda _: StreamingClient())
            terminal.handle_input("What does pricing.py do?")
            text = "\n".join(output)
            self.assertIn("The", text)
            self.assertIn("answer", text)
            self.assertIn("is 42.", text)
            self.assertEqual(terminal.session_provider_tokens, 7)

    def test_tool_activity_and_failed_tests_render_honestly(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, write=output.append)
            terminal.handle_activity({"type": "tool", "state": "start", "name": "zoom",
                                      "args": {"path": "pricing.py"}})
            terminal.handle_activity({"type": "tool", "state": "result", "name": "zoom",
                                      "ok": True, "elapsed": 0.12, "detail": "pricing.py"})
            terminal.handle_activity({"type": "tests", "passed": False, "exit_code": 1,
                                      "elapsed_seconds": 0.3, "output": "FAILED test_x"})
            text = "\n".join(output)
            self.assertIn("read", text)
            self.assertIn("pricing.py", text)
            self.assertIn("FAILED test_x", text)

    def test_task_summary_shows_status_usage_and_diff(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            output = []
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=output.append,
                                client_factory=lambda _: ScriptedClient())
            terminal.task("Fix discount")
            text = "\n".join(output)
            self.assertIn("tests passed", text)
            self.assertIn("pricing.py", text)
            self.assertIn("+1", text)
            self.assertIn("provider tokens", text)

    def test_non_interactive_exec_tasks_do_not_need_a_tty(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", test_command="exit 1",
                                write=output.append,
                                client_factory=lambda _: self.fail("Unexpected model call"))
            self.assertEqual(terminal.run(tasks=["hi"]), 0)
            text = "\n".join(output)
            self.assertIn("Hello!", text)
            self.assertIn("Session closed.", text)
            self.assertFalse(any("\x1b" in chunk for chunk in output))

    def test_usage_command_separates_messages_tasks_and_requests(self):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", test_command="exit 1",
                                write=output.append,
                                client_factory=lambda _: self.fail("Unexpected model call"))
            terminal.handle_input("hello")
            terminal.slash("/usage")
            text = "\n".join(output)
            self.assertIn("User messages", text)
            self.assertIn("Coding tasks", text)
            self.assertIn("Model requests", text)
            self.assertIn("no model requests yet", text)

    def test_cancelling_a_task_keeps_the_receipt_and_reports_interruption(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            output = []

            class InterruptingClient:
                def complete(self, *args, **kwargs):
                    raise KeyboardInterrupt

            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=output.append,
                                client_factory=lambda _: InterruptingClient())
            terminal.task("Fix discount")
            self.assertEqual(terminal.last_ledger.data["status"], "interrupted")
            self.assertIn("interrupted", "\n".join(output).lower())
            self.assertTrue(terminal.last_ledger.path.exists())

    def test_transport_failure_is_actionable_not_a_traceback(self):
        with tempfile.TemporaryDirectory() as root:
            output = []

            class Offline:
                def complete(self, *args, **kwargs):
                    raise RuntimeError("Cannot reach remote service; check its URL and availability")

            terminal = Terminal(root, model="fixture/model", write=output.append,
                                client_factory=lambda _: Offline())
            terminal.handle_input("What does pricing.py do?")
            text = "\n".join(output)
            self.assertIn("could not reach the model", text)
            self.assertIn("Start the gateway", text)
            self.assertEqual(terminal.gateway_state, "unreachable")

    def test_interactive_session_runs_a_scripted_multi_task_workflow(self):
        """Drive the real prompt loop over two tasks and check cross-task state."""
        class ErrorMessageClient:
            """Second task: same protocol fixture, a different real edit."""
            calls = 0

            def complete(self, messages, tools, max_tokens):
                self.calls += 1
                if self.calls == 1:
                    return response("zoom", {"path": "pricing.py", "level": 2})
                version = json.loads(messages[-1]["content"])["version"]
                return response("edit", {
                    "path": "pricing.py",
                    "old": 'raise ValueError("Invalid price or discount")',
                    "new": 'raise ValueError("Price must be non-negative and discount must be 0-100")',
                    "expected_version": version})

        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            output = []
            clients = iter([ScriptedClient(), ErrorMessageClient()])
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=output.append,
                                client_factory=lambda _: next(clients))
            exit_code = terminal.run(tasks=["Fix the discount calculation",
                                            "Fix the invalid-input error message in pricing.py"])
            text = "\n".join(output)
            self.assertEqual(exit_code, 0)
            self.assertIn("Session closed.", text)

            # Session accounting must cover both tasks, not only the last one.
            self.assertEqual(terminal.session_tasks_count, 2)
            self.assertEqual(len(terminal.task_history), 2)
            self.assertEqual([entry["status"] for entry in terminal.task_history],
                             ["tests_passed", "tests_passed"])
            self.assertEqual(terminal.session_model_requests, 4)
            self.assertEqual(terminal.session_provider_tokens, 480)
            self.assertEqual(terminal.session_provider_tokens,
                             sum(entry["tokens"] for entry in terminal.task_history))

            # Each task wrote its own patch, and each patch attributes only that
            # task's change. A unified diff also carries neighbouring lines as
            # context (task 2 reads the already-fixed file as its original), so
            # compare added/removed lines instead of raw patch text.
            patches = sorted((Path(root) / "runs").glob("session-*/patch.diff"))
            self.assertEqual(len(patches), 2)
            texts = [path.read_text(encoding="utf-8") for path in patches]
            self.assertNotEqual(texts[0], texts[1])
            changed = ["\n".join(line for line in item.splitlines()
                                 if line.startswith(("+", "-"))
                                 and not line.startswith(("+++", "---")))
                       for item in texts]
            self.assertEqual(sum("price * (1 - discount_percent / 100)" in item
                                 for item in changed), 1)
            self.assertEqual(sum("Price must be non-negative" in item for item in changed), 1)
            self.assertFalse(any("price * (1 - discount_percent / 100)" in item
                                 and "Price must be non-negative" in item for item in changed))

            # Both edits are real and cumulative in the workspace.
            self.assertEqual(terminal.workspace.modified, {"pricing.py"})
            final = (repo / "pricing.py").read_text(encoding="utf-8")
            self.assertIn("price * (1 - discount_percent / 100)", final)
            self.assertIn("Price must be non-negative", final)

            # Session commands report the whole session, not a single task.
            terminal.slash("/history")
            terminal.slash("/receipt")
            session_text = "\n".join(output)
            self.assertIn("session tasks (2)", session_text)
            self.assertIn("tests passed", session_text.lower())

    def test_approval_diff_option_then_accept_applies_the_edit(self):
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            answers = iter(["d", "y"])
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=lambda _: None,
                                read=lambda _: next(answers),
                                client_factory=lambda _: ScriptedClient())
            terminal.slash("/confirm on")
            terminal.task("Fix discount")
            self.assertEqual(terminal.last_ledger.data["status"], "tests_passed")
            self.assertIn("price * (1 - discount_percent / 100)", terminal.last_diff)


class TaskResultRenderingTests(unittest.TestCase):
    """A failed task renders one block, not a result panel plus an error block."""

    def render(self, error):
        with tempfile.TemporaryDirectory() as root:
            output = []
            terminal = Terminal(root, model="fixture/model", write=output.append)
            terminal.render_task_result({"status": "tests_failed", "model_calls": 1},
                                        1.0, Path(root), error=error)
            return "\n".join(output)

    def test_failure_renders_exactly_one_error_block(self):
        text = self.render(RuntimeError("provider returned HTTP 503"))
        self.assertEqual(text.count("the task stopped early"), 1)
        self.assertIn("provider returned HTTP 503", text)
        self.assertNotIn("tests_failed", text)
        self.assertNotIn("1 model request", text)

    def test_success_renders_the_result_panel_only(self):
        text = self.render(None)
        self.assertIn("tests_failed", text)
        self.assertNotIn("the task stopped early", text)


if __name__ == "__main__":
    unittest.main()

