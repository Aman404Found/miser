"""Explicit file reads are local actions, not coding-agent/model requests."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from miser.intent import classify_intent
from miser.terminal import Terminal
from miser.tui import screen


class LocalReadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "README.md").write_text("# MISER\nSecond line\nThird line\n")
        self.output = []
        self.terminal = Terminal(
            self.root, output_dir=self.root / "runs", write=self.output.append,
            client_factory=lambda _: self.fail("A literal file read must not construct a model client"))
        self.terminal.model = None

    def test_screenshot_request_reads_one_line_without_model_or_acceptance_tests(self):
        with patch("miser.terminal.ToolRunner") as runner:
            self.terminal.handle_input("read Readme.md file and print first line")
        runner.assert_not_called()
        output = "\n".join(self.output)
        self.assertIn("# MISER", output)
        self.assertNotIn("Second line", output)
        self.assertEqual(self.terminal.session_model_requests, 0)
        self.assertEqual(self.terminal.session_tasks_count, 1)
        ledger = self.terminal.last_ledger
        self.assertEqual(ledger.data["status"], "answered")
        self.assertEqual(ledger.data["metadata"]["mode"], "local-file-read")
        self.assertFalse(any(e["kind"] in ("model", "model_request", "tests") for e in ledger.data["events"]))
        self.assertEqual(json.loads(ledger.path.read_text())["status"], "answered")

    def test_direct_task_entry_used_by_tui_also_reads_locally(self):
        self.terminal.task("show first 2 lines of README.md")
        output = "\n".join(self.output)
        self.assertIn("Second line", output)
        self.assertNotIn("Third line", output)
        self.assertFalse(self.terminal.workspace.modified)

    def test_simple_read_and_quoted_filename_work_without_model_configuration(self):
        (self.root / "project notes.txt").write_text("local notes\n")
        self.terminal.task('read "project notes.txt"')
        self.assertIn("local notes", "\n".join(self.output))
        (self.root / "first line.txt").write_text("first\nsecond\n")
        self.terminal.task('read "first line.txt"')
        self.assertIn("second", "\n".join(self.output))

    def test_compound_edit_request_is_not_consumed_by_local_read_parser(self):
        self.assertEqual(classify_intent("show commands").kind, "help")
        self.assertEqual(classify_intent("Read README.md and fix the typo").kind, "coding")
        self.assertEqual(classify_intent("Read README.md and explain the architecture").kind, "coding")
        self.assertEqual(classify_intent("read Readme.md file and print first line").kind, "file_read")

    def test_read_path_guards_are_preserved_before_any_model_request(self):
        (self.root / "link.md").symlink_to(self.root / "README.md")
        for name in (".env", "../README.md", "/etc/passwd", "link.md", ".git/config"):
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, "relative path|sensitive|Symlinks"):
                self.terminal.task("read " + name)
        self.assertEqual(self.terminal.session_model_requests, 0)

    def test_case_insensitive_resolution_refuses_ambiguous_filenames(self):
        (self.root / "Readme.md").write_text("different file\n")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.terminal.task("read readme.md")
        self.assertEqual(self.output, [])

    def test_read_bounds_are_explicit_and_terminal_controls_are_not_executed(self):
        (self.root / "notes.txt").write_text("\x1b[2J" + "x" * 16000 + "\n")
        self.terminal.task("read notes.txt")
        output = "\n".join(self.output)
        self.assertIn("truncated", output.lower())
        self.assertNotIn("\x1b", output)
        self.assertLess(len(output), 15000)
        for count in (0, 121):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "1.*120"):
                self.terminal.task(f"show first {count} lines of README.md")

    def test_previous_session_edits_are_preserved_by_a_local_read(self):
        context = self.terminal.workspace.zoom("README.md", level=2)
        self.terminal.workspace.edit("README.md", "Third line", "Edited line", context["version"])
        self.terminal.task("read README.md")
        self.assertEqual(self.terminal.workspace.modified, {"README.md"})
        self.terminal.undo()
        self.assertIn("Third line", (self.root / "README.md").read_text())

    def test_welcome_logo_has_a_symmetric_m_and_plain_miser_identity(self):
        self.assertTrue(all(row == row[::-1] for row in screen._FONT["M"]))
        self.assertNotEqual(screen._FONT["M"][1], screen._FONT["M"][0])
        rendered = "\n".join(row.plain for row in screen.render(screen.UIState(width=100, height=32)))
        self.assertIn("MISER", rendered)


if __name__ == "__main__":
    unittest.main()
