"""Actual CLI launch in a PTY; only provider responses are simulated.

pyte is a development-only terminal emulator used to inspect incremental frames.
Real backend reads, version-checked edits, failed/passed unittest checks and receipts.
"""
import codecs
import fcntl
import json
import os
from pathlib import Path
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

import pyte


CHILD = r'''
import json, sys, time
from pathlib import Path
import miser.cli as cli
import miser.terminal as backend
from miser.terminal import Terminal
from miser.client import ModelClient
def refuse_live_model(*args, **kwargs): raise AssertionError('Live provider forbidden in this simulated fixture')
ModelClient.complete=refuse_live_model
class SimulatedProvider:
    supports_streaming = True
    def __init__(self): self.calls=0
    def complete(self, messages, tools=None, **kwargs):
        self.calls += 1
        name, arguments = None, None
        if tools:
            if self.calls == 1:
                text = 'I will inspect the function and the real failing check.'
                name, arguments = 'zoom', {'path':'app.py','level':2}
            else:
                text = 'The smallest correction is to return 2. Please review the patch.'
                version=json.loads(messages[-1]['content'])['version']
                name, arguments = 'edit', {'path':'app.py','old':'return 1','new':'return 2','expected_version':version}
        else:
            text = ('## Simulated provider response\n\n**Strong**, *emphasis*, and `inline code`.\n\n'
                    '- Read actual files\n- Review a checked patch\n\n'
                    '| Operation | Guard |\n|---|---|\n| edit | version check |\n\n'
                    '> This is a simulated provider, not a live model benchmark.\n\n'
                    '```python\ndef value():\n    return 2\n```\n\n[Docs](https://example.org)')
        if kwargs.get('on_token'):
            for start in range(0,len(text),11):
                kwargs['on_token'](text[start:start+11]); time.sleep(.003)
        message={'role':'assistant','content':text}
        if name:
            message['tool_calls']=[{'id':f'fixture-{self.calls}','type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}]
        return {'choices':[{'message':message,'finish_reason':'stop'}],
                'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
original=Terminal
def fixture_terminal(*args, **kwargs):
    kwargs['client_factory']=lambda _: SimulatedProvider()
    terminal=original(*args, **kwargs)
    terminal.confirm_edits=True
    return terminal
backend.Terminal=fixture_terminal
cli.load_env=lambda: None
root=Path(sys.argv[1])
command=f'{sys.executable} -m unittest discover -s .'
raise SystemExit(cli.main(['chat',str(root),'--tui','--model','simulated/native-pty','--test-command',command,'--no-memory']))
'''


class NativeCliPtyTests(unittest.TestCase):
    def test_real_launch_stream_resize_scroll_failed_tests_edit_approval_and_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "app.py").write_text("def value():\n    return 1\n")
            (root / "test_value.py").write_text("import unittest\nfrom app import value\nclass TestValue(unittest.TestCase):\n def test_value(self): self.assertEqual(value(), 2)\n")
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            environment = {key: value for key, value in os.environ.items()
                           if key not in {"NO_COLOR", "FORCE_COLOR", "MISER_PLAIN"}}
            environment.update(TERM="xterm-256color", PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                               MISER_ARCHITECT_MODEL="", MISER_FALLBACK_MODELS="",
                               COLORTERM="truecolor", TEXTUAL_COLOR_SYSTEM="truecolor")
            child = subprocess.Popen([sys.executable, "-c", CHILD, str(root)], cwd=root,
                                     stdin=slave, stdout=slave, stderr=slave, env=environment)
            os.close(slave)
            screen = pyte.Screen(80, 24)
            stream = pyte.Stream(screen)
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            raw = bytearray()

            def drain(duration=.1):
                end = time.monotonic() + duration
                while time.monotonic() < end:
                    if select.select([master], [], [], .02)[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError:
                            return
                        if not chunk:
                            return
                        raw.extend(chunk)
                        stream.feed(decoder.decode(chunk))

            def view():
                return "\n".join(screen.display)

            def wait_for(text, timeout=12):
                end = time.monotonic() + timeout
                while time.monotonic() < end:
                    drain(.05)
                    if text in view():
                        return
                    if child.poll() is not None:
                        break
                self.fail(f"Native CLI did not display {text!r}; exit={child.poll()}\n" + view())

            def capture(name):
                destination = os.getenv("MISER_NATIVE_CAPTURE")
                if destination:
                    target = Path(destination)
                    target.mkdir(parents=True, exist_ok=True)
                    data = {"source": "actual CLI PTY; simulated provider", "width": screen.columns,
                            "height": screen.lines, "display": screen.display,
                            "cells": [[{"text": cell.data, "fg": cell.fg, "bg": cell.bg,
                                        "bold": cell.bold, "italic": cell.italics}
                                       for cell in (screen.buffer[y][x] for x in range(screen.columns))]
                                      for y in range(screen.lines)]}
                    (target / (name + ".json")).write_text(json.dumps(data))

            def wait_for_layout():
                """Resize is complete only when the persistent footer reaches the new bottom."""
                end = time.monotonic() + 12
                while time.monotonic() < end:
                    drain(.05)
                    if "checks" in screen.display[-1]:
                        drain(.1)
                        return
                self.fail("Native footer did not follow terminal resize\n" + view())

            try:
                wait_for("Your workspace.")
                capture("welcome-80x24")
                os.write(master, b"hello\r")
                wait_for("Hello!")
                os.write(master, b"how are you?\r")
                # Native Markdown displays link labels; destinations are inspected
                # by clicking, never opened automatically by rendered content.
                wait_for("Docs")
                drain(.3)
                capture("conversation-80x24")
                for width, height in ((120, 36), (160, 45)):
                    screen.resize(lines=height, columns=width)
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))
                    os.kill(child.pid, signal.SIGWINCH)
                    wait_for_layout()
                    self.assertIn("MISER", view())
                    self.assertIn("Enter send", view())
                    capture(f"conversation-{width}x{height}")
                os.write(master, b"\x1b[5~")
                drain(.2)
                os.write(master, b"\x1b[6~")
                drain(.2)
                # Native editor receives actual multiline keys, then cancels the draft.
                os.write(master, b"draft one\x0adraft two")
                wait_for("draft two")
                os.write(master, b"\x03")
                drain(.2)
                os.write(master, b"Fix app.py\r")
                wait_for("Review edit")
                self.assertEqual((root / "app.py").read_text(), "def value():\n    return 1\n")
                # The title may paint before the native diff's asynchronous layout.
                # Require the actual patch and controls before reviewing the frame.
                wait_for("return 2")
                wait_for("Approve all edits")
                wait_for("Reject")
                capture("approval-160x45")
                screen.resize(lines=24, columns=80)
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                os.kill(child.pid, signal.SIGWINCH)
                drain(.3)
                wait_for("Approve")
                wait_for("Reject")
                capture("approval-80x24")
                os.write(master, b"\x03")
                drain(.5)
                end = time.monotonic() + 8
                while time.monotonic() < end:
                    drain(.1)
                    if "Ready" in view() and "Review edit" not in view():
                        break
                self.assertEqual((root / "app.py").read_text(), "def value():\n    return 1\n")
                os.write(master, b"Fix app.py\r")
                wait_for("Review edit")
                # Reject is focused by default; Tab moves to the explicit Approve button.
                os.write(master, b"\t\r")
                wait_for("Task completed")
                wait_for("tests passed")
                self.assertEqual((root / "app.py").read_text(), "def value():\n    return 2\n")
                records = [json.loads(path.read_text()) for path in (root / "runs").glob("session-*/ledger.json")]
                self.assertEqual(sorted(record["status"] for record in records), ["interrupted", "tests_passed"])
                passed = next(record for record in records if record["status"] == "tests_passed")
                tests = [event for event in passed["events"] if event["kind"] == "tests"]
                self.assertEqual([event["passed"] for event in tests], [False, True])
                self.assertEqual(sum(event["kind"] == "model" for event in passed["events"]), 2)
                screen.resize(lines=45, columns=160)
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 160, 0, 0))
                os.kill(child.pid, signal.SIGWINCH)
                wait_for_layout()
                capture("completed-160x45")
                os.write(master, b"\x04")
                deadline = time.monotonic() + 5
                while child.poll() is None and time.monotonic() < deadline:
                    drain(.05)
                self.assertIsNotNone(child.poll(), "Native UI did not exit within five seconds\n" + view())
                drain(.1)
                self.assertEqual(child.returncode, 0)
                self.assertNotIn(b"Traceback", raw)
                self.assertIn(b"?1049l", raw)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=3)
                os.close(master)
