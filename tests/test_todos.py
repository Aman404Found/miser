import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from miser.agent import run_agent
from miser.ledger import Ledger
from miser.todos import MAX_TASK_CHARS, MAX_TODOS, TodoList
from miser.tools import ToolRunner
from miser.ui import render
from miser.workspace import Workspace


class TodoListTests(unittest.TestCase):
    """Unit fixtures only; these never stand in for product benchmark numbers."""

    def test_order_is_preserved_and_fields_are_normalised(self):
        todos = TodoList()
        items = todos.update([{"task": "  read   pricing.py ", "completed": False},
                              {"task": "patch it", "completed": False}])
        self.assertEqual([item["task"] for item in items], ["read pricing.py", "patch it"])
        self.assertEqual([item["completed"] for item in items], [False, False])
        self.assertEqual(todos.total, 2)
        self.assertEqual(todos.next_item, "read pricing.py")
        self.assertFalse(todos.all_done)

    def test_revision_increments_once_per_update(self):
        todos = TodoList()
        self.assertEqual(todos.revision, 0)
        todos.update([{"task": "one", "completed": False}])
        todos.update([{"task": "one", "completed": True}])
        self.assertEqual(todos.revision, 2)
        self.assertEqual(todos.completed_count, 1)
        self.assertIsNone(todos.next_item)
        self.assertTrue(todos.all_done)

    def test_progress_and_state_are_compact(self):
        todos = TodoList()
        self.assertIsNone(todos.progress())
        todos.update([{"task": "a", "completed": True}, {"task": "b", "completed": False}])
        self.assertEqual(todos.progress(), "1/2 done")
        state = todos.state()
        self.assertEqual(state["revision"], 1)
        self.assertEqual(state["total"], 2)
        self.assertEqual(state["completed"], 1)
        self.assertEqual(state["next_step"], "b")
        self.assertEqual(state["items"], [{"task": "a", "completed": True},
                                          {"task": "b", "completed": False}])
        # Callers cannot mutate the stored list through the returned copy.
        state["items"][0]["task"] = "changed"
        self.assertEqual(todos.items[0]["task"], "a")

    def test_rejects_non_list_and_empty(self):
        with self.assertRaisesRegex(ValueError, "array"):
            TodoList.validate("read pricing.py")
        with self.assertRaisesRegex(ValueError, "at least one"):
            TodoList.validate([])

    def test_rejects_too_many_items(self):
        items = [{"task": f"step {i}", "completed": False} for i in range(MAX_TODOS + 1)]
        with self.assertRaisesRegex(ValueError, f"At most {MAX_TODOS}"):
            TodoList.validate(items)

    def test_rejects_malformed_items(self):
        with self.assertRaisesRegex(ValueError, "must be an object"):
            TodoList.validate(["read pricing.py"])
        with self.assertRaisesRegex(ValueError, "unknown field"):
            TodoList.validate([{"task": "read", "completed": False, "owner": "me"}])
        with self.assertRaisesRegex(ValueError, "nonempty task"):
            TodoList.validate([{"task": "   ", "completed": False}])
        with self.assertRaisesRegex(ValueError, "nonempty task"):
            TodoList.validate([{"task": 3, "completed": False}])
        with self.assertRaisesRegex(ValueError, "true or false"):
            TodoList.validate([{"task": "read", "completed": "yes"}])
        with self.assertRaisesRegex(ValueError, "exceeds"):
            TodoList.validate([{"task": "x" * (MAX_TASK_CHARS + 1), "completed": False}])

    def test_failed_validation_leaves_previous_plan_intact(self):
        todos = TodoList()
        todos.update([{"task": "keep me", "completed": False}])
        with self.assertRaises(ValueError):
            todos.update([])
        self.assertEqual(todos.total, 1)
        self.assertEqual(todos.items[0]["task"], "keep me")
        self.assertEqual(todos.revision, 1)


class WriteTodosToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.ledger = Ledger(Path(self.temp.name) / "ledger.json",
                             mode="unit-test-fixture", benchmark=False)
        self.runner = ToolRunner(Workspace(self.repo), self.ledger,
                                 [sys.executable, "-m", "unittest", "discover", "-s", "."])

    def test_invoke_returns_summary_and_records_event(self):
        result = json.loads(self.runner.invoke("write_todos", {"todos": [
            {"task": "read", "completed": True},
            {"task": "patch", "completed": False}]}))
        self.assertEqual(result["revision"], 1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["next_step"], "patch")
        self.assertEqual(self.runner.todos.total, 2)
        events = [e for e in self.ledger.data["events"] if e["kind"] == "todos"]
        self.assertEqual(events[-1]["revision"], 1)
        self.assertEqual(events[-1]["completed"], 1)

    def test_invoke_requires_exactly_the_todos_array(self):
        for arguments in ({}, {"todos": [{"task": "a", "completed": False}], "extra": 1}):
            result = json.loads(self.runner.invoke("write_todos", arguments))
            self.assertIn("exactly the todos array", result["error"])
        self.assertEqual(self.runner.todos.total, 0)

    def test_invoke_reports_validation_error(self):
        result = json.loads(self.runner.invoke("write_todos", {"todos": []}))
        self.assertIn("at least one", result["error"])
        self.assertEqual(self.runner.todos.revision, 0)


def response(name=None, arguments=None):
    message = {"role": "assistant", "content": None}
    if name:
        message["tool_calls"] = [{"id": "fixture-call", "type": "function",
                                  "function": {"name": name,
                                               "arguments": json.dumps(arguments or {})}}]
    else:
        message["content"] = "done"
    return {"choices": [{"message": message}], "model": "unit-test-fixture",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


class PlanReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        (self.repo / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.ledger = Ledger(Path(self.temp.name) / "ledger.json",
                             mode="unit-test-fixture", benchmark=False)
        self.runner = ToolRunner(Workspace(self.repo), self.ledger,
                                 [sys.executable, "-m", "unittest", "discover", "-s", "."])

    def test_stale_plan_reminder_is_sent_once_after_work_without_an_update(self):
        class Worker:
            def __init__(self):
                self.states = []

            def complete(self, messages, tools, max_tokens):
                self.states.append(json.loads(messages[1]["content"]))
                call = len(self.states)
                if call == 1:
                    return response("write_todos", {"todos": [
                        {"task": "inspect", "completed": False},
                        {"task": "report", "completed": False}]})
                if call == 2:
                    return response("list_files")
                if call == 3:
                    return response("write_todos", {"todos": [
                        {"task": "inspect", "completed": True},
                        {"task": "report", "completed": False}]})
                return response("list_files")

        client = Worker()
        status = run_agent("Inspect", client, self.runner, self.ledger, max_steps=4)
        self.assertEqual(status, "step_limit")
        self.assertNotIn("plan_reminder", client.states[1])  # fresh plan, no nudge
        self.assertIn("stale", client.states[2]["plan_reminder"])
        self.assertNotIn("plan_reminder", client.states[3])  # re-emitted, reminder cleared
        self.assertEqual(self.runner.todos.stale_checks, 1)

    def test_fresh_plan_has_no_reminder(self):
        class Planner:
            def __init__(self):
                self.states = []

            def complete(self, messages, tools, max_tokens):
                self.states.append(json.loads(messages[1]["content"]))
                if len(self.states) == 1:
                    return response("write_todos", {"todos": [{"task": "inspect",
                                                               "completed": False}]})
                return response("list_files")

        client = Planner()
        run_agent("Inspect", client, self.runner, self.ledger, max_steps=2)
        self.assertEqual(self.runner.todos.stale_checks, 0)
        self.assertTrue(all("plan_reminder" not in state for state in client.states))


class TodoRenderTests(unittest.TestCase):
    def test_checklist_marks_done_and_pending_items(self):
        text = render.todo_list([{"task": "read", "completed": True},
                                 {"task": "patch", "completed": False}], width=80)
        self.assertIn("plan", text)
        self.assertIn("1/2 done", text)
        self.assertIn("read", text)
        self.assertIn("patch", text)
        self.assertEqual(text.splitlines()[0].strip().split()[0], "plan")

    def test_tool_detail_reports_done_count(self):
        detail = render.tool_detail("write_todos", {"todos": [
            {"task": "a", "completed": True}, {"task": "b", "completed": False}]})
        self.assertEqual(detail, "1/2 done")
        self.assertEqual(render.TOOL_LABELS["write_todos"], "plan")


if __name__ == "__main__":
    unittest.main()
