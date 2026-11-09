"""Full-screen MISER application.

Owns the alternate screen, the raw input loop, the conversation transcript, and
the worker thread that runs the existing :class:`miser.terminal.Terminal` engine.
The engine still performs all agent, tool, ledger, and workspace work; this
module only routes its output into the rendered transcript and feeds keys back.
"""

import sys
import threading
import time
from pathlib import Path

from rich.style import Style
from rich.text import Text

from ..ui import render, theme
from . import screen
from .input import InputBuffer
from .keys import KeyReader
from .io import Screen, raw_mode

from ..terminal import COMMANDS


class TuiApp:
    def __init__(self, terminal, initial=None, screen_io=None, keys=None):
        self.terminal = terminal
        self.screen_io = screen_io or Screen()
        self.keys = keys or KeyReader()
        self.input = InputBuffer()
        self.commands = list(COMMANDS)
        self.transcript = []
        self.scroll = 0
        self.mode = "welcome"
        self.busy = False
        self.status = "idle"
        self.suggestions = []
        self.approval = None
        self.dirty = True
        self.running = True
        self.spinner_index = 0
        self.busy_started = 0.0
        self.elapsed = 0.0
        self._lock = threading.Lock()
        self._worker = None
        self._approval_event = None
        self._approval_result = False
        self._approval_diff = ""
        self._approval_is_command = False
        self._last_size = None
        self.glyphs = theme.symbols()
        self._load_history()

        terminal.spinner.enabled = False
        terminal.write = self.append_output
        terminal.cancel_event = threading.Event()
        terminal.activity_listener = self.on_activity
        terminal.prompt_edit_approval = self.request_approval
        terminal.prompt_command_approval = self.request_command_approval
        for text in initial or []:
            self.append_output(text)

    def _history_path(self):
        workspace = getattr(self.terminal, "workspace", None)
        root = getattr(workspace, "root", None) or getattr(self.terminal, "repo", None)
        return Path(root) / ".miser" / "history" if root else None

    def _load_history(self):
        path = self._history_path()
        if path is None or not path.is_file():
            return
        try:
            lines = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        except (OSError, UnicodeDecodeError):
            return
        self.input.history = lines[-self.input.max_history:]

    def _save_history(self):
        path = self._history_path()
        if path is None or not self.input.history:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(self.input.history[-self.input.max_history:]) + "\n",
                            encoding="utf-8")
        except OSError:
            pass

    # -- transcript --------------------------------------------------------

    def _max_width(self):
        width, _ = self.screen_io.size()
        return screen.content_width(width)

    def append_output(self, text=""):
        # Keep full lines here; the layout crops them to the content column, so
        # widening the terminal does not leave permanently truncated rows.
        value = str(text).rstrip("\n")
        with self._lock:
            if value == "":
                self.transcript.append(Text("", style=Style(bgcolor=screen.BG)))
            else:
                for raw in value.split("\n"):
                    entry = Text.from_ansi(raw, style=Style(bgcolor=screen.BG, color=screen.TEXT)) \
                        if raw else Text("", style=Style(bgcolor=screen.BG))
                    entry.no_wrap = True
                    self.transcript.append(entry)
            self.dirty = True

    # -- state for the layout ---------------------------------------------

    def ui_state(self):
        width, height = self.screen_io.size()
        if self.busy:
            spinner = self.glyphs.spinner[self.spinner_index % len(self.glyphs.spinner)]
        else:
            spinner = self.glyphs.info
        tests = ""
        if self.terminal.task_history:
            status = self.terminal.task_history[-1].get("status", "")
            if "tests_passed" in status:
                tests = "tests passed"
            elif "fail" in status or "incomplete" in status:
                tests = "tests not passing"
            elif "truncated" in status:
                tests = "output truncated"
            elif "interrupted" in status:
                tests = "interrupted"
        with self._lock:
            transcript = list(self.transcript)
        return screen.UIState(
            width=width,
            height=height,
            mode=self.mode,
            model=self.terminal.model or "",
            workspace=theme.shorten_home(str(self.terminal.repo)),
            budget=self.terminal.budget,
            tasks=self.terminal.session_tasks_count,
            requests=self.terminal.session_model_requests,
            tokens=(f"{self.terminal.session_provider_tokens:,} tok"
                    if self.terminal.session_model_requests else ""),
            tests=tests,
            approvals=self.terminal.confirm_edits,
            input_text=self.input.value(),
            cursor=self.input.cursor,
            transcript=transcript,
            scroll=self.scroll,
            busy=self.busy,
            status=self.status,
            spinner=spinner,
            elapsed=self.elapsed,
            suggestions=self.suggestions,
            approval=self.approval or "",
        )

    def draw(self):
        self.terminal.width_override = self._max_width()
        state = self.ui_state()
        self.screen_io.draw(screen.render(state))
        self.dirty = False
        self._last_size = (state.width, state.height)

    # -- interaction -------------------------------------------------------

    def on_activity(self, event):
        kind = event.get("type")
        if kind == "model_start" or kind == "step":
            self.status = "thinking"
        elif kind == "model_end":
            self.status = "thinking"
        elif kind == "tool":
            if event.get("state") == "start":
                self.status = render.tool_running(event.get("name", ""), event.get("args") or {})
            else:
                self.status = "working"
        elif kind == "tests":
            self.status = "tests passed" if event.get("passed") else "tests failed"
        elif kind == "compaction":
            self.status = "compacting context"
        elif kind == "fallback":
            self.status = "switching model"
        elif kind == "architect":
            self.status = "planning" if event.get("state") == "start" else "editing"
        elif kind == "stream_interrupted":
            self.status = "stream interrupted"
        elif kind == "model_unavailable":
            self.status = f"model unavailable (HTTP {event.get('status', '?')})"
        self.dirty = True

    def request_approval(self, path, diff):
        width = self._max_width()
        self.append_output("")
        self.append_output(render.approval_header(path, diff, width))
        self.append_output(render.render_diff(diff, width, max_lines=40, glyphs=self.glyphs))
        self._approval_event = threading.Event()
        self._approval_result = False
        self._approval_diff = diff
        self._approval_is_command = False
        self.approval = f"apply edit to {path}?   [y]es  [n]o  [a]ll  [d]iff"
        self.status = "awaiting approval"
        self.dirty = True
        self._approval_event.wait()
        self.approval = None
        self.dirty = True
        return self._approval_result

    def request_command_approval(self, command):
        width = self._max_width()
        self.append_output("")
        self.append_output(render.notice(f"the agent asks to run: {command}", width, self.glyphs))
        self._approval_event = threading.Event()
        self._approval_result = False
        self._approval_diff = ""
        self._approval_is_command = True
        self.approval = "run this command?   [y]es  [n]o  [a]lways"
        self.status = "awaiting command approval"
        self.dirty = True
        self._approval_event.wait()
        self.approval = None
        self._approval_is_command = False
        self.dirty = True
        return self._approval_result

    def _resolve_approval(self, result):
        self._approval_result = result
        if self._approval_event is not None:
            self._approval_event.set()

    def _handle_approval_key(self, key):
        if self._approval_is_command:
            width = self._max_width()
            if key.name == "ctrl+c":
                self.terminal.cancel_event.set()
                self.append_output(render.notice("command rejected", width, self.glyphs))
                self._resolve_approval(False)
            elif (key.name == "char" and key.text.lower() == "y") or key.name == "enter":
                self.append_output(render.notice("command approved", width, self.glyphs))
                self._resolve_approval(True)
            elif key.name == "char" and key.text.lower() == "a":
                self.append_output(render.notice("exact command approved for this session",
                                                 width, self.glyphs))
                self._resolve_approval("always")
            elif (key.name == "char" and key.text.lower() == "n") or key.name == "escape":
                self.append_output(render.notice("command rejected", width, self.glyphs))
                self._resolve_approval(False)
            return
        if key.name == "ctrl+c":
            self.terminal.cancel_event.set()
            self.append_output(render.notice("edit rejected", self._max_width(), self.glyphs))
            self._resolve_approval(False)
        elif (key.name == "char" and key.text.lower() == "y") or key.name == "enter":
            self.append_output(render.notice("edit approved", self._max_width(), self.glyphs))
            self._resolve_approval(True)
        elif key.name == "char" and key.text.lower() == "a":
            self.terminal.confirm_edits = False
            self.append_output(render.notice("approvals off; edit approved", self._max_width(), self.glyphs))
            self._resolve_approval(True)
        elif key.name == "char" and key.text.lower() == "d":
            self.append_output(render.render_diff(self._approval_diff, self._max_width(), glyphs=self.glyphs))
        elif (key.name == "char" and key.text.lower() == "n") or key.name == "escape":
            self.append_output(render.notice("edit rejected", self._max_width(), self.glyphs))
            self._resolve_approval(False)

    def _refresh_suggestions(self):
        head = self.input.text[:self.input.cursor]
        if head.startswith("/") and " " not in head.strip():
            matches = [command for command in self.commands if command.startswith(head)]
            self.suggestions = matches[:8] if head != "/" else self.commands[:8]
        else:
            self.suggestions = []

    def submit(self):
        text = self.input.value().strip()
        if not text:
            return
        if self.busy:
            self.status = "task running · ctrl+c to interrupt"
            self.dirty = True
            return
        self.input.remember(text)
        self.input.clear()
        self.suggestions = []
        self.scroll = 0
        self.mode = "conversation"
        self.append_output(render.user_block(text, self._max_width(), self.glyphs))
        if not text.startswith("/"):
            self.append_output("")
        if text.startswith("/"):
            command = text.split()[0].lower()
            if command in ("/exit", "/quit"):
                self.running = False
                return
            if command == "/clear":
                with self._lock:
                    self.transcript.clear()
                self.mode = "welcome"
                self.dirty = True
                return
            try:
                self.terminal.slash(text)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError, IndexError) as error:
                self.append_output(self.terminal.error_report(error))
            if not self.transcript:
                self.mode = "welcome"
            self.dirty = True
            return

        self.busy = True
        self.busy_started = time.monotonic()
        self.status = "starting"
        self.dirty = True

        def work():
            try:
                self.terminal.task(text)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError, IndexError) as error:
                self.append_output("")
                self.append_output(self.terminal.error_report(error))
            except Exception as error:  # keep the UI alive; surface the diagnostic
                self.append_output("")
                self.append_output(self.terminal.error_report(error))
            finally:
                self.busy = False
                self.status = "idle"
                self.suggestions = []
                self.dirty = True

        self._worker = threading.Thread(target=work, name="miser-task", daemon=True)
        self._worker.start()

    def _scroll(self, amount):
        with self._lock:
            total = len(self.transcript)
        self.scroll = max(0, min(self.scroll + amount, max(0, total - 1)))
        self.dirty = True

    def handle_key(self, key):
        if key is None:
            return
        if self.approval is not None:
            self._handle_approval_key(key)
            return
        name = key.name
        if name in ("ctrl+d", "eof"):
            if not self.busy:
                self.running = False
            return
        if name == "ctrl+c":
            if self.busy:
                self.terminal.cancel_event.set()
                self.status = "cancelling (waiting for the current request)"
            elif self.input.value():
                self.input.clear()
                self.suggestions = []
            else:
                self.status = "ctrl+d to exit"
            self.dirty = True
            return
        if name == "ctrl+l":
            self.dirty = True
            return
        if name == "pageup":
            self._scroll(8)
            return
        if name == "pagedown":
            self._scroll(-8)
            return
        if name == "escape":
            self.scroll = 0
            self.suggestions = []
            self.dirty = True
            return
        if name == "tab":
            completions = self.input.complete(self.commands)
            self.suggestions = completions[:8]
            self.dirty = True
            return
        if name == "enter":
            self.submit()
            return
        if name == "newline":
            self.input.newline()
        elif name == "backspace":
            self.input.backspace()
        elif name == "delete":
            self.input.delete()
        elif name == "left":
            self.input.left()
        elif name == "right":
            self.input.right()
        elif name == "home":
            self.input.home()
        elif name == "end":
            self.input.end()
        elif name == "up":
            self.input.up()
        elif name == "down":
            self.input.down()
        elif name == "ctrl+p":
            self.input.history_previous()
        elif name == "ctrl+n":
            self.input.history_next()
        elif name == "ctrl+u":
            self.input.clear()
        elif name == "paste":
            self.input.insert(key.text)
        elif name == "char":
            self.input.insert(key.text)
        else:
            return
        self._refresh_suggestions()
        self.dirty = True

    # -- main loop ---------------------------------------------------------

    def run(self):
        self.screen_io.enter()
        try:
            with raw_mode():
                self._loop()
        finally:
            self.screen_io.leave()
            self.terminal.cancel_event.set()
            self.terminal.spinner.stop()
        self._save_history()
        try:
            sys.stdout.write(theme.dim("Session closed.") + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        return 0

    def _loop(self):
        while self.running:
            size = self.screen_io.size()
            if self.busy:
                self.spinner_index += 1
                self.elapsed = time.monotonic() - self.busy_started
            if self.dirty or self.busy or size != self._last_size:
                self.draw()
            key = self.keys.read(0.05)
            # Drain typed/pasted bytes without a full repaint between characters.
            while key is not None and self.running:
                self.handle_key(key)
                key = self.keys.read(0)
        return 0
