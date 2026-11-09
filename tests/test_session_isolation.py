import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from miser.terminal import Terminal
from test_agent import ScriptedClient, response


class SessionIsolationTests(unittest.TestCase):
    def test_second_task_cannot_claim_previous_patch_as_success(self):
        class InspectThenStop:
            calls = 0
            def complete(self, *args, **kwargs):
                self.calls += 1
                return response("list_files") if self.calls == 1 else response()
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repo"
            shutil.copytree(Path(__file__).resolve().parent.parent / "examples/python_bug", repo)
            clients = iter([ScriptedClient(), InspectThenStop()])
            terminal = Terminal(repo, "fixture", f"{sys.executable} -m unittest discover -s .",
                                output_dir=Path(root) / "runs", write=lambda _: None,
                                client_factory=lambda _: next(clients))
            terminal.task("Fix discount")
            self.assertEqual(terminal.last_ledger.data["status"], "tests_passed")
            terminal.task("Add validation to pricing.py")
            self.assertEqual(terminal.last_ledger.data["status"], "answered")
            self.assertEqual(terminal.last_diff, "")
            self.assertIn("pricing.py", terminal.workspace.modified)
            terminal.undo()
            original = Path(__file__).resolve().parent.parent / "examples/python_bug/pricing.py"
            self.assertEqual((repo / "pricing.py").read_text(), original.read_text())

    def test_undo_preserves_external_changes(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "app.py"
            file.write_text("value = 1\n")
            output = []
            terminal = Terminal(root, write=output.append)
            context = terminal.workspace.zoom("app.py")
            terminal.workspace.edit("app.py", "1", "2", context["version"])
            file.write_text("value = 3\n")
            terminal.undo()
            self.assertEqual(file.read_text(), "value = 3\n")
            self.assertIn("app.py", terminal.workspace.modified)
            self.assertIn("externally changed", "\n".join(output))

    def test_resume_ignores_other_repository_and_unknown_origin(self):
        with tempfile.TemporaryDirectory() as root:
            runs = Path(root) / "runs"
            for number, metadata in enumerate([{"repo": root + "/other"}, {}]):
                directory = runs / f"session-{number}"
                directory.mkdir(parents=True)
                (directory / "ledger.json").write_text(json.dumps({
                    "status": "tests_passed", "metadata": metadata, "events": []}))
            terminal = Terminal(root, output_dir=runs, resume=True, write=lambda _: None)
            self.assertEqual(terminal.session_tasks_count, 0)
