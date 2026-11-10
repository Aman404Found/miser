"""Presentation-only empty-state hierarchy and transcript density."""
import tempfile
import unittest
from textual.widgets import Static
from miser.terminal import Terminal
from miser.tui.textual_app import MiserApp, BackendUpdate, MessageCard

class IdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_state_has_large_centered_brand_and_no_duplicate_session_panels(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal=Terminal(directory,write=lambda _:None)
            app=MiserApp(terminal)
            async with app.run_test(size=(160,45)) as pilot:
                await pilot.pause()
                self.assertGreaterEqual(app.ui('#welcome-brand').size.height,5)
                self.assertFalse(app.ui('#inspector').display)
                welcome=app.ui('#welcome').region
                area=app.ui('#conversation').region
                self.assertLess(abs(welcome.center[1]-area.center[1]),4)
                self.assertEqual(terminal.session_model_requests,0)
                await app.submit_text('hello'); await pilot.pause(.2)
                self.assertFalse(app.ui('#welcome').display)
                self.assertTrue(app.ui('#inspector').display)
                await app.submit_text('/clear'); await pilot.pause()
                self.assertTrue(app.ui('#welcome').display)
                self.assertFalse(app.ui('#inspector').display)

    async def test_welcome_shortcuts_fit_without_scrolling_at_standard_terminal_sizes(self):
        with tempfile.TemporaryDirectory() as directory:
            app = MiserApp(Terminal(directory, write=lambda _: None))
            async with app.run_test(size=(80, 24)) as pilot:
                for width, height in ((80, 24), (120, 36), (160, 45), (200, 30)):
                    await pilot.resize_terminal(width, height)
                    await pilot.pause()
                    area = app.ui('#conversation')
                    keys = app.ui('#welcome-keys')
                    self.assertEqual(area.max_scroll_y, 0, (width, height))
                    self.assertLessEqual(keys.region.bottom, area.region.bottom - 1)
                    self.assertFalse(app.ui('#inspector').display)

    async def test_routine_notes_are_compact_and_timing_remains_available_on_demand(self):
        with tempfile.TemporaryDirectory() as directory:
            app=MiserApp(Terminal(directory,write=lambda _:None))
            async with app.run_test(size=(80,24)) as pilot:
                await app.on_backend_update(BackendUpdate('note',source='Task mode: files'))
                self.assertFalse(any(card.title=='Workspace' for card in app.query(MessageCard)))
                self.assertTrue(any('Task mode: files' in str(row.render()) for row in app.query(Static)))
                await app._activity({'type':'timing','wall_seconds':1,'model_seconds':.5,'test_seconds':0,'tool_seconds_sum':0})
                self.assertTrue(app.ui('.timing').collapsed)

    async def test_question_and_answer_use_bounded_distinct_surfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            app = MiserApp(Terminal(directory, write=lambda _: None))
            async with app.run_test(size=(200, 36)) as pilot:
                app._show_home(False)
                question = MessageCard('user', 'A readable question')
                answer = MessageCard('assistant', '**A readable answer**')
                await app._append(question)
                await app._append(answer)
                await pilot.pause()
                self.assertLessEqual(question.size.width, 110)
                self.assertLessEqual(answer.size.width, 110)
                self.assertNotEqual(question.styles.background, answer.styles.background)
                self.assertEqual(answer.source, '**A readable answer**')
