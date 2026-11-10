"""Presentation-only review; synthetic events, no provider/tool execution."""
import tempfile
from pathlib import Path
import unittest
from textual.widgets import Static
from miser.terminal import Terminal
from miser.tui.textual_app import MiserApp, BackendUpdate

class PresentationReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.terminal=Terminal(self.tmp.name,model='simulated/review',write=lambda _:None)

    async def test_failed_tests_are_red_even_when_the_test_tool_itself_ran_successfully(self):
        app=MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app._activity({'type':'tool','state':'result','name':'run_tests',
                                 'ok':True,'passed':False,'elapsed':.1})
            self.assertIs(app._recent[0]['ok'],False)
            self.assertEqual(app._last_checks,'failed')
            self.assertTrue(any(row.has_class('test-failed') for row in app.query('.tool')))
            self.assertEqual(self.terminal.session_tool_calls,0)

    async def test_unverified_task_is_neutral_and_unknown_usage_is_not_zero_tokens(self):
        app=MiserApp(self.terminal)
        async with app.run_test(size=(160,45)) as pilot:
            await app.on_backend_update(BackendUpdate('result',bill={'status':'edited_unverified'},
                elapsed=1,directory=self.tmp.name,error=None,diff=''))
            self.assertIsNone(app._recent[0]['ok'])
            self.assertNotIn('✖',str(app.ui('#recent-details',Static).render()))
            self.terminal.session_unknown_usage=1
            app._refresh_status()
            self.assertIn('unknown',str(app.ui('#counters',Static).render()).lower())
            self.assertEqual(self.terminal.session_model_requests,0)

    async def test_resize_breakpoints_rail_cells_and_composer_bounds(self):
        app=MiserApp(self.terminal)
        async with app.run_test(size=(80,24)) as pilot:
            app._show_home(False)
            for width,height in ((80,24),(95,20),(96,24),(117,30),(118,24),(160,36),(200,45)):
                await pilot.resize_terminal(width,height); await pilot.pause()
                self.assertEqual(app.ui('#inspector').display,width>=118)
                self.assertEqual(app.ui('#counters').display,width>=96)
                self.assertLessEqual(app.ui('#composer').region.bottom,height)
                self.assertLessEqual(app.ui('#statusbar').region.bottom,height)
                for row in app._session_text().split('\n'):
                    self.assertLessEqual(row.cell_len,28)

    async def test_same_name_results_pair_fifo_and_recent_failure_is_not_mislabeled(self):
        app=MiserApp(self.terminal)
        async with app.run_test() as pilot:
            for path in ('first.py','second.py'):
                await app._activity({'type':'tool','state':'start','name':'zoom','args':{'path':path}})
            first,second=list(app._tools['zoom'])
            await app._activity({'type':'tool','state':'result','name':'zoom','ok':True,'detail':'first.py'})
            await app._activity({'type':'tool','state':'result','name':'zoom','ok':False,'error':'missing','detail':'second.py'})
            self.assertIn('first.py',str(first.render()))
            self.assertIn('second.py',str(second.render()))
            self.assertTrue(first.has_class('test-passed')); self.assertTrue(second.has_class('test-failed'))
            self.assertEqual(len(app._recent),2)
            self.assertIs(app._recent[0]['ok'],False)
            self.assertEqual(len(app._tools['zoom']),0)

    async def test_long_approval_keeps_buttons_visible_and_uses_native_primary_style(self):
        from miser.tui.textual_app import ApprovalScreen, PendingInput
        from textual.widgets import Button
        app=MiserApp(self.terminal)
        async with app.run_test(size=(80,24)) as pilot:
            request=PendingInput('edit','Review · '+('long/path/'*30),'--- a/long.txt\n+++ b/long.txt\n'+ '+line\n'*100)
            app.push_screen(ApprovalScreen(request)); await pilot.pause()
            for name in ('reject','approve','all-edits'):
                button=app.screen.query_one('#'+name,Button)
                self.assertGreaterEqual(button.region.y,0)
                self.assertLessEqual(button.region.bottom,24)
            self.assertEqual(app.screen.focused.id,'reject')
            self.assertEqual(app.screen.query_one('#approve',Button).styles.background.hex.lower(),'#28343d')
            await pilot.resize_terminal(120,36); await pilot.pause()
            self.assertLessEqual(app.screen.query_one('#approve',Button).region.bottom,36)
            await pilot.resize_terminal(80,20); await pilot.pause()
            self.assertLessEqual(app.screen.query_one('#approve',Button).region.bottom,20)

    async def test_long_question_keeps_answer_controls_visible_and_click_returns_existing_choice(self):
        from miser.tui.textual_app import QuestionScreen, PendingInput
        from textual.widgets import Button, Input
        app=MiserApp(self.terminal); answers=[]
        async with app.run_test(size=(80,24)) as pilot:
            options=['choice '+str(i)+' '+('detail '*15) for i in range(5)]
            app.push_screen(QuestionScreen(PendingInput('question','Question '*55,options=options)),answers.append)
            await pilot.pause()
            self.assertLessEqual(app.screen.query_one('#answer-send',Button).region.bottom,24)
            self.assertEqual(app.screen.focused.id,'answer')
            app.screen.query_one(Input).value='1'
            self.assertTrue(await pilot.click('#answer-send'))
            await pilot.pause()
            self.assertEqual(answers,[options[0]])

    async def test_native_css_selectors_style_fence_collapsible_and_focus(self):
        from miser.tui.textual_app import MessageCard, DiffView
        from miser.ui import theme
        app=MiserApp(self.terminal)
        async with app.run_test() as pilot:
            await app._append(MessageCard('assistant','```python\nprint("example")\n```'))
            await app._append(DiffView('--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-old\n+new\n'))
            await pilot.pause()
            self.assertEqual(app.query_one('MarkdownFence').styles.scrollbar_background.hex.lower(),'#1c1c21')
            self.assertEqual(app.query_one('CollapsibleTitle').styles.padding.left,1)
            self.assertEqual(app.ui('#composer').styles.border_top[1].hex.lower(),theme.ACCENT)

    async def test_unicode_workspace_and_long_activity_timing_stay_within_rail_cells(self):
        root=Path(self.tmp.name)/'界面项目'; root.mkdir()
        terminal=Terminal(root,model='simulated/review',write=lambda _:None)
        app=MiserApp(terminal)
        async with app.run_test(size=(120,36)) as pilot:
            for row in app._session_text().split('\n'):
                self.assertLessEqual(row.cell_len,28)
            await app._activity({'type':'tool','state':'result','name':'zoom','ok':True,
                                 'elapsed':100000.25,'detail':'very-long-file-name.txt'})
            for row in app.ui('#recent-details',Static).render().split('\n'):
                self.assertLessEqual(row.cell_length,28)

    async def test_short_wide_rail_can_scroll_recent_activity_without_moving_composer(self):
        from textual.containers import VerticalScroll
        app=MiserApp(self.terminal)
        async with app.run_test(size=(120,24)) as pilot:
            app._show_home(False)
            for index in range(4):
                app._remember_recent('tool '+str(index),True,'0.02s')
            await pilot.pause()
            rail=app.ui('#inspector')
            self.assertIsInstance(rail,VerticalScroll)
            self.assertGreater(rail.max_scroll_y,0)
            rail.scroll_end(animate=False,immediate=True); await pilot.pause()
            self.assertLessEqual(app.ui('#recent-panel').region.bottom,rail.content_region.bottom)
            self.assertLessEqual(app.ui('#composer').region.bottom,24)
