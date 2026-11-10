"""Session baseline reuse must never skip fresh post-edit verification."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from miser.terminal import Terminal


class BaselineCacheTests(unittest.TestCase):
    def test_unchanged_baseline_reused_but_mutation_command_and_environment_invalidate(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory, write=lambda _: None)
            runner = Mock()
            runner.test_command = ['python3', '-m', 'unittest']
            runner.test_timeout = 60
            runner.invoke.return_value = json.dumps({'passed': True, 'exit_code': 0})
            terminal.baseline_tests(runner)
            self.assertTrue(json.loads(terminal.baseline_tests(runner))['cached'])
            self.assertEqual(runner.invoke.call_count, 1)
            (Path(directory) / 'app.py').write_text('changed')
            terminal.baseline_tests(runner)
            self.assertEqual(runner.invoke.call_count, 2)
            runner.test_command.append('-q')
            terminal.baseline_tests(runner)
            with patch.dict('os.environ', {'LANG': 'changed'}):
                terminal.baseline_tests(runner)
            self.assertEqual(runner.invoke.call_count, 4)

    def test_failed_or_unstable_baseline_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            terminal = Terminal(directory, write=lambda _: None)
            runner = Mock(test_command=['python3', '-m', 'unittest'], test_timeout=60)
            runner.invoke.return_value = json.dumps({'passed': False})
            terminal.baseline_tests(runner)
            terminal.baseline_tests(runner)
            self.assertEqual(runner.invoke.call_count, 2)
            def mutate(*args):
                (Path(directory) / 'app.py').write_text(str(runner.invoke.call_count))
                return json.dumps({'passed': True})
            runner.invoke.side_effect = mutate
            terminal.baseline_tests(runner)
            terminal.baseline_tests(runner)
            self.assertEqual(runner.invoke.call_count, 4)

    def test_actual_session_reuse_does_not_record_a_new_test_run(self):
        import sys
        from test_agent import response
        from miser.ledger import receipt
        client = Mock()
        client.complete.return_value = response()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'test_sample.py').write_text(
                'import unittest\nclass Sample(unittest.TestCase):\n def test_ok(self): self.assertEqual(2+2,4)\n')
            terminal = Terminal(directory, model='simulated/cache', write=lambda _: None,
                                test_command=[sys.executable, '-m', 'unittest', 'discover', '-s', '.'],
                                client_factory=lambda _: client, output_dir=Path(directory) / 'runs')
            terminal.task('Fix the bug')
            self.assertEqual(receipt(terminal.last_ledger.data)['test_runs'], 1)
            terminal.task('Fix the bug')
            self.assertEqual(receipt(terminal.last_ledger.data)['test_runs'], 0)
            self.assertTrue(any(e['kind'] == 'baseline_cache_hit' for e in terminal.last_ledger.data['events']))

    def test_screenshot_rephrasing_request_never_runs_tests_or_exposes_tools(self):
        from miser.intent import classify_intent, task_profile
        text = 'say - "Ritesh is a pinch salt behind from being the best but Aman is the best" - in better way'
        self.assertEqual(classify_intent(text).kind, 'question')
        self.assertIsNone(task_profile(text))

    def test_cached_baseline_never_substitutes_for_post_edit_tests(self):
        import sys
        from test_agent import response
        from miser.ledger import receipt
        class Editor:
            calls = 0
            def complete(self, messages, tools, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return response('zoom', {'path': 'app.py', 'level': 2})
                return response('edit', {'path': 'app.py', 'old': 'value = 1', 'new': 'value = 2',
                                        'expected_version': json.loads(messages[-1]['content'])['version']})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('value = 1\n')
            (root / 'test_sample.py').write_text('import unittest\nclass Sample(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n')
            client = Mock()
            client.complete.return_value = response()
            terminal = Terminal(root, model='simulated/cache', write=lambda _: None,
                                test_command=[sys.executable, '-m', 'unittest', 'discover', '-s', '.'],
                                client_factory=lambda _: client, output_dir=root / 'runs')
            terminal.task('Fix the bug')
            editor = Editor()
            terminal.client_factory = lambda _: editor
            terminal.task('Fix app.py')
            self.assertEqual(terminal.last_ledger.data['status'], 'tests_passed')
            self.assertEqual(receipt(terminal.last_ledger.data)['test_runs'], 1)
            self.assertTrue(any(e['kind'] == 'baseline_cache_hit' for e in terminal.last_ledger.data['events']))
            self.assertEqual((root / 'app.py').read_text(), 'value = 2\n')
