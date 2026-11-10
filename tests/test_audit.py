"""Deterministic audit regressions; synthetic providers/transports, no listeners."""

import io
import contextlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from miser.agent import run_agent, run_parallel_batch
from miser.execution import CommandSupervisor, check_argv
from miser.ledger import Ledger, receipt
from miser.terminal import Terminal
from miser.tools import ToolRunner
from miser.web import WebAccess
from miser.workspace import Workspace, digest


def process_is_live(proc):
    """Read one process snapshot; exit during /proc read is already cleanup."""
    try:
        return proc.read_text().split(") ", 1)[1][0] != "Z"
    except (FileNotFoundError, ProcessLookupError):
        return False


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.file = self.root / "app.py"
        self.file.write_text("value = 1\n")
        self.ws = Workspace(self.root)
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.json")

    def supervisor(self, **kwargs):
        return CommandSupervisor(self.ws, self.ledger, **kwargs)

    def test_patch_refuses_external_changes_since_read(self):
        self.ws.zoom("app.py")
        self.file.write_text("value = 1\n# external\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.ws.apply_unified_diff(
                "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n")
        self.assertEqual(self.file.read_text(), "value = 1\n# external\n")

    def test_edit_rechecks_version_after_building_replacement(self):
        version = self.ws.zoom("app.py")["version"]
        mutated = False

        def race(text):
            nonlocal mutated
            if not mutated:
                mutated = True
                self.file.write_text("value = 9\n")
            return digest(text)

        with patch("miser.workspace.digest", side_effect=race):
            with self.assertRaisesRegex(ValueError, "changed"):
                self.ws.edit("app.py", "1", "2", version)
        self.assertEqual(self.file.read_text(), "value = 9\n")

    def test_failed_partial_batch_write_preserves_all_three_files(self):
        for name in ("caller.py", "third.py"):
            (self.root / name).write_text("value = 1\n")
        edits = [{"path": name, "old": "1", "new": "2",
                  "expected_version": self.ws.zoom(name)["version"]}
                 for name in ("app.py", "caller.py", "third.py")]
        real_write = Path.write_text

        def disk_full(path, *args, **kwargs):
            if path.name.startswith("caller.py"):
                path.write_bytes(b"partial")
                raise OSError("simulated disk full after partial write")
            return real_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", disk_full):
            with self.assertRaises((OSError, RuntimeError)):
                self.ws.edit_batch(edits)
        for name in ("app.py", "caller.py", "third.py"):
            self.assertEqual((self.root / name).read_text(), "value = 1\n")
        self.assertEqual(self.ws.modified, set())
        self.assertEqual(self.ws.originals, {})

    def test_edit_preserves_crlf_and_executable_mode(self):
        self.file.write_bytes(b"value = 1\r\nother = 3\r\n")
        self.file.chmod(0o751)
        version = self.ws.zoom("app.py")["version"]
        self.ws.edit("app.py", "value = 1\n", "value = 2\n", version)
        self.assertEqual(self.file.read_bytes(), b"value = 2\r\nother = 3\r\n")
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o751)

    def test_create_does_not_overwrite_a_file_appearing_after_check(self):
        target = self.root / "new.py"
        real_exists = Path.exists

        def race(path):
            if path == target and not real_exists(path):
                target.write_text("external\n")
                return False
            return real_exists(path)

        with patch.object(Path, "exists", race):
            with self.assertRaises((ValueError, RuntimeError, OSError)):
                self.ws.write_file("new.py", "model\n")
        self.assertEqual(target.read_text(), "external\n")

    def test_patch_can_remove_only_the_new_side_final_newline(self):
        self.ws.zoom("app.py")
        self.ws.apply_unified_diff(
            "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n"
            "\\ No newline at end of file\n")
        self.assertEqual(self.file.read_bytes(), b"value = 2")

    def test_run_validates_allowlist_even_when_called_directly(self):
        supervisor = self.supervisor(approval_callback=lambda _: True)
        with patch("miser.execution.subprocess.Popen") as spawn:
            spawn.return_value.returncode = 0
            with self.assertRaises(ValueError):
                supervisor.run(["sh", "-c", "true"])
        spawn.assert_not_called()

    def test_allowlisted_basename_cannot_select_an_arbitrary_executable_path(self):
        with self.assertRaises(ValueError):
            check_argv(["/tmp/git", "status"])

    def test_each_command_invocation_needs_fresh_approval(self):
        seen = []
        supervisor = self.supervisor(approval_callback=lambda cmd: seen.append(cmd) or "always")
        supervisor.run(["python3", "-m", "unittest", "--help"])
        supervisor.run(["python3", "-m", "unittest", "--help"])
        self.assertEqual(len(seen), 2)

    def test_job_from_another_supervisor_cannot_be_read_or_stopped(self):
        script = self.root / "sleep.py"
        script.write_text("import time\ntime.sleep(30)\n")
        first = self.supervisor(approval_callback=lambda _: True,
                                allowlist=(("python3", "sleep.py"),))
        job = first.run(["python3", "sleep.py"], background=True)["job_id"]
        self.addCleanup(lambda: first.stop(job))
        other = self.supervisor()
        for action in (other.status, other.stop):
            with self.assertRaisesRegex(ValueError, "Unknown job"):
                action(job)

    def test_keyboard_interrupt_kills_foreground_process(self):
        supervisor = self.supervisor(approval_callback=lambda _: True)
        with patch("miser.execution.subprocess.Popen") as spawn:
            process = spawn.return_value
            process.wait.side_effect = [KeyboardInterrupt, 0]
            with patch.object(supervisor, "_terminate") as terminate:
                with self.assertRaises(KeyboardInterrupt):
                    supervisor.run(["python3", "-m", "unittest"])
            terminate.assert_called_once_with(process)
            self.assertEqual(process.wait.call_count, 2)

    def test_parallel_activity_results_are_delivered_in_model_order(self):
        second_done = threading.Event()

        class Runner:
            def invoke(self, name, args):
                if name == "search":
                    self.assert_wait = second_done.wait(2)
                else:
                    second_done.set()
                return json.dumps({"name": name})

        seen = []
        results = run_parallel_batch(Runner(), [("search", {}), ("list_files", {})],
                                     on_result=lambda i, *rest: seen.append(i))
        self.assertEqual(seen, [0, 1])
        self.assertEqual([json.loads(item[0])["name"] for item in results],
                         ["search", "list_files"])

    def test_web_errors_do_not_echo_configured_credentials(self):
        marker = "synthetic-audit-credential"
        with patch.dict(os.environ, {"TAVILY_API_KEY": marker}), patch(
                "miser.web.post_json", side_effect=RuntimeError("reflected " + marker)):
            with self.assertRaises(RuntimeError) as caught:
                WebAccess(self.ledger).search("python")
        self.assertNotIn(marker, str(caught.exception))
        self.assertNotIn(marker, self.ledger.path.read_text())

    def test_fetch_refuses_a_configured_credential_in_url_before_transport(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "synthetic-audit-credential"}), patch(
                "miser.web._open_once", return_value=io.BytesIO(b"text")) as opened:
            with self.assertRaises(ValueError):
                WebAccess(self.ledger).fetch("https://example.org/?key=synthetic-audit-credential")
        opened.assert_not_called()

    def test_undo_missing_existing_file_reports_conflict_without_crashing(self):
        output = []
        terminal = Terminal(self.root, write=output.append)
        version = terminal.workspace.zoom("app.py")["version"]
        terminal.workspace.edit("app.py", "1", "2", version)
        self.file.unlink()
        terminal.undo()
        self.assertFalse(self.file.exists())
        self.assertIn("app.py", terminal.workspace.modified)
        self.assertIn("externally changed", "\n".join(output))

    def test_concurrent_ledger_events_are_persisted_once_and_known_kinds_only(self):
        def record(index):
            self.ledger.record("model", total_tokens=3, prompt_tokens=2,
                               completion_tokens=1, usage_known=True, index=index)
            self.ledger.record("tool_batch", total_tokens=999)

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(record, range(60)))
        self.ledger.finish("done")
        saved = json.loads(self.ledger.path.read_text())
        self.assertEqual(len(saved["events"]), 120)
        self.assertEqual(self.ledger.total_tokens, 180)
        self.assertEqual(receipt(saved)["total_tokens"], 180)
        self.assertEqual(saved["status"], "done")

    def test_receipt_tool_context_ignores_unrelated_event_fields(self):
        self.ledger.record("tool", context_tokens_estimate=7)
        self.ledger.record("tool_batch", context_tokens_estimate=999)
        self.assertEqual(receipt(self.ledger.data)["tool_context_tokens_estimate"], 7)

    def test_malformed_usage_still_records_unknown_spend(self):
        with self.assertRaisesRegex(ValueError, "valid usage"):
            self.ledger.model({"usage": [1, 2, 3]}, 0.1)
        self.assertFalse(receipt(self.ledger.data)["usage_complete"])

    def test_batch_rollback_failure_is_reported_and_backup_retained(self):
        (self.root / "caller.py").write_text("value = 1\n")
        edits = [{"path": name, "old": "1", "new": "2",
                  "expected_version": self.ws.zoom(name)["version"]}
                 for name in ("app.py", "caller.py")]
        real_replace = os.replace
        real_write = Path.write_text
        commits = 0
        old_writes = 0

        def failure(source, target):
            nonlocal commits
            commits += 1
            if commits >= 2:
                raise OSError("simulated commit and rollback failure")
            return real_replace(source, target)

        def old_failure(path, *args, **kwargs):
            nonlocal old_writes
            if path in (self.file, self.root / "caller.py"):
                old_writes += 1
                if old_writes >= 2:
                    raise OSError("simulated commit and rollback failure")
            return real_write(path, *args, **kwargs)

        with patch("miser.workspace.os.replace", side_effect=failure), patch.object(
                Path, "write_text", old_failure):
            with self.assertRaisesRegex(RuntimeError, "rollback incomplete.*backup"):
                self.ws.edit_batch(edits)
        self.assertEqual(self.file.read_text(), "value = 2\n")
        backups = list(self.root.glob("app.py.*.miser-tmp"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "value = 1\n")
        self.assertEqual(self.ws.modified, {"app.py"})

    def test_acceptance_interrupt_reaps_child(self):
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        with patch("miser.tools.subprocess.Popen") as spawn:
            process = spawn.return_value
            process.wait.side_effect = [KeyboardInterrupt, 0]
            with patch.object(runner, "_terminate") as terminate:
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_tests()
            terminate.assert_called_once_with(process)
            self.assertEqual(process.wait.call_count, 2)

    def test_agent_exit_closes_its_background_jobs(self):
        from test_agent import response

        class Client:
            def complete(self, *args, **kwargs):
                return response()

        (self.root / "sleep.py").write_text("import time\ntime.sleep(30)\n")
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"],
                            command_approval=lambda _: True,
                            command_allowlist=(("python3", "sleep.py"),))
        job = runner.commands.run(["python3", "sleep.py"], background=True)["job_id"]
        self.addCleanup(lambda: runner.commands.stop(job))
        run_agent("Inspect app.py", Client(), runner, self.ledger)
        self.assertFalse(runner.commands.status(job)["running"])

    def test_missing_tool_arguments_produces_recoverable_tool_message(self):
        from test_agent import response

        class Client:
            calls = 0
            messages = None

            def complete(self, messages, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    result = response("search")
                    del result["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"]
                    return result
                self.messages = messages
                return response()

        client = Client()
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        self.assertEqual(run_agent("Inspect app.py", client, runner, self.ledger), "answered")
        error = json.loads(client.messages[-1]["content"])["error"]
        self.assertIn("JSON object", error)

    def test_empty_reply_explains_incomplete_status(self):
        from test_agent import response

        class Client:
            def complete(self, *args, **kwargs):
                result = response()
                result["choices"][0]["message"]["content"] = ""
                return result

        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        self.assertEqual(run_agent("Inspect app.py", Client(), runner, self.ledger), "incomplete")
        self.assertIn("empty", self.ledger.data["note"])

    def test_non_tty_stdin_is_not_a_command_approval_channel(self):
        terminal = Terminal(self.root, write=lambda _: None)
        with patch("sys.stdin", io.StringIO("yes\n")):
            self.assertFalse(terminal.prompt_command_approval("git status"))

    def test_failed_edit_invalidates_pre_edit_acceptance_result(self):
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        runner.last_tests = {"passed": True}
        version = self.ws.zoom("app.py")["version"]
        with patch.object(self.ws, "edit", side_effect=RuntimeError("rollback incomplete")):
            result = json.loads(runner.invoke("edit", {
                "path": "app.py", "old": "1", "new": "2", "expected_version": version}))
        self.assertIn("error", result)
        self.assertIsNone(runner.last_tests)

    def test_unmetered_model_response_stops_evaluation_with_partial_report(self):
        from miser.evaluation import evaluate_fixtures
        from test_agent import response

        class Client:
            calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return response(usage=False)

        client = Client()
        target = Path(self.tmp.name) / "evaluation"
        report = evaluate_fixtures(target, client, "synthetic-audit-provider",
                                   languages=("python",), repeats=2, progress=None)
        self.assertEqual(client.calls, 1)
        self.assertEqual(len(report["runs"]), 1)
        self.assertIn("stopped_early", report)
        self.assertEqual(json.loads((target / "report.json").read_text()), report)

    def test_cancellation_is_checked_during_acceptance_wait(self):
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        runner.cancelled = lambda: True
        with patch("miser.tools.subprocess.Popen") as spawn:
            process = spawn.return_value
            process.returncode = 0
            with patch.object(runner, "_terminate") as terminate:
                with self.assertRaises(KeyboardInterrupt):
                    runner.run_tests()
            terminate.assert_called_once_with(process)

    def test_cancellation_is_checked_during_command_wait(self):
        supervisor = self.supervisor(approval_callback=lambda _: True)
        supervisor.cancelled = lambda: True
        with patch("miser.execution.subprocess.Popen") as spawn:
            process = spawn.return_value
            process.returncode = 0
            with patch.object(supervisor, "_terminate") as terminate:
                with self.assertRaises(KeyboardInterrupt):
                    supervisor.run(["python3", "-m", "unittest"])
            terminate.assert_called_once_with(process)

    def test_success_observes_every_result_in_the_completed_batch(self):
        from miser.memory import WorkingMemory
        from test_agent import batch_response

        (self.root / "test_smoke.py").write_text(
            "import unittest\nclass Smoke(unittest.TestCase):\n"
            "    def test_smoke(self): self.assertEqual(1, 1)\n")

        class Client:
            def complete(self, *args, **kwargs):
                return batch_response(("zoom", {"path": "app.py"}),
                                      ("write_file", {"path": "new.py", "content": "value = 2\n"}),
                                      ("run_tests", {}))

        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        seen = []
        original = WorkingMemory.observe

        def observe(memory, name, args, output):
            seen.append(name)
            return original(memory, name, args, output)

        with patch.object(WorkingMemory, "observe", observe):
            self.assertEqual(run_agent("Add new.py", Client(), runner, self.ledger), "tests_passed")
        self.assertEqual(seen, ["run_tests", "zoom", "write_file", "run_tests"])

    def test_failed_new_file_write_removes_its_partial_file(self):
        target = self.root / "new.py"
        real_open = Path.open

        class PartialWriter:
            def __enter__(self):
                self.handle = real_open(target, "x", encoding="utf-8")
                return self

            def write(self, value):
                self.handle.write(value[:2])
                raise OSError("simulated partial creation")

            def __exit__(self, *args):
                self.handle.close()

        def opening(path, *args, **kwargs):
            if path == target:
                return PartialWriter()
            return real_open(path, *args, **kwargs)

        with patch.object(Path, "open", opening):
            with self.assertRaises(RuntimeError):
                self.ws.write_file("new.py", "value = 2\n")
        self.assertFalse(target.exists())
        self.assertEqual(self.ws.modified, set())

    def test_execution_prefix_and_metacharacter_boundaries(self):
        for argv in (["gitfoo", "status"], ["GIT=git", "status"], ["env", "git", "status"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                check_argv(argv)
        for marker in ("\n", "\r", ";", "&&", "||", "|", "`id`", "$(id)",
                       "${X}", ">out", "<in", "(x)"):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                check_argv(["git", "diff", marker])
        # These are literal argv, not expanded by a shell. Keep the policy intact.
        self.assertEqual(check_argv(["git", "diff", "*.py"]), ["git", "diff", "*.py"])
        with self.assertRaisesRegex(ValueError, "metacharacter"):
            check_argv(["python3", "-c", "print(1)"])

    def test_normalized_ambiguity_and_protected_paths_leave_files_unchanged(self):
        self.file.write_text("    value = 1\n    value = 1\n")
        before = self.file.read_bytes()
        version = self.ws.zoom("app.py", level=2)["version"]
        with self.assertRaises(ValueError):
            self.ws.edit("app.py", "value = 1   \n", "value = 2\n", version)
        self.assertEqual(self.file.read_bytes(), before)
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        for path in ("../app.py", str(self.file), "link/app.py", ".env.local", ".ssh/id", "cert.pem"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.ws.text(path)

    def test_every_non_read_only_tool_disables_agent_parallel_batching(self):
        from miser.tools import SCHEMAS, READ_ONLY_TOOLS
        from test_agent import batch_response

        names = {schema["function"]["name"] for schema in SCHEMAS}
        self.assertEqual(len(names), 19)  # ask_user adds one capability to the audited catalog
        self.assertTrue({"edit", "edit_batch", "apply_patch", "write_file", "run_tests",
                         "run_command", "write_todos", "verify_claim"}.isdisjoint(READ_ONLY_TOOLS))
        for name in sorted(names - READ_ONLY_TOOLS):
            class Client:
                def complete(self, *args, **kwargs):
                    return batch_response(("list_files", {}), (name, {}))

            ledger = Ledger(Path(self.tmp.name) / (name + ".json"))
            runner = ToolRunner(self.ws, ledger, [sys.executable, "-m", "unittest"])
            with self.subTest(name=name), patch.object(runner, "invoke", return_value='{}'), patch(
                    "miser.agent.run_parallel_batch") as parallel:
                run_agent("Inspect app.py", Client(), runner, ledger, max_steps=1)
                parallel.assert_not_called()
                self.assertFalse(next(e for e in ledger.data["events"] if e["kind"] == "tool_batch")["parallel"])

    def test_atomic_json_snapshot_survives_partial_temp_write(self):
        before = self.ledger.path.read_bytes()
        real_write = Path.write_text

        def failure(path, *args, **kwargs):
            if path.suffix == ".tmp":
                path.write_bytes(b'{"partial":')
                raise OSError("simulated disk full")
            return real_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", failure):
            with self.assertRaises(OSError):
                self.ledger.record("tool", name="list_files")
        self.assertEqual(self.ledger.path.read_bytes(), before)
        json.loads(before)

    def test_provider_overshoot_is_reported_and_tools_are_not_executed(self):
        from test_agent import response

        class Client:
            def complete(self, *args, **kwargs):
                result = response("write_file", {"path": "new.py", "content": "x"})
                result["usage"] = {"prompt_tokens": 10900, "completion_tokens": 100, "total_tokens": 11000}
                return result

        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "-m", "unittest"])
        self.assertEqual(run_agent("Add new.py", Client(), runner, self.ledger,
                                   token_budget=10000), "budget_exceeded")
        self.assertEqual(self.ledger.total_tokens, 11000)
        self.assertFalse((self.root / "new.py").exists())

    def test_all_four_golden_conditions_and_cli_exit_are_independent(self):
        from miser.cli import main
        from miser.evaluation import golden_check, summarize

        row = {"status": "tests_passed", "receipt": {
            "usage_complete": True, "model_calls": 4, "total_tokens": 5999}}
        self.assertEqual(summarize([{**row, "golden": golden_check(row)}])["golden_tasks_passed"], 1)
        for field, value in (("status", "answered"), ("usage_complete", False),
                             ("model_calls", 5), ("total_tokens", 6000)):
            candidate = {"status": row["status"], "receipt": dict(row["receipt"])}
            if field == "status":
                candidate[field] = value
            else:
                candidate["receipt"][field] = value
            candidate["golden"] = golden_check(candidate)
            report = {"summary": summarize([candidate])}
            with self.subTest(field=field):
                self.assertEqual(report["summary"]["golden_tasks_passed"], 0)
                with patch("miser.cli.ModelClient"), patch(
                        "miser.evaluation.evaluate_fixtures", return_value=report), patch(
                        "miser.cli.load_env"), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(["evaluate", "--demo", "python", "--model", "synthetic"]), 1)

    def test_evaluation_refuses_existing_output_and_preserves_fixture_sources(self):
        from miser.evaluation import evaluate_fixtures
        from test_agent import ScriptedClient

        source = Path(__file__).resolve().parent.parent / "examples/python_bug/pricing.py"
        before = source.read_bytes()
        target = Path(self.tmp.name) / "evaluation"
        report = evaluate_fixtures(target, ScriptedClient(), "synthetic", languages=("python",), progress=None)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(report["runs"][0]["receipt"],
                         receipt(json.loads((target / report["runs"][0]["ledger"]).read_text())))
        with self.assertRaises(FileExistsError):
            evaluate_fixtures(target, ScriptedClient(), "synthetic", languages=("python",), progress=None)

    def test_legacy_numeric_private_addresses_are_refused_before_transport(self):
        for host in ("2130706433", "0177.0.0.1", "0x7f000001", "127.1"):
            with self.subTest(host=host), patch("miser.web._open_once", return_value=io.BytesIO(b"text")) as opened:
                with self.assertRaisesRegex(ValueError, "Refusing"):
                    WebAccess(self.ledger).fetch("https://" + host + "/")
                opened.assert_not_called()

    def test_successful_foreground_command_does_not_leave_live_descendants(self):
        script = self.root / "spawn.py"
        script.write_text("import subprocess, sys\n"
                          "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                          "print(child.pid, flush=True)\n")
        supervisor = self.supervisor(approval_callback=lambda _: True,
                                     allowlist=(("python3", "spawn.py"),))
        runner = ToolRunner(self.ws, self.ledger, [sys.executable, "spawn.py"])
        for label, run in (("command", lambda: supervisor.run(["python3", "spawn.py"])),
                           ("acceptance", runner.run_tests)):
            with self.subTest(label=label):
                pid = int(run()["output"].strip())

                def cleanup(pid=pid):
                    try:
                        os.kill(pid, 9)
                    except ProcessLookupError:
                        pass

                self.addCleanup(cleanup)
                proc = Path(f"/proc/{pid}/stat")
                deadline = time.monotonic() + 1
                while process_is_live(proc) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(process_is_live(proc), "Foreground command left a live descendant")

    def test_cleanup_probe_treats_exit_during_read_as_gone_but_live_process_as_live(self):
        proc = Path("/proc/fixture/stat")
        for error in (FileNotFoundError(), ProcessLookupError()):
            with self.subTest(error=type(error).__name__), patch.object(Path, "read_text", side_effect=error):
                self.assertFalse(process_is_live(proc))
        for state, expected in (("Z", False), ("S", True), ("R", True)):
            with self.subTest(state=state), patch.object(Path, "read_text", return_value=f"42 (child) {state} 1"):
                self.assertEqual(process_is_live(proc), expected)
        with patch.object(Path, "read_text", side_effect=PermissionError()), self.assertRaises(PermissionError):
            process_is_live(proc)

    def test_later_patch_hunk_uses_original_coordinates_after_line_insertion(self):
        target = self.root / "note.txt"
        target.write_text("top\nsame\nsame\nend\n")
        self.ws.zoom("note.txt")
        self.ws.apply_unified_diff(
            "--- a/note.txt\n+++ b/note.txt\n@@ -1 +1,2 @@\n top\n+added\n"
            "@@ -3 +4 @@\n-same\n+target\n")
        self.assertEqual(target.read_text(), "top\nadded\nsame\ntarget\nend\n")

    def test_every_edit_in_same_file_batch_must_have_the_base_version(self):
        version = self.ws.zoom("app.py")["version"]
        with self.assertRaisesRegex(ValueError, "changed|version"):
            self.ws.edit_batch([
                {"path": "app.py", "old": "1", "new": "2", "expected_version": version},
                {"path": "app.py", "old": "2", "new": "3", "expected_version": "invalid"}])
        self.assertEqual(self.file.read_text(), "value = 1\n")


if __name__ == "__main__":
    unittest.main()
