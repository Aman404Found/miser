"""Interactive coding terminal built on the measured agent loop.

Presentation lives in ``miser.ui``; this module owns session state, command
dispatch, the approval flow, and the wiring between the agent's honest events
and the renderer. Nothing here fabricates progress, usage, or edits.
"""

import difflib
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .agent import run_agent
from .client import ModelClient, parse_models
from .intent import classify_intent
from .ledger import Ledger, receipt
from .tools import ToolRunner
from .ui import render, theme
from .ui.prompt import InputSession, read_multiline
from .ui.spinner import WorkingIndicator
from .workspace import Workspace

clean = theme.clean

COMMANDS = ["/help", "/status", "/usage", "/model", "/architect", "/test", "/budget",
            "/map", "/diff", "/confirm", "/autocommit", "/undo", "/run", "/clear",
            "/history", "/receipt", "/exit", "/quit"]


def help_text():
    g = theme.symbols()
    groups = [
        ("task & testing", [
            ("/test [COMMAND]", "set or show the acceptance command"),
            ("/run", "run acceptance tests now (no model call)"),
            ("/diff [git|full]", "review the last patch, session changes, or git diff"),
            ("/undo", "revert files changed in this session"),
            ("/confirm [on|off]", "prompt before each edit"),
            ("/autocommit [on|off]", "commit passing changes to git"),
        ]),
        ("model & context", [
            ("/model [NAME[,FALLBACK]]", "set the editor model and fallback chain"),
            ("/architect [NAME|off]", "plan with a reasoning model before editing"),
            ("/budget [TOKENS]", "per-task approximate token budget"),
            ("/map [QUERY]", "task-ranked paths and symbols (no model call)"),
            ("/usage", "session counters and provider tokens"),
            ("/receipt [full]", "last task receipt; `full` prints raw JSON"),
        ]),
        ("session", [
            ("/status", "workspace, gateway, model, budget, and approvals"),
            ("/history", "completed tasks with status and spend"),
            ("/clear", "clear the screen (Ctrl+L does the same)"),
            ("/exit, /quit", "leave MISER (Ctrl+D also exits)"),
        ]),
    ]
    lines = [theme.bold("MISER commands"), ""]
    for title, rows in groups:
        lines.append(theme.dim(title))
        for command, description in rows:
            lines.append(f"  {theme.cyan(command.ljust(26))} {description}")
        lines.append("")
    lines.append(theme.dim("Input"))
    lines.append(f"  Tab completes commands and paths · Up/Down recalls history · Ctrl+R searches it")
    lines.append(f"  End a line with {theme.cyan(chr(92))} or paste a {theme.cyan(chr(34) * 3)} block for multi-line input")
    lines.append(f"  Ctrl+C interrupts a running task · Type a task naturally, or ask a question")
    lines.append("")
    lines.append(theme.dim(f"{g.info} Anything that is not a command is classified before tools run: "
                           "greetings and questions never edit files."))
    return "\n".join(lines)


class Terminal:
    def __init__(self, repo, model=None, test_command=None, budget=24000,
                 output_dir=None, read=input, write=print, client_factory=ModelClient,
                 auto_commit=False, resume=False, architect_model=None, fallbacks=None,
                 stream=True):
        self.workspace = Workspace(repo)
        self.repo = self.workspace.root
        self.model = model or os.getenv("MISER_MODEL")
        self.fallbacks = [item for item in parse_models(
            fallbacks if fallbacks is not None else os.getenv("MISER_FALLBACK_MODELS", ""))
            if item != self.model]
        self.architect_model = architect_model or os.getenv("MISER_ARCHITECT_MODEL")
        self.command = shlex.split(test_command) if isinstance(test_command, str) else list(test_command or [])
        self.budget = budget
        self.output_dir = Path(output_dir or "runs")
        self.read, self.write, self.client_factory = read, write, client_factory
        self.last_ledger = None
        self.last_bill = None
        self.last_diff = ""
        # The full-screen UI narrows output to its transcript width; line mode
        # leaves this unset and keeps using the real terminal width.
        self.width_override = None
        self.confirm_edits = False
        self.auto_commit = auto_commit
        self.stream_enabled = stream
        # Session accounting separates messages, tasks, requests, tools, and tokens.
        self.session_user_messages = 0
        self.session_tasks_count = 0
        self.session_model_requests = 0
        self.session_tool_calls = 0
        self.session_provider_tokens = 0
        self.session_input_tokens = 0
        self.session_output_tokens = 0
        self.session_unknown_usage = 0
        self.last_context_estimate = 0
        self.gateway_state = "not checked"
        self.current_task = None
        self.restored_receipt = None
        self.restored_receipt_path = None
        self.task_history = []
        self.conversation_history = []
        # Full-screen UI hooks: the engine keeps working unchanged, but lets the
        # TUI observe events and request cancellation between model/tool steps.
        self.cancel_event = threading.Event()
        self.activity_listener = None
        self.input = None
        self.glyphs = theme.symbols()
        self.spinner = WorkingIndicator(enabled=(write is print and theme.isatty(sys.stdout)
                                                 and theme.color_enabled()),
                                        glyphs=self.glyphs)
        if resume:
            self.resume_session()

    # -- session state -----------------------------------------------------

    def width(self):
        if self.width_override:
            return max(20, int(self.width_override))
        return theme.term_width()

    def say(self, text=""):
        # Never let the animated line interleave with printed output.
        self.spinner.stop()
        try:
            self.write(str(text))
        except BrokenPipeError:
            raise EOFError

    def resume_session(self):
        """Restore task history and session metrics from existing session folders."""
        if not self.output_dir.is_dir():
            return
        session_dirs = sorted(self.output_dir.glob("session-*"), key=lambda p: p.stat().st_mtime)
        resumed_count = 0
        for directory in session_dirs:
            ledger_file = directory / "ledger.json"
            if not ledger_file.is_file():
                continue
            try:
                data = json.loads(ledger_file.read_text(encoding="utf-8"))
                saved_repo = data.get("metadata", {}).get("repo")
                if not saved_repo or Path(saved_repo).resolve() != self.repo:
                    continue
                bill = receipt(data)
                self.session_provider_tokens += bill.get("total_tokens", 0)
                self.session_input_tokens += bill.get("input_tokens", 0)
                self.session_output_tokens += bill.get("output_tokens", 0)
                self.session_model_requests += bill.get("model_calls", 0)
                self.session_tool_calls += bill.get("tool_calls", 0)
                if not bill.get("usage_complete", True):
                    self.session_unknown_usage += 1
                self.session_tasks_count += 1
                task_name = data.get("metadata", {}).get("task", directory.name)
                self.task_history.append({"task": task_name, "status": data.get("status", "unknown"),
                                          "tokens": bill.get("total_tokens", 0)})
                resumed_count += 1
                self.restored_receipt = bill
                self.restored_receipt_path = ledger_file
                self.last_context_estimate = bill.get("tool_context_tokens_estimate", 0)
                patch_file = directory / "patch.diff"
                if patch_file.is_file():
                    self.last_diff = patch_file.read_text(encoding="utf-8")
            except (OSError, ValueError, KeyError):
                continue
        if resumed_count:
            self.say(render.notice(f"Resumed {resumed_count} prior session task(s) from {self.output_dir}",
                                   self.width(), self.glyphs))

    def get_git_branch(self):
        if not (self.repo / ".git").is_dir() and not (self.repo.parent / ".git").is_dir():
            return "none"
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo, text=True, stderr=subprocess.DEVNULL
            ).strip()
            dirty = subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=self.repo, text=True, stderr=subprocess.DEVNULL
            ).strip()
            return f"{branch} ({'dirty' if dirty else 'clean'})"
        except (OSError, subprocess.SubprocessError):
            return "git unavailable"

    def auto_detect_test_command(self):
        """Detect a conventional acceptance command in the workspace."""
        if (self.repo / "tests").is_dir() or any(self.repo.glob("test_*.py")):
            tests_dir = "tests" if (self.repo / "tests").is_dir() else "."
            return [sys.executable, "-m", "unittest", "discover", "-s", tests_dir]
        if (self.repo / "package.json").is_file():
            try:
                package = json.loads((self.repo / "package.json").read_text(encoding="utf-8"))
                if package.get("scripts", {}).get("test"):
                    return ["npm", "test"]
            except (OSError, ValueError):
                pass
        return []

    def make_client(self, model=None):
        """Editor or architect client carrying the configured fallback chain."""
        target = model or self.model
        if self.client_factory is ModelClient:
            return ModelClient(target, fallbacks=self.fallbacks, on_notice=self.say)
        return self.client_factory(target)

    # -- banner and status -------------------------------------------------

    def banner_lines(self):
        from . import __version__
        width = self.width()
        return [
            "",
            render.header(__version__, self.model, self.repo, width, self.glyphs),
            render.status_line(self.model, self.repo, self.budget, bool(self.command),
                               self.confirm_edits, width, self.glyphs),
        ]

    def usage_snapshot(self):
        return {
            "user_messages": self.session_user_messages,
            "tasks": self.session_tasks_count,
            "model_requests": self.session_model_requests,
            "tool_calls": self.session_tool_calls,
            "provider_tokens": self.session_provider_tokens,
            "input_tokens": self.session_input_tokens,
            "output_tokens": self.session_output_tokens,
            "unknown_usage": self.session_unknown_usage,
            "context_estimate": self.last_context_estimate or None,
            "last_receipt": str(self.last_ledger.path) if self.last_ledger else None,
        }

    def tokens_text(self):
        if self.session_model_requests == 0:
            return "no provider tokens yet"
        text = (f"{self.session_provider_tokens:,} provider tokens "
                f"({self.session_input_tokens:,} in / {self.session_output_tokens:,} out)")
        if self.session_unknown_usage:
            text += f" · {self.session_unknown_usage} request(s) unmetered"
        return text

    def status(self, verbose=False):
        modified = sorted(self.workspace.modified)
        modified_text = f"{len(modified)} files: {', '.join(modified)}" if modified else "none"
        tests = shlex.join(self.command) if self.command else "none (use /test COMMAND)"
        last_task = self.task_history[-1]["task"] if self.task_history else None
        task_label = "Current task" if self.current_task else "Last task"
        items = [
            ("Workspace", theme.shorten_home(str(self.repo))),
            (task_label, theme.clip(self.current_task or last_task or "none yet", 60)),
            ("Branch", self.get_git_branch()),
            ("Current model:", self.model or "none configured (use /model NAME)"),
            ("Fallbacks", ", ".join(self.fallbacks) or "none configured"),
            ("Architect", self.architect_model or "off (single-model mode)"),
            ("Gateway", f"{os.getenv('BIFROST_URL', 'http://localhost:8080/openai')} · {self.gateway_state}"),
            ("Current tests:", tests),
            ("Current budget:", f"{self.budget:,} tokens per task"),
            ("Approvals", "ON (prompts before edits)" if self.confirm_edits else "OFF (guarded edits apply directly)"),
            ("Modified", modified_text),
            ("Session", f"{self.session_tasks_count} tasks · {self.session_model_requests} model requests · "
                        f"{self.tokens_text()}"),
        ]
        self.say(render.panel("status", items, self.width(), self.glyphs))

    def usage(self):
        self.say(render.session_usage_panel(self.usage_snapshot(), self.width(), self.glyphs))

    # -- approval and manual actions ---------------------------------------

    def prompt_edit_approval(self, path: str, diff: str) -> bool:
        """Review one proposed edit before it is written."""
        self.spinner.stop()
        width = self.width()
        self.say("")
        self.say(render.approval_header(path, diff, width))
        self.say(render.render_diff(diff, width, max_lines=60, glyphs=self.glyphs))
        while True:
            try:
                choice = self.read(f"{theme.cyan(self.glyphs.prompt)} apply this edit? "
                                   "[y]es / [n]o / [a]ll / [d]iff ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                self.say(render.notice("Edit rejected.", width, self.glyphs))
                return False
            if choice in ("y", "yes", ""):
                return True
            if choice in ("a", "all"):
                self.confirm_edits = False
                self.say(render.notice("Approvals off for the rest of this session.", width, self.glyphs))
                return True
            if choice in ("d", "diff"):
                self.say(render.render_diff(diff, width, max_lines=None, glyphs=self.glyphs))
                continue
            self.say(render.notice("Edit rejected; nothing was written.", width, self.glyphs))
            return False

    def prompt_command_approval(self, command: str):
        """Approve one allowlisted command. Returns True, False, or "always"."""
        self.spinner.stop()
        width = self.width()
        self.say("")
        self.say(render.notice(f"The agent asks to run: {command}", width, self.glyphs))
        self.say(theme.dim("  It runs as a literal argv array in the repository, without a shell."))
        while True:
            try:
                choice = self.read(f"{theme.cyan(self.glyphs.prompt)} run this command? "
                                   "[y]es / [n]o / [a]lways " ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                self.say(render.notice("Command rejected.", width, self.glyphs))
                return False
            if choice in ("y", "yes", ""):
                return True
            if choice in ("a", "always"):
                self.say(render.notice("This exact command is approved for the rest of the session.",
                                       width, self.glyphs))
                return "always"
            self.say(render.notice("Command rejected; nothing was run.", width, self.glyphs))
            return False

    def undo(self):
        if not self.workspace.modified:
            self.say(render.notice("No modified files to revert in this session.", self.width(), self.glyphs))
            return
        reverted = []
        conflicts = []
        for path in list(self.workspace.modified):
            if path in self.workspace.originals:
                original = self.workspace.originals[path]
                current = None if original is None and not self.workspace.path(path).exists() \
                    else self.workspace.text(path)
                if current != self.workspace.last_written.get(path):
                    conflicts.append(path)
                    continue
                if original is None:
                    # Created by write_file this session: reverting means removing it.
                    self.workspace.path(path).unlink()
                else:
                    self.workspace.path(path).write_text(original, encoding="utf-8")
                reverted.append(path)
                self.workspace.modified.discard(path)
                self.workspace.originals.pop(path, None)
                self.workspace.last_written.pop(path, None)
                self.workspace.snapshots.pop(path, None)
        self.workspace.reads.clear()
        self.last_diff = ""
        if conflicts:
            self.say(render.warning("Undo skipped externally changed files: " + ", ".join(sorted(conflicts)),
                                    self.width(), self.glyphs))
        self.say(render.notice(f"Reverted {len(reverted)} file(s): {', '.join(reverted)}",
                               self.width(), self.glyphs))

    def run_tests_manually(self):
        if not self.command:
            raise ValueError("No test command configured. Set one with /test COMMAND")
        self.spinner.start("running acceptance tests")
        dummy_ledger = Ledger(self.output_dir / "manual-test.json", mode="manual-test")
        runner = ToolRunner(self.workspace, dummy_ledger, self.command)
        try:
            result = runner.run_tests()
        finally:
            self.spinner.stop()
        self.say(render.test_result(result, self.glyphs))
        output = (result.get("output") or "").strip()
        if output:
            for line in output.splitlines()[:30]:
                self.say(theme.dim("  " + line))
        elif result.get("passed"):
            self.say(render.notice("No output; the command exited cleanly.", self.width(), self.glyphs))

    def get_git_diff(self):
        try:
            result = subprocess.run(["git", "diff"], cwd=self.repo, capture_output=True,
                                    text=True, timeout=10)
            if result.returncode == 0:
                return result.stdout
        except (OSError, subprocess.SubprocessError):
            pass
        return ""

    # -- commands ----------------------------------------------------------

    def slash(self, line):
        command, _, value = line.partition(" ")
        value = value.strip()
        if command in ("/exit", "/quit"):
            return False
        if command == "/help":
            self.say(help_text())
        elif command == "/status":
            self.status(verbose=value.lower() in ("full", "verbose"))
        elif command == "/usage":
            self.usage()
        elif command == "/model":
            if not value:
                self.say(f"Current model: {self.model or 'none configured (use /model NAME)'}")
                if self.fallbacks:
                    self.say(f"Fallbacks: {', '.join(self.fallbacks)}")
            else:
                models = parse_models(value)
                if not models:
                    raise ValueError("Model name must be nonempty")
                self.model = models[0]
                self.fallbacks = [item for item in models[1:] if item != self.model]
                self.say(f"Model: {self.model}")
                if self.fallbacks:
                    self.say(f"Fallbacks: {', '.join(self.fallbacks)}")
        elif command == "/architect":
            if not value:
                self.say(f"Architect: {self.architect_model or 'off (single-model mode)'}")
            elif value.lower() in ("off", "none", "false", "0"):
                self.architect_model = None
                self.say("Architect: off (single-model mode)")
            else:
                self.architect_model = value
                self.say(f"Architect: {value} (plans before the editor patches)")
        elif command == "/test":
            if not value:
                self.say(f"Current tests: {shlex.join(self.command) if self.command else 'none (use /test COMMAND)'}")
            else:
                argv = shlex.split(value)
                self.command = argv
                self.say(f"Acceptance: {shlex.join(argv)}")
        elif command == "/budget":
            if not value:
                self.say(f"Current budget: {self.budget:,} tokens per task")
            else:
                budget = int(value)
                if budget < 1000:
                    raise ValueError("Budget must be at least 1000")
                self.budget = budget
                self.say(f"Per-task budget: {budget:,}")
        elif command == "/confirm":
            if value.lower() in ("on", "true", "1", "yes"):
                self.confirm_edits = True
            elif value.lower() in ("off", "false", "0", "no"):
                self.confirm_edits = False
            else:
                self.confirm_edits = not self.confirm_edits
            self.say(f"Edit approval: {'ON' if self.confirm_edits else 'OFF'}")
        elif command == "/undo":
            self.undo()
        elif command == "/run":
            self.run_tests_manually()
        elif command == "/clear":
            if os.name == "nt":
                os.system("cls")
            else:
                self.say("\033[2J\033[H")
                for line in self.banner_lines():
                    self.say(line)
        elif command == "/map":
            query = value
            as_json = query.endswith("--json")
            if as_json:
                query = query[: -len("--json")].strip()
            result = self.workspace.repo_map(query)
            if as_json:
                self.say(json.dumps(result, indent=2))
            else:
                self.say(render.repo_map(result, self.width(), self.glyphs))
        elif command == "/diff":
            mode = value.lower()
            if mode == "git":
                diff = self.get_git_diff()
                self.say(render.render_diff(diff, self.width(), glyphs=self.glyphs) if diff
                         else render.notice("No git changes in the working tree.", self.width(), self.glyphs))
                return True
            diff = self.last_diff or self.get_git_diff()
            if not diff:
                self.say(render.notice("No patch from the last task or git working tree.",
                                       self.width(), self.glyphs))
            else:
                limit = None if mode in ("full", "all") else 400
                self.say(render.render_diff(diff, self.width(), max_lines=limit, glyphs=self.glyphs))
        elif command == "/receipt":
            bill_data = self.last_ledger.data if self.last_ledger else None
            receipt_path = self.last_ledger.path if self.last_ledger else self.restored_receipt_path
            if bill_data is None and self.restored_receipt is not None:
                bill_data = {"status": self.restored_receipt.get("status", "unknown"),
                             "events": [], "restored": self.restored_receipt}
            if bill_data is None:
                self.say(render.notice("No task has run yet.", self.width(), self.glyphs))
            else:
                bill = self.restored_receipt if self.restored_receipt is not None and self.last_ledger is None \
                    else receipt(bill_data)
                if value.lower() in ("full", "json", "--json"):
                    self.say(json.dumps(bill, indent=2))
                else:
                    items = [
                        ("Status", bill["status"]),
                        ("Provider usage", render.usage_phrase(bill)),
                        ("Test runs", str(bill["test_runs"])),
                        ("Compactions", str(bill["compactions"])),
                        ("Model fallbacks", str(bill["model_fallbacks"])),
                        ("Context (local)", f"~{bill.get('tool_context_tokens_estimate', 0):,} tokens (estimate, not billing)"),
                        ("Ledger", str(receipt_path)),
                    ]
                    self.say(render.panel("receipt", items, self.width(), self.glyphs))
                    self.say(theme.dim("  `receipt full` prints raw JSON"))
        elif command == "/history":
            self.show_history()
        elif command == "/autocommit":
            if value.lower() in ("on", "true", "1", "yes"):
                self.auto_commit = True
            elif value.lower() in ("off", "false", "0", "no"):
                self.auto_commit = False
            else:
                self.auto_commit = not self.auto_commit
            self.say(f"Git auto-commit: {'ON' if self.auto_commit else 'OFF'}")
        else:
            raise ValueError("Unknown command. Type /help")
        return True

    def show_history(self):
        if not self.task_history:
            self.say("No tasks have been executed in this session.")
            return
        self.say("")
        self.say(theme.bold(f"session tasks ({len(self.task_history)})"))
        self.say(render.history_lines(self.task_history, self.glyphs))
        self.say("")
        self.say(theme.dim(f"  {self.session_tasks_count} tasks · {self.session_model_requests} model requests"
                           f" · {self.session_tool_calls} tool calls · {self.tokens_text()}"))

    def auto_commit_changes(self, task_name):
        if not (self.repo / ".git").is_dir() and not (self.repo.parent / ".git").is_dir():
            return
        try:
            modified = list(self.workspace.modified)
            if not modified:
                return
            subprocess.run(["git", "add"] + modified, cwd=self.repo, check=True, capture_output=True)
            message = f"miser: {task_name[:64]}"
            result = subprocess.run(["git", "commit", "-m", message], cwd=self.repo,
                                    capture_output=True, text=True)
            if result.returncode == 0:
                self.say(render.notice(f"Committed: {message}", self.width(), self.glyphs))
            else:
                self.say(render.warning("Git commit failed; changes remain in the working tree.",
                                        self.width(), self.glyphs))
        except (OSError, subprocess.SubprocessError) as error:
            self.say(render.notice(f"Auto-commit skipped: {error}", self.width(), self.glyphs))

    # -- conversation ------------------------------------------------------

    def reply(self, text):
        self.say("")
        self.say(render.agent_label("", self.width(), self.glyphs))
        self.say(render.markdown_text(text, self.width() - 2, self.glyphs))

    def record_usage(self, response):
        """Attribute one completed request to the session, honestly."""
        self.session_model_requests += 1
        usage = response.get("usage") or {}
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        valid = all(isinstance(usage.get(key), int) and usage.get(key, 0) >= 0 for key in keys)
        if valid and usage["total_tokens"] >= usage["prompt_tokens"] + usage["completion_tokens"]:
            self.session_provider_tokens += usage["total_tokens"]
            self.session_input_tokens += usage["prompt_tokens"]
            self.session_output_tokens += usage["completion_tokens"]
        else:
            self.session_unknown_usage += 1

    def answer_question(self, text):
        if not self.model:
            self.say(render.notice("Set a model with /model NAME to ask questions, or /help for commands.",
                                   self.width(), self.glyphs))
            return
        client = self.make_client(self.model)
        code_related = any(key in text.lower() for key in (
            "code", "function", "class", "file", "repo", "test", "tests",
            "symbol", "pricing", "discount", "bug", "implement", "how does",
            "what does", "where is", "explain", "module", "variable",
        ))
        entries = []
        if code_related:
            try:
                entries = self.workspace.repo_map(text).get("entries", [])[:10]
            except (OSError, ValueError):
                entries = []
        messages = [
            {"role": "system", "content": "You are MISER, a lightweight, focused coding agent. "
                                          "Answer questions directly and concisely. Do not claim to "
                                          "have modified files or run tests; this is an informational answer."}
        ]
        if self.conversation_history:
            messages.extend(self.conversation_history[-6:])
        # A compact outline costs far fewer tokens than pretty-printed JSON and still
        # gives the model the file/symbol vocabulary the question refers to.
        outline = ""
        for entry in entries:
            names = []
            for item in entry.get("symbols") or []:
                name = item.get("name", "")
                if name and name not in names:
                    names.append(name)
            line = f"{entry.get('path', '')}: {', '.join(names[:6])}"
            if len(outline) + len(line) > 1200:
                break
            outline += line + "\n"
        content = text
        if outline:
            content = ("Repository outline (paths and defined symbols, not file contents):\n"
                       f"{outline}\nQuestion: {text}")
        messages.append({"role": "user", "content": content})

        width = self.width()
        self.say("")
        self.say(render.agent_label(self.model, width, self.glyphs))
        parts = []
        stream = {"md": None}

        def on_token(chunk):
            if stream["md"] is None:
                self.spinner.stop()
                stream["md"] = render.MarkdownStream(self.say, width - 2, self.glyphs)
            parts.append(chunk)
            stream["md"].feed(chunk)

        self.spinner.start("thinking")
        try:
            if self.stream_enabled and getattr(client, "supports_streaming", False):
                response = client.complete(messages, tools=None, max_tokens=1000,
                                           stream=True, on_token=on_token)
            else:
                response = client.complete(messages, tools=None, max_tokens=1000)
        except Exception as error:
            self.spinner.stop()
            if stream["md"] is not None:
                stream["md"].finish()
            self.gateway_state = "unreachable" if "reach" in str(error).lower() else "error"
            self.say("")
            self.say(render.error_block("could not reach the model", str(error),
                                        render.error_hint(error), width, self.glyphs))
            return
        self.spinner.stop()
        if stream["md"] is not None:
            stream["md"].finish()
            answer = "".join(parts)
        else:
            answer = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if answer:
                self.say(render.markdown_text(answer, width - 2, self.glyphs))
        self.gateway_state = "reachable"
        self.record_usage(response)
        self.conversation_history.extend([{"role": "user", "content": text},
                                          {"role": "assistant", "content": answer}])
        self.conversation_history = self.conversation_history[-12:]

    def handle_input(self, line):
        line = line.strip()
        if not line:
            return True
        if line.startswith("/"):
            return self.slash(line)
        self.session_user_messages += 1
        intent = classify_intent(line)
        if intent.kind in ("greeting", "acknowledgement", "help"):
            self.reply(intent.response or "")
            return True
        if intent.kind == "ambiguous":
            self.say(render.warning(intent.clarification or "Please clarify the request.",
                                    self.width(), self.glyphs))
            self.say(render.notice("Try a concrete task, ask a question, or type /help.",
                                   self.width(), self.glyphs))
            return True
        if intent.kind == "question":
            self.answer_question(line)
            return True
        self.task(line)
        return True

    # -- coding tasks ------------------------------------------------------

    def _event_text(self, event):
        kind = event.get("type")
        if kind == "step":
            return f"step {event.get('step')}/{event.get('max_steps')} · {event.get('tokens', 0):,} tokens"
        if kind == "model_start":
            return "thinking"
        if kind == "tool" and event.get("state") == "start":
            return render.tool_running(event.get("name", ""), event.get("args") or {})
        return None

    def _activity(self, event):
        listener = self.activity_listener
        if listener is not None:
            try:
                listener(event)
            except Exception:
                pass
        self.handle_activity(event)

    def handle_activity(self, event):
        """Render one honest agent event; no invented progress."""
        kind = event.get("type")
        if kind in ("step", "model_start"):
            self.spinner.start(self._event_text(event) or "thinking")
            return
        if kind == "tool":
            if event.get("state") == "start":
                self.spinner.start(self._event_text(event) or "working")
            else:
                self.spinner.stop()
                self.say(render.tool_result(event.get("name", ""), event, self.glyphs))
            return
        if kind == "tests":
            self.spinner.stop()
            if event.get("baseline"):
                state = "passing" if event.get("passed") else f"failing (exit {event.get('exit_code')})"
                self.say(render.notice(f"baseline acceptance tests: {state}",
                                       self.width(), self.glyphs))
                return
            self.say(render.test_result(event, self.glyphs))
            output = (event.get("output") or "").strip()
            if not event.get("passed") and output:
                for line in output.splitlines()[:8]:
                    self.say(theme.dim("    " + line))
            return
        if kind == "compaction":
            self.spinner.stop()
            self.say(render.notice(
                f"Context compacted: {event.get('dropped_turns', 0)} older turn(s), "
                f"prompt ~{event.get('before', 0):,} → ~{event.get('after', 0):,} tokens (estimate)",
                self.width(), self.glyphs))
            return
        if kind == "fallback":
            self.spinner.stop()
            self.say(render.warning(
                f"{event.get('from_model')} returned HTTP {event.get('status')}; "
                f"using {event.get('to_model')}", self.width(), self.glyphs))
            return
        if kind == "architect":
            if event.get("state") == "start":
                self.spinner.start("architect planning")
            else:
                self.spinner.stop()
                self.say(render.notice(
                    "Architect plan ready" if event.get("planned") else "Architect unavailable; continuing without a plan",
                    self.width(), self.glyphs))
            return

    def compute_diff(self, workspace=None):
        workspace = workspace or self.workspace
        chunks = []
        for path, original in workspace.originals.items():
            current = workspace.text(path)
            created = original is None
            chunks.extend(difflib.unified_diff(
                "" if created else original.splitlines(keepends=True),
                current.splitlines(keepends=True),
                fromfile="/dev/null" if created else "a/" + path, tofile="b/" + path))
        return "".join(chunks)

    def record_task(self, bill, text, started):
        self.last_bill = bill
        self.session_model_requests += bill.get("model_calls", 0)
        self.session_tool_calls += bill.get("tool_calls", 0)
        self.session_provider_tokens += bill.get("total_tokens", 0)
        self.session_input_tokens += bill.get("input_tokens", 0)
        self.session_output_tokens += bill.get("output_tokens", 0)
        if not bill.get("usage_complete", True):
            self.session_unknown_usage += max(1, bill.get("failed_model_requests", 0))
        self.session_tasks_count += 1
        self.last_context_estimate = bill.get("tool_context_tokens_estimate", 0)
        self.task_history.append({"task": text, "status": bill.get("status", "unknown"),
                                  "tokens": bill.get("total_tokens", 0),
                                  "elapsed": round(time.monotonic() - started, 2)})

    def task(self, text):
        self.cancel_event.clear()
        intent = classify_intent(text)
        if intent.kind != "coding":
            if intent.response:
                self.reply(intent.response)
            elif intent.clarification:
                self.say(render.warning(intent.clarification, self.width(), self.glyphs))
            elif intent.kind == "question":
                self.answer_question(text)
            return
        if not self.model:
            raise ValueError("Set /model NAME before running a task")
        if not self.command:
            detected = self.auto_detect_test_command()
            if detected:
                self.command = detected
                self.say(render.notice(f"Auto-detected acceptance command: {shlex.join(self.command)}",
                                       self.width(), self.glyphs))
            else:
                raise ValueError("Set /test COMMAND before running a task")

        directory = self.output_dir / ("session-" + uuid.uuid4().hex[:12])
        directory.mkdir(parents=True, exist_ok=False)
        ledger = Ledger(directory / "ledger.json", mode="interactive", model=self.model,
                        repo=str(self.repo), task=text, test_command=self.command,
                        token_budget=self.budget, max_steps=16)
        self.last_ledger, self.last_diff = ledger, ""
        self.current_task = text
        approval = self.prompt_edit_approval if self.confirm_edits else None
        task_workspace = Workspace(self.repo)
        runner = ToolRunner(task_workspace, ledger, self.command, approval_callback=approval,
                            command_approval=self.prompt_command_approval)
        started = time.monotonic()
        width = self.width()
        state = {"stream": None, "parts": []}

        def on_token(chunk):
            if state["stream"] is None:
                self.spinner.stop()
                self.say(render.agent_label(self.model, width, self.glyphs))
                state["stream"] = render.MarkdownStream(self.say, width - 2, self.glyphs)
            state["parts"].append(chunk)
            state["stream"].feed(chunk)

        error = None
        try:
            architect = self.make_client(self.architect_model) if self.architect_model else None
            run_agent(text, self.make_client(self.model), runner, ledger,
                      token_budget=self.budget, progress=None,
                      on_token=on_token if self.stream_enabled else None,
                      activity=self._activity, architect_client=architect,
                      cancelled=self.cancel_event.is_set)
        except KeyboardInterrupt:
            self.spinner.stop()
            self.say("")
            self.say(render.warning("Task interrupted. Edits and receipt retained.",
                                    width, self.glyphs))
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            error = exc
        finally:
            self.spinner.stop()
            if state["stream"] is not None:
                state["stream"].finish()
                self.say("")
            self.last_diff = self.compute_diff(task_workspace)
            for path in task_workspace.modified:
                self.workspace.originals.setdefault(path, task_workspace.originals[path])
                self.workspace.last_written[path] = task_workspace.last_written[path]
                self.workspace.modified.add(path)
            try:
                (directory / "patch.diff").write_text(self.last_diff, encoding="utf-8")
            except OSError:
                pass
            bill = receipt(ledger.data)
            self.current_task = None
            self.record_task(bill, text, started)
            self.render_task_result(bill, time.monotonic() - started, directory, error)
        if error is not None:
            self.gateway_state = "error"
        elif self.last_ledger and receipt(ledger.data)["model_calls"]:
            self.gateway_state = "reachable"
        if self.auto_commit and ledger.data.get("status") == "tests_passed" and self.last_diff:
            self.auto_commit_changes(text)

    def render_task_result(self, bill, elapsed, directory, error=None):
        width = self.width()
        self.say("")
        if error is None:
            self.say(render.result_panel(bill, elapsed, width, glyphs=self.glyphs))
        else:
            # One block per failure: a panel plus an error block says the same thing twice.
            self.say(render.error_block("the task stopped early", str(error),
                                        render.error_hint(error), width, self.glyphs))
        if self.last_diff:
            self.say(render.render_diff(self.last_diff, width, max_lines=80, glyphs=self.glyphs))
        hints = [str(directory / "patch.diff") + " · /diff", "/receipt"]
        self.say(render.hint_line(hints, self.glyphs))

    # -- prompt loop -------------------------------------------------------

    def read_multiline_input(self, prompt=None):
        return read_multiline(self.read, prompt if prompt is not None else render.prompt(self.glyphs),
                              continuation=theme.dim("… "))

    def error_report(self, error):
        return render.error_block("error", str(error), render.error_hint(error),
                                  self.width(), self.glyphs)

    def run(self, tasks=None):
        self.input = InputSession(self.workspace, COMMANDS, read=self.read, write=self.write)
        for line in self.banner_lines():
            self.say(line)
        self.say("")
        self.say(render.notice("Describe a task, ask a question, or type /help. "
                               "Tasks edit the workspace and use API tokens.",
                               self.width(), self.glyphs))
        self.say("")
        pending = list(tasks or [])
        non_interactive = tasks is not None
        while True:
            try:
                if pending:
                    line = pending.pop(0)
                    self.say(render.user_block(line, self.width(), self.glyphs))
                elif non_interactive:
                    break
                else:
                    line = self.read_multiline_input(render.prompt(self.glyphs))
                if not self.handle_input(line):
                    break
            except EOFError:
                break
            except KeyboardInterrupt:
                self.say(render.notice("Use /exit or Ctrl+D to leave.", self.width(), self.glyphs))
            except BrokenPipeError:
                return 0
            except (ValueError, RuntimeError, OSError, KeyError, TypeError, IndexError) as error:
                self.say(self.error_report(error))
        self.spinner.stop()
        if self.input is not None:
            self.input.save_history()
        self.say(theme.dim("Session closed."))
        return 0
