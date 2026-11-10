"""Reference redesign contracts: layout and Markdown, no provider or socket calls."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from miser.ui import render, theme
from miser.tui import screen
from miser.tui.app import TuiApp
from miser.terminal import Terminal
from test_agent import response


class MarkdownRedesignTests(unittest.TestCase):
    def test_append_stream_respects_tilde_fence_length(self):
        source = "~~~~python\nprint(1)\n~~~\n~~~~"
        rows = []
        stream = render.MarkdownStream(rows.append, 60, theme.Symbols(False))
        for start in range(0, len(source), 3):
            stream.feed(source[start:start + 3])
        stream.finish()
        self.assertEqual(rows, render.markdown(source, 60, theme.Symbols(False)))

    def test_line_stream_tables_and_emphasis_match_complete_rendering(self):
        source = "**Result** and *details*.\n\n| A | B |\n|---|---|\n|one|two|\n"
        rows = []
        stream = render.MarkdownStream(rows.append, 60)
        for start in range(0, len(source), 3):
            stream.feed(source[start:start + 3])
        stream.finish()
        text = "\n".join(rows)
        self.assertNotIn("*details*", text)
        self.assertNotIn("|---|", text)
        self.assertIn("one", text)
        self.assertIn("two", text)

    def test_diff_wraps_long_code_and_paths_without_losing_the_tail(self):
        path = "folder/" * 8 + "example.py"
        source = "--- /dev/null\n+++ b/" + path + "\n@@ -0,0 +1 @@\n+" + "value_" * 30 + "TAIL\n"
        text = render.render_diff(source, width=40, max_lines=None)
        self.assertIn("TAIL", text)
        self.assertTrue(all(theme.display_width(row) <= 40 for row in text.splitlines()))
        self.assertNotIn("…", text)

    def plain(self, text, width=60):
        return "\n".join(theme.ANSI_RE.sub("", row) for row in render.markdown(text, width))

    def test_emphasis_links_and_rules_are_typeset_without_raw_markers(self):
        text = self.plain("## Result\n\n**bold** and *italic* and `code`.\n\n[Docs](https://example.org)\n\n---")
        self.assertIn("italic", text)
        for marker in ("**", "*italic*", "[Docs]", "---", "##"):
            self.assertNotIn(marker, text)
        self.assertIn("https://example.org", text)

    def test_table_has_readable_cells_and_narrow_fallback(self):
        source = "| Operation | Result |\n| --- | --- |\n| read | success |\n| write | checked |"
        for width in (24, 60, 100):
            rows = render.markdown(source, width)
            self.assertTrue(all(theme.display_width(row) <= width for row in rows))
            text = "\n".join(rows)
            self.assertNotIn("---", text)
            self.assertIn("success", text)
            self.assertIn("checked", text)

    def test_tilde_fences_and_nested_lists_do_not_show_markdown_syntax(self):
        text = self.plain("1. first\n   - nested\n\n~~~python\nprint('safe')\n~~~")
        self.assertNotIn("~~~", text)
        self.assertIn("nested", text)
        self.assertIn("print('safe')", text)

    def test_partial_stream_can_replace_one_block_without_duplicating_text(self):
        updates = []
        stream = render.MarkdownStream(lambda _: self.fail("append in replace mode"), width=40,
                                       replace=updates.append)
        for chunk in ("**bo", "ld**\n\n", "| A | B |\n", "|---|---|\n|1|2|", "\n"):
            stream.feed(chunk)
        stream.finish()
        self.assertEqual(updates[-1], "**bold**\n\n| A | B |\n|---|---|\n|1|2|\n")
        self.assertEqual(stream.raw, updates[-1])

    def test_markdown_block_reflows_from_original_source_after_resize(self):
        source = "A paragraph with **emphasis** and a very long explanation. " * 4
        block = render.MarkdownBlock(source)
        for width in (100, 32, 80):
            rows = screen.reflow_transcript([block], width)
            self.assertTrue(all(row.cell_len <= width for row in rows))
            self.assertEqual(block.source, source)
            self.assertNotIn("**", "\n".join(row.plain for row in rows))

    def test_code_is_preserved_and_highlighted_without_terminal_injection(self):
        source = "```python\nvalue = 42\nprint(value)\n```"
        with patch("miser.ui.theme.color_enabled", return_value=True):
            rows = render.markdown(source, 60)
        self.assertIn("value = 42", "\n".join(theme.ANSI_RE.sub("", row) for row in rows))
        self.assertIn("38;2;", "\n".join(rows))
        self.assertNotIn("\x1b]", "\n".join(render.markdown("[link](https://example.org)", 60)))


class ReferenceLayoutTests(unittest.TestCase):
    def test_cursor_remains_visible_at_the_end_of_a_full_input_row(self):
        from rich.style import Style
        state = screen.UIState(width=40, height=24, mode="conversation", input_text="x" * 35, cursor=35)
        rows = screen.render(state)
        self.assertTrue(any(isinstance(span.style, Style) and span.style.bgcolor
                            and span.style.bgcolor.name == screen.ACCENT
                            for row in rows for span in row.spans))

    def test_composer_wraps_wide_unicode_by_cells_without_losing_input(self):
        source = "界" * 30
        rows = screen._wrap_rows(source, 20)
        self.assertTrue(all(theme.display_width(row[0]) <= 20 for row in rows))
        self.assertEqual("".join(row[0] for row in rows), source)

    def test_unmetered_requests_are_not_presented_as_zero_cost(self):
        from test_tui_app import FakeTerminal
        terminal = FakeTerminal()
        terminal.session_model_requests = 1
        terminal.session_unknown_usage = 1
        app = TuiApp(terminal)
        self.assertEqual(app.ui_state().tokens, "usage unknown")

    def test_user_surface_fills_only_the_content_column(self):
        from rich.text import Text
        from rich.style import Style
        from rich.console import Console
        state = screen.UIState(width=100, height=24, mode="conversation", transcript=[
            Text("▌ a user message", style=Style(bgcolor=screen.COMPOSER_BG))])
        row = screen.render(state)[2]
        end = screen.content_left(100) + screen.content_width(100) - 1
        self.assertEqual(row.get_style_at_offset(Console(), end).bgcolor.name, screen.COMPOSER_BG)
        self.assertEqual(row.get_style_at_offset(Console(), 0).bgcolor.name, screen.BG)

    def test_welcome_is_compact_and_uses_persistent_input_not_giant_logo(self):
        state = screen.UIState(width=120, height=32, model="simulated", workspace="/tmp/demo")
        rows = screen.render(state)
        text = "\n".join(row.plain for row in rows)
        self.assertIn("MISER", rows[0].plain)
        self.assertNotIn("████", text)
        self.assertIn("/help", text)
        self.assertTrue(any("Ask anything" in row.plain for row in rows[-7:]))

    def test_wide_header_includes_workspace_usage_and_model(self):
        state = screen.UIState(width=140, height=30, mode="conversation", model="simulated",
                               workspace="~/fresh-code", tokens="5,214 tok", tasks=1)
        text = screen.render(state)[0].plain
        for value in ("MISER", "simulated", "fresh-code", "5,214 tok"):
            self.assertIn(value, text)

    def test_failure_status_never_uses_success_color(self):
        state = screen.UIState(width=100, height=24, mode="conversation", tests="tests not passing")
        rows = screen.render(state)
        styles = [str(span.style) for row in rows for span in row.spans
                  if "not passing" in row.plain[span.start:span.end]]
        self.assertTrue(any(screen.BAD in style for style in styles))


class AgentPresentationTests(unittest.TestCase):
    def test_output_arriving_during_a_frame_schedules_another_repaint(self):
        from unittest.mock import Mock
        from test_tui_app import FakeTerminal
        io = Mock()
        io.size.return_value = (80, 24)
        app = TuiApp(FakeTerminal(), screen_io=io)
        io.draw.side_effect = lambda _: app.append_output("arrived during drawing")
        app.draw()
        self.assertTrue(app.dirty)
        self.assertIn("arrived during drawing", app.transcript[-1].plain)

    def test_edit_approval_worker_observes_cancellation_without_another_key(self):
        import threading, time
        from test_tui_app import FakeTerminal
        app = TuiApp(FakeTerminal())
        worker = threading.Thread(target=lambda: app.request_approval("app.py", "diff"))
        try:
            worker.start()
            deadline = time.monotonic() + 1
            while app.approval is None and time.monotonic() < deadline:
                time.sleep(.005)
            app.terminal.cancel_event.set()
            worker.join(.3)
            self.assertFalse(worker.is_alive())
        finally:
            app._resolve_approval(False)
            worker.join(1)

    def test_nonstreaming_agent_answer_is_rendered_as_markdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 42\n")
            class Client:
                def complete(self, *args, **kwargs):
                    result = response()
                    result["choices"][0]["message"]["content"] = "## Verified\n\nA **simulated** answer."
                    return result
            terminal = Terminal(root, model="simulated", output_dir=root / "runs", client_factory=lambda _: Client())
            app = TuiApp(terminal)
            terminal.task("Explain app.py")
            blocks = [entry for entry in app.transcript if isinstance(entry, render.MarkdownBlock)]
            self.assertEqual([block.source for block in blocks], ["## Verified\n\nA **simulated** answer."])

    def test_streamed_model_turns_keep_tool_output_between_separate_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("value = 42\n")
            class Client:
                supports_streaming = True
                calls = 0
                def complete(self, *args, **kwargs):
                    self.calls += 1
                    result = response("zoom", {"path": "app.py", "level": 2}) if self.calls == 1 else response()
                    text = "Looking **now**." if self.calls == 1 else "## Answer\n\nIt stores 42."
                    kwargs["on_token"](text)
                    result["choices"][0]["message"]["content"] = text
                    return result
            terminal = Terminal(root, model="simulated", output_dir=root / "runs", client_factory=lambda _: Client())
            app = TuiApp(terminal)
            terminal.task("Explain app.py")
            indexed = [(i, entry) for i, entry in enumerate(app.transcript) if isinstance(entry, render.MarkdownBlock)]
            self.assertEqual([entry.source for _, entry in indexed], ["Looking **now**.", "## Answer\n\nIt stores 42."])
            self.assertTrue(any("read" in entry.plain for entry in app.transcript[indexed[0][0] + 1:indexed[1][0]]))
