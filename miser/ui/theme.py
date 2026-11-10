"""Terminal styling primitives: colours, glyphs, and width-aware text layout.

Every helper is a pure function over strings, so the same renderers serve a real
terminal, a captured stream, and a non-interactive script. Colour and Unicode are
detected from the stream rather than assumed.
"""

import os
import re
import shutil
import sys
import unicodedata

# Shared by the plain terminal renderers and the optional Rich full-screen UI.
BG = "#0b0d13"
SURFACE = "#151923"
TEXT = "#e6eaf2"
MUTED = "#9aa7bd"
FAINT = "#485267"
ACCENT = "#4f8cff"
CYAN = "#8bd5e5"
OK = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(value):
    """Strip escape sequences and control characters from untrusted text."""
    text = ANSI_RE.sub("", str(value))
    return CONTROL_RE.sub("", text)


def isatty(stream=None):
    try:
        return bool((stream or sys.stdout).isatty())
    except Exception:
        return False


def color_enabled(stream=None):
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("TERM") == "dumb":
        return False
    if os.getenv("MISER_FORCE_COLOR") not in (None, "", "0"):
        return True
    return isatty(stream)


def unicode_enabled(stream=None):
    if os.getenv("MISER_ASCII"):
        return False
    encoding = getattr(stream or sys.stdout, "encoding", None) or "ascii"
    for probe in ("▌", "✔", "⠋", "•"):
        try:
            probe.encode(encoding)
        except (UnicodeEncodeError, LookupError):
            return False
    return True


def term_width(default=100, minimum=40, maximum=160):
    """Current terminal width, clamped so narrow windows stay readable."""
    try:
        columns = shutil.get_terminal_size(fallback=(default, 24)).columns
    except (OSError, ValueError):
        columns = default
    return max(minimum, min(maximum, columns))


def visible_len(text):
    return len(ANSI_RE.sub("", str(text)))


def display_width(text):
    """Width in terminal cells, honouring wide and combining characters."""
    width = 0
    for char in ANSI_RE.sub("", str(text)):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def paint(text, *codes):
    if not codes or not color_enabled():
        return str(text)
    return "\x1b[" + ";".join(str(code) for code in codes) + "m" + str(text) + "\x1b[0m"


def bold(text):
    return paint(text, 1)


def dim(text):
    return paint(text, 2)


def italic(text):
    return paint(text, 3)


def red(text):
    return palette(text, BAD)


def green(text):
    return palette(text, OK)


def change(text, added):
    """Restrained diff surfaces; plain text when colour is unavailable."""
    foreground, background = ((182, 235, 206), (16, 38, 27)) if added else ((249, 180, 180), (43, 21, 27))
    return paint(text, 38, 2, *foreground, 48, 2, *background)


def yellow(text):
    return palette(text, WARN)


def blue(text):
    return palette(text, ACCENT)


def magenta(text):
    return paint(text, 35)


def cyan(text):
    return palette(text, CYAN)


def palette(text, color):
    """Use the shared truecolor palette; colour detection still applies."""
    return paint(text, 38, 2, *(int(color[index:index + 2], 16) for index in (1, 3, 5)))


def gray(text):
    return paint(text, 90)


def clip(text, width, marker="…"):
    """Hard-clip plain text to a display width, marking the cut."""
    text = str(text)
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    if width == 1:
        return marker if display_width(marker) <= 1 else text[:1]
    out, used = [], 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + char_width > width - 1:
            break
        out.append(char)
        used += char_width
    return "".join(out) + marker


def wrap(text, width, initial="", subsequent=""):
    """Wrap by terminal cells; never split ANSI sequences or wide characters."""
    width = max(8, int(width))
    if not str(text).strip():
        return [initial.rstrip()]
    lines, current, used = [], initial, display_width(initial)
    active = ""

    def new_line():
        nonlocal current, used
        lines.append(current + ("\x1b[0m" if active else ""))
        current, used = subsequent + active, display_width(subsequent)

    for word in str(text).split():
        gap = 1 if used > display_width(initial if not lines else subsequent) else 0
        if used + gap + display_width(word) > width and gap:
            new_line()
            gap = 0
        if gap:
            current += " "
            used += 1
        for token in re.findall(r"\x1b\[[0-9;]*[A-Za-z]|[^\x1b]", word):
            cells = display_width(token)
            if cells and used + cells > width:
                new_line()
            if token.startswith("\x1b["):
                active = "" if token == "\x1b[0m" else active + token
            current += token
            used += cells
    if current:
        lines.append(current + ("\x1b[0m" if active else ""))
    return lines or [initial.rstrip()]


def fold(text, width):
    """Hard-wrap code by cells, retaining spaces; display tabs at four columns."""
    lines, current, used = [], "", 0
    for char in str(text).expandtabs(4):
        cells = display_width(char)
        if cells and used + cells > width:
            lines.append(current)
            current, used = "", 0
        current += char
        used += cells
    return lines + [current]


def pad_between(left, right, width):
    """Place ANSI-styled left and right strings on one line, right-aligned."""
    gap = max(1, width - visible_len(left) - visible_len(right))
    return left + " " * gap + right


def shorten_home(path):
    text = str(path)
    home = os.path.expanduser("~")
    if home and text.startswith(home):
        return "~" + text[len(home):]
    return text


def shorten_path(path, width):
    text = shorten_home(path)
    if display_width(text) <= width:
        return text
    parts = text.replace("\\", "/").split("/")
    tail = "/".join(parts[-2:])
    return clip("…/" + tail, width)


class Symbols:
    """Glyphs that degrade to plain ASCII when the terminal cannot show them."""

    def __init__(self, fancy=True):
        self.fancy = fancy
        self.prompt = "❯" if fancy else ">"
        self.user = "▌" if fancy else "|"
        self.agent = "◆" if fancy else "*"
        self.ok = "✔" if fancy else "+"
        self.fail = "✖" if fancy else "x"
        self.warn = "▲" if fancy else "!"
        self.info = "·" if fancy else "."
        self.arrow = "→" if fancy else "->"
        self.bullet = "•" if fancy else "-"
        self.rule = "─" if fancy else "-"
        self.bar = "│" if fancy else "|"
        self.spinner = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏") \
            if fancy else ("|", "/", "-", "\\")


def symbols():
    return Symbols(unicode_enabled())
