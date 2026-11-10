import tempfile
import os
import unittest
from pathlib import Path

from miser.workspace import Workspace, diff_previews, digest


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "def cost(price):\n    return price * 2\n"
        (self.root / "price.py").write_text(self.source)
        self.workspace = Workspace(self.root)

    def test_python_outline_and_symbol_read(self):
        outline = self.workspace.zoom("price.py")
        self.assertEqual(outline["analysis"], "python-ast")
        self.assertEqual(outline["symbols"][0]["name"], "cost")
        result = self.workspace.zoom("price.py", level=1, symbol="cost")
        self.assertIn("return price", result["text"])

    def test_repeated_reads_and_delta_recall(self):
        self.workspace.zoom("price.py", level=2)
        self.assertTrue(self.workspace.zoom("price.py", level=2)["unchanged"])
        self.assertTrue(self.workspace.recall("price.py")["unchanged"])
        (self.root / "price.py").write_text(self.source.replace("* 2", "* 3"))
        result = self.workspace.recall("price.py")
        self.assertFalse(result["unchanged"])
        self.assertIn("+    return price * 3", result["delta"])

    def test_stale_edits_are_rejected(self):
        version = self.workspace.zoom("price.py")["version"]
        (self.root / "price.py").write_text(self.source + "# external edit\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.workspace.edit("price.py", "* 2", "* 3", version)

    def test_exact_edit_and_ambiguous_edit(self):
        version = self.workspace.zoom("price.py")["version"]
        with self.assertRaisesRegex(ValueError, "exactly once"):
            self.workspace.edit("price.py", "price", "amount", version)
        self.workspace.edit("price.py", "* 2", "* 3", version)
        self.assertIn("* 3", (self.root / "price.py").read_text())

    def test_paths_sensitive_files_and_symlinks(self):
        (self.root / ".env").write_text("secret")
        (self.root / "link.py").symlink_to(self.root / "price.py")
        for path in ("../price.py", "/etc/passwd", ".env", "x.key", "link.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.workspace.text(path)
        self.assertEqual(self.workspace.list_files()["files"], ["price.py"])

    def test_javascript_html_and_css_text_support(self):
        for name, source in (("app.js", "const price = 3;\n"),
                             ("index.html", "<h1>Price</h1>\n"),
                             ("style.css", "h1 { color: red; }\n")):
            (self.root / name).write_text(source)
            context = self.workspace.zoom(name, level=2)
            self.assertIn(source.strip(), context["text"])
            updated = source + "\n"
            self.workspace.edit(name, source, updated, context["version"])
            self.assertEqual(self.workspace.text(name), updated)
        self.assertEqual(self.workspace.search("const price")["matches"][0]["path"], "app.js")

    def test_file_size_guard(self):
        (self.root / "large.js").write_text("x" * 250001)
        with self.assertRaisesRegex(ValueError, "250 KB"):
            self.workspace.zoom("large.js", level=2)

    def test_whitespace_tolerant_edit_fallback(self):
        # Test trailing whitespace mismatch
        version = self.workspace.zoom("price.py")["version"]
        self.workspace.edit("price.py", "return price * 2   \n", "return price * 5\n", version)
        self.assertIn("* 5", self.workspace.text("price.py"))

        # Test uniform indentation shift
        nested_src = "class Calc:\n    def run(self):\n        return 42\n"
        (self.root / "nested.py").write_text(nested_src)
        ver2 = self.workspace.zoom("nested.py")["version"]
        # Provide unindented old and new blocks (common LLM behavior)
        self.workspace.edit("nested.py", "def run(self):\n    return 42\n", "def run(self):\n    return 100\n", ver2)
        expected = "class Calc:\n    def run(self):\n        return 100\n"
        self.assertEqual(self.workspace.text("nested.py"), expected)

    def test_edit_diagnostics_shows_line_number(self):
        version = self.workspace.zoom("price.py")["version"]
        with self.assertRaisesRegex(ValueError, "around line"):
            self.workspace.edit("price.py", "return non_existent_variable * 99", "new code", version)

    def test_multi_file_batch_edit_writes_all_files(self):
        (self.root / "caller.py").write_text("from price import cost\n\ndef total():\n    return cost(10) * 2\n")
        price_version = self.workspace.zoom("price.py")["version"]
        caller_version = self.workspace.zoom("caller.py")["version"]
        result = self.workspace.edit_batch([
            {"path": "price.py", "old": "* 2", "new": "* 4", "expected_version": price_version},
            {"path": "caller.py", "old": "cost(10) * 2", "new": "cost(10)", "expected_version": caller_version},
        ])
        self.assertEqual(result["files"], ["caller.py", "price.py"])
        self.assertIn("* 4", self.workspace.text("price.py"))
        self.assertIn("return cost(10)\n", self.workspace.text("caller.py"))
        self.assertEqual(self.workspace.modified, {"price.py", "caller.py"})

    def test_batch_edit_failure_rolls_back_every_file(self):
        (self.root / "caller.py").write_text("def total():\n    return cost(10)\n")
        price_version = self.workspace.zoom("price.py")["version"]
        caller_version = self.workspace.zoom("caller.py")["version"]
        before = (self.workspace.text("price.py"), self.workspace.text("caller.py"))
        with self.assertRaisesRegex(ValueError, "not found"):
            self.workspace.edit_batch([
                {"path": "price.py", "old": "* 2", "new": "* 4", "expected_version": price_version},
                {"path": "caller.py", "old": "missing text", "new": "x", "expected_version": caller_version},
            ])
        self.assertEqual((self.workspace.text("price.py"), self.workspace.text("caller.py")), before)
        self.assertEqual(self.workspace.modified, set())

    def test_batch_write_failure_restores_prior_state(self):
        (self.root / "caller.py").write_text("def total():\n    return cost(10)\n")
        price_version = self.workspace.zoom("price.py")["version"]
        caller_version = self.workspace.zoom("caller.py")["version"]
        before_price = self.workspace.text("price.py")
        original_replace = os.replace
        real_path = self.root / "caller.py"

        def failing_replace(source, target):
            if target == real_path:
                raise OSError("disk full")
            return original_replace(source, target)

        os.replace = failing_replace
        try:
            with self.assertRaisesRegex(RuntimeError, "rolled back"):
                self.workspace.edit_batch([
                    {"path": "price.py", "old": "* 2", "new": "* 4", "expected_version": price_version},
                    {"path": "caller.py", "old": "cost(10)", "new": "cost(20)", "expected_version": caller_version},
                ])
        finally:
            os.replace = original_replace
        self.assertEqual(self.workspace.text("price.py"), before_price)
        self.assertEqual(self.workspace.modified, set())

    def test_unified_diff_applies_hunks_across_files(self):
        (self.root / "caller.py").write_text("from price import cost\n\ntotal = cost(10)\n")
        self.workspace.zoom("price.py")
        self.workspace.zoom("caller.py")
        patch = (
            "diff --git a/price.py b/price.py\n"
            "--- a/price.py\n"
            "+++ b/price.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def cost(price):\n"
            "-    return price * 2\n"
            "+    return price * 4\n"
            "--- a/caller.py\n"
            "+++ b/caller.py\n"
            "@@ -1,3 +1,3 @@\n"
            " from price import cost\n"
            " \n"
            "-total = cost(10)\n"
            "+total = cost(5)\n"
        )
        previews = diff_previews(patch)
        self.assertEqual(sorted(previews), ["caller.py", "price.py"])
        self.assertNotIn("caller.py", previews["price.py"])
        result = self.workspace.apply_unified_diff(patch)
        self.assertEqual(result["files"], ["caller.py", "price.py"])
        self.assertIn("* 4", self.workspace.text("price.py"))
        self.assertIn("cost(5)", self.workspace.text("caller.py"))

    def test_unified_diff_rejects_mismatch_without_writing(self):
        (self.root / "caller.py").write_text("total = cost(10)\n")
        self.workspace.zoom("price.py")
        self.workspace.zoom("caller.py")
        before = self.workspace.text("price.py")
        patch = (
            "--- a/price.py\n+++ b/price.py\n@@ -1,2 +1,2 @@\n def cost(price):\n"
            "-    return price * 9\n+    return price * 4\n"
        )
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.workspace.apply_unified_diff(patch)
        self.assertEqual(self.workspace.text("price.py"), before)

    def test_unified_diff_rejects_malformed_and_new_files(self):
        self.workspace.zoom("price.py")
        with self.assertRaisesRegex(ValueError, "No unified diff"):
            self.workspace.apply_unified_diff("not a patch")
        create = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1\n"
        with self.assertRaisesRegex(ValueError, "not supported"):
            self.workspace.apply_unified_diff(create)
        bad_counts = "--- a/price.py\n+++ b/price.py\n@@ -1,3 +1,3 @@\n def cost(price):\n"
        with self.assertRaisesRegex(ValueError, "does not match its body"):
            self.workspace.apply_unified_diff(bad_counts)

    def test_scope_normalizes_and_rejects_non_directories(self):
        (self.root / "pkg").mkdir()
        self.assertEqual(self.workspace.scope(""), "")
        self.assertEqual(self.workspace.scope("."), "")
        self.assertEqual(self.workspace.scope("./pkg/"), "pkg")
        with self.assertRaisesRegex(ValueError, "not a directory"):
            self.workspace.scope("missing")
        with self.assertRaisesRegex(ValueError, "cwd must be"):
            self.workspace.scope(3)
        with self.assertRaises(ValueError):
            self.workspace.scope("../outside")

    def test_find_files_recursive_scoped_and_limited(self):
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "a.py").write_text("a = 1\n")
        (self.root / "pkg" / "b.py").write_text("b = 2\n")
        (self.root / "pkg" / "note.txt").write_text("text\n")
        everything = self.workspace.find_files("**/*.py")
        self.assertEqual(everything["files"], ["pkg/a.py", "pkg/b.py", "price.py"])
        scoped = self.workspace.find_files("*.py", cwd="pkg")
        self.assertEqual(scoped["files"], ["pkg/a.py", "pkg/b.py"])
        self.assertEqual(scoped["cwd"], "pkg")
        limited = self.workspace.find_files("**/*.py", limit=1)
        self.assertEqual(len(limited["files"]), 1)
        self.assertTrue(limited["truncated"])
        with self.assertRaisesRegex(ValueError, "nonempty glob"):
            self.workspace.find_files("  ")
        with self.assertRaisesRegex(ValueError, "Limit"):
            self.workspace.find_files("*.py", limit=0)
        (self.root / ".env").write_text("secret\n")
        self.assertNotIn(".env", self.workspace.find_files("*", limit=500)["files"])

    def test_search_scope_and_context_shape(self):
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "a.py").write_text("def helper():\n    return 1\n")
        plain = self.workspace.search("return")
        self.assertNotIn("cwd", plain)
        self.assertNotIn("context", plain["matches"][0])
        self.assertEqual({m["path"] for m in plain["matches"]}, {"pkg/a.py", "price.py"})
        scoped = self.workspace.search("return", cwd="pkg")
        self.assertEqual(scoped["cwd"], "pkg")
        self.assertEqual([m["path"] for m in scoped["matches"]], ["pkg/a.py"])
        window = self.workspace.search("return 1", context=1, cwd="pkg")
        lines = window["matches"][0]["context"]
        self.assertEqual([entry["line"] for entry in lines], [1, 2])
        with self.assertRaisesRegex(ValueError, "Context"):
            self.workspace.search("return", context=9)

    def test_read_many_versions_allow_a_follow_up_edit(self):
        result = self.workspace.read_many([{"path": "price.py"}])
        entry = result["reads"][0]
        self.assertEqual(entry["start"], 1)
        self.assertEqual(entry["total_lines"], 2)
        self.assertIn("1: def cost(price):", entry["text"])
        self.workspace.edit("price.py", "* 2", "* 3", entry["version"])
        self.assertIn("* 3", (self.root / "price.py").read_text())

    def test_read_many_budget_per_file_errors_and_limits(self):
        for name in ("big_a.py", "big_b.py"):
            (self.root / name).write_text("".join(f"value_{i} = {i}  # padding line\n"
                                                  for i in range(400)))
        result = self.workspace.read_many([{"path": "big_a.py"}, {"path": "big_b.py"}],
                                          max_chars=2000)
        self.assertTrue(result["reads"][0]["truncated"])
        self.assertEqual(result["remaining"], 0)
        self.assertIn("budget exhausted", result["reads"][1]["error"])
        missing = self.workspace.read_many([{"path": "ghost.py"}])
        self.assertIn("error", missing["reads"][0])
        with self.assertRaisesRegex(ValueError, "at most 8"):
            self.workspace.read_many([{"path": "price.py"}] * 9)
        with self.assertRaisesRegex(ValueError, "max_chars"):
            self.workspace.read_many([{"path": "price.py"}], max_chars=10)
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            self.workspace.read_many([])

    def test_write_file_creates_new_files_only(self):
        (self.root / "pkg").mkdir()
        created = self.workspace.write_file("pkg/new_module.py", "VALUE = 1\n")
        self.assertTrue(created["created"])
        self.assertEqual((self.root / "pkg" / "new_module.py").read_text(), "VALUE = 1\n")
        self.assertIn("pkg/new_module.py", self.workspace.modified)
        self.assertIsNone(self.workspace.originals["pkg/new_module.py"])
        self.workspace.edit("pkg/new_module.py", "VALUE = 1", "VALUE = 2", created["version"])
        self.assertIn("VALUE = 2", (self.root / "pkg" / "new_module.py").read_text())
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.workspace.write_file("price.py", "x = 1\n")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.workspace.write_file("missing_dir/x.py", "x = 1\n")
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.workspace.write_file("pkg/empty.py", "")
        with self.assertRaisesRegex(ValueError, "Content must be text"):
            self.workspace.write_file("pkg/binary.py", b"x")
        with self.assertRaises(ValueError):
            self.workspace.write_file(".env", "secret\n")

    def test_edit_mismatch_error_quotes_numbered_region(self):
        version = self.workspace.zoom("price.py")["version"]
        with self.assertRaises(ValueError) as caught:
            self.workspace.edit("price.py", "return price * 99", "x", version)
        message = str(caught.exception)
        self.assertIn("around line", message)
        self.assertIn("1: def cost(price):", message)
        self.assertIn("2:     return price * 2", message)

    def test_repo_map_symbol_caching(self):
        map1 = self.workspace.repo_map()
        self.assertIn(("price.py", (self.root / "price.py").stat().st_mtime_ns, (self.root / "price.py").stat().st_size),
                      self.workspace.symbol_cache)
        # Calling again reuses the cache
        map2 = self.workspace.repo_map()
        self.assertEqual(len(map1["entries"]), len(map2["entries"]))
