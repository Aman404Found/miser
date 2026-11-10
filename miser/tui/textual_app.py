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


_LOGO_PIXELS = (
    ("10001", "11011", "10101", "10001", "10001"),
    ("11111", "00100", "00100", "00100", "11111"),
    ("11111", "10000", "11111", "00001", "11111"),
    ("11111", "10000", "11110", "10000", "11111"),
    ("11110", "10001", "11110", "10100", "10010"),
)
WORDMARK = "\n".join("  ".join("".join("██" if pixel == "1" else "  " for pixel in letter[row])
                              for letter in _LOGO_PIXELS) for row in range(5))

GLYPHS = {"user": "▌", "assistant": "◆", "system": "◇", "error": "✖", "result": "✓", "literal": "◇"}


class MessageCard(Vertical):
    """A semantic conversation entry, not an ANSI line in a transcript buffer."""
    def __init__(self, kind, source, title="", **kwargs):
        super().__init__(classes=f"message {kind}", **kwargs)
        self.kind, self.source, self.title = kind, theme.clean(source), title

    def compose(self):
        glyph = GLYPHS.get(self.kind, "·")
        title = self.title or ("You" if self.kind == "user" else "MISER")
        yield Label(f"{glyph}  {title}", classes="message-title", markup=False)
        if self.kind == "assistant":
            yield Markdown(self.source, open_links=False)
        else:
            yield Static(Text(self.source), classes="message-body")

    async def replace_source(self, source):
        self.source = source
        await self.query_one(Markdown).update(source)


class DiffView(Collapsible):
    """A compact patch card: file header, +/− counts, and a collapsible body."""
    def __init__(self, source, *, collapsed=False):
        self.source = source
        files = diff_files(source)
        names = ", ".join(item["path"] for item in files) or "Patch"
        added, removed = sum(item["added"] for item in files), sum(item["removed"] for item in files)
        super().__init__(Static(Syntax(theme.clean(source), "diff", theme="monokai", line_numbers=True,
                                       word_wrap=True, background_color=theme.PANEL)),
                         title=escape(theme.clean(f"▤  {names}   +{added} −{removed}")),
                         collapsed=collapsed, classes="diff-view")


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
        self.set_class(len(request.title) > 100 or len(request.detail.splitlines()) > 8, "scroll-review")

    def compose(self):
        with Vertical(id="approval-dialog"):
            yield Label(self.request.title, id="approval-title", markup=False)
            with VerticalScroll(id="approval-details"):
                if self.request.kind in {"edit", "delete"}:
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

    CSS = (f"$miser-bg: {theme.BG}; $miser-surface: {theme.SURFACE}; $miser-panel: {theme.PANEL}; "
           f"$miser-line: {theme.LINE}; $miser-text: {theme.TEXT}; $miser-accent: {theme.ACCENT}; $miser-cyan: {theme.CYAN};\n"
           """
    Screen { background: $miser-bg; color: $miser-text; layout: vertical; }

    /* Chrome: one quiet header row and a persistent footer. */
    #topbar { height: 2; padding: 0 2; background: #17171a; border-bottom: solid $miser-line; align-vertical: middle; }
    #brand { width: auto; min-width: 11; text-style: bold; color: $miser-cyan; }
    #tagline { width: 1fr; padding-left: 1; color: #7f7b77; }
    #model { width: auto; max-width: 38; padding-left: 2; color: #b6b2ac; }
    #workspace-name { width: auto; max-width: 32; padding-left: 2; color: #908c87; }
    #counters { width: auto; padding-left: 2; color: #908c87; }
    .compact #tagline, .compact #workspace-name { display: none; }
    .narrow #tagline, .narrow #workspace-name, .narrow #counters { display: none; }

    #workspace { height: 1fr; }
    #conversation { width: 1fr; height: 1fr; padding: 1 2 1 2; background: $miser-bg;
                    scrollbar-size-vertical: 1; scrollbar-color: #3b3b42; scrollbar-background: $miser-bg; }

    /* Session rail: two restrained panels, hidden on narrow terminals. */
    #inspector { width: 35; height: 1fr; padding: 1 1 0 1; background: $miser-bg;
                 scrollbar-size-vertical: 1; scrollbar-color: #3b3b42; scrollbar-background: $miser-bg; }
    .side-panel { width: 1fr; height: auto; max-height: 21; padding: 1 1; margin-bottom: 1;
                  background: transparent; border-left: solid $miser-line; }
    #recent-panel { max-height: 13; }
    .panel-title { height: 1; margin-bottom: 1; color: #d8d4cd; text-style: bold; }
    #session-details, #recent-details { height: auto; color: #aba7a2; }
    #session-state-row { height: 1; margin-top: 1; }
    #activity { width: 1fr; height: 1; color: $miser-cyan; }
    #spinner { height: 1; width: 3; display: none; }

    /* Welcome: branding, real workspace/model facts, and usable shortcuts. */
    #conversation.home { align: center middle; }
    #welcome { width: 72; max-width: 100%; height: auto; margin: 0; padding: 0 1; background: transparent; text-align: center; }
    #welcome > Static { text-align: center; }
    #welcome-brand { height: 5; color: $miser-cyan; text-style: bold; margin-bottom: 1; }
    #welcome-name { height: 1; color: $miser-cyan; margin: 0 0 1 0; }
    #welcome-title { height: auto; color: #ece7e0; text-style: bold; margin-bottom: 1; }
    #welcome-sub { height: auto; color: #a5a19c; margin-bottom: 1; }
    #welcome-meta { height: auto; color: #918d88; margin-bottom: 1; }
    #welcome-keys { height: auto; color: #7f7c78; }
    .short #welcome-sub { display: none; }
    .muted { color: #a5a29f; height: auto; }

    /* Conversation cards. */
    .message { width: 100%; max-width: 110; height: auto; margin: 0 0 1 0; padding: 0; }
    .message-title { height: 1; color: $miser-cyan; text-style: bold; margin-bottom: 1; }
    .message-body { height: auto; }
    .user { background: #20242b; border-left: solid $miser-accent; padding: 1 2; margin: 1 0 1 0; }
    .user .message-title { color: $miser-accent; }
    .assistant { background: #181a1e; border-left: solid #34434c; padding: 1 2; margin: 0 0 1 0; }
    .assistant .message-title { color: #aacbd2; }
    .literal { background: #191d20; border-left: thick #46636c; padding: 1 2; }
    .system { background: transparent; padding: 0 1; }
    .notice { height: auto; color: #a5a19c; padding: 0 1; margin-bottom: 1; }
    .timing { height: auto; padding: 0; margin: 0; background: transparent; }
    .timing CollapsibleTitle { color: #807d79; padding: 0 1; }
    .receipt { border-top: solid $miser-line; padding: 1; margin: 1 0; }
    .error { background: #251b1d; border-left: thick #f87171; padding: 1 2; }
    .error .message-title { color: #f0a4a4; }
    .result { background: #142019; border: round #2c5647; padding: 1 2; margin-bottom: 1; }
    .result .message-title { color: #98e3c1; }
    .tool { height: auto; margin: 0 0 0 1; padding: 0 2; color: #b7b3ad; background: #17171a;
            border-left: tall #3d5a63; }
    .test-passed { border-left: tall #34d399; color: #b3e7d1; }
    .test-failed { border-left: tall #f87171; color: #f1b4bc; }

    /* Markdown: consistent rhythm without oversized gaps. */
    Markdown { background: transparent; margin: 0; padding: 0; height: auto; }
    Markdown > MarkdownParagraph { margin: 0 0 1 0; }
    MarkdownHeader { margin: 1 0 1 0; }
    MarkdownH1 { color: #ece7e0; text-style: bold; margin: 0 0 1 0; padding: 0; }
    MarkdownH2 { color: #dcd8d1; text-style: bold; margin: 0 0 1 0; padding: 0; }
    MarkdownH3, MarkdownH4, MarkdownH5, MarkdownH6 { color: #c9d5d5; text-style: bold;
                                                     margin: 0 0 1 0; padding: 0; }
    MarkdownBlockQuote { background: #1b1b1f; border-left: thick #4d6b74; margin: 0 0 1 0;
                         padding: 0 1; color: #bdb9b3; }
    MarkdownFence { background: #161619; border: round #2c2c33; border-title-color: $miser-cyan;
                    border-title-align: left; margin: 1 0; padding: 0;
                    scrollbar-size-horizontal: 1; scrollbar-color: #4a4a52;
                    scrollbar-background: #1c1c21; }
    MarkdownFence > Label { padding: 0 2; }
    MarkdownTable { margin: 1 0; }
    MarkdownHorizontalRule { border-bottom: solid #333338; height: 1; margin: 1 0; padding: 0; }

    .diff-view { height: auto; margin: 0 0 1 0; padding: 0; background: #18181b; border: round #2c2c33; }
    .diff-view CollapsibleTitle { padding: 0 1; color: #b6d2d8; text-style: bold; }
    .diff-view Contents { padding: 0 1 0 1; }

    /* Activity, composer and footer stay visible while the transcript scrolls. */
    #workline { display: none; height: 1; margin: 0 2; color: #8faeb5; }
    #composer { height: auto; max-height: 12; margin: 0 2; padding: 0 1; background: #1b1b1f;
                border: round #36363d; }
    #composer:focus-within { border: round $miser-accent; background: #1d1d22; }
    #prompt { height: 1; min-height: 1; max-height: 8; border: none; background: transparent; padding: 0 1; }
    #composer-hints { height: 1; color: #807d79; padding: 0 1; }
    #statusbar { height: 1; margin: 0 2; color: #8c8884; }

    #approval-dialog, #question-dialog { width: 86%; height: auto; max-height: 90%; padding: 1 2;
                                          background: $miser-surface; border: round $miser-accent; }
    #approval-dialog { max-height: 90%; }
    ApprovalScreen.scroll-review #approval-dialog { height: 85%; }
    ApprovalScreen.scroll-review #approval-details { height: 1fr; min-height: 3; }
    ApprovalScreen, QuestionScreen { align: center middle; background: #101011 80%; }
    #approval-title { height: auto; max-height: 3; text-style: bold; margin-bottom: 1; color: #d4dcda; }
    #approval-details { height: auto; max-height: 22; min-height: 6; }
    .dialog-buttons { height: 3; margin-top: 1; align-horizontal: right; }
    Button { min-width: 12; margin-left: 1; background: #232327; color: #d8d4cd; border: tall #3a3a41; }
    Button:hover { background: #2d2d34; border: tall #4a4a52; }
    Button.-primary { background: #28343d; color: #cfe4ea; border: tall $miser-accent; text-style: bold; }
    Button.-primary:hover { background: #31424d; border: tall $miser-cyan; }
    #answer { margin-top: 1; }
    """)

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
        self._recent = deque(maxlen=4)

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Static(Text.assemble(("▌ ", f"bold {theme.ACCENT}"), ("MISER", f"bold {theme.CYAN}")), id="brand")
            yield Static("Focused coding assistant", id="tagline", markup=False)
            yield Static("", id="model", markup=False)
            yield Static(theme.shorten_path(str(self.terminal.repo), 30), id="workspace-name", markup=False)
            yield Static("", id="counters", markup=False)
        with Horizontal(id="workspace"):
            with VerticalScroll(id="conversation"):
                with Vertical(id="welcome"):
                    yield Static(Text(WORDMARK, style=f"bold {theme.CYAN}"), id="welcome-brand")
                    yield Static("MISER  /  focused coding", id="welcome-name", markup=False)
                    yield Static("Your workspace. One focused change at a time.", id="welcome-title", markup=False)
                    yield Static("Describe a task, ask about the code, or review what changed.",
                                 id="welcome-sub", markup=False)
                    yield Static("", id="welcome-meta", markup=False)
                    yield Static("/help   /status   /diff   /files   /checks\n"
                                 "F2 diff · PgUp/PgDn scroll · Ctrl+P/Ctrl+N history · Ctrl+D exit",
                                 id="welcome-keys", markup=False)
            with VerticalScroll(id="inspector"):
                with Vertical(id="session-panel", classes="side-panel"):
                    yield Static("◈  Session", classes="panel-title", markup=False)
                    yield Static("", id="session-details", markup=False)
                    with Horizontal(id="session-state-row"):
                        yield LoadingIndicator(id="spinner")
                        yield Static("", id="activity", markup=False)
                with Vertical(id="recent-panel", classes="side-panel"):
                    yield Static("◷  Recent activity", classes="panel-title", markup=False)
                    yield Static("", id="recent-details", markup=False)
        yield Static("ACTIVITY · Ready", id="workline", markup=False)
        with Vertical(id="composer"):
            yield Composer(id="prompt", placeholder="› Ask about code, describe a change, or type /help", soft_wrap=True,
                           show_line_numbers=False, tab_behavior="focus", highlight_cursor_line=False)
            yield Static("Enter send · Ctrl+J newline · Tab complete · Ctrl+C cancel", id="composer-hints")
        yield Static("Ready · checks not run", id="statusbar", markup=False)

    def on_mount(self):
        self._main_screen = self.screen
        ensure_wakeup_poll(asyncio.get_running_loop())
        self.theme = "textual-dark"
        self._attach_backend()
        self._load_history()
        self.on_resize()
        self._show_home(True)
        self.ui(Composer).focus()
        self._refresh_welcome()
        self._refresh_recent()
        self.set_interval(.1, self._refresh_status)
        for text in self.initial:
            self._note(text)

    def ui(self, selector, expect_type=None):
        return self._main_screen.query_one(selector, expect_type)

    def on_resize(self, event: events.Resize | None = None):
        if not self.is_running:
            return
        width = event.size.width if event is not None else self.size.width
        height = event.size.height if event is not None else self.size.height
        if hasattr(self, "_main_screen"):
            self._main_screen.set_class(width < 118, "compact")
            self._main_screen.set_class(width < 96, "narrow")
            self._main_screen.set_class(height < 28, "short")
            self.ui("#inspector").display = width >= 118 and not self.ui("#welcome").display
        self.terminal.width_override = max(30, width - (36 if width >= 118 else 8))

    def _show_home(self, visible):
        """Switch presentation only; keep transcript/context and counters separate."""
        self.ui("#welcome").display = visible
        view = self.ui("#conversation", VerticalScroll)
        view.set_class(visible, "home")
        view.anchor(not visible)
        if visible:
            view.scroll_to(y=0, animate=False, immediate=True)
        self.on_resize()

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
            "prompt_delete_approval": self._approve_delete,
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

    def _approve_delete(self, path, diff):
        return self._wait_input(PendingInput("delete", f"Delete file · {path}", diff)) is True

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
            await self._append(Static(Text(data["source"]), classes="notice"))
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
                title = "Edited · tests not run (files mode)" if self.terminal.last_route == "files" else "Edited · tests not run (manual policy)"
            receipt = Path(data["directory"]).name
            text = f"{usage_phrase(bill)}\nElapsed {data['elapsed']:.2f}s   ·   receipt {receipt}"
            card = MessageCard("result" if bill["status"] == "tests_passed" else
                               "error" if data["error"] else "system", text, title)
            card.add_class("receipt")
            await self._append(card)
            if data["error"]:
                await self._append(MessageCard("error", data["error"], "Error"))
            self._remember_recent("Task " + ("completed" if bill["status"] == "tests_passed"
                                              else bill["status"].replace("_", " ")),
                                  True if bill["status"] == "tests_passed" else
                                  None if bill["status"] in {"answered", "edited_unverified", "needs_input", "interrupted"} else False)
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
            self._status = "Waiting for your answer" if request.kind == "question" else "Waiting for approval"
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
            if event["profile"] == "files":
                self._last_checks = "not run (files mode)"
            if event["profile"] == "coding":
                self._last_checks = "skipped (manual)" if event.get("test_policy") == "manual" else "pending"
            await self._append(Static(Text(f"Route: {event['profile']} · {event['verification']}"), classes="tool"))
        elif kind == "timing":
            await self._append(Collapsible(Static(Text(timing_line(event))),
                title=f"Timing · {event['wall_seconds']:.2f}s elapsed", collapsed=True, classes="timing"))
        elif kind == "model_start":
            self._status = f"Model request · step {event.get('step', '?')}"
        elif kind == "model_end":
            self._status = "Model response received"
        elif kind == "tool":
            name = event.get("name", "tool")
            if event.get("state") == "start":
                card = Static(Text.assemble(("● ", theme.CYAN), (name, "#d3cfc9"), ("  · running", "dim")),
                              classes="tool")
                self._tools[name].append(card)
                await self._append(card)
                verbs = {"zoom": "Reading", "read_many": "Reading files", "search": "Searching",
                         "find_files": "Locating files", "write_file": "Creating", "edit": "Editing",
                         "edit_batch": "Editing files", "delete_file": "Deleting", "run_tests": "Running checks"}
                path = theme.clean(str((event.get("args") or {}).get("path", "")))[:120]
                self._status = (verbs.get(name, name) + " " + path).strip()
            else:
                card = self._tools[name].popleft() if self._tools[name] else await self._append(Static(classes="tool"))
                ok = event.get("passed") if name == "run_tests" and "passed" in event else event.get("ok")
                if name == "run_tests" and "passed" in event:
                    self._last_checks = "passed" if ok else "failed"
                elapsed = event.get("elapsed")
                timing = f"{elapsed:.2f}s" if isinstance(elapsed, (int, float)) else ""
                detail = theme.clean(str(event.get("detail") or ""))[:90]
                row = Text.assemble(("✓ " if ok else "✗ ", theme.OK if ok else theme.BAD),
                                    (name, "#d3cfc9"))
                if detail:
                    row.append("  · " + detail, style="#8f8b86")
                if timing:
                    row.append("  · " + timing, style="#7f7b77")
                if not ok:
                    row.append("\n" + theme.clean(event.get("error") or ("Acceptance checks failed" if name == "run_tests" else "Tool failed; inspect the receipt")), style=theme.BAD)
                card.update(row)
                card.add_class("test-passed" if ok else "test-failed")
                self._remember_recent(f"{name}{'  ' + detail if detail else ''}", ok, timing)
        elif kind == "tests":
            label = ("Baseline checks (cached)" if event.get("cached") else "Baseline checks") if event.get("baseline") else "Acceptance checks"
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
            timing = f"{event['elapsed_seconds']:.2f}s" if isinstance(event.get("elapsed_seconds"), (int, float)) else ""
            self._remember_recent(label.replace(" checks", ""), passed, timing)
        elif kind in {"fallback", "compaction", "stream_interrupted", "model_unavailable", "agent_stopped"}:
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
            self._show_home(True)
            self.ui(Composer).load_text("")
            self._responses.clear()
            return
        self._show_home(False)
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

    def _refresh_welcome(self):
        if not self.is_mounted or not self.is_running:
            return
        terminal = self.terminal
        meta = (f"{theme.shorten_home(str(terminal.repo))}   ·   "
                f"{terminal.model or 'No model configured'}   ·   checks {self._last_checks}")
        self.ui("#welcome-meta", Static).update(Text(meta))

    def _remember_recent(self, label, ok=None, timing=""):
        self._recent.appendleft({"label": theme.clean(label), "ok": ok, "timing": timing})
        self._refresh_recent()

    def _refresh_recent(self):
        if not self.is_mounted or not self.is_running:
            return
        text = Text()
        if not self._recent:
            text.append("No completed work yet.", style="#807c78")
        for index, item in enumerate(self._recent):
            if index:
                text.append("\n")
            marker, color = ("✓", theme.OK) if item["ok"] is True else ("✖", theme.BAD) if item["ok"] is False else ("·", theme.MUTED)
            text.append(marker + "  ", style=color)
            timing = theme.clip(theme.clean(item["timing"]), 10)
            label_width = min(15, 28 - 3 - (2 + theme.display_width(timing) if timing else 0))
            text.append(theme.clip(item["label"], label_width), style="#c1bdb7")
            if timing:
                text.append("  " + timing, style="#7f7b77")
        self.ui("#recent-details", Static).update(text)

    def _checks_short(self):
        """Compact rail wording; the status bar keeps the full check state."""
        checks = self._last_checks
        if checks.startswith("failed"):
            return "failed"
        if "files mode" in checks:
            return "files: not run"
        if "manual" in checks:
            return "manual skip"
        if checks.startswith("baseline"):
            return "baseline"
        return checks

    def _session_text(self):
        terminal = self.terminal
        if not terminal.session_model_requests and not terminal.session_unknown_usage:
            usage = "no requests"
        else:
            usage = "unknown" if not terminal.session_provider_tokens else f"{terminal.session_provider_tokens:,}"
        rows = (("workspace", terminal.repo.name), ("budget", f"{terminal.budget:,}"),
                ("requests", str(terminal.session_model_requests)),
                ("tool calls", str(terminal.session_tool_calls)), ("known tokens", usage),
                ("last checks", self._checks_short()),
                ("edit review", "on" if terminal.confirm_edits else "off"))
        text = Text()
        for index, (key, value) in enumerate(rows):
            if index:
                text.append("\n")
            text.append(key.ljust(14), style="#85817c")
            clipped = theme.clip(theme.clean(value), 14)
            text.append(" " * max(0, 14 - theme.display_width(clipped)) + clipped, style="#c5c1bb")
        return text

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
        self.ui("#workline", Static).display = self.busy
        self.ui("#workline", Static).update(Text("ACTIVITY  ·  " + status))
        self.ui("#statusbar", Static).update(Text(
            f"checks {self._last_checks}   ·   {usage}   ·   {terminal.session_tasks_count} tasks"))
        self.ui("#session-details", Static).update(self._session_text())
        marker = "● "
        self.ui("#model", Static).update(Text.assemble((marker, theme.OK if not self.busy else theme.WARN),
                                                       (terminal.model or "No model configured", "#b6b2ac")))
        tokens = f"{terminal.session_provider_tokens:,} known tok"
        if terminal.session_unknown_usage:
            tokens = "usage unknown" if not terminal.session_provider_tokens else f"{terminal.session_provider_tokens:,} known + ?"
        tasks = terminal.session_tasks_count
        self.ui("#counters", Static).update(Text(f"{tokens}  ·  {tasks} task{'s' if tasks != 1 else ''}"))
        self.ui("#activity", Static).update(Text.assemble((marker, theme.OK if status == "Ready" else theme.WARN),
                                                          (status, "#b8c9cd")))
        self.ui("#spinner").display = self.busy
        self._refresh_welcome()

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
