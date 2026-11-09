"""A single-line working indicator driven by real elapsed time.

The indicator never pretends that work is progressing: it only animates while a
call is actually in flight and shows the wall-clock time spent so far. It is a
no-op when the output stream is not an interactive terminal, so captured output
and non-interactive runs stay clean.
"""

import sys
import threading
import time

from . import theme


class WorkingIndicator:
    def __init__(self, write=None, stream=None, enabled=None, interval=0.1, glyphs=None):
        self.stream = stream or sys.stdout
        self._write = write
        self.enabled = (enabled if enabled is not None
                        else theme.isatty(self.stream) and theme.color_enabled(self.stream))
        self.interval = interval
        self.glyphs = glyphs or theme.symbols()
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._label = ""
        self._frame = 0
        self._phase_started = time.monotonic()
        self._started = time.monotonic()
        self._visible = False

    def _emit(self, text):
        if self._write is not None:
            self._write(text)
            return
        try:
            self.stream.write(text)
            self.stream.flush()
        except (BrokenPipeError, ValueError):
            pass

    def start(self, label="working"):
        """Begin (or relabel) the indicator; safe to call repeatedly."""
        if not self.enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._label = label
                return
            self._label = label
            self._phase_started = time.monotonic()
            self._started = time.monotonic()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="miser-spinner", daemon=True)
            self._thread.start()

    def update(self, label):
        if not self.enabled:
            return
        with self._lock:
            self._label = label

    def _loop(self):
        while not self._stop.wait(self.interval):
            self._render()

    def _render(self):
        frames = self.glyphs.spinner
        with self._lock:
            frame = frames[self._frame % len(frames)]
            self._frame += 1
            label = self._label
            elapsed = time.monotonic() - self._phase_started
        line = f"{theme.cyan(frame)} {label}  {theme.dim(f'{elapsed:.1f}s')}"
        padding = max(0, theme.term_width() - theme.visible_len(line) - 1)
        self._visible = True
        self._emit("\r" + line + " " * padding + "\x1b[K")

    def stop(self):
        """Clear the indicator line without printing anything."""
        if not self.enabled:
            return
        with self._lock:
            thread, self._thread = self._thread, None
            self._stop.set()
        if thread:
            thread.join(timeout=0.5)
        if self._visible:
            self._visible = False
            self._emit("\r\x1b[K")

    def suspend(self):
        """Temporarily clear the line (used while streaming text arrives)."""
        self.stop()

    def resume(self, label="working"):
        self.start(label)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False
