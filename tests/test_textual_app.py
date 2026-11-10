"""Native Textual integration. Providers are scripted; MISER backend is real."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.app import App
from textual.widgets import Markdown, TextArea
from miser.terminal import Terminal
from miser.tui.textual_app import MiserApp, ApprovalScreen, QuestionScreen, MessageCard
from test_agent import response


class NativeApplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_charcoal_theme_and_persistent_activity_show_operations_not_invented_reasoning(self):
        from textual.widgets import Static
        from miser.ui import theme
        app = MiserApp(self.terminal)
        async with app.run_test(size=(80,24)) as pilot:
            self.assertEqual(app.screen.styles.background.hex.lower(), '#141414')
            self.assertEqual(theme.BG, '#141414')
            await app._activity({'type':'model_start','step':2})
            app._refresh_status()
            self.assertIn('Model request', str(app.ui('#workline',Static).render()))
            await app._activity({'type':'tool','state':'start','name':'zoom','args':{'path':'note.txt'}})
            app._refresh_status()
            self.assertIn('Reading note.txt', str(app.ui('#workline',Static).render()))
            self.assertLessEqual(app.ui('#composer').region.bottom,24)
            self.assertEqual(self.terminal.session_model_requests,0)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text("value = 1\n")
        self.terminal = Terminal(self.root, model="simulated/native", output_dir=self.root / "runs")

    async def idle(self, app, pilot):
        for _ in range(100):
            await pilot.pause(.03)
            if not app.busy:
                return
        self.fail("Backend worker did not finish")

    async def test_home_and_session_rail_show_only_real_workspace_facts_and_activity(self):
        from textual.widgets import Static
        app = MiserApp(self.terminal)
        async with app.run_test(size=(160,45)) as pilot:
            home = str(app.ui("#welcome-meta", Static).render())
            self.assertIn("simulated/native", home)
            self.assertIn(self.root.name, home)
            self.assertIn("No completed work", str(app.ui("#recent-details", Static).render()))
            await app._activity({"type": "tool", "state": "result", "name": "zoom",
                                 "ok": True, "elapsed": .02, "detail": "app.py"})
            await pilot.pause()
            recent = str(app.ui("#recent-details", Static).render())
            self.assertIn("zoom", recent)
            self.assertIn("0.02s", recent)
            self.assertEqual(self.terminal.session_model_requests, 0)
            self.assertEqual(self.terminal.session_tool_calls, 0)

    async def test_native_layout_and_composer_at_required_sizes(self):
        self.assertTrue(issubclass(MiserApp, App))
        for size in ((80, 24), (120, 36), (160, 45)):
            app = MiserApp(self.terminal)
            async with app.run_test(size=size) as pilot:
                self.assertIsInstance(app.query_one("#prompt"), TextArea)
                self.assertGreater(app.query_one("#conversation").size.height, 5)
                self.assertTrue(app.query_one("#composer").region.bottom <= size[1])
                self.assertTrue(app.query_one("#welcome").display)
                self.assertFalse(app.query_one("#inspector").display)
                app._show_home(False)
                self.assertEqual(app.query_one("#inspector").display, size[0] >= 118)
                await pilot.press("h", "i", "ctrl+j", "x")
                self.assertEqual(app.query_one("#prompt", TextArea).text, "hi\nx")

    async def test_greeting_local_file_and_commands_use_actual_backend_without_model(self):
        self.terminal.client_factory = lambda _: self.fail("Unexpected model request")
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("hello")
            await self.idle(app, pilot)
            self.assertTrue(any(card.kind == "assistant" for card in app.query(MessageCard)))
            await app.submit_text("show first line of app.py")
            await self.idle(app, pilot)
            self.assertEqual(self.terminal.last_ledger.data["metadata"]["mode"], "local-file-read")
            self.assertEqual(self.terminal.session_model_requests, 0)
            await app.submit_text("/budget 3000")
            await self.idle(app, pilot)
            self.assertEqual(self.terminal.budget, 3000)

    async def test_native_activity_displays_route_timings_and_actual_test_running_state(self):
        from textual.widgets import Static
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("hello")
            await self.idle(app, pilot)
            output = "\n".join(str(widget.render()) for widget in app.query(Static))
            self.assertIn("Route: conversation", output)
            self.assertIn("Model requests", output)
            self.assertEqual(self.terminal.session_model_requests, 0)
            await app._activity({"type": "tests", "baseline": True, "state": "start"})
            self.assertEqual(app._status, "Baseline checks")
            await app._activity({"type": "tests", "baseline": True, "passed": False,
                                 "exit_code": 1, "elapsed_seconds": 2.5})
            output = "\n".join(str(widget.render()) for widget in app.query(Static))
            self.assertIn("2.50s", output)
            self.assertEqual(app._last_checks, "failed (exit 1)")

    async def test_failed_tool_shows_reason_and_manual_checks_cannot_show_previous_green_status(self):
        from textual.widgets import Static
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app._activity({"type": "tool", "state": "result", "name": "apply_patch",
                                 "ok": False, "elapsed": .01, "error": "File deletion is unsupported"})
            output = "\n".join(str(widget.render()) for widget in app.query(Static))
            self.assertIn("File deletion is unsupported", output)
            app._last_checks = "passed"
            await app._activity({"type": "route", "profile": "coding", "test_policy": "manual",
                                 "verification": "manual checks"})
            self.assertEqual(app._last_checks, "skipped (manual)")

    async def test_streaming_updates_one_native_markdown_widget_and_keeps_source(self):
        source = "## Answer\n\n**Bold** and *italic*.\n\n| A | B |\n|---|---|\n|one|two|"
        class Client:
            supports_streaming = True
            def complete(self, messages, tools=None, **kwargs):
                for start in range(0, len(source), 5):
                    kwargs["on_token"](source[start:start+5])
                result = response()
                result["choices"][0]["message"]["content"] = source
                return result
        self.terminal.client_factory = lambda _: Client()
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("how are you?")
            await self.idle(app, pilot)
            cards = [card for card in app.query(MessageCard) if card.kind == "assistant"]
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0].source, source)
            self.assertIsInstance(cards[0].query_one(Markdown), Markdown)
            self.assertEqual(self.terminal.session_model_requests, 1)

    async def test_close_cancels_pending_approval_without_writing(self):
        class Client:
            def complete(self, *args, **kwargs):
                return response("write_file", {"path": "new.txt", "content": "must be approved"})
        import sys
        self.terminal.command = [sys.executable, "-m", "unittest", "discover", "-s", "."]
        self.terminal.confirm_edits = True
        self.terminal.client_factory = lambda _: Client()
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("Create new.txt")
            for _ in range(100):
                await pilot.pause(.03)
                if isinstance(app.screen, ApprovalScreen):
                    break
            self.assertIsInstance(app.screen, ApprovalScreen)
            self.assertFalse((self.root / "new.txt").exists())
            await pilot.press("ctrl+c")
            await self.idle(app, pilot)
            self.assertFalse((self.root / "new.txt").exists())
            self.assertEqual(self.terminal.last_ledger.data["status"], "interrupted")

    async def test_resize_completion_and_multiline_history_remain_native(self):
        app = MiserApp(self.terminal)
        async with app.run_test(size=(160, 45)) as pilot:
            self.assertFalse(app.ui("#inspector").display)
            app._show_home(False)
            self.assertTrue(app.ui("#inspector").display)
            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            self.assertFalse(app.ui("#inspector").display)
            editor = app.ui("#prompt", TextArea)
            editor.load_text("read app")
            app.action_complete()
            self.assertEqual(editor.text, "read app.py")
            app._history.remember("prior\nmultiline prompt")
            app.action_history_previous()
            self.assertEqual(editor.text, "prior\nmultiline prompt")
        saved = json.loads((self.root / ".miser" / "textual-history.json").read_text())
        self.assertEqual(saved, ["prior\nmultiline prompt"])
        second = MiserApp(self.terminal)
        async with second.run_test() as pilot:
            second.action_history_previous()
            self.assertEqual(second.ui(TextArea).text, "prior\nmultiline prompt")

    async def test_question_modal_resumes_the_actual_loop_with_the_answer(self):
        class Client:
            calls = 0
            def complete(inner, messages, tools, **kwargs):
                inner.calls += 1
                if inner.calls == 1:
                    return response("ask_user", {"question": "Which detail?", "options": ["API", "implementation"]})
                self.assertEqual(json.loads(messages[-1]["content"])["answer"], "API")
                return response()
        self.terminal.client_factory = lambda _: Client()
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("Explain app.py")
            for _ in range(100):
                await pilot.pause(.03)
                if isinstance(app.screen, QuestionScreen):
                    break
            self.assertIsInstance(app.screen, QuestionScreen)
            await pilot.press("1", "enter")
            await self.idle(app, pilot)
            self.assertEqual(self.terminal.last_ledger.data["status"], "answered")
            self.assertEqual(self.terminal.session_model_requests, 2)

    async def test_model_error_is_an_error_card_and_usage_stays_unknown(self):
        class Client:
            def complete(self, *args, **kwargs):
                raise RuntimeError("simulated failure")
        self.terminal.client_factory = lambda _: Client()
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app.submit_text("how are you?")
            await self.idle(app, pilot)
            self.assertTrue(any(card.kind == "error" for card in app.query(MessageCard)))
            self.assertEqual(self.terminal.session_unknown_usage, 1)
            self.assertEqual(self.terminal.session_provider_tokens, 0)

    async def test_native_scroll_and_new_submission_restore_follow_output(self):
        from textual.containers import VerticalScroll
        app = MiserApp(self.terminal)
        async with app.run_test(size=(80, 24)) as pilot:
            for _ in range(3):
                await app._append(MessageCard("system", "history line\n" * 30, "Fixture history"))
            await pilot.pause()
            view = app.ui("#conversation", VerticalScroll)
            view.scroll_end(immediate=True, animate=False)
            await pilot.pause()
            end = view.scroll_y
            self.assertGreater(end, 0)
            await pilot.press("pageup")
            await pilot.pause()
            self.assertLess(view.scroll_y, end)
            await app.submit_text("hello")
            await self.idle(app, pilot)
            self.assertTrue(view.is_vertical_scroll_end)
            self.assertEqual(self.terminal.session_model_requests, 0)

    async def test_command_and_mcp_approvals_are_fresh_native_dialogs(self):
        import threading
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            for kind in ("command", "mcp"):
                answers = []
                callback = (lambda: app._approve_command("git status")) if kind == "command" else (
                    lambda: app._approve_mcp("docs", "lookup", {"query": "safe"}))
                for _ in range(2):
                    worker = threading.Thread(target=lambda: answers.append(callback()))
                    try:
                        worker.start()
                        for _ in range(100):
                            await pilot.pause(.02)
                            if isinstance(app.screen, ApprovalScreen):
                                break
                        self.assertIsInstance(app.screen, ApprovalScreen)
                        self.assertEqual(app.screen.request.kind, kind)
                        self.assertEqual(len(app.screen.query("#all-edits")), 0)
                        await pilot.pause()
                        self.assertGreater(app.screen.query_one("#approve").region.height, 0)
                        self.assertTrue(await pilot.click("#approve", offset=(4, 1)))
                        deadline = asyncio.get_running_loop().time() + 1
                        while worker.is_alive() and asyncio.get_running_loop().time() < deadline:
                            await pilot.pause(.02)
                        self.assertFalse(worker.is_alive(), f"{kind}: decision event={app.screen.request.event.is_set() if isinstance(app.screen, ApprovalScreen) else 'dismissed'}")
                    finally:
                        if worker.is_alive():
                            self.terminal.cancel_event.set()
                            worker.join(1)
                self.assertEqual(answers, [True, True])

    async def test_link_inspection_displays_destination_without_opening_browser(self):
        app = MiserApp(self.terminal)
        with patch.object(app, "open_url") as opened:
            async with app.run_test() as pilot:
                app._assistant("[Docs](https://example.org)")
                await pilot.pause()
                markdown = app.query_one(Markdown)
                app.post_message(Markdown.LinkClicked(markdown, "https://example.org"))
                await pilot.pause()
                self.assertTrue(any(card.source == "https://example.org" for card in app.query(MessageCard)))
                opened.assert_not_called()

    async def test_explicit_approve_all_edits_applies_until_host_reenables_review(self):
        import threading
        self.terminal.confirm_edits = True
        app = MiserApp(self.terminal)
        async with app.run_test() as pilot:
            results = []
            for index in range(3):
                if index == 2:
                    self.terminal.confirm_edits = True
                worker = threading.Thread(target=lambda: results.append(app._approve_edit("app.py", "--- a/app.py\n+++ b/app.py\n")))
                try:
                    worker.start()
                    if index != 1:
                        for _ in range(100):
                            await pilot.pause(.02)
                            if isinstance(app.screen, ApprovalScreen):
                                break
                        await pilot.pause()
                        if index == 0:
                            self.assertTrue(await pilot.click("#all-edits", offset=(4, 1)))
                        else:
                            await pilot.press("escape")
                    deadline = asyncio.get_running_loop().time() + 1
                    while worker.is_alive() and asyncio.get_running_loop().time() < deadline:
                        await pilot.pause(.02)
                    self.assertFalse(worker.is_alive())
                finally:
                    if worker.is_alive():
                        self.terminal.cancel_event.set()
                        worker.join(1)
            self.assertEqual(results, [True, True, False])


    async def test_file_delete_cancel_then_fresh_approval_has_no_approve_all_and_keeps_undo(self):
        from textual.widgets import Button
        path = self.root / 'note.txt'
        path.write_text('Keep me until approved.\n')
        class Client:
            calls = 0
            def complete(inner, messages, tools, **kwargs):
                inner.calls += 1
                if inner.calls == 1:
                    return response('zoom', {'path':'note.txt','level':2})
                if inner.calls == 2:
                    return response('delete_file', {'path':'note.txt',
                        'expected_version':json.loads(messages[-1]['content'])['version']})
                answer = response()
                answer['choices'][0]['message']['content'] = 'Deleted with recovery copy; tests not run.'
                return answer
        self.terminal.task_mode = 'files'
        self.terminal.confirm_edits = False
        self.terminal.client_factory = lambda _: Client()
        app = MiserApp(self.terminal)
        async with app.run_test(size=(80,24)) as pilot:
            for attempt in range(2):
                await app.submit_text('Delete note.txt')
                for _ in range(100):
                    await pilot.pause(.03)
                    if isinstance(app.screen, ApprovalScreen) and {
                            button.id for button in app.screen.query(Button)} >= {'reject', 'approve'}:
                        break
                self.assertIsInstance(app.screen, ApprovalScreen)
                # The screen is pushed before its children finish composing.
                self.assertEqual({button.id for button in app.screen.query(Button)}, {'reject','approve'})
                self.assertTrue(path.exists())
                await pilot.press('ctrl+c' if attempt == 0 else 'tab', *([] if attempt == 0 else ['enter']))
                await self.idle(app, pilot)
                self.assertEqual(path.exists(), attempt == 0)
            self.assertEqual(self.terminal.last_ledger.data['status'], 'edited_unverified')
            self.assertFalse(any(event['kind']=='tests' for event in self.terminal.last_ledger.data['events']))
            self.terminal.undo()
            self.assertEqual(path.read_text(), 'Keep me until approved.\n')


class NativeLaunchSelectionTests(unittest.TestCase):
    def test_missing_ui_warning_gives_complete_project_launch_command(self):
        import contextlib
        import io
        from miser.cli import main
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as root, patch("miser.cli.load_env"), patch(
                "miser.cli.want_tui", return_value=False), patch.dict("os.environ", {}, clear=True), patch(
                "sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch(
                "miser.terminal.Terminal.run", return_value=0), contextlib.redirect_stderr(output):
            self.assertEqual(main(["chat", root, "--model", "unused"]), 0)
        self.assertIn(".venv/bin/python -m miser chat . --tui", output.getvalue())

    def test_diff_filenames_are_data_not_native_markup(self):
        from textual.content import Content
        from miser.tui.textual_app import DiffView
        view = DiffView("--- /dev/null\n+++ b/[red]name.py\n@@ -0,0 +1 @@\n+safe\n")
        self.assertIn("[red]name.py", Content.from_markup(view.title).plain)

    def test_cli_routes_forced_interactive_launch_to_textual_not_legacy(self):
        from miser.cli import main
        with tempfile.TemporaryDirectory() as root, patch("miser.cli.load_env"), patch(
                "sys.stdin.isatty", return_value=True), patch("sys.stdout.isatty", return_value=True), patch(
                "miser.tui.textual_app.MiserApp.run", return_value=0) as native, patch(
                "miser.tui.app.TuiApp.run", side_effect=AssertionError("Legacy UI must not launch")):
            self.assertEqual(main(["chat", root, "--tui", "--model", "unused"]), 0)
            native.assert_called_once()

    def test_required_tui_refuses_noninteractive_exec(self):
        from miser.cli import build_parser, want_tui
        args = build_parser().parse_args(["chat", "--tui", "--exec", "hello"])
        with self.assertRaisesRegex(ValueError, "non-interactive"):
            want_tui(args)


class WakeupCompatibilityTests(unittest.TestCase):
    class Loop:
        def __init__(self): self.callbacks, self.closed = [], False
        def call_later(self, delay, callback):
            self.callbacks.append(callback)
            return object()
        def is_closed(self): return self.closed

    def test_blocked_local_wakeup_installs_bounded_poll_and_stops_on_loop_close(self):
        import errno
        from unittest.mock import Mock
        from miser.tui.wakeup import ensure_wakeup_poll
        loop = self.Loop()
        left, right = Mock(), Mock()
        left.send.side_effect = PermissionError(errno.EPERM, "blocked")
        with patch("miser.tui.wakeup.socket.socketpair", return_value=(left, right)):
            self.assertTrue(ensure_wakeup_poll(loop))
        left.close.assert_called_once()
        right.close.assert_called_once()
        loop.callbacks[-1]()
        self.assertEqual(len(loop.callbacks), 2)
        loop.closed = True
        loop.callbacks[-1]()
        self.assertEqual(len(loop.callbacks), 2)

    def test_normal_local_wakeup_does_not_install_extra_poll(self):
        from unittest.mock import Mock
        from miser.tui.wakeup import ensure_wakeup_poll
        loop = self.Loop()
        with patch("miser.tui.wakeup.socket.socketpair", return_value=(Mock(), Mock())):
            self.assertFalse(ensure_wakeup_poll(loop))
        self.assertEqual(loop.callbacks, [])
