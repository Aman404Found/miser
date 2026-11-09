"""Repeatable fixture checks; these are smoke tests, not an OSS benchmark."""

import json
import shutil
import sys
import time
from pathlib import Path

from .agent import run_agent
from .ledger import Ledger, receipt, write_json
from .tools import ToolRunner
from .workspace import Workspace


# Golden-task thresholds from the master plan: a fixture bug must be solved cheaply.
GOLDEN_LIMITS = {"max_model_calls": 4, "max_provider_tokens": 6000}


def golden_check(row):
    """Grade one run against the golden-task thresholds using provider-reported usage."""
    bill = row["receipt"]
    return {"solved": row["status"] == "tests_passed",
            "usage_complete": bool(bill["usage_complete"]),
            "within_model_calls": bill["model_calls"] <= GOLDEN_LIMITS["max_model_calls"],
            "within_provider_tokens": bill["total_tokens"] < GOLDEN_LIMITS["max_provider_tokens"],
            "model_calls": bill["model_calls"],
            "provider_tokens": bill["total_tokens"]}


def summarize(rows):
    solved = sum(row["status"] == "tests_passed" for row in rows)
    complete = all(row["receipt"]["usage_complete"] for row in rows)
    tokens = sum(row["receipt"]["total_tokens"] for row in rows)
    summary = {"tasks": len(rows), "solved": solved,
               "success_rate": solved / len(rows) if rows else None,
               "reported_tokens_including_failures": tokens,
               "usage_complete": complete,
               "tokens_per_solved_task": tokens / solved if solved and complete else None}
    graded = [row["golden"] for row in rows if "golden" in row]
    if graded:
        summary["golden_tasks"] = len(graded)
        summary["golden_tasks_passed"] = sum(
            check["solved"] and check["usage_complete"] and check["within_model_calls"]
            and check["within_provider_tokens"] for check in graded)
    return summary


def evaluate_fixtures(directory, client, model, repeats=1, languages=("python", "javascript"),
                      token_budget=12000, max_steps=8, progress=print, golden=False):
    if repeats < 1 or repeats > 10:
        raise ValueError("Repeats must be between 1 and 10")
    if not languages or any(language not in ("python", "javascript") for language in languages):
        raise ValueError("Choose Python and/or JavaScript fixtures")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    report = {"kind": "golden-task-evaluation" if golden else "live-fixture-evaluation",
              "benchmark": False, "model": model,
              "note": "Small synthetic fixtures; no baseline or token-savings claim. Disable gateway caching.",
              "runs": []}
    if golden:
        report["golden_thresholds"] = GOLDEN_LIMITS
    fixtures = Path(__file__).resolve().parent.parent / "examples"
    for repeat in range(1, repeats + 1):
        for language in languages:
            label = f"{language}-{repeat}"
            run_dir = directory / label
            target = run_dir / "repo"
            shutil.copytree(fixtures / f"{language}_bug", target,
                            ignore=shutil.ignore_patterns("__pycache__"))
            command = [sys.executable, "-m", "unittest", "discover", "-s", "."] if language == "python" else ["node", "--test"]
            ledger = Ledger(run_dir / "ledger.json", mode="live-fixture-evaluation",
                            model=model, language=language, repeat=repeat, benchmark=False,
                            test_command=command, token_budget=token_budget, max_steps=max_steps)
            runner = ToolRunner(Workspace(target), ledger, command)
            started = time.monotonic()
            if progress:
                progress(f"Evaluating {label}")
            try:
                status = run_agent("Fix the percentage discount calculation. Preserve tests and public API.",
                                   client, runner, ledger, token_budget, max_steps, progress=progress)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError, IndexError) as error:
                status = "error"
                ledger.finish(status, error=str(error))
            row = {"task": label, "status": status, "receipt": receipt(ledger.data),
                   "elapsed_seconds": round(time.monotonic() - started, 3),
                   "ledger": str(ledger.path.relative_to(directory))}
            if golden:
                row["golden"] = golden_check(row)
            report["runs"].append(row)
            report["summary"] = summarize(report["runs"])
            write_json(directory / "report.json", report)
            # A transport/auth failure should not trigger more paid retries.
            if row["receipt"]["failed_model_requests"]:
                report["stopped_early"] = "Model request failed; inspect gateway before retrying"
                write_json(directory / "report.json", report)
                return report
    return report
