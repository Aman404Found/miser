"""Model usage is authoritative; context sizes are separate estimates."""

import json
import math
import os
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
        self.flush()

    def record(self, kind, **fields):
        self.data["events"].append({"at": now(), "kind": kind, **fields})
        self.flush()

    def flush(self):
        write_json(self.path, self.data)

    def finish(self, status, **fields):
        self.data.update(status=status, finished_at=now(), **fields)
        self.flush()

    @property
    def total_tokens(self):
        return sum(e.get("total_tokens", 0) for e in self.data["events"]
                   if e["kind"] == "model")

    def model(self, response, elapsed):
        usage = response.get("usage") or {}
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        valid = all(isinstance(usage.get(k), int) and not isinstance(usage[k], bool)
                    and usage[k] >= 0 for k in keys)
        if valid:
            valid = usage["total_tokens"] >= usage["prompt_tokens"] + usage["completion_tokens"]
        self.record("model", model=response.get("model"), elapsed_seconds=round(elapsed, 3),
                    usage_known=valid, **{k: usage.get(k, 0) if valid else 0 for k in keys},
                    cached_input_tokens=(usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                    gateway_cache=(response.get("extra_fields") or {}).get("cache_debug"))
        if not valid:
            raise ValueError("Model response lacks valid usage; stopping rather than inventing a bill")


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
        "tool_context_tokens_estimate": sum(e.get("context_tokens_estimate", 0) for e in events),
        "billing_note": "Tool-context estimates are diagnostic; do not add them to model tokens. "
                        "Search API credits and monetary cost are not inferred from tokens.",
    }
