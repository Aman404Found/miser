import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from miser import tui
from miser.cli import build_parser, want_tui
from miser.tui.app import TuiApp
from miser.tui.keys import Key


class FakeSpinner:
    enabled = True

    def stop(self):
        pass

    def start(self, text=""):
        pass


class FakeTerminal:
    def __init__(self):
        self.spinner = FakeSpinner()
        self.model = "gemini/gemini-3.5-flash"
        self.repo = Path("/tmp/workspace")
        self.budget = 24000
        self.confirm_edits = False
        self.cancel_event = threading.Event()
        self.activity_listener = None
        self.prompt_edit_approval = None
        self.task_history = []
        self.session_tasks_count = 0
        self.session_model_requests = 0
        self.session_provider_tokens = 0
        self.last_bill = None
        self.tasks = []
        self.write = None

    def tokens_text(self):
        return "no provider tokens yet"

    def slash(self, line):
        if line == "/raised":
            raise ValueError("bad command")

    def task(self, text):
        self.tasks.append(text)
        self.write("working on it")

    def error_report(self, error):
        return f"error: {error}"


class TuiAppTests(unittest.TestCase):
    def make_app(self):
        return TuiApp(FakeTerminal())

    def test_submitting_input_transitions_to_conversation(self):
        app = self.make_app()
        app.input.set_text("fix the discount")
        app.submit()
        app._worker.join(1)
        self.assertEqual(app.mode, "conversation")
        self.assertFalse(app.busy)
        self.assertEqual(app.terminal.tasks, ["fix the discount"])
        text = "\n".join(entry.plain for entry in app.transcript)
        self.assertIn("fix the discount", text)
        self.assertIn("working on it", text)

    def test_submit_is_blocked_while_a_task_runs(self):
        app = self.make_app()
        app.busy = True
        app.input.set_text("second task")
        app.submit()
        self.assertEqual(app.terminal.tasks, [])
        self.assertEqual(app.input.value(), "second task")
        self.assertIn("task running", app.status)

    def test_slash_clear_returns_to_welcome(self):
        app = self.make_app()
        app.input.set_text("/help")
        app.submit()
        self.assertTrue(app.transcript)
        app.input.set_text("/clear")
        app.submit()
        self.assertEqual(app.mode, "welcome")
        self.assertEqual(app.transcript, [])

    def test_slash_errors_are_rendered_not_raised(self):
        app = self.make_app()
        app.input.set_text("/raised")
        app.submit()
        text = "\n".join(entry.plain for entry in app.transcript)
        self.assertIn("error: bad command", text)

    def test_ctrl_c_cancels_running_task(self):
        app = self.make_app()
        app.busy = True
        app.terminal.cancel_event.clear()
        app.handle_key(Key("ctrl+c"))
        self.assertTrue(app.terminal.cancel_event.is_set())
        self.assertIn("cancelling", app.status)

    def test_ctrl_d_exits_only_when_idle(self):
        app = self.make_app()
        app.busy = True
        app.handle_key(Key("ctrl+d"))
        self.assertTrue(app.running)
        app.busy = False
        app.handle_key(Key("ctrl+d"))
        self.assertFalse(app.running)

    def test_approval_handshake_releases_worker(self):
        app = self.make_app()
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault("value", app.request_approval(
            "pricing.py", "--- a/pricing.py\n+++ b/pricing.py\n@@ -1 +1 @@\n-price\n+price")))
        worker.start()
        deadline = time.time() + 1
        while app.approval is None and time.time() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(app.approval)
        app.handle_key(Key("char", "y"))
        worker.join(1)
        self.assertTrue(result["value"])
        self.assertIsNone(app.approval)
        self.assertIn("proposed edit", "\n".join(entry.plain for entry in app.transcript))

    def test_approval_rejection_and_full_diff(self):
        app = self.make_app()
        worker = threading.Thread(target=lambda: app.request_approval("pricing.py", "+++ b/pricing.py\n+new"))
        worker.start()
        deadline = time.time() + 1
        while app.approval is None and time.time() < deadline:
            time.sleep(0.01)
        app.handle_key(Key("char", "d"))
        self.assertIsNotNone(app.approval)
        app.handle_key(Key("char", "n"))
        worker.join(1)
        self.assertIsNone(app.approval)

    def test_prompt_history_persists_in_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / ".miser" / "history"
            history.parent.mkdir()
            history.write_text("earlier prompt\nsecond prompt\n")
            terminal = FakeTerminal()
            terminal.repo = Path(directory)
            terminal.workspace = types.SimpleNamespace(root=Path(directory))
            app = TuiApp(terminal)
            self.assertEqual(app.input.history[-2:], ["earlier prompt", "second prompt"])
            app.input.remember("new prompt")
            app._save_history()
            self.assertIn("new prompt", history.read_text())

    def test_tab_completion_and_history(self):
        app = self.make_app()
        app.input.set_text("/mod")
        app.handle_key(Key("tab"))
        self.assertEqual(app.input.value(), "/model")
        app.input.remember("previous task")
        app.input.clear()
        app.handle_key(Key("up"))
        self.assertEqual(app.input.value(), "previous task")

    def test_paste_and_newline_are_multiline(self):
        app = self.make_app()
        app.handle_key(Key("paste", "first\nsecond"))
        app.handle_key(Key("newline"))
        app.handle_key(Key("char", "!"))
        self.assertEqual(app.input.value(), "first\nsecond\n!")

    def test_footer_hints_scrollback_when_idle(self):
        app = self.make_app()
        app.mode = "conversation"
        footer = tui.screen.render(app.ui_state())[-1].plain
        self.assertIn("PgUp history", footer)

    def test_scrolling_is_clamped(self):
        app = self.make_app()
        for index in range(5):
            app.append_output(f"line {index}")
        app.handle_key(Key("pageup"))
        self.assertGreater(app.scroll, 0)
        app.handle_key(Key("pagedown"))
        self.assertEqual(app.scroll, 0)


class InterfaceSelectionTests(unittest.TestCase):
    def args(self, **overrides):
        parser = build_parser()
        values = ["chat"] + sum(([f"--{key.replace('_', '-')}"] for key in overrides), [])
        return parser.parse_args(values)

    def test_tui_requires_a_tty(self):
        args = self.args()
        with mock.patch.object(sys.stdin, "isatty", return_value=False), \
                mock.patch.object(sys.stdout, "isatty", return_value=True), \
                mock.patch.dict(os.environ, {}, clear=False):
            self.assertFalse(want_tui(args))

    def test_no_color_and_no_tui_fall_back_to_line_mode(self):
        args = self.args()
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch.object(sys.stdout, "isatty", return_value=True), \
                mock.patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertFalse(want_tui(args))
        self.assertFalse(want_tui(self.args(no_tui=True)))

    def test_exec_is_non_interactive(self):
        parser = build_parser()
        args = parser.parse_args(["chat", "--exec", "fix it"])
        with mock.patch.object(sys.stdin, "isatty", return_value=True), \
                mock.patch.object(sys.stdout, "isatty", return_value=True), \
                mock.patch.dict(os.environ, {}, clear=False):
            self.assertFalse(want_tui(args))


if __name__ == "__main__":
    unittest.main()
