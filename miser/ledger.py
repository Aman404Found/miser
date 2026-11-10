"""Model usage is authoritative; context sizes are separate estimates."""

import json
import math
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def estimate_tokens(text):
    # Deliberately not sold as a tokenizer or added to reported model usage.
    return math.ceil(len(text.encode("utf-8")) / 4)


def request_diagnostics(messages, tools):
    """Sizes only: never persist prompt bodies or confuse estimates with usage."""
    groups = {"instructions": [], "state": [], "history": []}
    for index, message in enumerate(messages):
        group = "instructions" if message.get("role") == "system" else ("state" if index == 1 else "history")
        groups[group].append(message)
    sizes = {name: estimate_tokens(json.dumps(value)) for name, value in groups.items()}
    sizes["tool_definitions"] = estimate_tokens(json.dumps(tools))
    return {"component_tokens_estimate": sizes,
            "input_tokens_estimate": estimate_tokens(json.dumps(messages) + json.dumps(tools)),
            "message_count": len(messages), "tool_count": len(tools),
            "note": "UTF-8 bytes / 4 estimates; not provider tokens. Component rounding/framing differs from total."}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(temp, path)


class Ledger:
    def __init__(self, path, **metadata):
        self.path = Path(path)
        self.data = {"schema_version": 1, "started_at": now(), "metadata": metadata,
                     "status": "running", "events": []}
        # Concurrent read-only tool calls record at the same time; write_json
        # reuses one .tmp path, so serialise the write itself.
        self._lock = threading.RLock()
        self.flush()

    def record(self, kind, **fields):
        with self._lock:
            self.data["events"].append({"at": now(), "kind": kind, **fields})
            self.flush()

    def flush(self):
        with self._lock:
            write_json(self.path, self.data)

    def finish(self, status, **fields):
        with self._lock:
            self.data.update(status=status, finished_at=now(), **fields)
            self.flush()

    @property
    def total_tokens(self):
        with self._lock:
            return sum(e.get("total_tokens", 0) for e in self.data["events"]
                       if e["kind"] == "model")

    def model(self, response, elapsed):
        usage = response.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        valid = all(isinstance(usage.get(k), int) and not isinstance(usage[k], bool)
                    and usage[k] >= 0 for k in keys)
        if valid:
            valid = usage["total_tokens"] >= usage["prompt_tokens"] + usage["completion_tokens"]
        details = usage.get("prompt_tokens_details") or {}
        extra = response.get("extra_fields") or {}
        self.record("model", model=response.get("model"), elapsed_seconds=round(elapsed, 3),
                    usage_known=valid, **{k: usage.get(k, 0) if valid else 0 for k in keys},
                    cached_input_tokens=details.get("cached_tokens") if isinstance(details, dict) else None,
                    gateway_cache=extra.get("cache_debug") if isinstance(extra, dict) else None)
        if not valid:
            raise ValueError("Model response lacks valid usage; stopping rather than inventing a bill")


def timing_summary(events, wall_seconds):
    """Host durations only, not billing or a partition of elapsed wall time.

    Tests have their own event inside run_tests, so exclude that tool wrapper.
    Parallel tools overlap; approval waits and nested work remain in tool sums.
    """
    totals = {"model_seconds": 0.0, "test_seconds": 0.0, "tool_seconds_sum": 0.0}
    missing, pending = 0, 0
    for event in events:
        kind = event.get("kind")
        if kind == "model_request":
            pending += 1
        elif (kind in {"model", "model_error"} and event.get("role") != "architect"
              and not event.get("duration_in_model_event") and pending):
            pending -= 1
        if kind in {"model", "model_error"}:
            if event.get("duration_in_model_event"):
                continue
            key = "model_seconds"
        elif kind == "tests":
            key = "test_seconds"
        elif kind == "tool" and event.get("name") != "run_tests":
            key = "tool_seconds_sum"
        else:
            continue
        duration = event.get("elapsed_seconds")
        if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
                or not math.isfinite(duration) or duration < 0):
            missing += 1
        else:
            totals[key] += duration
    return {"wall_seconds": round(wall_seconds, 3),
            **{key: round(value, 3) for key, value in totals.items()},
            "missing_durations": missing + pending,
            "note": "Host durations, not billing. Tool sums include approval waits; parallel/nested work can overlap. "
                    "Model waits include client retries, not separate provider compute time."}


def receipt(data):
    events = data["events"]
    models = [e for e in events if e["kind"] == "model"]
    requests = [e for e in events if e["kind"] == "model_request"]
    return {
        "status": data["status"],
        "model_calls": len(models),
        "failed_model_requests": sum(e["kind"] == "model_error" for e in events),
        "input_tokens": sum(e.get("prompt_tokens", 0) for e in models),
        "output_tokens": sum(e.get("completion_tokens", 0) for e in models),
        "total_tokens": sum(e.get("total_tokens", 0) for e in models),
        "usage_complete": all(e.get("usage_known", False) for e in models)
                          and not any(e["kind"] == "model_error" for e in events),
        "tool_calls": sum(e["kind"] == "tool" for e in events),
        "test_runs": sum(e["kind"] == "tests" for e in events),
        "search_attempts": sum(e["kind"] == "search" for e in events),
        "web_calls": sum(e["kind"] == "web" for e in events),
        "compactions": sum(e["kind"] == "compaction" for e in events),
        "model_fallbacks": sum(e["kind"] == "model_fallback" for e in events),
        "architect_plans": sum(e["kind"] == "architect_plan" for e in events),
        "measured_request_count": len(requests),
        "request_component_tokens_estimate": {
            name: sum(e.get("component_tokens_estimate", {}).get(name, 0) for e in requests)
            for name in ("instructions", "state", "history", "tool_definitions")},
        "context_tokens_freed_estimate": sum(e.get("tokens_freed", 0) for e in events
                                             if e["kind"] == "compaction"),
        "tool_context_tokens_estimate": sum(e.get("context_tokens_estimate", 0) for e in events
                                             if e["kind"] == "tool"),
        "billing_note": "Tool-context estimates are diagnostic; do not add them to model tokens. "
                        "Search API credits and monetary cost are not inferred from tokens.",
    }
