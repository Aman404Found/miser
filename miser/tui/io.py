"""Alternate-screen terminal I/O.

Frames are composed as exact-height Rich lines and written in one call after a
cursor-home escape, so updates repaint in place instead of appending output.
"""

import contextlib
import io
import shutil
import sys

from rich.console import Console

ENTER = "\x1b[0m\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H\x1b[?2004h"
LEAVE = "\x1b[0m\x1b[?2004l\x1b[?25h\x1b[?1049l"


@contextlib.contextmanager
def raw_mode(stream=None):
    """Raw keyboard input while keeping newline output processing intact.

    Ctrl+C must arrive as a byte rather than SIGINT and Enter must stay ``\r``,
    but output still needs OPOST so frames advance correctly.
    """
    stream = stream or sys.stdin
    try:
        import termios
        fd = stream.fileno()
        original = termios.tcgetattr(fd)
    except (ImportError, OSError, ValueError, AttributeError):
        yield
        return
    import termios
    import copy
    updated = copy.deepcopy(original)
    updated[3] &= ~(termios.ICANON | termios.ECHO | termios.ISIG | termios.IEXTEN)
    updated[0] &= ~(termios.IXON | termios.ICRNL)
    updated[6][termios.VMIN] = 1
    updated[6][termios.VTIME] = 0
    try:
        termios.tcsetattr(fd, termios.TCSAFLUSH, updated)
    except (OSError, ValueError):
        yield
        return
    try:
        yield
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSAFLUSH, original)
        except (OSError, ValueError):
            pass


class Screen:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdout
        self.entered = False
        self.console = None
        self.console_size = None

    def size(self):
        size = shutil.get_terminal_size(fallback=(80, 24))
        return max(20, size.columns), max(8, size.lines)

    def enter(self):
        if self.entered:
            return
        self._write(ENTER)
        self.entered = True

    def leave(self):
        if not self.entered:
            return
        self._write(LEAVE)
        self.entered = False

    def _write(self, value):
        try:
            self.stream.write(value)
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def _console(self, width, height):
        if self.console is None or self.console_size != (width, height):
            buffer = io.StringIO()
            self.console = Console(
                file=buffer,
                width=width,
                height=height,
                force_terminal=True,
                color_system="truecolor",
                highlight=False,
                soft_wrap=False,
            )
            self.console_size = (width, height)
        self.console.file.seek(0)
        self.console.file.truncate(0)
        return self.console

    def draw(self, lines):
        width, height = self.size()
        if not lines:
            return
        console = self._console(width, height)
        for index in range(height):
            row = lines[index] if index < len(lines) else ""
            console.print(row, end="")
            if index < height - 1:
                console.print()
        frame = console.file.getvalue()
        self._write("\x1b[H" + frame + "\x1b[J")
