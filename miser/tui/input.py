"""Editable composer state, independent of terminal I/O.

Keeping insertion, cursor movement, history, and completion here makes the
composer testable without a pseudo-terminal.
"""


class InputBuffer:
    def __init__(self):
        self.text = ""
        self.cursor = 0
        self.history = []
        self.history_index = None
        self.draft = ""
        self.max_history = 200

    # -- editing -----------------------------------------------------------

    def value(self):
        return self.text

    def is_empty(self):
        return not self.text.strip()

    def clear(self):
        self.text = ""
        self.cursor = 0
        self.history_index = None
        self.draft = ""

    def set_text(self, text, cursor=None):
        self.text = str(text)
        self.cursor = len(self.text) if cursor is None else max(0, min(cursor, len(self.text)))

    def insert(self, value):
        self.text = self.text[:self.cursor] + value + self.text[self.cursor:]
        self.cursor += len(value)

    def backspace(self):
        if self.cursor:
            self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1

    def delete(self):
        if self.cursor < len(self.text):
            self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]

    def left(self):
        self.cursor = max(0, self.cursor - 1)

    def right(self):
        self.cursor = min(len(self.text), self.cursor + 1)

    def home(self):
        line_start = self.text.rfind("\n", 0, self.cursor) + 1
        self.cursor = line_start

    def end(self):
        line_end = self.text.find("\n", self.cursor)
        self.cursor = len(self.text) if line_end < 0 else line_end

    def newline(self):
        self.insert("\n")

    def _line_bounds(self):
        start = self.text.rfind("\n", 0, self.cursor) + 1
        end = self.text.find("\n", self.cursor)
        return start, (len(self.text) if end < 0 else end)

    def up(self):
        if "\n" in self.text:
            start, _ = self._line_bounds()
            if start == 0:
                self.home()
                return
            column = self.cursor - start
            previous_end = start - 1
            previous_start = self.text.rfind("\n", 0, previous_end) + 1
            self.cursor = min(previous_start + column, previous_end)
            return
        self.history_previous()

    def down(self):
        if "\n" in self.text:
            _, end = self._line_bounds()
            if end >= len(self.text):
                self.end()
                return
            column = self.cursor - self._line_bounds()[0]
            next_start = end + 1
            next_end = self.text.find("\n", next_start)
            next_end = len(self.text) if next_end < 0 else next_end
            self.cursor = min(next_start + column, next_end)
            return
        self.history_next()

    # -- history -----------------------------------------------------------

    def remember(self, text):
        text = str(text)
        if not text.strip():
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
            del self.history[:-self.max_history]

    def history_previous(self):
        if not self.history:
            return
        if self.history_index is None:
            self.draft = self.text
            self.history_index = len(self.history)
        self.history_index = max(0, self.history_index - 1)
        self.set_text(self.history[self.history_index])

    def history_next(self):
        if self.history_index is None:
            return
        self.history_index += 1
        if self.history_index >= len(self.history):
            self.history_index = None
            self.set_text(self.draft)
        else:
            self.set_text(self.history[self.history_index])

    # -- completion --------------------------------------------------------

    def complete(self, commands):
        """Complete the current slash command, returning remaining candidates."""
        head = self.text[:self.cursor]
        if not head.startswith("/") or " " in head.strip():
            return []
        matches = [command for command in commands if command.startswith(head)]
        if not matches:
            return []
        if len(matches) == 1:
            self.text = matches[0] + self.text[self.cursor:]
            self.cursor = len(matches[0])
            return []
        common = matches[0]
        for match in matches[1:]:
            while not match.startswith(common):
                common = common[:-1]
        if len(common) > len(head):
            self.text = common + self.text[self.cursor:]
            self.cursor = len(common)
        return matches
