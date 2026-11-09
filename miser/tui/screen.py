"""Pure composition for the MISER full-screen interface.

The function :func:`render` maps a state snapshot plus terminal dimensions to a
fixed list of Rich ``Text`` lines. It performs no terminal I/O, so the welcome
screen, conversation layout, scrolling, and narrow-terminal behaviour can all
be tested without a pseudo-terminal.
"""

from dataclasses import dataclass, field

from rich.style import Style
from rich.text import Text

BG = "#0b0c0e"
TEXT = "#e6e7eb"
MUTED = "#8b8f9a"
FAINT = "#3b3f49"
ACCENT = "#4f8cff"
COMPOSER_BG = "#15171c"
OK = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"


def _style(color=TEXT, bg=BG, bold=False, italic=False, reverse=False):
    return Style(color=color, bgcolor=bg, bold=bold, italic=italic, reverse=reverse)


BG_STYLE = _style()
FAINT_STYLE = _style(FAINT)
MUTED_STYLE = _style(MUTED)


@dataclass
class UIState:
    width: int = 100
    height: int = 30
    mode: str = "welcome"
    model: str = ""
    workspace: str = ""
    budget: int = 0
    tasks: int = 0
    requests: int = 0
    tokens: str = ""
    tests: str = ""
    approvals: bool = False
    input_text: str = ""
    cursor: int = 0
    transcript: list = field(default_factory=list)
    scroll: int = 0
    busy: bool = False
    status: str = "idle"
    spinner: str = "·"
    elapsed: float = 0.0
    suggestions: list = field(default_factory=list)
    approval: str = ""


# -- low-level line helpers ------------------------------------------------


def blank(width):
    return Text(" " * max(0, width), style=BG_STYLE)


def fit(text, width, bg=BG):
    if not isinstance(text, Text):
        text = Text(str(text), style=_style(bg=bg))
    out = text.copy()
    out.no_wrap = True
    if out.cell_len > width:
        out.truncate(max(0, width), overflow="crop")
    if out.cell_len < width:
        out.append(" " * (width - out.cell_len), style=_style(bg=bg))
    out.no_wrap = True
    return out


def line(parts, width, bg=BG):
    text = Text(style=_style(bg=bg))
    for part in parts:
        if isinstance(part, Text):
            text.append(part)
        else:
            value, style = part
            text.append(value, style=style or _style(bg=bg))
    return fit(text, width, bg=bg)


def centered(content, width):
    content = content.copy()
    content.no_wrap = True
    if content.cell_len > width:
        content.truncate(width, overflow="crop")
    left = max(0, (width - content.cell_len) // 2)
    out = Text(" " * left, style=BG_STYLE)
    out.append(content)
    out.append(" " * max(0, width - left - content.cell_len), style=BG_STYLE)
    return fit(out, width)


def placed(content, left, width):
    left = max(0, min(left, width))
    out = Text(" " * left, style=BG_STYLE)
    out.append(content)
    return fit(out, width)


MAX_CONTENT_WIDTH = 92


def content_width(width):
    """One readable column: generous gutters, never wider than 92 cells."""
    width = max(0, int(width))
    if width <= 44:
        return max(20, width - 2)
    return min(MAX_CONTENT_WIDTH, max(20, width - 8))


def content_left(width):
    return max(0, (max(0, int(width)) - content_width(width)) // 2)


def column_row(content, width):
    """Place content in the single content column, padded out to the full width."""
    return placed(content, content_left(width), width)


# -- logo ------------------------------------------------------------------

_FONT = {
    "M": ["██  ██", "███ ██", "██ ███", "██  ██", "██  ██"],
    "I": ["██████", "  ██  ", "  ██  ", "  ██  ", "██████"],
    "S": ["██████", "██    ", "██████", "    ██", "██████"],
    "E": ["██████", "██    ", "█████ ", "██    ", "██████"],
    "R": ["█████ ", "██  ██", "█████ ", "██ ██ ", "██  ██"],
}


def logo_lines(width):
    if width < 48:
        return [centered(Text("M I S E R", style=_style(TEXT, bold=True)), width)]
    rows = []
    for row_index in range(5):
        row = Text(style=_style(TEXT, bold=True))
        for letter_index, letter in enumerate("MISER"):
            if letter_index:
                row.append("  ", style=BG_STYLE)
            row.append(_FONT[letter][row_index], style=_style(TEXT, bold=True))
        rows.append(centered(row, width))
    return rows


# -- composer --------------------------------------------------------------


def _wrap_rows(text, width):
    width = max(1, width)
    rows = []
    index = 0
    for hard in str(text).split("\n"):
        if hard == "":
            rows.append(("", index, index))
        else:
            position = 0
            while position < len(hard):
                if len(hard) - position <= width:
                    rows.append((hard[position:], index + position, index + len(hard)))
                    break
                cut = hard.rfind(" ", position, position + width)
                if cut <= position:
                    cut = position + width
                rows.append((hard[position:cut].rstrip(), index + position, index + cut))
                position = cut
                while position < len(hard) and hard[position] == " ":
                    position += 1
        index += len(hard) + 1
    return rows


def _composer_contents(state, inner, placeholder):
    inner = max(4, inner)
    if not state.input_text:
        content = Text(style=_style(bg=COMPOSER_BG))
        content.append(" ", style=_style(bg=COMPOSER_BG))
        content.append(placeholder, style=_style(color=MUTED, bg=COMPOSER_BG, italic=True))
        return [_inner_pad(content, inner)], 0
    rows = _wrap_rows(state.input_text, inner)
    cursor = max(0, min(state.cursor, len(state.input_text)))
    cursor_row = len(rows) - 1
    for row_index, (_, start, end) in enumerate(rows):
        if start <= cursor <= end:
            cursor_row = row_index
            break
    rendered = []
    for row_index, (segment, start, end) in enumerate(rows):
        content = Text(style=_style(bg=COMPOSER_BG))
        for offset, char in enumerate(segment):
            if start + offset == cursor:
                content.append(char, style=_style(color=BG, bg=ACCENT, bold=True))
            else:
                content.append(char, style=_style(bg=COMPOSER_BG))
        if cursor == end and start <= cursor <= end and cursor_row == row_index:
            content.append(" ", style=_style(color=BG, bg=ACCENT))
        rendered.append(_inner_pad(content, inner))
    return rendered, cursor_row


def _inner_pad(text, inner, bg=COMPOSER_BG):
    text = text.copy()
    text.no_wrap = True
    if text.cell_len > inner:
        text.truncate(inner, overflow="crop")
    if text.cell_len < inner:
        text.append(" " * (inner - text.cell_len), style=_style(bg=bg))
    return text


def _card_row(content, card_width):
    row = Text(style=BG_STYLE)
    row.append("▌", style=_style(color=ACCENT, bold=True))
    row.append(" ", style=_style(bg=COMPOSER_BG))
    row.append(content)
    row.append(" ", style=_style(bg=COMPOSER_BG))
    return fit(row, card_width)


def composer(state, card_width, placeholder, show_meta=True):
    inner = max(4, card_width - 3)
    contents, cursor_row = _composer_contents(state, inner, placeholder)
    if len(contents) > 4:
        start = min(max(0, cursor_row - 3), len(contents) - 4)
        contents = contents[start:start + 4]
    lines = [_card_row(content, card_width) for content in contents]
    if show_meta:
        lines.append(_card_row(_inner_pad(Text("", style=_style(bg=COMPOSER_BG)), inner), card_width))
        meta = Text(style=_style(bg=COMPOSER_BG))
        meta.append("chat", style=_style(color=ACCENT, bg=COMPOSER_BG, bold=True))
        meta.append("  ·  ", style=_style(color=FAINT, bg=COMPOSER_BG))
        meta.append(state.model or "no model", style=_style(bg=COMPOSER_BG))
        meta.append("  ·  ", style=_style(color=FAINT, bg=COMPOSER_BG))
        meta.append(f"{max(0, state.budget) // 1000}k budget", style=_style(color=MUTED, bg=COMPOSER_BG))
        if state.approvals:
            meta.append("  ·  approvals on", style=_style(color=MUTED, bg=COMPOSER_BG))
        lines.append(_card_row(_inner_pad(meta, inner), card_width))
    return lines


# -- welcome ---------------------------------------------------------------


def _short_workspace(workspace):
    value = str(workspace or "")
    if value.startswith("/home/"):
        parts = value.split("/")
        if len(parts) >= 4:
            value = "~/" + "/".join(parts[3:])
    if len(value) > 28:
        parts = [part for part in value.split("/") if part]
        if len(parts) >= 2:
            parent = parts[-2] if len(parts[-2]) <= 14 else parts[-2][:13] + "…"
            value = f"…/{parent}/{parts[-1]}"
        else:
            value = "…/" + (parts[-1][-20:] if parts else value[-20:])
        if len(value) > 28:
            value = "…/" + (parts[-1][-20:] if parts else value[-20:])
    return value or "."


def _welcome(state):
    width, height = state.width, state.height
    compact = height < 18
    logo = logo_lines(width)
    tagline = centered(
        Text("focused coding agent  ·  type a task or /help", style=_style(color=MUTED)),
        width,
    )
    card_width = content_width(width)
    card = [column_row(row, width) for row in composer(state, card_width, 'Ask anything… "Fix a failing test in pricing.py"', show_meta=True)]

    workspace = _short_workspace(state.workspace)
    hints = "tab complete   ctrl+j newline   ctrl+d exit"
    if card_width < 68:
        hints = "tab complete · ctrl+d exit"
    footer_parts = [("  ", None), (workspace, MUTED_STYLE)]
    if 2 + len(workspace) + 1 + len(hints) <= card_width:
        footer_parts.append((" " * (card_width - 2 - len(workspace) - len(hints)), None))
        footer_parts.append((hints, MUTED_STYLE))
    footer = column_row(line(footer_parts, card_width), width)

    block = list(logo)
    if not compact:
        block.append(blank(width))
        block.append(tagline)
        block.append(blank(width))
    else:
        block.append(blank(width))
    block.extend(card)
    block.append(blank(width))
    block.append(footer)
    if state.suggestions:
        block.append(
            centered(Text("   ".join(state.suggestions[:6]), style=_style(color=FAINT)), width)
        )

    top = 0 if compact else max(0, (height - len(block)) // 2)
    lines = [blank(width) for _ in range(top)]
    lines.extend(block)
    return lines


# -- conversation ----------------------------------------------------------


def _rule(width):
    inner = content_width(width)
    return column_row(line([("─" * inner, FAINT_STYLE)], inner), width)


def _header(state, width):
    inner = content_width(width)
    left = Text(style=_style(bg=BG))
    left.append("MISER", style=_style(color=TEXT, bold=True))
    left.append("  ", style=BG_STYLE)
    left.append(state.model or "no model", style=_style(color=MUTED))
    right_bits = []
    if state.scroll:
        right_bits.append(f"↑ {state.scroll} lines")
    if state.tokens:
        right_bits.append(state.tokens)
    right_bits.append(f"{state.tasks} task" + ("" if state.tasks == 1 else "s"))
    right = Text("  ·  ".join(right_bits), style=_style(color=MUTED))
    gap = max(2, inner - left.cell_len - right.cell_len)
    row = Text(style=BG_STYLE)
    row.append(left)
    row.append(" " * gap, style=BG_STYLE)
    row.append(right)
    return column_row(fit(row, inner), width)


def _status(state):
    parts = []
    if state.busy:
        parts.append((f"{state.spinner} {state.status}", _style(color=ACCENT, bold=True)))
        if state.elapsed >= 0.1:
            parts.append((f" {state.elapsed:.1f}s", FAINT_STYLE))
    else:
        parts.append(("ready", MUTED_STYLE))
    if state.tokens:
        parts.append(("  ·  ", FAINT_STYLE))
        parts.append((state.tokens, MUTED_STYLE))
    if state.tests:
        parts.append(("  ·  ", FAINT_STYLE))
        color = OK if "pass" in state.tests.lower() else BAD
        parts.append((state.tests, _style(color=color)))
    return parts


def _footer(state, width):
    inner = content_width(width)
    if state.busy:
        hints = "ctrl+c interrupt"
    elif inner < 72:
        hints = "PgUp · ctrl+d"
    elif inner < 90:
        hints = "PgUp history · ctrl+d exit"
    else:
        hints = "tab complete · PgUp history · ctrl+d exit"
    left = Text(hints, style=FAINT_STYLE)
    right = Text(style=_style(bg=BG))
    for value, style in _status(state):
        right.append(value, style=style)
    gap = max(1, inner - left.cell_len - right.cell_len)
    row = Text(style=BG_STYLE)
    row.append(left)
    row.append(" " * gap, style=BG_STYLE)
    row.append(right)
    return column_row(fit(row, inner), width)


def _conversation(state):
    width, height = state.width, state.height
    inner = content_width(width)
    lines = [_header(state, width), _rule(width)]

    card = [column_row(row, width) for row in composer(state, inner, "Ask anything…", show_meta=False)]
    extras = []
    if state.approval:
        extras.append(column_row(line([("▸ ", _style(color=WARN, bold=True)), (state.approval, _style(color=WARN))], inner), width))
    if state.suggestions:
        extras.append(column_row(line([("   ".join(state.suggestions[:7]), FAINT_STYLE)], inner), width))
    footer = _footer(state, width)

    viewport = height - len(lines) - len(extras) - len(card) - 1 - 1
    viewport = max(0, viewport)
    entries = state.transcript
    end = max(0, len(entries) - max(0, state.scroll))
    start = max(0, end - viewport)
    window = entries[start:end]
    transcript_rows = []
    for entry in window:
        row = Text(style=BG_STYLE)
        row.append(entry)
        transcript_rows.append(column_row(fit(row, inner), width))
    # Start a conversation at the top; once it overflows, keep the newest lines
    # anchored above the composer (chat-style, with explicit scrolling).
    filler = max(0, viewport - len(window))
    if state.scroll == 0 and len(window) < viewport:
        lines.extend(transcript_rows)
        lines.extend(blank(width) for _ in range(filler))
    else:
        lines.extend(blank(width) for _ in range(filler))
        lines.extend(transcript_rows)
    if viewport:
        lines.append(blank(width))
    lines.extend(extras)
    lines.extend(card)
    lines.append(footer)
    return lines


# -- entry point -----------------------------------------------------------


def render(state):
    width = max(20, int(state.width))
    height = max(8, int(state.height))
    state.width, state.height = width, height
    lines = _welcome(state) if state.mode == "welcome" else _conversation(state)
    while len(lines) < height:
        lines.append(blank(width))
    return [fit(row, width) for row in lines[:height]]
