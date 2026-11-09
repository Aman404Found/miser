import json
import stat
import tempfile
import unittest
from pathlib import Path

from miser.repomap import RepoMap, pagerank, query_terms
from miser.workspace import Workspace


def write(root, name, text):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class PageRankTests(unittest.TestCase):
    def test_rank_favours_the_referenced_node(self):
        rank = pagerank(["a", "b", "c"], {("a", "b"): 3.0, ("c", "b"): 1.0})
        self.assertGreater(rank["b"], rank["a"])
        self.assertGreater(rank["b"], rank["c"])
        self.assertAlmostEqual(sum(rank.values()), 1.0, places=6)

    def test_personalization_and_dangling_nodes(self):
        rank = pagerank(["a", "b", "isolated"], {("a", "b"): 1.0},
                        personalization={"a": 1.0})
        self.assertGreater(rank["a"], rank["b"])
        self.assertGreater(rank["isolated"], 0.0)
        self.assertAlmostEqual(sum(rank.values()), 1.0, places=6)

    def test_empty_graph_and_query_terms(self):
        self.assertEqual(pagerank([], {}), {})
        self.assertEqual(query_terms("A and the"), set())
        self.assertEqual(query_terms("disk_cache, pricing!"), {"disk_cache", "pricing"})


class RepoMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root, "core.py",
              "class Engine:\n    def run(self):\n        return start()\n\n"
              "def start():\n    return Engine()\n")
        write(self.root, "lonely.py", "def unused_helper():\n    return 1\n")
        write(self.root, "app.py",
              "from core import Engine\n\n\ndef boot():\n    engine = Engine()\n    return engine.run()\n")
        write(self.root, "notes.txt", "engine bootstrap notes\n")
        self.workspace = Workspace(self.root)

    def test_reference_graph_ranks_relevant_files_and_symbols(self):
        result = self.workspace.repo_map("engine run", max_chars=4000)
        self.assertEqual(result["analysis"], "pagerank-reference-graph")
        paths = [entry["path"] for entry in result["entries"]]
        self.assertEqual(paths[0], "core.py")
        self.assertIn("app.py", paths)
        core = next(entry for entry in result["entries"] if entry["path"] == "core.py")
        names = [symbol["name"] for symbol in core["symbols"]]
        self.assertIn("Engine", names)
        self.assertLess(names.index("Engine"), len(names))
        self.assertNotIn(".miser", json.dumps(result))

    def test_unreferenced_definition_ranks_below_hub(self):
        result = self.workspace.repo_map("", max_chars=4000)
        order = [entry["path"] for entry in result["entries"]]
        self.assertLess(order.index("core.py"), order.index("lonely.py"))

    def test_map_respects_budget(self):
        for index in range(25):
            write(self.root, f"module{index}.py",
                  f"def handler_{index}(value):\n    return value + {index}\n")
        result = self.workspace.repo_map("engine", max_chars=500)
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 500)
        self.assertTrue(result["truncated"])

    def test_python_and_javascript_definitions(self):
        write(self.root, "ui.js",
              "export function renderPanel(state) {\n  return format(state);\n}\n"
              "const format = (state) => state.title;\n"
              "export class Panel {\n  paint() { return renderPanel(this.state); }\n}\n")
        write(self.root, "view.js", "import { Panel } from './ui.js';\nexport const panel = new Panel();\n")
        workspace = Workspace(self.root)
        result = workspace.repo_map("panel render", max_chars=6000)
        by_path = {entry["path"]: entry for entry in result["entries"]}
        self.assertEqual(by_path["ui.js"]["symbols"][0]["name"], "renderPanel")
        self.assertIn("Panel", [symbol["name"] for symbol in by_path["ui.js"]["symbols"]])
        self.assertIn("view.js", by_path)

    def test_cache_persists_and_invalidates_on_mtime(self):
        self.workspace.repo_map("engine", max_chars=2000)
        cache_path = self.root / ".miser" / "cache" / "repomap.json"
        self.assertTrue(cache_path.is_file())
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertEqual(cached["version"], 2)
        self.assertIn("core.py", cached["files"])
        self.assertIn("Engine", [definition[0] for definition in cached["files"]["core.py"]["defs"]])

        target = self.root / "core.py"
        target.write_text(target.read_text(encoding="utf-8").replace("Engine", "Motor"),
                          encoding="utf-8")
        result = self.workspace.repo_map("motor", max_chars=2000)
        cache_after = json.loads(cache_path.read_text(encoding="utf-8"))
        self.assertIn("Motor", [definition[0] for definition in cache_after["files"]["core.py"]["defs"]])
        self.assertNotIn("Engine", [definition[0] for definition in cache_after["files"]["core.py"]["defs"]])
        self.assertEqual(result["entries"][0]["path"], "core.py")

    def test_cache_survives_unreadable_payload(self):
        cache_path = self.root / ".miser" / "cache" / "repomap.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("{not json", encoding="utf-8")
        result = self.workspace.repo_map("engine", max_chars=2000)
        self.assertEqual(result["entries"][0]["path"], "core.py")
        self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8"))["version"], 2)

    def test_broken_python_file_is_skipped_without_crashing(self):
        write(self.root, "broken.py", "def broken(\n")
        result = self.workspace.repo_map("engine", max_chars=3000)
        paths = [entry["path"] for entry in result["entries"]]
        self.assertNotIn("broken.py", json.dumps([entry.get("symbols") for entry in result["entries"]]))
        self.assertIn("core.py", paths)


if __name__ == "__main__":
    unittest.main()
