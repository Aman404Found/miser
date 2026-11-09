import argparse
import json
import os
import shlex
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .agent import run_agent
from .client import ModelClient
from .ledger import Ledger, receipt, write_json
from .tools import ToolRunner
from .verification import EvidenceSearch
from .workspace import Workspace


def load_env(path=None):
    """Load environment variables from .env or ~/.miser.env without external dependencies."""
    candidates = [
        Path(path) if path else None,
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path.home() / ".miser.env",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
                break
            except (OSError, UnicodeDecodeError):
                continue


def run_path(label):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return Path("runs") / f"{label}-{stamp}-{uuid.uuid4().hex[:6]}"


def show(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def want_tui(args):
    """Full-screen UI only for an interactive terminal with Rich available."""
    if args.no_tui or args.exec_tasks:
        return False
    if os.getenv("MISER_PLAIN") or os.getenv("NO_COLOR"):
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    try:
        from rich.console import Console  # noqa: F401
    except ImportError:
        return False
    return True


def build_parser():
    parser = argparse.ArgumentParser(prog="miser", description="Focused coding context, explicit budgets, honest receipts.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check local prerequisites without displaying keys")
    chat = commands.add_parser("chat", help="Open the interactive coding terminal")
    chat.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    chat.add_argument("--model", default=os.getenv("MISER_MODEL"))
    chat.add_argument("--test-command")
    chat.add_argument("--token-budget", type=int, default=24000)
    chat.add_argument("--demo", choices=["python", "javascript"], help="Work on a disposable fixture copy")
    chat.add_argument("--resume", nargs="?", const=True, default=False, help="Resume previous interactive session context")
    chat.add_argument("--exec", dest="exec_tasks", action="append", metavar="TASK",
                      help="Run one task/question non-interactively, then exit; repeatable")
    chat.add_argument("--no-stream", action="store_true", help="Disable live streaming (use plain responses)")
    chat.add_argument("--no-tui", action="store_true", help="Use the line-oriented interface instead of the full-screen UI")
    chat.add_argument("--auto-commit", action="store_true", help="Automatically commit passing edits to Git")
    chat.add_argument("--architect-model", default=os.getenv("MISER_ARCHITECT_MODEL"),
                      help="Reasoning model that plans before the editor model patches")
    smoke = commands.add_parser("smoke", help="Live model test on a disposable demo copy (uses API tokens)")
    smoke.add_argument("--language", choices=["python", "javascript"], default="python")
    smoke.add_argument("--model", default=os.getenv("MISER_MODEL"))
    smoke.add_argument("--out", type=Path)
    evaluate = commands.add_parser("evaluate", help="Live fixture suite with usage report (uses API tokens)")
    evaluate.add_argument("--model", default=os.getenv("MISER_MODEL"))
    evaluate.add_argument("--repeats", type=int, choices=range(1, 11), default=1)
    evaluate.add_argument("--language", choices=["python", "javascript"], action="append")
    evaluate.add_argument("--demo", choices=["python", "javascript"],
                          help="Run the golden fixture task with call/token thresholds")
    evaluate.add_argument("--token-budget", type=int, default=12000)
    evaluate.add_argument("--max-steps", type=int, default=8)
    evaluate.add_argument("--out", type=Path)
    inspect = commands.add_parser("inspect", help="Explore a repository without a model")
    inspect.add_argument("repo", type=Path)
    inspect.add_argument("--file")
    inspect.add_argument("--query")
    inspect.add_argument("--map", action="store_true", help="Show task-ranked paths and Python symbols")
    inspect.add_argument("--level", type=int, choices=[0, 1, 2], default=0)
    inspect.add_argument("--symbol")
    inspect.add_argument("--start", type=int, default=1)
    inspect.add_argument("--end", type=int)
    run = commands.add_parser("run", help="Run the real model-backed coding agent")
    run.add_argument("repo", type=Path)
    run.add_argument("task")
    run.add_argument("--test-command", required=True, help="Fixed acceptance command; parsed as argv, never a shell")
    run.add_argument("--model", default=os.getenv("MISER_MODEL"))
    run.add_argument("--token-budget", type=int, default=24000)
    run.add_argument("--max-steps", type=int, default=16)
    run.add_argument("--test-timeout", type=int, default=60)
    run.add_argument("--architect-model", default=os.getenv("MISER_ARCHITECT_MODEL"),
                     help="Reasoning model that plans before the editor model patches")
    run.add_argument("--fallback-models", default=os.getenv("MISER_FALLBACK_MODELS"),
                     help="Comma-separated models to try after a 429/503 from the primary")
    run.add_argument("--out", type=Path)
    bill = commands.add_parser("receipt", help="Read a run's recorded bill")
    bill.add_argument("ledger", type=Path)
    demo = commands.add_parser("demo", help="Scripted offline tool demo; not an LLM benchmark")
    demo.add_argument("--language", choices=["python", "javascript"], default="python")
    demo.add_argument("--out", type=Path)
    verify = commands.add_parser("verify", help="Discover evidence for one explicit claim (candidate stage)")
    verify.add_argument("--claim", required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--domain", action="append", required=True)
    verify.add_argument("--out", type=Path)
    verify.add_argument("--judge-model", help="Optional Bifrost model for provisional cited review; uses API tokens")
    return parser


def offline_demo(language, directory):
    fixtures = Path(__file__).resolve().parent.parent / "examples" / f"{language}_bug"
    if not fixtures.is_dir():
        raise ValueError("Demo fixtures not found; run from the source checkout")
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "repo"
    shutil.copytree(fixtures, target, ignore=shutil.ignore_patterns("__pycache__"))
    ledger = Ledger(directory / "ledger.json", mode="scripted-offline-demo", language=language,
                    model_used=False, benchmark=False)
    workspace = Workspace(target)
    test = [sys.executable, "-m", "unittest", "discover", "-s", "."] if language == "python" else ["node", "--test"]
    runner = ToolRunner(workspace, ledger, test)
    source = "pricing.py" if language == "python" else "pricing.js"
    try:
        print("SCRIPTED OFFLINE DEMO — real edits/tests; no model call or token-savings claim")
        before = json.loads(runner.invoke("run_tests", {}))
        if before.get("passed") is not False:
            raise RuntimeError("Expected the unmodified demo's acceptance tests to fail")
        context = json.loads(runner.invoke("zoom", {"path": source, "level": 2}))
        edit = json.loads(runner.invoke("edit", {
            "path": source, "old": "price * discount_percent / 100",
            "new": "price * (1 - discount_percent / 100)", "expected_version": context["version"]}))
        if "error" in edit:
            raise RuntimeError(edit["error"])
        runner.invoke("recall", {"path": source})
        after = json.loads(runner.invoke("run_tests", {}))
        status = "demo_tests_passed" if after.get("passed") else "demo_failed"
        ledger.finish(status, modified_files=sorted(workspace.modified))
        show({"before_passed": before["passed"], "after_passed": after.get("passed"),
              "receipt": receipt(ledger.data), "ledger": str(ledger.path)})
        return 0 if after.get("passed") else 1
    except Exception as error:
        ledger.finish("demo_error", error=str(error))
        raise


def main(argv=None):
    load_env()
    effective = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(effective or ["chat"])
    try:
        if args.command == "chat":
            from .terminal import Terminal
            if args.token_budget < 1000:
                raise ValueError("Budget must be at least 1000")
            if args.demo:
                fixtures = Path(__file__).resolve().parent.parent / "examples" / f"{args.demo}_bug"
                target = run_path("interactive-" + args.demo) / "repo"
                shutil.copytree(fixtures, target, ignore=shutil.ignore_patterns("__pycache__"))
                args.repo = target
                args.test_command = shlex.join([sys.executable, "-m", "unittest", "discover", "-s", "."]) if args.demo == "python" else "node --test"
            use_tui = want_tui(args)
            initial = []
            terminal = Terminal(args.repo, args.model, args.test_command, args.token_budget,
                                write=initial.append if use_tui else print,
                                auto_commit=args.auto_commit, resume=bool(args.resume),
                                architect_model=args.architect_model,
                                stream=not args.no_stream)
            if use_tui:
                from .tui.app import TuiApp
                return TuiApp(terminal, initial=initial).run()
            return terminal.run(tasks=args.exec_tasks)
        if args.command == "evaluate":
            from .evaluation import evaluate_fixtures
            if not args.model:
                raise ValueError("Set MISER_MODEL or pass --model")
            languages = (args.demo,) if args.demo else (args.language or ("python", "javascript"))
            directory = args.out or run_path("golden" if args.demo else "evaluation")
            client = ModelClient(args.model, on_notice=lambda text: print(text, file=sys.stderr))
            report = evaluate_fixtures(directory, client, args.model, args.repeats, languages,
                                       token_budget=args.token_budget, max_steps=args.max_steps,
                                       golden=bool(args.demo))
            show({"summary": report["summary"], "report": str(directory / "report.json")})
            solved_all = report["summary"]["solved"] == report["summary"]["tasks"]
            golden_ok = (not args.demo or report["summary"].get("golden_tasks_passed", 0)
                         == report["summary"]["tasks"])
            return 0 if solved_all and golden_ok and not report.get("stopped_early") else 1
        if args.command == "smoke":
            if not args.model:
                raise ValueError("Set MISER_MODEL or pass --model (configure its provider in Bifrost first)")
            directory = args.out or run_path("smoke-" + args.language)
            fixtures = Path(__file__).resolve().parent.parent / "examples" / f"{args.language}_bug"
            directory.mkdir(parents=True, exist_ok=False)
            target = directory / "repo"
            shutil.copytree(fixtures, target, ignore=shutil.ignore_patterns("__pycache__"))
            command = shlex.join([sys.executable, "-m", "unittest", "discover", "-s", "."]) if args.language == "python" else "node --test"
            return main(["run", str(target),
                         "Fix the percentage discount calculation. Preserve the existing tests and public API.",
                         "--test-command", command, "--model", args.model,
                         "--token-budget", "12000", "--max-steps", "8",
                         "--out", str(directory / "result")])
        if args.command == "doctor":
            show({"python": sys.version.split()[0], "node_available": bool(shutil.which("node")),
                  "bifrost_url": os.getenv("BIFROST_URL", "http://localhost:8080/openai"),
                  "model_configured": bool(os.getenv("MISER_MODEL")),
                  "gateway_auth_configured": bool(os.getenv("BIFROST_API_KEY") or os.getenv("BIFROST_VIRTUAL_KEY")),
                  "tavily_key_configured": bool(os.getenv("TAVILY_API_KEY")),
                  "note": "Configuration checks only; no network request or secret values."})
            return 0
        if args.command == "inspect":
            workspace = Workspace(args.repo)
            if args.map:
                show(workspace.repo_map(args.query or ""))
            elif args.file:
                show(workspace.zoom(args.file, args.level, args.start, args.end, args.symbol))
            elif args.query:
                show(workspace.search(args.query))
            else:
                show(workspace.list_files())
            return 0
        if args.command == "receipt":
            show(receipt(json.loads(args.ledger.read_text())))
            return 0
        if args.command == "demo":
            return offline_demo(args.language, args.out or run_path("demo-" + args.language))
        if args.command == "verify":
            directory = args.out or run_path("verify")
            directory.mkdir(parents=True, exist_ok=False)
            ledger = Ledger(directory / "ledger.json", mode="live-evidence-discovery")
            try:
                card = EvidenceSearch(ledger).verify_claim(args.claim, args.version, args.domain)
                if args.judge_model:
                    from .review import review_evidence
                    card = review_evidence(card, ModelClient(args.judge_model), ledger)
                write_json(directory / "evidence.json", card)
                ledger.finish("evidence_reviewed" if args.judge_model else "evidence_candidates", evidence_file="evidence.json")
                show(card)
                return 0
            except Exception as error:
                ledger.finish("error", error=str(error))
                raise
        if args.command == "run":
            if not args.model:
                raise ValueError("Set MISER_MODEL or pass --model (configure its provider in Bifrost first)")
            command = shlex.split(args.test_command)
            workspace = Workspace(args.repo)
            directory = args.out or run_path("agent")
            directory.mkdir(parents=True, exist_ok=False)
            ledger = Ledger(directory / "ledger.json", mode="live-agent", model=args.model,
                            repo=str(workspace.root), task=args.task, test_command=command,
                            token_budget=args.token_budget, max_steps=args.max_steps,
                            history_turns=4, fallback_models=args.fallback_models,
                            architect_model=args.architect_model,
                            cache_policy="Disable gateway caching for fair cold-run comparisons")
            runner = ToolRunner(workspace, ledger, command, test_timeout=args.test_timeout)
            client = ModelClient(args.model, fallbacks=args.fallback_models,
                                 on_notice=lambda text: print(text, file=sys.stderr))
            architect = ModelClient(args.architect_model, fallbacks=args.fallback_models,
                                    on_notice=lambda text: print(text, file=sys.stderr)) \
                if args.architect_model else None
            status = run_agent(args.task, client, runner, ledger,
                               args.token_budget, args.max_steps, progress=print,
                               architect_client=architect)
            show({"receipt": receipt(ledger.data), "ledger": str(ledger.path)})
            return 0 if status == "tests_passed" else 1
    except (ValueError, OSError, RuntimeError, KeyError, IndexError, TypeError) as error:
        print(f"MISER: {error}", file=sys.stderr)
        return 2
    return 0
