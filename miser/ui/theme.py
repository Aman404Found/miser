"""Terminal styling primitives: colours, glyphs, and width-aware text layout.

Every helper is a pure function over strings, so the same renderers serve a real
terminal, a captured stream, and a non-interactive script. Colour and Unicode are
detected from the stream rather than assumed.
"""

import os
import re
import shutil
import sys
import textwrap
import unicodedata

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
    return paint(text, 31)


def green(text):
    return paint(text, 32)


def yellow(text):
    return paint(text, 33)


def blue(text):
    return paint(text, 34)


def magenta(text):
    return paint(text, 35)


def cyan(text):
    return paint(text, 36)


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
    """Wrap plain text; indent strings count toward the width."""
    width = max(8, int(width))
    if not str(text).strip():
        return [initial.rstrip()]
    return textwrap.wrap(str(text), width=width, initial_indent=initial,
                         subsequent_indent=subsequent, break_long_words=True,
                         break_on_hyphens=False) or [initial.rstrip()]


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
        self.agent = "⏺" if fancy else "*"
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
