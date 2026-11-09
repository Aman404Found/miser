import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from miser.ui import render, theme
from miser.ui.prompt import read_multiline
from miser.ui.spinner import WorkingIndicator

DIFF = """--- a/pricing.py
+++ b/pricing.py
@@ -1,3 +1,3 @@
 def price(x):
-    return x * 0.9
+    return x * (1 - 0.1)
"""


class ThemeTests(unittest.TestCase):
    def test_clean_strips_escape_and_control_sequences(self):
        self.assertEqual(theme.clean("\x1b[31mred\x1b[0m\x07"), "red")

    def test_wrap_respects_width_and_indent(self):
        lines = theme.wrap("word " * 40, 30, initial="• ", subsequent="  ")
        self.assertTrue(all(theme.visible_len(line) <= 30 for line in lines))
        self.assertTrue(lines[0].startswith("• "))

    def test_clip_marks_and_bounds_truncation(self):
        self.assertEqual(theme.clip("abcdef", 4), "abc…")
        self.assertEqual(theme.clip("abc", 5), "abc")
        self.assertEqual(theme.clip("abcdef", 0), "")

    def test_display_width_counts_wide_characters(self):
        self.assertEqual(theme.display_width("ab"), 2)
        self.assertEqual(theme.display_width("日本"), 4)

    def test_no_color_environment_is_honoured(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(theme.red("x"), "x")
            self.assertEqual(theme.bold("y"), "y")


class MarkdownTests(unittest.TestCase):
    def test_markdown_renders_headings_lists_and_code(self):
        bullet = theme.symbols().bullet
        lines = render.markdown("# Title\n\n- one\n- two\n\n```python\nx = 1\n```", width=40)
        text = "\n".join(lines)
        self.assertIn("Title", text)
        self.assertIn(f"{bullet} one", text)
        self.assertIn("python", text)
        self.assertIn("x = 1", text)

    def test_inline_code_and_bold_are_styled_only_with_colour(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertEqual(render._inline("use `x` and **y**"), "use x and y")

    def test_stream_emits_complete_lines_and_code_progressively(self):
        out = []
        stream = render.MarkdownStream(out.append, width=40)
        stream.feed("Hel")
        self.assertEqual(out, [])
        stream.feed("lo\n")
        self.assertIn("Hello", out)
        stream.feed("```python\n")
        stream.feed("x = 1\n")
        self.assertIn("x = 1", "\n".join(out))
        self.assertEqual(stream.fence, "python")
        stream.feed("```\n")
        stream.finish()
        self.assertIsNone(stream.fence)
        self.assertTrue(stream.finished)

    def test_stream_wraps_a_long_paragraph_while_it_arrives(self):
        out = []
        stream = render.MarkdownStream(out.append, width=30)
        stream.feed("word " * 30)
        self.assertGreater(len(out), 1)
        stream.finish()
        self.assertTrue(all(theme.display_width(line) <= 32 for line in out))


class PanelAndDiffTests(unittest.TestCase):
    def test_panel_never_exceeds_requested_width(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            text = render.panel("status", [("Workspace", "/very/long/path/" * 8),
                                           ("Current model:", "gemini/a, gemini/b")], width=60)
            for line in text.splitlines():
                self.assertLessEqual(theme.display_width(line), 60)

    def test_diff_stats_and_lines(self):
        files = render.diff_files(DIFF)
        self.assertEqual(files, [{"path": "pricing.py", "added": 1, "removed": 1}])
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            text = render.render_diff(DIFF, width=60)
        self.assertIn("pricing.py", text)
        self.assertIn("+1", text)
        self.assertIn("−1", text)
        self.assertIn("return x * (1 - 0.1)", text)

    def test_banner_and_panel_follow_a_narrow_terminal(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}), \
                patch("miser.ui.theme.term_width", return_value=56):
            header = render.header("0.1.0", "provider/model-name", "/tmp/a/repo", theme.term_width())
            self.assertTrue(all(theme.display_width(line) <= 56 for line in header.splitlines()))
            panel = render.panel("status", [("Current tests:",
                                             "python3 -m unittest discover -s tests")], 56)
            self.assertTrue(all(theme.display_width(line) <= 56 for line in panel.splitlines()))

    def test_diff_truncation_is_reported(self):
        with patch.dict(os.environ, {"NO_COLOR": "1"}):
            text = render.render_diff(DIFF, width=60, max_lines=2)
        self.assertIn("more diff lines", text)

    def test_empty_diff_is_explicit(self):
        self.assertIn("no changes", render.render_diff("", width=40))

    def test_usage_phrase_distinguishes_zero_unknown_and_metered(self):
        self.assertIn("no model requests", render.usage_phrase({"model_calls": 0}))
        self.assertIn("usage incomplete",
                      render.usage_phrase({"model_calls": 1, "total_tokens": 5,
                                           "usage_complete": False}))
        self.assertIn("1,200 provider tokens",
                      render.usage_phrase({"model_calls": 1, "total_tokens": 1200,
                                           "input_tokens": 1000, "output_tokens": 200,
                                           "usage_complete": True}))


class SpinnerTests(unittest.TestCase):
    def test_spinner_is_silent_without_a_terminal(self):
        out = []
        spinner = WorkingIndicator(write=out.append, enabled=False)
        spinner.start("thinking")
        spinner.update("still thinking")
        spinner.stop()
        self.assertEqual(out, [])

    def test_spinner_renders_one_line_with_real_elapsed_time(self):
        out = []
        spinner = WorkingIndicator(write=out.append, enabled=True, interval=0.01)
        spinner.start("working")
        time.sleep(0.05)
        spinner.stop()
        rendered = "".join(out)
        self.assertIn("working", rendered)
        self.assertIn("s", rendered)
        self.assertIn("\r", rendered)


class PromptTests(unittest.TestCase):
    def test_backslash_continuation(self):
        lines = iter(["one \\", "two"])
        self.assertEqual(read_multiline(lambda _: next(lines), "> "), "one two")

    def test_triple_quoted_block(self):
        lines = iter(['"""first', 'second"""'])
        self.assertEqual(read_multiline(lambda _: next(lines), "> "), "first\nsecond")

    def test_single_line_passthrough(self):
        self.assertEqual(read_multiline(lambda _: "  hello  ", "> "), "hello")


if __name__ == "__main__":
    unittest.main()
