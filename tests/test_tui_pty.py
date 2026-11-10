"""Actual POSIX PTY exercise; provider responses are explicitly simulated.

Real keyboard input, resize, approval, local file writes and unittest execution.
No sockets, gateway, reference repositories or external credentials are used.
"""
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

from miser.ui import theme


CHILD = r'''
import json, sys, time
from pathlib import Path
from miser.terminal import Terminal
from miser.tui.app import TuiApp
root = Path(sys.argv[1])
class SimulatedClient:
    supports_streaming = True
    def complete(self, messages, tools=None, **kwargs):
        text = ("I will create **notes.txt** after your approval." if tools else
                "## Simulated answer\n\n**Bold**, *italic*, and `code`.\n\n"
                "| Operation | Result |\n|---|---|\n| read | checked |\n\n"
                "```python\nvalue = 42\nprint(value)\n```\n\n[Docs](https://example.org)")
        if kwargs.get('on_token'):
            for start in range(0, len(text), 9):
                kwargs['on_token'](text[start:start + 9])
                time.sleep(.005)
        message = {'role': 'assistant', 'content': text}
        if tools:
            message['tool_calls'] = [{'id':'simulated-write', 'type':'function', 'function': {
                'name':'write_file', 'arguments':json.dumps({'path':'notes.txt', 'content':'PTY approved write\n'})}}]
        return {'choices':[{'message':message, 'finish_reason':'stop'}],
                'usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}}
terminal = Terminal(root, model='simulated/pty',
                    test_command=f'{sys.executable} -m unittest discover -s .',
                    output_dir=root / 'runs', client_factory=lambda _: SimulatedClient())
terminal.confirm_edits = True
TuiApp(terminal).run()
'''


class ActualTerminalTests(unittest.TestCase):
    def test_keyboard_stream_resize_errors_approval_tests_and_cleanup_in_actual_pty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_acceptance.py").write_text(
                "import unittest\nclass Acceptance(unittest.TestCase):\n def test_real(self): self.assertEqual(2 + 2, 4)\n")
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 0, 0))
            child = subprocess.Popen([sys.executable, "-c", CHILD, str(root)],
                                     stdin=slave, stdout=slave, stderr=slave,
                                     env={**{key: value for key, value in os.environ.items()
                                             if key not in {"NO_COLOR", "FORCE_COLOR"}},
                                          "TERM": "xterm-256color"})
            os.close(slave)
            captured = bytearray()

            def drain(duration=.15):
                end = time.monotonic() + duration
                while time.monotonic() < end:
                    if select.select([master], [], [], .02)[0]:
                        try:
                            captured.extend(os.read(master, 65536))
                        except OSError:
                            return

            def wait_for(text, timeout=8, start=0):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    drain(.05)
                    if text in theme.clean(captured[start:].decode(errors="replace")):
                        return
                    if child.poll() is not None:
                        break
                self.fail(f"PTY did not display {text!r}; exit={child.poll()}; tail=" +
                          theme.clean(captured.decode(errors="replace"))[-1200:])

            try:
                wait_for("Ready when you are")
                capture_path = os.getenv("MISER_UI_CAPTURE")
                if capture_path:
                    Path(capture_path).with_suffix(".welcome.ansi").write_bytes(captured)
                os.write(master, b"hello\r")
                wait_for("Hello!")
                os.write(master, b"how are you?\r")
                wait_for("Simulated answer")
                wait_for("example.org")
                for width in (60, 80, 140):
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 32, width, 0, 0))
                    os.kill(child.pid, signal.SIGWINCH)
                    drain(.25)
                    frame = captured.decode(errors="replace").rsplit("\x1b[H", 1)[-1].split("\x1b[J", 1)[0]
                    rows = theme.clean(frame).splitlines()
                    self.assertEqual(len(rows), 32)
                    self.assertTrue(all(theme.display_width(row) == width for row in rows))
                if capture_path:
                    Path(capture_path).with_suffix(".markdown.ansi").write_bytes(captured)
                os.write(master, b"/budget 2\r")
                wait_for("Budget must be at least")
                os.write(master, b"Create notes.txt\r")
                wait_for("apply edit to notes.txt?")
                self.assertFalse((root / "notes.txt").exists())
                os.write(master, b"\x03")
                wait_for("Task interrupted")
                drain(.2)
                self.assertFalse((root / "notes.txt").exists())
                start = len(captured)
                os.write(master, b"Create notes.txt\r")
                wait_for("apply edit to notes.txt?", start=start)
                os.write(master, b"y")
                wait_for("Task completed")
                self.assertEqual((root / "notes.txt").read_text(), "PTY approved write\n")
                ledgers = list((root / "runs").glob("session-*/ledger.json"))
                self.assertEqual(len(ledgers), 2)
                records = [json.loads(path.read_text()) for path in ledgers]
                self.assertEqual(sorted(record["status"] for record in records), ["interrupted", "tests_passed"])
                ledger = next(record for record in records if record["status"] == "tests_passed")
                self.assertEqual(ledger["status"], "tests_passed")
                self.assertEqual(sum(event["kind"] == "model" for event in ledger["events"]), 1)
                self.assertEqual(sum(event["kind"] == "tests" for event in ledger["events"]), 2)
                drain(.2)
                capture_path = os.getenv("MISER_UI_CAPTURE")
                if capture_path:
                    Path(capture_path).write_bytes(captured)
                os.write(master, b"\x04")
                child.wait(timeout=4)
                drain(.1)
                self.assertEqual(child.returncode, 0)
                self.assertIn(b"\x1b[?1049l", captured)
                self.assertIn(b"\x1b[?25h", captured)
                self.assertNotIn(b"Traceback", captured)
                self.assertIn(b"\x1b[38;2;", captured)
                self.assertIn(b"48;2;", captured)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=3)
                os.close(master)
