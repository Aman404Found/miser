"""Deterministic capability tests: scripted models and no network/listeners."""

import io
import contextlib
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from miser.agent import run_agent
from miser.ledger import Ledger, receipt
from miser.terminal import Terminal
from miser.tools import SCHEMAS, ToolRunner
from miser.workspace import Workspace
from test_agent import batch_response, response


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text("def total():\n    return 42\n")
        self.ledger = Ledger(self.root / "ledger.json", mode="synthetic-capability-test")
        self.ws = Workspace(self.root)

    def runner(self, **kwargs):
        return ToolRunner(self.ws, self.ledger, [], profile="inspect", **kwargs)

    def test_inspection_reads_real_source_with_no_tests_or_architect_request(self):
        class Client:
            calls = 0
            schemas = None
            messages = None

            def complete(self, messages, tools, **kwargs):
                self.calls += 1
                self.schemas = tools
                self.messages = messages
                return response("zoom", {"path": "app.py", "level": 2}) if self.calls == 1 else response()

        client = Client()
        runner = self.runner()
        with patch.object(runner, "run_tests", side_effect=AssertionError("Must not run acceptance")), patch(
                "miser.agent.plan_task", side_effect=AssertionError("Inspection needs no architect")):
            status = run_agent("Explain app.py", client, runner, self.ledger, architect_client=object())
        self.assertEqual(status, "answered")
        names = {item["function"]["name"] for item in client.schemas}
        self.assertEqual(names, {"repo_map", "list_files", "find_files", "search", "zoom", "recall",
                                 "read_many", "blast_radius", "ask_user"})
        self.assertIn("return 42", client.messages[-1]["content"])
        bill = receipt(self.ledger.data)
        self.assertEqual(bill["test_runs"], 0)
        self.assertEqual(bill["model_calls"], 2)
        self.assertEqual(bill["total_tokens"], 240)  # synthetic protocol usage
        self.assertEqual(next(e for e in self.ledger.data["events"] if e["kind"] == "model_request")["purpose"], "inspect")

    def test_inspect_dispatch_refuses_all_mutations_commands_tests_and_web(self):
        runner = self.runner()
        for name in ("edit", "edit_batch", "apply_patch", "write_file", "run_tests", "run_command",
                     "write_todos", "web_search", "fetch_url", "verify_claim"):
            with self.subTest(tool=name):
                result = json.loads(runner.invoke(name, {}))
                self.assertIn("inspect", result["error"])
                self.assertIn("unavailable", result["error"])
        with self.assertRaises(ValueError):
            runner.run_tests()
        self.assertEqual(self.ws.modified, set())
        self.assertEqual((self.root / "app.py").read_text(), "def total():\n    return 42\n")

    def test_hallucinated_write_in_inspection_gets_error_and_cannot_change_files(self):
        class Client:
            calls = 0

            def complete(inner, messages, tools, **kwargs):
                inner.calls += 1
                if inner.calls == 1:
                    return batch_response(("write_file", {"path": "bad.py", "content": "bad"}), ("list_files", {}))
                tool_results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
                self.assertIn("unavailable", tool_results[0]["error"])
                return response()

        self.assertEqual(run_agent("Inspect app.py", Client(), self.runner(), self.ledger), "answered")
        self.assertFalse((self.root / "bad.py").exists())
        self.assertEqual(receipt(self.ledger.data)["test_runs"], 0)

    def test_research_profile_allows_web_but_not_execution_or_edits(self):
        runner = ToolRunner(self.ws, self.ledger, [], profile="research")
        names = {item["function"]["name"] for item in runner.schemas}
        self.assertTrue({"web_search", "fetch_url", "verify_claim", "ask_user"} <= names)
        self.assertTrue({"run_command", "run_tests", "write_file", "edit"}.isdisjoint(names))
        self.assertIn("unavailable", json.loads(runner.invoke("run_command", {}))["error"])

    def test_terminal_routes_repo_questions_to_read_only_loop_without_test_configuration(self):
        class Client:
            calls = 0

            def complete(self, messages, tools, **kwargs):
                self.calls += 1
                return response("zoom", {"path": "app.py", "level": 2}) if self.calls == 1 else response()

        terminal = Terminal(self.root, model="synthetic", output_dir=self.root / "runs",
                            write=lambda _: None, client_factory=lambda _: Client())
        terminal.handle_input("How does app.py work?")
        self.assertEqual(terminal.last_ledger.data["metadata"]["profile"], "inspect")
        self.assertEqual(receipt(terminal.last_ledger.data)["test_runs"], 0)
        self.assertEqual(terminal.command, [])

    def test_explicit_change_request_keeps_the_coding_path(self):
        terminal = Terminal(self.root, model="synthetic", write=lambda _: None)
        with patch("miser.terminal.run_agent", return_value="answered") as agent, patch.object(
                terminal, "auto_detect_test_command", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Set /test"):
                terminal.task("Review app.py and fix the bug")
        agent.assert_not_called()

    def test_clarification_answer_resumes_the_same_model_task_without_logging_answer(self):
        secret_free_answer = "Use weekly totals"
        seen = []
        runner = self.runner(clarification_callback=lambda question, options: seen.append((question, options)) or secret_free_answer)

        class Client:
            calls = 0

            def complete(inner, messages, tools, **kwargs):
                inner.calls += 1
                if inner.calls == 1:
                    return response("ask_user", {"question": "Which totals?", "options": ["Daily", "Weekly"]})
                result = json.loads(messages[-1]["content"])
                self.assertEqual(result["answer"], secret_free_answer)
                self.assertEqual(result["source"], "user")
                return response()

        client = Client()
        self.assertEqual(run_agent("Inspect app.py", client, runner, self.ledger), "answered")
        self.assertEqual(seen, [("Which totals?", ["Daily", "Weekly"])])
        self.assertNotIn(secret_free_answer, self.ledger.path.read_text())
        self.assertEqual(client.calls, 2)

    def test_unavailable_or_declined_clarification_stops_without_another_model_call(self):
        for callback in (None, lambda *_: None):
            with self.subTest(callback=callback):
                ledger = Ledger(self.root / "question.json")
                runner = ToolRunner(self.ws, ledger, [], profile="inspect", clarification_callback=callback)

                class Client:
                    calls = 0

                    def complete(self, *args, **kwargs):
                        self.calls += 1
                        return response("ask_user", {"question": "Which file?"})

                client = Client()
                self.assertEqual(run_agent("Inspect the repository", client, runner, ledger), "needs_input")
                self.assertEqual(client.calls, 1)
                self.assertEqual(ledger.data["question"], "Which file?")
                from miser.ui import render, theme
                panel = render.result_panel(receipt(ledger.data), 0, glyphs=theme.symbols())
                self.assertTrue(theme.clean(panel).startswith(theme.symbols().warn))

    def test_clarification_validates_shape_and_limits_prompts(self):
        seen = []
        runner = self.runner(clarification_callback=lambda *args: seen.append(args) or "answer")
        for args in ({"question": ""}, {"question": "Q", "options": "bad"},
                     {"question": "Q", "options": ["a"] * 6}, {"question": "Q", "extra": "bad"}):
            with self.subTest(args=args):
                self.assertIn("error", json.loads(runner.invoke("ask_user", args)))
        self.assertEqual(seen, [])
        for _ in range(3):
            self.assertIn("answer", json.loads(runner.invoke("ask_user", {"question": "Q"})))
        self.assertIn("limit", json.loads(runner.invoke("ask_user", {"question": "Q"}))["error"])
        self.assertEqual(len(seen), 3)

    def test_piped_stdin_is_not_used_for_clarification(self):
        terminal = Terminal(self.root, write=lambda _: None)
        with patch("sys.stdin", io.StringIO("answer\n")):
            self.assertIsNone(terminal.prompt_clarification("Which file?", []))

    def test_batch_mode_never_prompts_even_with_a_custom_interactive_reader(self):
        terminal = Terminal(self.root, read=lambda _: self.fail("Batch mode must not ask for input"),
                            write=lambda _: None)
        terminal.batch_mode = True
        for method, args in ((terminal.prompt_clarification, ("Which file?", [])),
                             (terminal.prompt_command_approval, ("git status",)),
                             (terminal.prompt_edit_approval, ("app.py", "diff"))):
            with self.subTest(method=method.__name__):
                self.assertFalse(method(*args))

    def test_profile_selection_preserves_advice_and_explicit_edit_boundaries(self):
        from miser.intent import task_profile
        cases = {
            "Explain app.py": "inspect", "How do I fix app.py?": "inspect",
            "Inspect": "inspect", "Review edit.py": "inspect",
            "Review app.py without modifying it": "inspect",
            "Review app.py and do not change files": "inspect",
            "Review app.py for code that may delete files": "inspect",
            "Search code for edit": "inspect", "Find references in app.py": "inspect",
            "Review app.py, fix the bug": "coding",
            "Explain app.py and fix the bug": "coding", "Fix app.py": "coding",
            "discounted_price should subtract the discount": "coding",
            "What does discounted_price do?": "inspect",
            "Look up official documentation for pathlib": "research", "How are you?": None,
        }
        for task, expected in cases.items():
            with self.subTest(task=task):
                self.assertEqual(task_profile(task), expected)

    def test_clarification_cannot_be_batched_with_preplanned_writes(self):
        seen = []
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"],
                            clarification_callback=lambda *_: seen.append(True) or "No")

        class Client:
            def complete(self, *args, **kwargs):
                return batch_response(("ask_user", {"question": "Which file?"}),
                                      ("write_file", {"path": "bad.py", "content": "bad"}))

        run_agent("Add a file", Client(), runner, self.ledger, max_steps=1)
        self.assertFalse((self.root / "bad.py").exists())
        self.assertEqual(seen, [])
        self.assertTrue(any(e["kind"] == "tool" and not e["success"] for e in self.ledger.data["events"]))

    def test_cli_inspection_needs_no_test_command_but_coding_still_requires_one(self):
        from miser.cli import main

        class Client:
            def complete(self, *args, **kwargs):
                return response()

        target = self.root / "inspection"
        with patch("miser.cli.load_env"), patch("miser.cli.ModelClient", return_value=Client()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["run", str(self.root), "Explain app.py", "--profile", "inspect",
                                   "--model", "synthetic", "--out", str(target)]), 0)
        bill = receipt(json.loads((target / "ledger.json").read_text()))
        self.assertEqual(bill["test_runs"], 0)
        self.assertEqual(bill["status"], "answered")
        with patch("miser.cli.load_env"), patch("miser.cli.ModelClient") as client, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["run", str(self.root), "Fix app.py", "--model", "synthetic"]), 2)
        client.assert_not_called()

    def test_headless_cli_reports_the_unanswered_question_and_returns_failure(self):
        from miser.cli import main

        class Client:
            def complete(self, *args, **kwargs):
                return response("ask_user", {"question": "Which totals should I inspect?"})

        output = io.StringIO()
        with patch("miser.cli.load_env"), patch("miser.cli.ModelClient", return_value=Client()), contextlib.redirect_stdout(output):
            result = main(["run", str(self.root), "Inspect app.py", "--model", "synthetic",
                           "--out", str(self.root / "pending")])
        self.assertEqual(result, 1)
        self.assertIn("Which totals should I inspect?", output.getvalue())


class TuiClarificationTests(unittest.TestCase):
    def test_answered_question_does_not_overwrite_followup_composer_text(self):
        from test_tui_app import FakeTerminal
        from miser.tui.app import TuiApp
        from miser.tui.keys import Key

        app = TuiApp(FakeTerminal())
        answered, release = threading.Event(), threading.Event()

        class Gate:
            def wait(self, timeout):
                result = answered.wait(timeout)
                if result:
                    release.wait(2)
                return result

            def set(self):
                answered.set()

        worker = threading.Thread(target=lambda: app.request_clarification("Which file?", []))
        try:
            with patch("miser.tui.app.threading.Event", return_value=Gate()):
                worker.start()
                deadline = time.monotonic() + 1
                while app.question is None and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertIsNotNone(app.question)
                app.handle_key(Key("paste", "app.py"))
                app.handle_key(Key("enter"))
                app.handle_key(Key("paste", "follow-up"))
                release.set()
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(app.input.value(), "follow-up")
        finally:
            app.terminal.cancel_event.set()
            answered.set()
            release.set()
            worker.join(1)

    def start_question(self):
        from test_tui_app import FakeTerminal
        from miser.tui.app import TuiApp
        app = TuiApp(FakeTerminal())
        self.assertTrue(hasattr(app, "request_clarification"))
        answer = []
        worker = threading.Thread(target=lambda: answer.append(app.request_clarification("Which totals?", ["Daily", "Weekly"])))
        worker.start()
        self.addCleanup(lambda: (app.terminal.cancel_event.set(), app._question_event.set(), worker.join(1)))
        deadline = time.monotonic() + 1
        while app.question is None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNotNone(app.question)
        return app, worker, answer

    def test_tui_number_selection_answers_without_submitting_a_second_task(self):
        from miser.tui.keys import Key
        app, worker, answer = self.start_question()
        app.handle_key(Key("paste", "2"))
        app.handle_key(Key("enter"))
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(answer, ["Weekly"])
        self.assertEqual(app.terminal.tasks, [])

    def test_tui_eof_releases_the_waiting_question(self):
        from miser.tui.keys import Key
        app, worker, answer = self.start_question()
        app.handle_key(Key("eof"))
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(answer, [None])
        self.assertFalse(app.running)


if __name__ == "__main__":
    unittest.main()
