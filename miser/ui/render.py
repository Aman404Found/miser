"""Width-aware rendering for the coding terminal.

The renderers return strings rather than printing, which keeps presentation
separate from the agent, the ledger, and the workspace. ANSI styling is applied
only when the output stream supports it, and layout is recomputed from the real
terminal width on every call so resizing stays correct.
"""

import re
import io
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import theme

try:  # Rich is the existing optional TUI extra, never a core dependency.
    from rich.console import Console
    from rich.markdown import Markdown, Heading, CodeBlock, TableElement, HorizontalRule
    from rich.text import Text
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.theme import Theme
    from rich import box
except ImportError:
    Markdown = None


if Markdown is not None:
    class _Separator(HorizontalRule):
        @classmethod
        def create(cls, markdown, token):
            element = cls()
            element.character = markdown.glyphs.rule
            return element

        def __rich_console__(self, console, options):
            yield Text(self.character * options.max_width, style=theme.FAINT)

    class _Heading(Heading):
        def __rich_console__(self, console, options):
            self.text.justify = "left"
            yield self.text

    class _Code(CodeBlock):
        @classmethod
        def create(cls, markdown, token):
            element = super().create(markdown, token)
            element.bar = markdown.glyphs.bar
            return element

        def __rich_console__(self, console, options):
            prefix = f"  {self.bar} "
            yield Text(prefix + self.lexer_name, style=f"dim {theme.CYAN}")
            source = str(self.text).removesuffix("\n").expandtabs(4)
            syntax = Syntax(source, self.lexer_name,
                            theme="monokai", background_color=theme.SURFACE,
                            word_wrap=True, padding=0)
            highlighted = syntax.highlight(source)[:len(source)]
            for logical in highlighted.split("\n", allow_blank=True):
                cuts, offset = [], 0
                for part in theme.fold(logical.plain, max(1, options.max_width - 4))[:-1]:
                    offset += len(part)
                    cuts.append(offset)
                for part in logical.divide(cuts):
                    row = Text(prefix, style=f"dim {theme.FAINT}")
                    row.append(part)
                    yield row
            yield Text(f"  {self.bar}", style=f"dim {theme.FAINT}")

    class _Table(TableElement):
        def __rich_console__(self, console, options):
            headers = self.header.row.cells if self.header and self.header.row else []
            rows = self.body.rows if self.body else []
            if len(headers) * 14 > options.max_width:
                for index, row in enumerate(rows):
                    if index:
                        yield Text("")
                    for column, cell in enumerate(row.cells):
                        label = headers[column].content if column < len(headers) else Text(str(column + 1))
                        yield Text.assemble(label, (": ", f"dim {theme.MUTED}"), cell.content)
                return
            table = Table(box=box.SIMPLE_HEAD, border_style=theme.FAINT,
                          header_style=f"bold {theme.TEXT}", padding=(0, 1), expand=False)
            for header in headers:
                table.add_column(header.content, overflow="fold")
            for row in rows:
                table.add_row(*(cell.content for cell in row.cells))
            yield table

    class _Markdown(Markdown):
        elements = {**Markdown.elements, "heading_open": _Heading, "fence": _Code,
                    "code_block": _Code, "table_open": _Table, "hr": _Separator}


@dataclass
class MarkdownBlock:
    """Original response retained for streaming replacement and width reflow."""
    source: str = ""
    _cache: tuple = field(default=(), init=False, repr=False)
    _rows: list = field(default_factory=list, init=False, repr=False)

    def lines(self, width):
        source = self.source
        key = (source, width)
        if self._cache != key:
            self._rows = markdown(source, width, color=True) or [""]
            self._cache = key
        return self._rows

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

TOOL_LABELS = {
    "repo_map": "index", "list_files": "list", "search": "search", "zoom": "read",
    "recall": "recheck", "edit": "edit", "edit_batch": "edit", "apply_patch": "patch",
    "blast_radius": "refs", "run_tests": "test", "verify_claim": "verify",
    "ask_user": "question",
    "mcp_list_tools": "external tools", "mcp_call": "external call",
    "write_todos": "plan", "web_search": "web", "fetch_url": "fetch",
}

STATUS_LABELS = {
    "tests_passed": ("tests passed", theme.green),
    "answered": ("answered", theme.dim),
    "edited_unverified": ("edited · tests not run", theme.yellow),
    "needs_input": ("needs your input", theme.yellow),
    "incomplete": ("no more tool calls", theme.yellow),
    "truncated": ("output truncated", theme.yellow),
    "step_limit": ("step limit reached", theme.yellow),
    "budget_exhausted": ("token budget exhausted", theme.yellow),
    "budget_exceeded": ("token budget exceeded", theme.yellow),
    "interrupted": ("interrupted", theme.yellow),
    "stream_interrupted": ("stream interrupted", theme.yellow),
    "rejected_non_coding": ("not a coding task", theme.dim),
    "model_unavailable": ("model unavailable", theme.yellow),
    "error": ("failed", theme.red),
}


def _glyphs(glyphs=None):
    return glyphs or theme.symbols()


# -- framing ---------------------------------------------------------------

def header(version, model, workspace, width, glyphs=None):
    g = _glyphs(glyphs)
    title = f"{theme.bold('MISER')} {theme.dim(version)}"
    right = theme.dim("/help for commands")
    lines = [theme.pad_between(title, right, width)]
    details = [theme.cyan(model or "no model configured")]
    details.append(theme.dim(theme.shorten_path(workspace, max(20, width - 24))))
    lines.append(" · ".join(details))
    lines.append(theme.dim(g.rule * min(width, 72)))
    return "\n".join(lines)


def status_line(model, workspace, budget, tests, approvals, width, glyphs=None):
    g = _glyphs(glyphs)
    left = theme.cyan(model or "no model configured")
    left += theme.dim(" · ") + theme.dim(Path(str(workspace)).name or str(workspace))
    right_bits = [f"budget {budget // 1000}k"]
    right_bits.append("tests set" if tests else "tests unset")
    right_bits.append("approvals on" if approvals else "approvals off")
    return theme.pad_between(left, theme.dim(" · ".join(right_bits)), width)


def prompt(glyphs=None):
    g = _glyphs(glyphs)
    if theme.color_enabled():
        return f"{theme.bold(theme.cyan(g.prompt))} "
    return "miser > "


def user_block(text, width, glyphs=None):
    g = _glyphs(glyphs)
    lines = []
    for index, logical in enumerate(str(text).splitlines() or [""]):
        wrapped = theme.wrap(logical, width - 2) if logical else [""]
        for position, line in enumerate(wrapped):
            if index == 0 and position == 0:
                lines.append(f"{theme.cyan(g.user)} {line}")
            else:
                lines.append(f"  {line}")
    return "\n".join(lines)


def agent_label(model, width=0, glyphs=None):
    g = _glyphs(glyphs)
    label = f"{theme.cyan(g.agent)} {theme.bold('MISER')}"
    if model:
        available = max(0, width - theme.display_width(label) - 3) if width else len(model)
        if available:
            label += theme.dim(" · " + theme.clip(model, available))
    return label


def notice(text, width=None, glyphs=None):
    g = _glyphs(glyphs)
    lines = theme.wrap(theme.clean(text), max(20, (width or theme.term_width()) - 4))
    out = [theme.dim(f"  {g.info} {lines[0]}")]
    out.extend(theme.dim("    " + line) for line in lines[1:])
    return "\n".join(out)


def warning(text, width=None, glyphs=None):
    g = _glyphs(glyphs)
    lines = theme.wrap(theme.clean(text), max(20, (width or theme.term_width()) - 4))
    out = [theme.yellow(f"  {g.warn} {lines[0]}")]
    out.extend("    " + line for line in lines[1:])
    return "\n".join(out)


def error_block(title, detail=None, hint=None, width=None, glyphs=None):
    g = _glyphs(glyphs)
    width = max(30, (width or theme.term_width()) - 4)
    lines = [f"{theme.red(g.fail)} {theme.bold(theme.clean(title))}"]
    if detail:
        text = " ".join(str(detail).split())
        for line in theme.wrap(theme.clean(text), width):
            lines.append("  " + line)
    if hint:
        for line in theme.wrap(theme.clean(hint), width - 2):
            lines.append(theme.dim(f"  {g.arrow} {line}"))
    return "\n".join(lines)


def panel(title, items, width=None, glyphs=None, indent="  "):
    """A light framed list; no right border, so values never overflow the frame."""
    g = _glyphs(glyphs)
    width = max(40, (width or theme.term_width()) - len(indent))
    key_width = min(16, max((theme.visible_len(key) for key, _ in items), default=12) + 1)
    lines = [f"{indent}{theme.dim(g.rule)} {theme.bold(title)}"]
    for key, value in items:
        prefix = f"{indent}{theme.dim(g.bar)} {theme.dim(key.ljust(key_width))} "
        continuation = f"{indent}{theme.dim(g.bar)} " + " " * (key_width + 1)
        wrapped = theme.wrap(theme.clean(value), width - key_width - 4)
        lines.append(prefix + wrapped[0])
        lines.extend(continuation + line for line in wrapped[1:])
    return "\n".join(lines)


# -- markdown --------------------------------------------------------------

def _inline(text):
    pieces = re.split(r"(`[^`]*`|\*\*[^*]+\*\*)", str(text))
    out = []
    for piece in pieces:
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 1:
            out.append(theme.cyan(piece[1:-1]))
        elif piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            out.append(theme.bold(piece[2:-2]))
        else:
            out.append(piece)
    return "".join(out)


def render_line(line, width, glyphs=None, fence=None):
    """Render one markdown line. Returns (output_lines, next_fence)."""
    g = _glyphs(glyphs)
    stripped = line.strip()
    if fence is not None:
        if stripped.startswith("```"):
            return [theme.dim(f"  {g.bar}")], None
        return [theme.dim(f"  {g.bar} ") + part for part in theme.fold(line, max(1, width - 4))], fence
    if stripped.startswith("```"):
        language = stripped[3:].strip() or "code"
        return [theme.dim(f"  {g.bar} {language}")], language
    if not stripped:
        return [""], None
    heading = HEADING_RE.match(line)
    if heading:
        level, text = len(heading.group(1)), heading.group(2)
        if level == 1:
            return theme.wrap(theme.bold(_inline(text)), width) + [theme.dim(g.rule * min(width, 60))], None
        return theme.wrap(theme.bold(_inline(text)), width), None
    bullet = BULLET_RE.match(line)
    if bullet:
        prefix = " " * len(bullet.group(1)) + f"{g.bullet} "
        return theme.wrap(_inline(bullet.group(2)), width, initial=prefix,
                          subsequent=" " * len(prefix)), None
    ordered = ORDERED_RE.match(line)
    if ordered:
        prefix = " " * len(ordered.group(1)) + ordered.group(2) + ". "
        return theme.wrap(_inline(ordered.group(3)), width, initial=prefix,
                          subsequent=" " * len(prefix)), None
    quote = QUOTE_RE.match(line)
    if quote:
        return theme.wrap(theme.italic(_inline(quote.group(1))), width,
                          initial=f"  {g.bar} ", subsequent=f"  {g.bar} "), None
    return theme.wrap(_inline(line), width), None


def markdown(text, width=None, glyphs=None, color=None):
    """Shared Markdown renderer; Rich when installed, stdlib fallback otherwise."""
    width = max(20, width or theme.term_width())
    if Markdown is not None:
        buffer = io.StringIO()
        colored = theme.color_enabled() if color is None else color
        console = Console(file=buffer, width=width, height=10000, force_terminal=colored,
                          color_system="truecolor" if colored else None, no_color=not colored, highlight=False,
                          theme=Theme({"markdown.h1": f"bold {theme.TEXT}",
                                       "markdown.h2": f"bold {theme.CYAN}",
                                       "markdown.code": f"{theme.CYAN} on {theme.SURFACE}",
                                       "markdown.link": f"underline {theme.CYAN}",
                                       "markdown.link_url": f"dim {theme.MUTED}"}))
        document = _Markdown(theme.clean(text), hyperlinks=False, justify="left", style=theme.TEXT)
        document.glyphs = _glyphs(glyphs)
        console.print(document, end="")
        rows = buffer.getvalue().splitlines()
        prefix = f"  {document.glyphs.bar} "
        return [row if theme.ANSI_RE.sub("", row).startswith(prefix) else
                re.sub(r" +(?=(?:\x1b\[[0-9;]*m)*$)", "", row) for row in rows]
    lines, fence, blank = [], None, False
    for raw in theme.clean(text).splitlines():
        rendered, fence = render_line(raw, width, glyphs, fence)
        for line in rendered:
            if line == "":
                if lines and not blank:
                    lines.append("")
                blank = True
                continue
            lines.append(line)
            blank = False
    if fence is not None:
        lines.append(theme.dim(f"  {_glyphs(glyphs).bar}"))
    return lines


def markdown_text(text, width=None, glyphs=None):
    return "\n".join(markdown(text, width, glyphs))


class MarkdownStream:
    """Incremental markdown rendering for streamed model output.

    Complete lines render with formatting; a long unterminated paragraph is cut
    at a word boundary and emitted as it grows so text appears while it arrives.
    """

    def __init__(self, emit, width=None, glyphs=None, replace=None):
        self.emit = emit
        self.width = max(20, width or theme.term_width())
        self.glyphs = glyphs or theme.symbols()
        self.buffer = ""
        self.fence = None
        self.started = False
        self.finished = False
        self.replace = replace
        self.raw = ""
        self._last_update = 0.0
        self._table = []
        self._delimiter = ""

    def _emit_line(self, line):
        opening = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if self.fence is None and opening:
            self._delimiter = opening[1]
            self.fence = opening[2].strip() or "code"
            self.emit(theme.dim(f"  {self.glyphs.bar} {self.fence}"))
            return
        if self.fence is not None:
            if re.fullmatch(r"\s*" + re.escape(self._delimiter[0]) + "{" + str(len(self._delimiter)) + r",}\s*", line):
                self.emit(theme.dim(f"  {self.glyphs.bar}"))
                self.fence = None
            else:
                for part in theme.fold(line, max(1, self.width - 4)):
                    self.emit(theme.dim(f"  {self.glyphs.bar} ") + part)
            return
        if Markdown is not None:
            for item in markdown(line, self.width, self.glyphs) or [""]:
                self.emit(item)
            return
        rendered, self.fence = render_line(line, self.width, self.glyphs, self.fence)
        for item in rendered:
            self.emit(item)

    def _consume_line(self, line):
        if self.fence is None and (self._table or line.count("|") >= 2):
            if line.strip() and "|" in line:
                self._table.append(line)
                return
            self._flush_table()
        self._emit_line(line)

    def _flush_table(self):
        if self._table:
            for item in markdown("\n".join(self._table), self.width, self.glyphs):
                self.emit(item)
            self._table = []

    def feed(self, chunk):
        if not chunk or self.finished:
            return
        self.started = True
        self.raw += chunk
        if self.replace is not None:
            now = time.monotonic()
            if not self._last_update or now - self._last_update >= 0.04:
                self.replace(self.raw)
                self._last_update = now
            return
        self.buffer += chunk.replace("\r\n", "\n")
        while True:
            if self.fence is not None:
                index = self.buffer.find("\n")
                if index < 0:
                    return
                line, self.buffer = self.buffer[:index], self.buffer[index + 1:]
                self._consume_line(line)
                continue
            index = self.buffer.find("\n")
            if index >= 0:
                line, self.buffer = self.buffer[:index], self.buffer[index + 1:]
                self._consume_line(line)
                continue
            if theme.display_width(self.buffer) > self.width:
                # Inline constructs need their closing delimiter before append-only
                # output is committed. The TUI instead replaces a live raw block.
                if any(marker in self.buffer for marker in ("*", "`", "[", "|", "~", "_")):
                    return
                cut = self.buffer.rfind(" ", 0, self.width)
                if cut <= 0:
                    cut = self.width
                piece, self.buffer = self.buffer[:cut], self.buffer[cut:].lstrip()
                self._emit_line(piece)
                continue
            return

    def finish(self):
        if self.finished:
            return
        self.finished = True
        if self.replace is not None:
            self.replace(self.raw)
            return
        if self._table:
            if self.buffer:
                self._table.append(self.buffer)
                self.buffer = ""
            self._flush_table()
        if self.buffer:
            self._emit_line(self.buffer)
            self.buffer = ""
        if self.fence is not None:
            self.emit(theme.dim(f"  {self.glyphs.bar}"))
        self.fence = None


# -- activity --------------------------------------------------------------

def tool_detail(name, args):
    args = args or {}
    path = args.get("path") or ""
    if name == "search":
        return f'"{args.get("query", "")}"'
    if name in ("zoom", "recall", "edit"):
        symbol = args.get("symbol")
        start, end = args.get("start"), args.get("end")
        extra = f" · {symbol}" if symbol else (f" · lines {start}–{end}" if start and end else "")
        return f"{path}{extra}"
    if name == "edit_batch":
        edits = args.get("edits") or []
        names = sorted({str(item.get("path")) for item in edits if isinstance(item, dict)})
        return ", ".join(names) or "files"
    if name == "apply_patch":
        return "unified diff"
    if name == "blast_radius":
        return f'"{args.get("symbol", "")}"'
    if name == "run_tests":
        return "acceptance command"
    if name == "verify_claim":
        return f'"{args.get("claim", "")[:48]}"'
    if name == "repo_map":
        return args.get("query", "") or "workspace"
    if name == "write_todos":
        todos = args.get("todos") or []
        done = sum(1 for item in todos if isinstance(item, dict) and item.get("completed"))
        return f"{done}/{len(todos)} done" if todos else ""
    if name == "web_search":
        return f'"{args.get("query", "")[:60]}"'
    if name == "fetch_url":
        return str(args.get("url") or "")[:80]
    return ""


def tool_running(name, args):
    label = TOOL_LABELS.get(name, name)
    detail = tool_detail(name, args)
    return f"{label} {detail}".strip()


def tool_result(name, event, glyphs=None):
    g = _glyphs(glyphs)
    ok = event.get("ok", True)
    label = TOOL_LABELS.get(name, name)
    detail = event.get("detail") or ""
    elapsed = event.get("elapsed")
    timing = theme.dim(f" · {elapsed:.1f}s") if isinstance(elapsed, (int, float)) else ""
    if not ok:
        error = theme.clean(event.get("error") or "tool failed")
        return f"  {theme.red(g.fail)} {label} {theme.red(error)}{timing}"
    line = f"  {theme.green(g.ok)} {label}"
    if detail:
        line += " " + theme.dim(detail)
    return line + timing


def todo_list(items, total=None, completed=None, width=None, glyphs=None):
    """One compact checklist for a ``write_todos`` update."""
    g = _glyphs(glyphs)
    width = max(30, width or theme.term_width())
    items = [item for item in (items or []) if isinstance(item, dict)]
    total = len(items) if total is None else total
    completed = (sum(1 for item in items if item.get("completed"))
                 if completed is None else completed)
    done_mark = g.ok if g.fancy else "x"
    open_mark = "○" if g.fancy else " "
    lines = [f"  {theme.bold('plan')} {theme.dim(f'{completed}/{total} done')}"]
    for item in items:
        task = theme.clean(str(item.get("task", "")))
        body = theme.clip(task, width - 8)
        if item.get("completed"):
            lines.append(f"  {theme.dim(g.bar)} {theme.green(done_mark)} {theme.dim(body)}")
        else:
            lines.append(f"  {theme.dim(g.bar)} {theme.dim(open_mark)} {body}")
    return "\n".join(lines)


def test_result(event, glyphs=None):
    g = _glyphs(glyphs)
    passed = event.get("passed")
    elapsed = event.get("elapsed")
    timing = theme.dim(f" · {elapsed:.1f}s") if isinstance(elapsed, (int, float)) else ""
    if passed:
        return f"  {theme.green(g.ok)} acceptance tests passed{timing}"
    if event.get("timed_out"):
        return f"  {theme.red(g.fail)} acceptance tests timed out{timing}"
    code = event.get("exit_code")
    return f"  {theme.red(g.fail)} acceptance tests failed (exit {code}){timing}"


# -- diffs -----------------------------------------------------------------

def diff_files(diff_text):
    files, current = [], None
    for line in str(diff_text or "").splitlines():
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            current = {"path": path, "added": 0, "removed": 0}
            files.append(current)
        elif current is not None and line.startswith("+") and not line.startswith("+++"):
            current["added"] += 1
        elif current is not None and line.startswith("-") and not line.startswith("---"):
            current["removed"] += 1
    return files


def diff_summary_line(files, glyphs=None):
    if not files:
        return ""
    added = sum(item["added"] for item in files)
    removed = sum(item["removed"] for item in files)
    names = ", ".join(item["path"] for item in files[:3])
    if len(files) > 3:
        names += f" +{len(files) - 3} more"
    return f"{names}  {theme.green('+' + str(added))} {theme.red('−' + str(removed))}"


def render_diff(diff_text, width=None, max_lines=120, glyphs=None):
    """Render a unified diff with file headers, hunk context, and gutters."""
    g = _glyphs(glyphs)
    width = max(30, width or theme.term_width())
    text = str(diff_text or "")
    if not text.strip():
        return theme.dim("  no changes")
    files = {item["path"]: item for item in diff_files(text)}
    raw_lines = text.splitlines()
    limit = float("inf") if max_lines is None else max(1, int(max_lines))
    out = []
    old_line = new_line = 0
    truncation = ""
    for index, line in enumerate(raw_lines):
        if len(out) >= limit:
            remaining = len(raw_lines) - index
            truncation = theme.dim(f"  … {remaining} more diff lines")
            break
        if line.startswith("+++ "):
            path = line[4:].strip()
            if path.startswith("b/"):
                path = path[2:]
            stats = files.get(path, {"added": 0, "removed": 0})
            out.append("")
            out.extend(theme.wrap(f"{theme.bold(path)}  "
                                 f"{theme.green('+' + str(stats['added']))} "
                                 f"{theme.red('−' + str(stats['removed']))}", width))
            continue
        if line.startswith("--- ") or line.startswith("diff --git") or line.startswith("index "):
            continue
        match = HUNK_RE.match(line)
        if match:
            old_line, new_line = int(match.group(1)), int(match.group(3))
            out.append(theme.dim("  " + theme.clip(line, width - 2)))
            continue
        if line.startswith("\\"):
            out.append(theme.dim("  " + line))
            continue
        if line.startswith("+"):
            for position, part in enumerate(theme.fold(line[1:], width - 9)):
                out.append(theme.dim(f"{new_line:>5}" if position == 0 else "     ") +
                           theme.green(" + " if position == 0 else "   ") + theme.change(part, True))
            new_line += 1
        elif line.startswith("-"):
            for position, part in enumerate(theme.fold(line[1:], width - 9)):
                out.append(theme.dim(f"{old_line:>5}" if position == 0 else "     ") +
                           theme.red(" - " if position == 0 else "   ") + theme.change(part, False))
            old_line += 1
        elif line.startswith(" "):
            for position, part in enumerate(theme.fold(line[1:], width - 9)):
                out.append(theme.dim(f"{new_line:>5}" if position == 0 else "     ") + "   " + part)
            old_line += 1
            new_line += 1
        else:
            out.append(theme.dim("  " + theme.clip(line, width - 2)))
    if truncation:
        out.append(truncation)
    return "\n".join(out)


def approval_header(path, diff_text, width=None):
    files = diff_files(diff_text)
    stats = next((item for item in files if item["path"] == path), {"added": 0, "removed": 0})
    return (f"{theme.bold('proposed edit')}  {theme.cyan(path)}  "
            f"{theme.green('+' + str(stats['added']))} {theme.red('−' + str(stats['removed']))}")


# -- repository map --------------------------------------------------------

def repo_map(result, width=None, glyphs=None):
    g = _glyphs(glyphs)
    width = max(30, width or theme.term_width())
    entries = result.get("entries") or []
    if not entries:
        return theme.dim("  no readable source files")
    lines = []
    for entry in entries:
        path = entry.get("path", "")
        seen = []
        for item in entry.get("symbols") or []:
            name = item.get("name", "")
            if name and name not in seen:
                seen.append(name)
        symbols = ", ".join(seen)
        line = f"  {theme.cyan(path)}"
        if symbols:
            line += theme.dim("  ·  ") + theme.dim(theme.clip(symbols, max(10, width - theme.display_width(path) - 4)))
        lines.append(line)
    if result.get("truncated"):
        lines.append(theme.dim("  … truncated to fit the context budget"))
    return "\n".join(lines)


# -- task results ----------------------------------------------------------

def result_panel(bill, elapsed, width=None, prefix="task", glyphs=None):
    g = _glyphs(glyphs)
    width = width or theme.term_width()
    status = bill.get("status", "unknown")
    label, color = STATUS_LABELS.get(status, (status, theme.dim))
    if status == "tests_passed":
        glyph = g.ok
        label = "Task completed · tests passed"
    elif status == "answered":
        glyph = g.info
    elif status in ("incomplete", "truncated", "step_limit", "budget_exhausted", "budget_exceeded",
                    "interrupted", "stream_interrupted", "rejected_non_coding",
                    "model_unavailable", "needs_input", "edited_unverified"):
        glyph = g.warn
    else:
        glyph = g.fail
    lines = [f"{color(glyph)} {theme.bold(label)}"
             f"{theme.dim(f'  ·  {elapsed:.1f}s')}"]
    usage = usage_phrase(bill)
    if usage:
        lines.extend(theme.dim(line) for line in theme.wrap(usage, width, initial="  ", subsequent="  "))
    if status == "model_unavailable":
        lines.append(theme.dim("  retried automatically; wait, or /model primary,fallback"))
    if status == "truncated":
        lines.append(theme.dim("  the reply was cut off by the output cap; retry with a narrower ask"))
    return "\n".join(lines)


def usage_phrase(bill):
    calls = bill.get("model_calls", 0)
    if not calls:
        if bill.get("failed_model_requests"):
            return "no completed model requests; usage unknown"
        return "no model requests"
    tokens = bill.get("total_tokens", 0)
    phrase = (f"{tokens:,} provider tokens "
              f"({bill.get('input_tokens', 0):,} in / {bill.get('output_tokens', 0):,} out)")
    phrase += f" · {calls} model request{'s' if calls != 1 else ''}"
    tools = bill.get("tool_calls", 0)
    if tools:
        phrase += f" · {tools} tool call{'s' if tools != 1 else ''}"
    if not bill.get("usage_complete", False):
        phrase += " · usage incomplete"
    return phrase


def session_usage_panel(snapshot, width=None, glyphs=None):
    tokens = snapshot.get("provider_tokens", 0)
    requests = snapshot.get("model_requests", 0)
    if requests == 0:
        token_text = "no model requests yet"
    else:
        token_text = (f"{tokens:,} provider tokens "
                      f"({snapshot.get('input_tokens', 0):,} in / {snapshot.get('output_tokens', 0):,} out)")
        if snapshot.get("unknown_usage"):
            token_text += f" · {snapshot['unknown_usage']} unmetered request(s)"
    context = snapshot.get("context_estimate")
    items = [
        ("User messages", f"{snapshot.get('user_messages', 0)}"),
        ("Coding tasks", f"{snapshot.get('tasks', 0)} completed"),
        ("Model requests", f"{requests}"),
        ("Tool executions", f"{snapshot.get('tool_calls', 0)}"),
        ("Provider tokens", token_text),
        ("Context", f"~{context:,} tokens (local estimate)" if context else "not measured yet"),
        ("Receipts", snapshot.get("last_receipt") or "none yet"),
    ]
    return panel("session usage", items, width, glyphs)


def history_lines(history, glyphs=None):
    g = _glyphs(glyphs)
    lines = []
    for index, item in enumerate(history, 1):
        status = item.get("status", "unknown")
        _, color = STATUS_LABELS.get(status, (status, theme.dim))
        badge = color(g.ok if status == "tests_passed" else g.info)
        tokens = f"{item.get('tokens', 0):,} tok"
        lines.append(f"  {badge} {index:>2}  {theme.dim(tokens):>12}  "
                     f"{theme.clip(item.get('task', ''), 60)}")
    return "\n".join(lines)


def hint_line(parts, glyphs=None):
    g = _glyphs(glyphs)
    return theme.dim("  " + " · ".join(parts))


def error_hint(error):
    """Turn a transport or configuration failure into an actionable next step."""
    text = str(error).lower()
    if "cannot reach remote service" in text or "connection refused" in text:
        return "Start the gateway (npx -y @maximhq/bifrost) and check BIFROST_URL."
    if "http 401" in text:
        return "Set BIFROST_VIRTUAL_KEY (or BIFROST_API_KEY) for this gateway; never commit keys."
    if "http 403" in text:
        return "Check the gateway provider/model permissions and upstream account access."
    if "http 429" in text or "http 503" in text:
        return "Wait, or configure a fallback with /model primary,fallback."
    if "lacks valid usage" in text:
        return "The gateway omitted usage; disable streaming or enable usage reporting."
    return None


def timing_line(timing):
    """Compact host timing, keeping overlapping sums and missing data explicit."""
    line = (f"Elapsed {timing['wall_seconds']:.2f}s · Model requests {timing['model_seconds']:.2f}s"
            f" · Tests {timing['test_seconds']:.2f}s · Other tools (sum) {timing['tool_seconds_sum']:.2f}s")
    if timing.get("missing_durations"):
        line += f" · {timing['missing_durations']} duration(s) unknown"
    return line
