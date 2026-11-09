"""Raw key decoding for the full-screen UI.

The UI runs in raw mode, so it owns escape-sequence parsing: arrows, home/end,
paging, paste, control keys, and UTF-8 characters. This module performs no I/O
beyond reading the injected stream.
"""

import os
import select
import sys

CSI_KEYS = {
    "A": "up", "B": "down", "C": "right", "D": "left",
    "H": "home", "F": "end", "Z": "shift+tab",
    "1~": "home", "2~": "insert", "3~": "delete",
    "4~": "end", "5~": "pageup", "6~": "pagedown",
    "7~": "home", "8~": "end",
}

CONTROL_KEYS = {
    "\r": "enter", "\n": "newline", "\t": "tab",
    "\x7f": "backspace", "\x08": "backspace",
    "\x03": "ctrl+c", "\x04": "ctrl+d", "\x0c": "ctrl+l",
    "\x15": "ctrl+u", "\x10": "ctrl+p", "\x0e": "ctrl+n",
    "\x1b": "escape",
}

PASTE_START = "\x1b[200~"
PASTE_END = "\x1b[201~"


class Key:
    __slots__ = ("name", "text")

    def __init__(self, name, text=""):
        self.name = name
        self.text = text

    def __repr__(self):
        return f"Key({self.name!r}, {self.text!r})"

    def __eq__(self, other):
        return isinstance(other, Key) and (self.name, self.text) == (other.name, other.text)


class KeyReader:
    def __init__(self, stream=None):
        self.stream = stream or sys.stdin
        self.fd = self.stream.fileno()
        self.buffer = ""

    @classmethod
    def decode(cls, data):
        """Decode every complete token in a byte string (used by tests)."""
        reader = cls.__new__(cls)
        reader.buffer = data
        keys = []
        while reader.buffer:
            key = reader._parse()
            if key is None:
                break
            keys.append(key)
        return keys

    def read(self, timeout=0.1):
        if self.buffer:
            key = self._parse()
            if key is not None:
                return key
        try:
            ready, _, _ = select.select([self.fd], [], [], timeout)
        except (OSError, ValueError):
            return Key("eof")
        if not ready:
            return None
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            return Key("eof")
        if not data:
            return Key("eof")
        self.buffer += data.decode("utf-8", errors="replace")
        return self._parse()

    def _parse(self):
        buffer = self.buffer
        if not buffer:
            return None
        if buffer.startswith(PASTE_START):
            end = buffer.find(PASTE_END)
            if end < 0:
                return None
            text = buffer[len(PASTE_START):end]
            self.buffer = buffer[end + len(PASTE_END):]
            return Key("paste", text.replace("\r\n", "\n").replace("\r", "\n"))
        if buffer.startswith("\x1b["):
            return self._parse_csi()
        if buffer.startswith("\x1b\r") or buffer.startswith("\x1b\n"):
            self.buffer = buffer[2:]
            return Key("newline")
        if buffer == "\x1b":
            self.buffer = ""
            return Key("escape")
        if len(buffer) >= 2 and buffer[0] == "\x1b":
            # Unknown escape (e.g. alt+key): ignore the ESC, keep the character.
            self.buffer = buffer[1:]
            return self._parse()
        char = buffer[0]
        self.buffer = buffer[1:]
        if char in CONTROL_KEYS:
            return Key(CONTROL_KEYS[char])
        if char == " " or char.isprintable():
            return Key("char", char)
        return None

    def _parse_csi(self):
        buffer = self.buffer
        end = 2
        while end < len(buffer) and not ("@" <= buffer[end] <= "~"):
            end += 1
        if end >= len(buffer):
            return None  # incomplete sequence; wait for more bytes
        final = buffer[end]
        params = buffer[2:end]
        self.buffer = buffer[end + 1:]
        sequence = params + (final if final == "~" else "")
        name = CSI_KEYS.get(sequence) or CSI_KEYS.get(final)
        if final in "HF" and not name:
            name = "home" if final == "H" else "end"
        if name is None:
            return Key("escape")
        if params.endswith(";2"):
            name = "shift+" + name
        return Key(name)
