"""Recent turns and terminal layout regressions; all model replies are simulated."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miser.terminal import Terminal
from miser.intent import parse_file_read
from miser.ui import render, theme
from test_agent import response


class RecentTurnsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text("one\ntwo\nthree\nfour\nfive\n")
        self.output = []
        self.requests = []
        owner = self

        class Client:
            def complete(self, messages, tools=None, **kwargs):
                owner.requests.append(messages)
                result = response()
                result["choices"][0]["message"]["content"] = "Simulated answer"
                return result

        self.term = Terminal(self.root, model="simulated", write=self.output.append,
                             output_dir=self.root / "runs", client_factory=lambda _: Client())

    def test_previous_message_includes_local_file_requests_without_a_model(self):
        self.term.handle_input("am i readable?")
        self.term.handle_input("read README.md and print first line")
        self.output.clear()
        before = len(self.requests)
        self.term.handle_input("what was my previous message?")
        self.assertIn("read README.md and print first line", "\n".join(self.output))
        self.assertEqual(len(self.requests), before)

    def test_tui_task_entry_records_greetings_and_previous_queries_in_order(self):
        self.term.task("hello")
        self.term.task("what was my previous message?")
        self.assertIn("hello", "\n".join(self.output))
        self.output.clear()
        self.term.task("repeat my previous message")
        self.assertIn("what was my previous message?", "\n".join(self.output))
        self.assertEqual(self.requests, [])

    def test_empty_history_is_honest_and_slash_commands_do_not_become_turns(self):
        self.term.handle_input("/status")
        self.term.handle_input("what was my previous message?")
        self.assertIn("No previous message", "\n".join(self.output))
        self.assertEqual(self.requests, [])

    def test_general_question_receives_intervening_file_read_exactly_once(self):
        self.term.task("read README.md and print first line")
        self.term.task("how are you?")
        messages = self.requests[-1]
        self.assertEqual(sum(m.get("content") == "read README.md and print first line" for m in messages), 1)
        self.assertEqual(sum(m.get("content") == "how are you?" for m in messages), 1)

    def test_inspection_gets_recent_turn_data_without_replaying_old_tools(self):
        self.term.task("read README.md and print first line")
        self.term.task("Explain README.md")
        states = [json.loads(m["content"]) for m in self.requests[-1] if m["role"] == "user"]
        context = states[0]["recent_conversation"]
        self.assertEqual(context[0]["content"], "read README.md and print first line")
        self.assertTrue(all(m["role"] in {"user", "assistant"} for m in context))

    def test_failed_request_still_counts_as_previous_message(self):
        self.term.model = None
        with self.assertRaises(ValueError):
            self.term.task("Fix the bug")
        self.term.task("what was my previous message?")
        self.assertIn("Fix the bug", "\n".join(self.output))

    def test_inspection_answer_is_available_to_the_next_general_question(self):
        self.term.task("Explain README.md")
        self.term.task("how are you?")
        self.assertIn({"role": "assistant", "content": "Simulated answer"}, self.requests[-1])

    def test_recent_context_is_bounded_and_isolated_between_sessions(self):
        for index in range(10):
            self.term.task("hello")
        self.assertLessEqual(len(self.term.conversation_history), 12)
        self.assertLessEqual(len(json.dumps(self.term.conversation_history, ensure_ascii=False).encode()), 12000)
        other = Terminal(self.root, write=lambda _: None)
        self.assertEqual(other.conversation_history, [])

    def test_screenshot_file_request_is_local_but_compound_edit_is_not(self):
        request = "i want you to read 4 lines from Readme.md and then print here"
        self.assertEqual(parse_file_read(request), ("Readme.md", 4))
        self.assertIsNone(parse_file_read(request + " and edit it"))
        with patch("miser.terminal.run_agent") as agent:
            self.term.task(request)
        agent.assert_not_called()
        self.assertEqual(self.requests, [])
        self.assertIn("one\ntwo\nthree\nfour", "\n".join(self.output))


class LayoutRegressionTests(unittest.TestCase):
    def test_tui_reflows_long_transcript_rows_instead_of_cropping_the_tail(self):
        from rich.text import Text
        from miser.tui import screen
        state = screen.UIState(width=40, height=24, mode="conversation",
                               transcript=[Text("HEAD" + "x" * 120 + "TAIL")])
        output = "\n".join(row.plain for row in screen.render(state))
        self.assertIn("HEAD", output)
        self.assertIn("TAIL", output)

    def test_tui_can_scroll_within_one_long_wrapped_entry(self):
        from rich.text import Text
        from miser.tui.app import TuiApp
        from test_tui_app import FakeTerminal
        from unittest.mock import Mock
        app = TuiApp(FakeTerminal(), screen_io=Mock())
        app.screen_io.size.return_value = (40, 24)
        app.transcript = [Text("HEAD" + "x" * 1500 + "TAIL")]
        app._scroll(20)
        self.assertEqual(app.scroll, 20)

    def test_long_headings_and_model_labels_respect_column_width(self):
        lines = render.markdown("# " + "Long title " * 20, 30)
        self.assertTrue(all(theme.display_width(line) <= 30 for line in lines))
        self.assertLessEqual(theme.display_width(render.agent_label("provider/" + "model" * 20, 30)), 30)

    def test_long_code_lines_wrap_without_losing_content(self):
        code = "abc_" * 40
        lines = render.markdown("```python\n" + code + "\n```", 30, theme.Symbols(False))
        self.assertTrue(all(theme.display_width(line) <= 30 for line in lines))
        self.assertEqual("".join(line[4:] for line in lines[1:-1]), code)

    def test_streamed_closing_fence_without_newline_is_not_printed_as_code(self):
        lines = []
        stream = render.MarkdownStream(lines.append, 30, theme.Symbols(False))
        for piece in ("```py\n", "value = 1\n", "`", "``"):
            stream.feed(piece)
        stream.finish()
        self.assertNotIn("```", "\n".join(lines))
        self.assertIn("value = 1", "\n".join(lines))

    def test_styled_wide_text_wraps_by_cells_without_breaking_ansi(self):
        with patch("miser.ui.theme.color_enabled", return_value=True):
            lines = theme.wrap(theme.bold("界界界 " * 12), 24)
        self.assertTrue(all(theme.display_width(line) <= 24 for line in lines))
        self.assertTrue(all("\x1b" not in theme.ANSI_RE.sub("", line) for line in lines))
        self.assertTrue(all("\x1b[1m" in line for line in lines))

    def test_streamed_long_code_matches_complete_rendering(self):
        text = "```text\n" + "界abc" * 40 + "\n```"
        lines = []
        stream = render.MarkdownStream(lines.append, 30, theme.Symbols(False))
        for start in range(0, len(text), 7):
            stream.feed(text[start:start + 7])
        stream.finish()
        self.assertEqual(lines, render.markdown(text, 30, theme.Symbols(False)))
