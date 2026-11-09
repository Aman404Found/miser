"""Readline-backed input: history, completion, multiline entry, and fallback.

The terminal keeps accepting ordinary line input, but coding sessions benefit
from persistent history, Tab completion for both commands and repository paths,
and a documented way to enter multi-line prompts without a full-screen editor.
"""

from pathlib import Path

MAX_HISTORY = 2000
MAX_COMPLETIONS = 200


def read_multiline(read, prompt, continuation="… ", hint=None):
    """Read one prompt that may span lines.

    A trailing backslash joins the next line; a triple-quoted block captures a
    pasted block until the closing quotes. Everything else is one line.
    """
    first = read(prompt)
    stripped = first.strip()
    if stripped.startswith('"""') and not (stripped.endswith('"""') and len(stripped) > 3):
        lines = [stripped[3:]]
        while True:
            next_line = read(continuation)
            if next_line.strip().endswith('"""'):
                lines.append(next_line.strip()[:-3])
                break
            lines.append(next_line)
        return "\n".join(lines).strip()
    if stripped.endswith("\\"):
        lines = [stripped[:-1].strip()]
        while True:
            next_line = read(continuation)
            piece = next_line.strip()
            if piece.endswith("\\"):
                lines.append(piece[:-1].strip())
            else:
                lines.append(piece)
                break
        return " ".join(lines).strip()
    return stripped


class InputSession:
    """Owns readline configuration and durable prompt history for a session."""

    def __init__(self, workspace, commands, read=input, write=print):
        self.workspace = workspace
        self.root = Path(workspace.root)
        self.commands = list(commands)
        self.read = read
        self.write = write
        self.history_path = self.root / ".miser" / "history"
        self._files = None
        self.readline = self._configure()

    def _configure(self):
        try:
            import readline
        except ImportError:
            return None
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            if self.history_path.is_file():
                readline.read_history_file(str(self.history_path))
            readline.set_history_length(MAX_HISTORY)
        except (OSError, ValueError):
            pass
        readline.set_completer(self._complete)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")
        # Ctrl+L clears a noisy screen; Ctrl+R and Up/Down keep their readline defaults.
        try:
            readline.parse_and_bind('"\\C-l": clear-screen')
        except Exception:
            pass
        return readline

    def _workspace_files(self):
        if self._files is None:
            try:
                self._files = sorted(self.workspace.files().get("files", []))
            except Exception:
                self._files = []
        return self._files

    def _complete(self, text, state):
        buffer = ""
        if self.readline is not None:
            try:
                buffer = self.readline.get_line_buffer().lstrip()
            except Exception:
                buffer = ""
        if buffer.startswith("/"):
            matches = [command for command in self.commands if command.startswith(text)]
        else:
            matches = [name for name in self._workspace_files() if name.startswith(text)][:MAX_COMPLETIONS]
            if not matches:
                matches = [command for command in self.commands if command.startswith(text)]
        return (matches + [None])[state]

    def read_line(self, prompt):
        if self.read is input:
            try:
                return input(prompt)
            except EOFError:
                raise
        return self.read(prompt)

    def save_history(self):
        if self.readline is None:
            return
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.readline.write_history_file(str(self.history_path))
        except (OSError, ValueError):
            pass
