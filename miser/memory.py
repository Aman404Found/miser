"""Bounded factual breadcrumbs; no extra model calls or copied source bodies."""

import json
from collections import Counter, deque


class WorkingMemory:
    """Compact task state that survives history compaction.

    Raw tool results live in a small ring buffer; the durable breadcrumb records which
    files were read or edited (with their versions), the errors seen, and the latest
    acceptance-test status. Compaction folds the ring buffer into counters and clears it,
    so old tool JSON cannot keep inflating the prompt.
    """

    def __init__(self, observation_limit=8):
        self.observations = deque(maxlen=observation_limit)
        self.files = {}
        self.errors = deque(maxlen=5)
        self.test_status = None
        self.compactions = 0
        self.observations_dropped = 0

    def observe(self, name, arguments, output):
        value = json.loads(output)
        entry = {"tool": name}
        path = arguments.get("path") if isinstance(arguments.get("path"), str) else None
        if path:
            entry["path"] = path[:250]
        if "error" in value:
            entry["error"] = str(value["error"])[:250]
            self.errors.append(f"{name}: {str(value['error'])[:200]}")
        else:
            for field in ("version", "edited", "unchanged", "passed", "timed_out"):
                if field in value:
                    entry[field] = value[field]
            if name == "search":
                entry["paths"] = [p[:250] for p in dict.fromkeys(m["path"] for m in value.get("matches", []))][:5]
        if path:
            record = self.files.setdefault(path[:250], {})
            if "version" in value:
                record["version"] = value["version"]
            if name == "zoom":
                record["read"] = True
            if name in ("edit", "edit_batch", "apply_patch"):
                record["edited"] = bool(value.get("edited"))
        if name == "run_tests":
            self.test_status = {"passed": bool(value.get("passed")),
                                "exit_code": value.get("exit_code"),
                                "timed_out": bool(value.get("timed_out")),
                                "output_tail": (value.get("output") or "")[-400:] if not value.get("passed") else None}
        self.observations.append(entry)

    def compact(self):
        """Fold raw observations into counters and keep only the durable breadcrumb."""
        tools = Counter(entry["tool"] for entry in self.observations)
        self.observations_dropped += len(self.observations)
        self.observations.clear()
        self.compactions += 1
        return {"tools_used": dict(tools), "observations_dropped": self.observations_dropped}

    def snapshot(self):
        files = [{"path": path, **record} for path, record in list(self.files.items())[-8:]]
        return {"recent_observations": list(self.observations),
                "files": files,
                "errors": list(self.errors),
                "latest_tests": self.test_status,
                "compactions": self.compactions,
                "observations_dropped": self.observations_dropped,
                "note": "Breadcrumbs may be stale. Refresh zoom for exact current text; recall returns only deltas."}
