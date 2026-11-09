import json
import tempfile
import unittest
from pathlib import Path

from miser.memory import WorkingMemory
from miser.workspace import Workspace


class ContextTests(unittest.TestCase):
    def test_tiny_file_first_read_can_supply_exact_edit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "small.py"
            path.write_text("def value():\n    return 1\n")
            workspace = Workspace(root)
            result = workspace.zoom("small.py")
            self.assertTrue(result["complete"])
            self.assertIn("return 1", result["text"])
            workspace.edit("small.py", "return 1", "return 2", result["version"])
            self.assertIn("return 2", path.read_text())

    def test_large_outline_does_not_include_full_body(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "large.py"
            for text in ("# line\n" * 41, "value = '" + "x" * 2100 + "'\n"):
                path.write_text(text)
                result = Workspace(root).zoom("large.py")
                self.assertNotIn("complete", result)
                self.assertNotIn("text", result)

    def test_map_ranks_paths_and_respects_budget_and_exclusions(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            (path / "pricing.py").write_text("def discount(price):\n    return price\n")
            (path / ".env").write_text("SECRET=hidden")
            (path / "broken.py").write_text("def broken(")
            for i in range(40):
                (path / f"other{i}.txt").write_text("ordinary content")
            result = Workspace(path).repo_map("pricing discount", max_chars=500)
            self.assertEqual(result["entries"][0]["path"], "pricing.py")
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 500)
            self.assertTrue(result["truncated"])
            self.assertNotIn(".env", json.dumps(result))

    def test_expired_read_can_be_refreshed_without_disabling_policy(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / "app.py").write_text("value = 1\n")
            workspace = Workspace(root)
            first = workspace.zoom("app.py", 2)
            self.assertTrue(workspace.zoom("app.py", 2)["unchanged"])
            refreshed = workspace.zoom("app.py", 2, refresh=True)
            self.assertEqual(first["text"], refreshed["text"])
            self.assertEqual(first["version"], refreshed["version"])

    def test_memory_stays_bounded_and_does_not_copy_source(self):
        memory = WorkingMemory()
        for i in range(30):
            memory.observe("zoom", {"path": f"app{i}.py"},
                           json.dumps({"version": "abc", "text": "private source body"}))
        snapshot = memory.snapshot()
        self.assertEqual(len(snapshot["recent_observations"]), 8)
        self.assertNotIn("private source body", json.dumps(snapshot))
        self.assertEqual(snapshot["recent_observations"][-1]["path"], "app29.py")
