"""Native full-screen Textual application over the real MISER backend.

Only the UI thread mutates widgets. Backend callbacks post typed messages; modal
requests wait on cancellation-aware events. No provider or tool is implemented here.
"""
from collections import defaultdict, deque
import asyncio
from dataclasses import dataclass, field
import json
import os
import stat
from pathlib import Path
import threading
import time
import uuid

from rich.syntax import Syntax
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Button, Collapsible, Input, Label, LoadingIndicator, Markdown, Static, TextArea

from ..terminal import COMMANDS
from ..ui import theme
from ..ui.render import diff_files, usage_phrase, timing_line
from .input import InputBuffer
from .wakeup import ensure_wakeup_poll


class Composer(TextArea):
    """A native multiline editor: Enter sends; Ctrl+J keeps a newline."""
    class Submitted(Message):
        def __init__(self, text):
            super().__init__()
            self.text = text

    async def _on_key(self, event: events.Key):
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self.text))
        elif event.key in {"ctrl+j", "shift+enter", "alt+enter"}:
            event.stop()
            event.prevent_default()
            self.insert("\n")
        elif event.key == "tab":
            event.stop()
            event.prevent_default()
            self.app.action_complete()
        else:
            await super()._on_key(event)


class MessageCard(Vertical):
    """A semantic conversation entry, not an ANSI line in a transcript buffer."""
    def __init__(self, kind, source, title="", **kwargs):
        super().__init__(classes=f"message {kind}", **kwargs)
        self.kind, self.source, self.title = kind, theme.clean(source), title

    def compose(self):
        yield Label(self.title or ("You" if self.kind == "user" else "MISER"), classes="message-title", markup=False)
        if self.kind == "assistant":
            yield Markdown(self.source, open_links=False)
        else:
            yield Static(Text(self.source), classes="message-body")

    async def replace_source(self, source):
        self.source = source
        await self.query_one(Markdown).update(source)


class DiffView(Collapsible):
    def __init__(self, source, *, collapsed=False):
        self.source = source
        files = diff_files(source)
        names = ", ".join(item["path"] for item in files) or "Patch"
        added, removed = sum(item["added"] for item in files), sum(item["removed"] for item in files)
        super().__init__(Static(Syntax(theme.clean(source), "diff", theme="monokai", line_numbers=True,
                                       word_wrap=True, background_color="#101820")),
                         title=escape(theme.clean(f"{names}   +{added} −{removed}")), collapsed=collapsed, classes="diff-view")


@dataclass
class PendingInput:
    kind: str
    title: str
    detail: str = ""
    options: list = field(default_factory=list)
    event: threading.Event = field(default_factory=threading.Event)
    result: object = None


class ApprovalScreen(ModalScreen):
    BINDINGS = [Binding("escape", "reject", priority=True), Binding("ctrl+c", "interrupt", priority=True)]

    def __init__(self, request):
        super().__init__()
        self.request = request

    def compose(self):
        with Vertical(id="approval-dialog"):
            yield Label(self.request.title, id="approval-title", markup=False)
            with VerticalScroll(id="approval-details"):
                if self.request.kind == "edit":
                    yield DiffView(self.request.detail)
                else:
                    yield Static(Text(self.request.detail))
            yield Static("Review this invocation. Escape rejects; Ctrl+C cancels the task.", classes="muted")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Reject", id="reject")
                yield Button("Approve", id="approve", variant="primary")
                if self.request.kind == "edit":
                    yield Button("Approve all edits", id="all-edits")

    def on_mount(self):
        self.query_one("#reject", Button).focus()

    def action_reject(self):
        self.dismiss(False)

    def action_interrupt(self):
        self.app.terminal.cancel_event.set()
        self.dismiss(False)

    @on(Button.Pressed)
    def button_pressed(self, event):
        self.dismiss("all" if event.button.id == "all-edits" else event.button.id == "approve")


class QuestionScreen(ModalScreen):
    BINDINGS = [Binding("escape", "decline", priority=True), Binding("ctrl+c", "interrupt", priority=True)]

    def __init__(self, request):
        super().__init__()
        self.request = request

    def compose(self):
        with Vertical(id="question-dialog"):
            yield Label(self.request.title, markup=False)
            for index, option in enumerate(self.request.options, 1):
                yield Static(Text(f"{index}. {option}"))
            yield Input(placeholder="Answer or choice number; never enter credentials", id="answer", max_length=2000)
            with Horizontal(classes="dialog-buttons"):
                yield Button("Leave unanswered", id="decline")
                yield Button("Answer", id="answer-send", variant="primary")

    def on_mount(self):
        self.query_one(Input).focus()

    def action_decline(self):
        self.dismiss(None)

    def action_interrupt(self):
        self.app.terminal.cancel_event.set()
        self.dismiss(None)

    def send(self):
        answer = self.query_one(Input).value.strip()
        if not answer:
            return
        if answer.isdecimal() and 1 <= int(answer) <= len(self.request.options):
            answer = self.request.options[int(answer) - 1]
        self.dismiss(answer)

    @on(Input.Submitted)
    def input_submitted(self):
        self.send()

    @on(Button.Pressed)
    def button_pressed(self, event):
        self.action_decline() if event.button.id == "decline" else self.send()


class BackendUpdate(Message):
    def __init__(self, kind, **data):
        super().__init__()
        self.kind, self.data = kind, data


class ResponseStream:
    """Retain original response text; post bounded-frequency native widget updates."""
    def __init__(self, app):
        self.app, self.key, self.source, self.updated = app, uuid.uuid4().hex, "", 0.0

    def feed(self, chunk):
        self.source += chunk
        now = time.monotonic()
        if now - self.updated >= .04:
            self.flush()
            self.updated = now

    def flush(self):
        self.app.post_message(BackendUpdate("assistant", key=self.key, source=self.source))

    def finish(self):
        self.flush()


class MiserApp(App):
    TITLE = "MISER"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+c", "interrupt", priority=True),
                Binding("ctrl+d", "quit_safe", priority=True),
                Binding("ctrl+p", "history_previous", priority=True),
                Binding("ctrl+n", "history_next", priority=True),
                Binding("pageup", "conversation_up", priority=True),
                Binding("pagedown", "conversation_down", priority=True),
                Binding("ctrl+l", "focus_prompt", priority=True),
                Binding("f2", "review_diff", priority=True)]

    CSS = """
    Screen { background: #0b0f16; color: #dce6f3; layout: vertical; }
    #topbar { height: 2; padding: 0 2; border-bottom: solid #253143; align-vertical: middle; }
    #brand { width: 14; color: #8bd5e5; text-style: bold; }
    #model { width: 1fr; color: #a4b5ce; }
    #workspace-name { width: auto; max-width: 38; color: #8292aa; }
    #workspace { height: 1fr; }
    #conversation { width: 1fr; height: 1fr; padding: 1 2; scrollbar-size: 1 1; }
    #inspector { width: 30; padding: 1 2; border-left: solid #202c3c; background: #0f1520; }
    .compact #inspector { display: none; }
    #welcome { height: auto; margin: 1 0 2 0; padding: 1 2; background: #111b28; border-left: tall #4f8cff; }
    #welcome-title { text-style: bold; color: #c9eaf4; margin-bottom: 1; }
    .muted { color: #899ab3; height: auto; }
    .message { height: auto; margin: 0 0 1 0; padding: 1 2; }
    .message-title { height: 1; color: #8bd5e5; text-style: bold; margin-bottom: 1; }
    .user { background: #172132; border-left: tall #4f8cff; }
    .assistant, .literal { background: #101722; border-left: tall #33445c; }
    .system { background: #101722; border-left: tall #33445c; padding: 0 2; }
    .error { background: #251920; border-left: tall #f87171; }
    .error .message-title { color: #f87171; }
    .tool { padding: 0 1; margin-bottom: 1; height: auto; color: #a7b9ce; border-left: tall #3d506a; }
    .test-passed { border-left: tall #34d399; color: #a8e9cd; }
    .test-failed { border-left: tall #f87171; color: #f1b4bc; }
    .result { background: #12241f; border-left: tall #34d399; }
    .message-body { height: auto; }
    Markdown { background: transparent; margin: 0; padding: 0; height: auto; }
    MarkdownH1, MarkdownH2, MarkdownH3 { color: #b6ddea; border: none; margin: 1 0; padding: 0; text-align: left; }
    MarkdownFence { background: #0c121b; margin: 1 0; padding: 1; border-top: solid #2b3e56; border-title-color: #8bd5e5; scrollbar-size-horizontal: 1; }
    .diff-view { height: auto; background: #101820; margin: 0 0 1 0; padding: 0; }
    #composer { height: auto; max-height: 12; margin: 0 2; padding: 0 1; border: round #334862; background: #111a28; }
    #composer:focus-within { border: round #4f8cff; }
    #prompt { height: 1; min-height: 1; max-height: 8; border: none; background: #111a28; padding: 0; }
    #composer-hints { height: 1; color: #8495af; }
    #statusbar { height: 1; margin: 0 2; color: #a4b6cf; }
    #activity { height: auto; margin-top: 1; color: #8bd5e5; }
    #session-details { height: auto; color: #9cacc3; }
    #spinner { height: 1; width: 5; display: none; }
    #approval-dialog, #question-dialog { width: 86%; height: auto; max-height: 90%; padding: 1 2; background: #121d2d; border: round #4f8cff; }
    #approval-dialog { height: 85%; }
    ApprovalScreen, QuestionScreen { align: center middle; background: #05090f 80%; }
    #approval-title { height: auto; text-style: bold; margin-bottom: 1; color: #b7dfeb; }
    #approval-details { height: 1fr; }
    .dialog-buttons { height: 3; margin-top: 1; align-horizontal: right; }
    Button { min-width: 12; margin-left: 1; }
    #answer { margin-top: 1; }
    """

    def __init__(self, terminal, initial=None):
        super().__init__()
        self.terminal, self.initial = terminal, list(initial or [])
        self.busy, self._quit_requested = False, False
        self._responses, self._tools = {}, defaultdict(deque)
        self._pending, self._saved = [], {}
        self._history = InputBuffer()
        self._status = "Ready"
        self._started = 0.0
        self._last_checks = "not run"
        self._backend_thread = None
        self._status_snapshot = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static("MISER / code", id="brand", markup=False)
            yield Static(self.terminal.model or "No model configured", id="model", markup=False)
            yield Static(theme.shorten_home(str(self.terminal.repo)), id="workspace-name", markup=False)
        with Horizontal(id="workspace"):
            with VerticalScroll(id="conversation"):
                with Vertical(id="welcome"):
                    yield Static("Your workspace. One focused change at a time.", id="welcome-title", markup=False)
                    yield Static("Describe a task or ask about the code. Edits, checks and usage stay visible.", classes="muted")
                    yield Static("/model · /test · /status     F2 review diff     PgUp/PgDn scroll", classes="muted")
            with Vertical(id="inspector"):
                yield Static("SESSION", classes="message-title")
                yield Static("", id="session-details", markup=False)
                yield LoadingIndicator(id="spinner")
                yield Static("Ready", id="activity", markup=False)
        with Vertical(id="composer"):
            yield Composer(id="prompt", placeholder="Ask about code, describe a change, or type /help", soft_wrap=True,
                           show_line_numbers=False, tab_behavior="focus", highlight_cursor_line=False)
            yield Static("Enter send · Ctrl+J newline · Tab complete · Ctrl+C cancel · Ctrl+D exit", id="composer-hints")
        yield Static("Ready", id="statusbar", markup=False)

    def on_mount(self):
        self._main_screen = self.screen
        ensure_wakeup_poll(asyncio.get_running_loop())
        self.theme = "textual-dark"
        self._attach_backend()
        self._load_history()
        self.on_resize()
        self.ui("#conversation", VerticalScroll).anchor()
        self.ui(Composer).focus()
        self.set_interval(.1, self._refresh_status)
        for text in self.initial:
            self._note(text)

    def ui(self, selector, expect_type=None):
        return self._main_screen.query_one(selector, expect_type)

    def on_resize(self, event: events.Resize | None = None):
        if not self.is_running:
            return
        width = event.size.width if event is not None else self.size.width
        if hasattr(self, "_main_screen"):
            self._main_screen.set_class(width < 118, "compact")
            self.ui("#inspector").display = width >= 118
        self.terminal.width_override = max(30, width - (36 if width >= 118 else 8))

    def _attach_backend(self):
        callbacks = {
            "write": self._note, "reply": lambda text: self._assistant(text),
            "markdown_output": self._assistant, "markdown_stream_factory": lambda _: ResponseStream(self),
            "agent_label_output": lambda _: None, "local_read_output": self._file_read,
            "model_error_output": lambda error: self.post_message(BackendUpdate("error", source=str(error))),
            "literal_answer_output": lambda text: self.post_message(BackendUpdate("literal", source=text)),
            "activity_listener": lambda event: self.post_message(BackendUpdate("activity", event=event)),
            "handle_activity": lambda _: None, "render_task_result": self._result,
            "prompt_edit_approval": self._approve_edit, "prompt_command_approval": self._approve_command,
            "prompt_mcp_approval": self._approve_mcp, "prompt_clarification": self._ask_question,
        }
        self._spinner_enabled = self.terminal.spinner.enabled
        self.terminal.spinner.enabled = False
        for name, callback in callbacks.items():
            self._saved[name] = (hasattr(self.terminal, name), getattr(self.terminal, name, None))
            setattr(self.terminal, name, callback)

    def _note(self, text=""):
        text = theme.clean(text).strip()
        if text:
            self.post_message(BackendUpdate("note", source=text))

    def _assistant(self, source):
        self.post_message(BackendUpdate("assistant", key=uuid.uuid4().hex, source=source))

    def _file_read(self, path, source, truncated, empty):
        self.post_message(BackendUpdate("file", path=path, source=source, truncated=truncated, empty=empty))

    def _result(self, bill, elapsed, directory, error=None):
        self.post_message(BackendUpdate("result", bill=dict(bill), elapsed=elapsed,
                                       directory=str(directory), error=str(error) if error else None,
                                       diff=self.terminal.last_diff))

    def _wait_input(self, request):
        self.post_message(BackendUpdate("input", request=request))
        while not request.event.wait(.1):
            if self.terminal.cancel_event.is_set() or self._quit_requested or not self.is_running:
                return None
        return request.result

    def _approve_edit(self, path, diff):
        if not self.terminal.confirm_edits:
            return True
        result = self._wait_input(PendingInput("edit", f"Review edit · {path}", diff))
        if result == "all":
            self.terminal.confirm_edits = False
            return True
        return result is True

    def _approve_command(self, command):
        return self._wait_input(PendingInput("command", "Approve this command invocation?", str(command))) is True

    def _approve_mcp(self, server, tool, arguments):
        detail = f"{server}/{tool}\n{json.dumps(arguments, ensure_ascii=False)}"
        return self._wait_input(PendingInput("mcp", "Approve this external tool call?", detail)) is True

    def _ask_question(self, question, options):
        return self._wait_input(PendingInput("question", question, options=list(options)))

    async def _append(self, widget):
        view = self.ui("#conversation", VerticalScroll)
        await view.mount(widget)
        return widget

    async def on_backend_update(self, message):
        if not self.is_running:
            return
        kind, data = message.kind, message.data
        if kind == "assistant":
            card = self._responses.get(data["key"])
            if card is None:
                card = MessageCard("assistant", theme.clean(data["source"]),
                                   f"MISER · {self.terminal.model or 'local'}")
                self._responses[data["key"]] = card
                await self._append(card)
            else:
                await card.replace_source(theme.clean(data["source"]))
        elif kind == "note":
            await self._append(MessageCard("system", data["source"], "Workspace"))
        elif kind == "literal":
            await self._append(MessageCard("literal", data["source"], "MISER · local recall"))
        elif kind == "error":
            await self._append(MessageCard("error", theme.clean(data["source"]), "Task stopped"))
        elif kind == "file":
            source = data["source"] if not data["empty"] else "(empty file)"
            await self._append(MessageCard("system", source, f"Local file · {data['path']}" +
                                          (" · truncated" if data["truncated"] else "")))
        elif kind == "activity":
            await self._activity(data["event"])
        elif kind == "diff":
            await self._append(DiffView(data["source"]))
        elif kind == "result":
            bill = data["bill"]
            title = "Task completed · tests passed" if bill["status"] == "tests_passed" else bill["status"].replace("_", " ")
            if bill["status"] == "edited_unverified":
                title = "Edited · tests not run (manual policy)"
            text = f"{usage_phrase(bill)}\n{data['elapsed']:.2f}s · {data['directory']}"
            await self._append(MessageCard("result" if bill["status"] == "tests_passed" else
                                          "error" if data["error"] else "system", text, title))
            if data["error"]:
                await self._append(MessageCard("error", data["error"], "Error"))
            if data["diff"]:
                await self._append(DiffView(data["diff"], collapsed=self.size.width < 110))
        elif kind == "input":
            request = data["request"]
            if self._quit_requested or self.terminal.cancel_event.is_set():
                request.event.set()
                return
            self._pending.append(request)
            def resolve(result):
                request.result = result
                request.event.set()
                if request in self._pending:
                    self._pending.remove(request)
                if self.is_running:
                    self.ui(Composer).focus()
            self.push_screen(QuestionScreen(request) if request.kind == "question" else ApprovalScreen(request), resolve)
        elif kind == "done":
            self.busy = False
            self._status = "Ready"
            self.ui("#prompt", Composer).read_only = False
            self._refresh_status()
            if self._quit_requested:
                self.exit(0)

    async def _activity(self, event):
        kind = event.get("type")
        if kind == "route":
            if event["profile"] == "coding":
                self._last_checks = "skipped (manual)" if event.get("test_policy") == "manual" else "pending"
            await self._append(Static(Text(f"Route: {event['profile']} · {event['verification']}"), classes="tool"))
        elif kind == "timing":
            await self._append(Static(Text(timing_line(event)), classes="tool"))
        elif kind == "model_start":
            self._status = "Thinking"
        elif kind == "tool":
            name = event.get("name", "tool")
            if event.get("state") == "start":
                card = Static(Text(f"● {name} · running"), classes="tool")
                self._tools[name].append(card)
                await self._append(card)
                self._status = name
            else:
                card = self._tools[name].popleft() if self._tools[name] else await self._append(Static(classes="tool"))
                elapsed = event.get("elapsed")
                timing = f" · {elapsed:.2f}s" if isinstance(elapsed, (int, float)) else ""
                error = "" if event.get("ok") else "\n" + theme.clean(event.get("error") or "Tool failed; inspect the receipt")
                card.update(Text(f"{'✓' if event.get('ok') else '✗'} {name}{timing}{error}"))
                card.add_class("test-passed" if event.get("ok") else "test-failed")
        elif kind == "tests":
            label = "Baseline checks" if event.get("baseline") else "Acceptance checks"
            if event.get("state") == "start":
                self._status = label
                return
            passed = event.get("passed")
            self._last_checks = ("baseline passed" if event.get("baseline") else "passed") if passed else f"failed (exit {event.get('exit_code')})"
            text = f"{'✓' if passed else '✗'} {label} · {'passed' if passed else 'failed'}"
            if isinstance(event.get("elapsed_seconds"), (int, float)):
                text += f" · {event['elapsed_seconds']:.2f}s"
            if not passed:
                text += f" · exit {event.get('exit_code')}\n{theme.clean(event.get('output', ''))[-2000:]}"
            await self._append(Static(Text(text), classes="tool test-passed" if passed else "tool test-failed"))
        elif kind in {"fallback", "compaction", "stream_interrupted", "model_unavailable"}:
            await self._append(MessageCard("system", theme.clean(event.get("message") or kind.replace("_", " ")), "Activity"))

    @on(Composer.Submitted)
    async def composer_submitted(self, event):
        await self.submit_text(event.text)

    @on(Markdown.LinkClicked)
    async def link_clicked(self, event):
        event.stop()
        await self._append(MessageCard("system", theme.clean(event.href), "Link destination · not opened"))

    @on(Markdown.TableOfContentsUpdated)
    def label_code_blocks(self, event):
        for block in event.control.query("MarkdownFence"):
            block.border_title = theme.clean(getattr(block, "lexer", "") or "text")[:40]

    async def submit_text(self, text):
        text = text.strip()
        if not text:
            return
        if self.busy:
            self.notify("A task is running. Ctrl+C cancels it.")
            return
        if text in {"/exit", "/quit"}:
            self.action_quit_safe()
            return
        if text == "/clear":
            for child in list(self.ui("#conversation").children):
                if child.id != "welcome":
                    await child.remove()
            self.ui("#welcome").display = True
            self.ui(Composer).load_text("")
            self._responses.clear()
            return
        self.ui("#welcome").display = False
        self.ui("#conversation", VerticalScroll).anchor()
        self._history.remember(text)
        self._history.history_index = None
        self.ui(Composer).load_text("")
        await self._append(MessageCard("user", text))
        self.busy, self._started, self._status = True, time.monotonic(), "Starting"
        self._backend_thread = threading.Thread(target=self._execute, args=(text,),
                                                name="miser-backend", daemon=True)
        self._backend_thread.start()

    def _execute(self, text):
        try:
            if text in {"/diff", "/diff full"}:
                diff = self.terminal.last_diff or self.terminal.get_git_diff()
                self.post_message(BackendUpdate("diff", source=diff)) if diff else self._note("No changes to review.")
            elif text.startswith("/"):
                self.terminal.slash(text)
            else:
                self.terminal.session_user_messages += 1
                self.terminal.task(text)
        except KeyboardInterrupt:
            self._note("Task interrupted; edits and receipts retained.")
        except Exception as error:
            self.post_message(BackendUpdate("error", source=str(error)))
        finally:
            self.post_message(BackendUpdate("done"))

    def _refresh_status(self):
        if not self.is_mounted or not self.is_running:
            return
        terminal = self.terminal
        usage = f"{terminal.session_provider_tokens:,} known tokens"
        if terminal.session_unknown_usage:
            usage = "Usage unknown" if not terminal.session_provider_tokens else usage + " · usage incomplete"
        if not terminal.session_model_requests and not terminal.session_unknown_usage:
            usage = "No model requests"
        status = self._status + (f" · {time.monotonic() - self._started:.1f}s" if self.busy else "")
        snapshot = (status, usage, terminal.session_tasks_count, terminal.budget, terminal.model,
                    terminal.session_model_requests, terminal.session_tool_calls, terminal.confirm_edits, self._last_checks)
        if snapshot == self._status_snapshot:
            return
        self._status_snapshot = snapshot
        self.ui("#statusbar", Static).update(Text(f"{status} | {usage} | {terminal.session_tasks_count} tasks | checks {self._last_checks}"))
        self.ui("#session-details", Static).update(Text(
            f"{terminal.repo.name}\n\nBudget  {terminal.budget:,}\nCompleted requests  {terminal.session_model_requests}\n"
            f"Tool calls  {terminal.session_tool_calls}\n\n{usage}\n\n"
            f"Last checks  {self._last_checks}\n\nEdit approval  {'on' if terminal.confirm_edits else 'off'}"))
        self.ui("#model", Static).update(Text(terminal.model or "No model configured"))
        self.ui("#activity", Static).update(Text(status))
        self.ui("#spinner").display = self.busy

    @on(TextArea.Changed, "#prompt")
    def prompt_changed(self, event):
        if not self.is_running or not event.text_area.is_mounted:
            return
        prompt = event.text_area
        prompt.styles.height = min(8, max(1, prompt.wrapped_document.height))

    def action_interrupt(self):
        if isinstance(self.screen, (ApprovalScreen, QuestionScreen)):
            self.screen.dismiss(None if isinstance(self.screen, QuestionScreen) else False)
        if self.busy:
            self.terminal.cancel_event.set()
            self._status = "Cancelling · waiting for backend cleanup"
            for request in self._pending:
                request.event.set()
        else:
            self.ui(Composer).load_text("")

    def action_quit_safe(self):
        self._quit_requested = True
        if self.busy:
            self.action_interrupt()
        else:
            self.exit(0)

    def action_quit(self):
        self.action_quit_safe()

    def action_focus_prompt(self):
        self.ui(Composer).focus()

    async def action_review_diff(self):
        await self.submit_text("/diff")

    def action_conversation_up(self):
        view = self.screen.query_one("#approval-details", VerticalScroll) if isinstance(self.screen, ApprovalScreen) else self.ui("#conversation", VerticalScroll)
        view.anchor(False)
        view.scroll_page_up(animate=False)

    def action_conversation_down(self):
        view = self.screen.query_one("#approval-details", VerticalScroll) if isinstance(self.screen, ApprovalScreen) else self.ui("#conversation", VerticalScroll)
        view.scroll_page_down(animate=False)
        if view.scroll_target_y >= view.max_scroll_y:
            view.anchor()

    def action_complete(self):
        prompt = self.ui(Composer)
        head = prompt.text
        prefix, separator, word = head.rpartition(" ")
        commands = head.startswith("/") and " " not in head
        choices = [command for command in COMMANDS if command.startswith(head)] if commands else [
            name for name in self.terminal.workspace.files() if name.startswith(word or head)][:200]
        if len(choices) == 1:
            prompt.load_text((prefix + separator if not commands else "") + choices[0])
            prompt.move_cursor(prompt.document.end)
        elif choices:
            self.notify("  ".join(choices))

    def action_history_previous(self):
        prompt = self.ui(Composer)
        self._history.set_text(prompt.text)
        self._history.history_previous()
        prompt.load_text(self._history.value())

    def action_history_next(self):
        self._history.history_next()
        self.ui(Composer).load_text(self._history.value())

    def _load_history(self):
        if os.name != "posix":
            return
        directory = None
        try:
            directory = os.open(self.terminal.repo / ".miser", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            legacy = False
            try:
                fd = os.open("textual-history.json", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                fd = os.open("history", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=directory)
                legacy = True
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1000000:
                    return
                raw = stream.read(1000001)
            if len(raw) > 1000000:
                return
            data = raw.decode().splitlines() if legacy else json.loads(raw)
            if isinstance(data, list) and all(isinstance(item, str) for item in data):
                self._history.history = data[-2000:]
        except (OSError, UnicodeError, ValueError):
            return
        finally:
            if directory is not None:
                os.close(directory)

    def _save_history(self):
        """Host UI state only; refuse symlinks and atomically replace private JSON."""
        if not self._history.history or os.name != "posix":
            return
        parent = self.terminal.repo / ".miser"
        temporary = "history-" + uuid.uuid4().hex + ".tmp"
        directory = None
        try:
            parent.mkdir(mode=0o700, exist_ok=True)
            directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            data = json.dumps(self._history.history[-2000:], ensure_ascii=False).encode()
            if len(data) > 1000000:
                data = json.dumps(self._history.history[-100:], ensure_ascii=False).encode()
            if len(data) > 1000000:
                return
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, "textual-history.json", src_dir_fd=directory, dst_dir_fd=directory)
        except OSError as error:
            self.log.warning("UI history could not be saved: %s", type(error).__name__)
        finally:
            if directory is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
                os.close(directory)

    def on_unmount(self):
        self._quit_requested = True
        self.terminal.cancel_event.set()
        for request in self._pending:
            request.event.set()
        if self._backend_thread is not None:
            self._backend_thread.join(timeout=.5)
        self._save_history()
        for name, (existed, value) in self._saved.items():
            if existed:
                setattr(self.terminal, name, value)
            else:
                delattr(self.terminal, name)
        self.terminal.spinner.enabled = self._spinner_enabled
