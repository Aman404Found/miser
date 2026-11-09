import unittest

from rich.text import Text

from miser.tui import screen


def welcome(**overrides):
    values = dict(width=100, height=32, model="gemini/gemini-3.5-flash",
                  workspace="/home/dev/Desktop/fresh-code", budget=24000)
    values.update(overrides)
    return screen.UIState(**values)


def conversation(**overrides):
    values = dict(width=80, height=24, mode="conversation", model="gemini/gemini-3.5-flash",
                  workspace="/home/dev/Desktop/fresh-code", budget=24000,
                  input_text="fix the discount", cursor=16,
                  transcript=[Text("  ▌ fix the discount"), Text("  ⏺ reading pricing.py")])
    values.update(overrides)
    return screen.UIState(**values)


class WelcomeLayoutTests(unittest.TestCase):
    def test_exact_dimensions_and_filled_background(self):
        lines = screen.render(welcome())
        self.assertEqual(len(lines), 32)
        self.assertTrue(all(line.cell_len == 100 for line in lines))

    def test_logo_and_composer_are_centered(self):
        lines = screen.render(welcome())
        logo_rows = [line for line in lines if "█" in line.plain]
        self.assertEqual(len(logo_rows), 5)
        lefts = {len(row.plain) - len(row.plain.lstrip(" ")) for row in logo_rows}
        self.assertEqual(len(lefts), 1)
        self.assertLessEqual(abs(100 - 38 - 2 * lefts.pop()), 1)

        composer_rows = [line for line in lines if "▌" in line.plain]
        self.assertGreaterEqual(len(composer_rows), 3)
        for row in composer_rows:
            self.assertEqual(len(row.plain) - len(row.plain.lstrip(" ")), screen.content_left(100))


    def test_welcome_contains_identity_placeholder_model_and_shortcuts(self):
        text = "\n".join(line.plain for line in screen.render(welcome()))
        self.assertIn("█", text)
        self.assertIn("focused coding agent", text)
        self.assertIn("Ask anything", text)
        self.assertIn("gemini/gemini-3.5-flash", text)
        self.assertIn("24k budget", text)
        self.assertIn("tab complete", text)
        self.assertIn("~/Desktop/fresh-code", text)
        self.assertNotIn("OpenCode", text)

    def test_short_and_narrow_welcome_keeps_composer_visible(self):
        for width, height in ((40, 12), (46, 14), (120, 20)):
            lines = screen.render(welcome(width=width, height=height))
            self.assertEqual(len(lines), height)
            self.assertTrue(all(line.cell_len == width for line in lines))
            self.assertTrue(any("Ask anything" in line.plain for line in lines))

    def test_suggestions_are_rendered(self):
        text = "\n".join(line.plain for line in screen.render(welcome(input_text="/m", cursor=2,
                                                                      suggestions=["/model", "/map"])))
        self.assertIn("/model", text)
        self.assertIn("/map", text)


def leading_spaces(line):
    return len(line.plain) - len(line.plain.lstrip(" "))


class ContentColumnTests(unittest.TestCase):
    def test_content_column_is_capped_and_centered(self):
        self.assertEqual(screen.content_width(100), 92)
        self.assertEqual(screen.content_width(80), 72)
        self.assertEqual(screen.content_width(40), 38)
        self.assertEqual(screen.content_left(100), 4)
        self.assertEqual(screen.content_left(40), 1)
        self.assertEqual(screen.content_width(200), screen.MAX_CONTENT_WIDTH)


class ConversationLayoutTests(unittest.TestCase):
    def test_header_composer_and_footer(self):
        lines = screen.render(conversation())
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(line.cell_len == 80 for line in lines))
        self.assertEqual(lines[0].plain.lstrip().startswith("MISER"), True)
        self.assertIn("gemini/gemini-3.5-flash", lines[0].plain)

        composer_index = max(i for i, line in enumerate(lines) if "▌" in line.plain)
        self.assertGreaterEqual(composer_index, 20)
        self.assertIn("fix the discount", lines[composer_index].plain)

        # Header, rule, transcript and composer share one gutter.
        gutter = screen.content_left(80)
        self.assertEqual(leading_spaces(lines[0]), gutter)
        self.assertEqual(leading_spaces(lines[composer_index]), gutter)
        self.assertIn("ctrl+d exit", lines[-1].plain)

    def test_conversation_starts_at_the_top(self):
        lines = screen.render(conversation())
        self.assertIn("fix the discount", lines[2].plain)
        self.assertIn("reading pricing.py", lines[3].plain)

    def test_overflowing_history_scrolls_and_indicates_position(self):
        state = conversation(transcript=[Text(f"line {index}") for index in range(100)], scroll=10)
        lines = screen.render(state)
        text = "\n".join(line.plain for line in lines)
        self.assertIn("line 89", text)
        self.assertNotIn("line 99", text)
        self.assertIn("↑ 10 lines", lines[0].plain)
        self.assertNotIn("line 0 ", text)

    def test_busy_status_and_tool_activity_are_visible(self):
        state = conversation(busy=True, status="reading pricing.py", spinner="⠹", elapsed=1.2,
                             tokens="680 tok", tests="tests passed")
        footer = screen.render(state)[-1].plain
        self.assertIn("⠹ reading pricing.py", footer)
        self.assertIn("1.2s", footer)
        self.assertIn("680 tok", footer)
        self.assertIn("tests passed", footer)

    def test_approval_prompt_and_diff_hint_above_composer(self):
        state = conversation(approval="apply edit to pricing.py?   [y]es  [n]o  [a]ll  [d]iff")
        lines = screen.render(state)
        approval = [i for i, line in enumerate(lines) if "apply edit to pricing.py" in line.plain]
        composer = max(i for i, line in enumerate(lines) if "▌" in line.plain)
        self.assertEqual(len(approval), 1)
        self.assertLess(approval[0], composer)

    def test_narrow_and_short_conversation_never_overflows(self):
        for width, height in ((40, 12), (44, 10), (60, 20)):
            state = conversation(width=width, height=height,
                                 input_text="x" * 200, cursor=200,
                                 transcript=[Text("y" * 300) for _ in range(50)])
            lines = screen.render(state)
            self.assertEqual(len(lines), height)
            self.assertTrue(all(line.cell_len == width for line in lines))
            self.assertTrue(any("▌" in line.plain for line in lines))

    def test_cursor_is_drawn_inside_composer(self):
        state = conversation(input_text="abc", cursor=1)
        lines = screen.render(state)
        composer = next(line for line in lines if "abc" in line.plain)
        spans = [(span.start, span.end) for span in composer.spans
                 if span.style is not None and "on #4f8cff" in str(span.style)]
        self.assertTrue(spans, "expected a visible cursor cell in the composer")

    def test_empty_conversation_keeps_composer_and_placeholder(self):
        text = "\n".join(line.plain for line in screen.render(
            conversation(transcript=[], input_text="", cursor=0)))
        self.assertIn("Ask anything", text)


if __name__ == "__main__":
    unittest.main()
