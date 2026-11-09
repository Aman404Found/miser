import unittest

from miser.tui.input import InputBuffer
from miser.tui.keys import Key, KeyReader


class InputBufferTests(unittest.TestCase):
    def test_insert_edit_and_navigation(self):
        buffer = InputBuffer()
        buffer.insert("helo")
        buffer.left()
        buffer.insert("l")
        self.assertEqual(buffer.value(), "hello")
        buffer.home()
        buffer.delete()
        self.assertEqual(buffer.value(), "ello")
        buffer.end()
        buffer.backspace()
        self.assertEqual(buffer.value(), "ell")
        buffer.set_text("abc", 0)
        buffer.right()
        self.assertEqual(buffer.cursor, 1)

    def test_multiline_insertion_and_vertical_navigation(self):
        buffer = InputBuffer()
        buffer.insert("first")
        buffer.newline()
        buffer.insert("second")
        self.assertEqual(buffer.value(), "first\nsecond")
        buffer.up()
        self.assertEqual(buffer.cursor, 5)
        buffer.down()
        self.assertEqual(buffer.cursor, 11)

    def test_history_round_trip(self):
        buffer = InputBuffer()
        buffer.remember("first task")
        buffer.remember("second task")
        buffer.set_text("draft")
        buffer.history_previous()
        self.assertEqual(buffer.value(), "second task")
        buffer.history_previous()
        self.assertEqual(buffer.value(), "first task")
        buffer.history_next()
        self.assertEqual(buffer.value(), "second task")
        buffer.history_next()
        self.assertEqual(buffer.value(), "draft")

    def test_completion_unique_and_ambiguous(self):
        buffer = InputBuffer()
        buffer.set_text("/bud")
        self.assertEqual(buffer.complete(["/budget", "/help"]), [])
        self.assertEqual(buffer.value(), "/budget")

        buffer.set_text("/m")
        matches = buffer.complete(["/model", "/map", "/help"])
        self.assertEqual(matches, ["/model", "/map"])
        self.assertEqual(buffer.value(), "/m")

    def test_completion_ignores_plain_text(self):
        buffer = InputBuffer()
        buffer.set_text("fix the bug")
        self.assertEqual(buffer.complete(["/help"]), [])
        self.assertEqual(buffer.value(), "fix the bug")


class KeyReaderTests(unittest.TestCase):
    def test_printable_and_control_keys(self):
        keys = KeyReader.decode("a\x03\x04\x7f\t")
        self.assertEqual([key.name for key in keys], ["char", "ctrl+c", "ctrl+d", "backspace", "tab"])
        self.assertEqual(keys[0].text, "a")

    def test_arrow_and_navigation_sequences(self):
        keys = KeyReader.decode("\x1b[A\x1b[B\x1b[C\x1b[D\x1b[H\x1b[F\x1b[5~\x1b[6~\x1b[3~")
        self.assertEqual([key.name for key in keys],
                         ["up", "down", "right", "left", "home", "end", "pageup", "pagedown", "delete"])

    def test_shifted_arrow_and_alt_enter(self):
        keys = KeyReader.decode("\x1b[1;2A\x1b\r")
        self.assertEqual([key.name for key in keys], ["shift+up", "newline"])

    def test_utf8_characters_and_paste(self):
        keys = KeyReader.decode("é\x1b[200~line one\r\nline two\x1b[201~")
        self.assertEqual(keys[0], Key("char", "é"))
        self.assertEqual(keys[1], Key("paste", "line one\nline two"))

    def test_incomplete_sequence_waits_for_more_bytes(self):
        self.assertEqual(KeyReader.decode("\x1b["), [])


if __name__ == "__main__":
    unittest.main()
