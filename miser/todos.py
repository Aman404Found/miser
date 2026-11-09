"""An ordered plan the model rewrites as it advances.

The list is deliberately small and strict: it is a progress ledger, not a
scratchpad. Validation happens in one place so the tool, the prompt, and the
renderer all agree on what a valid update looks like.
"""

MAX_TODOS = 20
MAX_TASK_CHARS = 200


class TodoList:
    """Ordered ``{task, completed}`` items with a monotonic revision counter."""

    def __init__(self):
        self.items = []
        self.revision = 0
        # Incremented by the agent only when a model turn did work but
        # re-emitted no list; used to nudge the next turn.
        self.stale_checks = 0

    @staticmethod
    def validate(items):
        """Return normalised items or raise ValueError describing the first problem."""
        if not isinstance(items, list):
            raise ValueError("todos must be an array")
        if not items:
            raise ValueError("todos must contain at least one item")
        if len(items) > MAX_TODOS:
            raise ValueError(f"At most {MAX_TODOS} todos are allowed")
        normalised = []
        for index, item in enumerate(items, 1):
            if not isinstance(item, dict):
                raise ValueError(f"Todo {index} must be an object")
            unknown = set(item) - {"task", "completed"}
            if unknown:
                raise ValueError(f"Todo {index} has unknown field(s): {', '.join(sorted(unknown))}")
            task = item.get("task")
            if not isinstance(task, str) or not task.strip():
                raise ValueError(f"Todo {index} needs nonempty task text")
            task = " ".join(task.split())
            if len(task) > MAX_TASK_CHARS:
                raise ValueError(f"Todo {index} task exceeds {MAX_TASK_CHARS} characters")
            completed = item.get("completed", False)
            if not isinstance(completed, bool):
                raise ValueError(f"Todo {index} completed must be true or false")
            normalised.append({"task": task, "completed": completed})
        return normalised

    def update(self, items):
        """Replace the list; returns the stored items."""
        self.items = self.validate(items)
        self.revision += 1
        return self.items

    def summary(self):
        return [dict(item) for item in self.items]

    @property
    def total(self):
        return len(self.items)

    @property
    def completed_count(self):
        return sum(1 for item in self.items if item["completed"])

    @property
    def next_item(self):
        return next((item["task"] for item in self.items if not item["completed"]), None)

    @property
    def all_done(self):
        return bool(self.items) and self.completed_count == self.total

    def progress(self):
        """Compact ``2/5 done`` phrase, or None when nothing is planned."""
        if not self.items:
            return None
        return f"{self.completed_count}/{self.total} done"

    def state(self):
        """The slice that goes into the prompt each step."""
        return {"revision": self.revision, "total": self.total,
                "completed": self.completed_count, "next_step": self.next_item,
                "items": self.summary()}
