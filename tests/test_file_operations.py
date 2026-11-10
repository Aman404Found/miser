"""Guarded deletion and small file workflows; scripted providers, real files."""
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from miser.ledger import Ledger, receipt
from miser.terminal import Terminal
from miser.tools import ToolRunner, READ_ONLY_TOOLS, schemas_for_profile
from miser.workspace import Workspace, digest
from test_agent import response, batch_response


class FileOperationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / 'note.txt'
        self.file.write_bytes(b'original\r\n')
        self.file.chmod(0o640)
        self.ws = Workspace(self.root)
        self.book = Ledger(self.root / 'ledger.json')

    def runner(self, **kwargs):
        return ToolRunner(self.ws, self.book, [], profile='files', **kwargs)

    def test_delete_requires_prior_read_exact_version_and_keeps_private_recovery_copy(self):
        with self.assertRaisesRegex(ValueError, 'read|Read'):
            self.ws.delete_file('note.txt', digest('original\r\n'))
        version = self.ws.zoom('note.txt')['version']
        with self.assertRaisesRegex(ValueError, 'version|changed'):
            self.ws.delete_file('note.txt', 'wrong')
        self.assertTrue(self.file.exists())
        result = self.ws.delete_file('note.txt', version)
        self.assertFalse(self.file.exists())
        self.assertEqual((self.root / result['backup']).read_bytes(), b'original\r\n')
        self.assertEqual(stat.S_IMODE((self.root / result['backup']).stat().st_mode), 0o600)
        manifest = json.loads((self.root / (result['backup'] + '.json')).read_text())
        self.assertEqual(manifest['path'], 'note.txt')
        self.assertEqual(manifest['original_mode'], 0o640)
        self.assertEqual(manifest['version'], version)
        self.assertNotIn(result['backup'], self.ws.files())
        with self.assertRaises(ValueError):
            self.ws.text(result['backup'])

    def test_delete_rechecks_after_recovery_staging_and_does_not_remove_external_change(self):
        version = self.ws.zoom('note.txt')['version']
        original = self.ws._save_deletion_backup
        def race(*args):
            backup = original(*args)
            self.file.write_text('external change')
            return backup
        with patch.object(self.ws, '_save_deletion_backup', side_effect=race), self.assertRaisesRegex(ValueError, 'changed'):
            self.ws.delete_file('note.txt', version)
        self.assertEqual(self.file.read_text(), 'external change')
        self.assertFalse(self.ws.modified)

    def test_deletion_refuses_unsafe_sensitive_nonregular_and_protected_targets(self):
        runner = self.runner(deletion_approval=lambda *_: True)
        (self.root / 'link.txt').symlink_to(self.file)
        (self.root / 'folder.txt').mkdir()
        for path in ('../note.txt', '/etc/passwd', '.env', 'link.txt', 'folder.txt', 'tests/note.txt'):
            with self.subTest(path=path):
                self.assertIn('error', json.loads(runner.invoke('delete_file', {'path':path,'expected_version':'x'})))
        self.assertTrue(self.file.exists())

    def test_deletion_requires_fresh_approval_even_without_normal_edit_confirmation(self):
        version = self.ws.zoom('note.txt')['version']
        args = {'path':'note.txt','expected_version':version}
        self.assertIn('error', json.loads(self.runner().invoke('delete_file', args)))
        seen = []
        runner = self.runner(deletion_approval=lambda path, diff: seen.append((path,diff)) or False)
        self.assertIn('error', json.loads(runner.invoke('delete_file', args)))
        self.assertIn('error', json.loads(runner.invoke('delete_file', args)))
        self.assertEqual(len(seen), 2)
        self.assertIn('+++ /dev/null', seen[0][1])
        self.assertTrue(self.file.exists())
        self.assertNotIn('delete_file', READ_ONLY_TOOLS)

    def test_undo_deletion_preserves_bytes_mode_and_refuses_reappeared_file(self):
        terminal = Terminal(self.root, write=lambda _: None)
        version = terminal.workspace.zoom('note.txt')['version']
        terminal.workspace.delete_file('note.txt', version)
        self.assertIn('+++ /dev/null', terminal.compute_diff())
        self.file.write_text('external')
        terminal.undo()
        self.assertEqual(self.file.read_text(), 'external')
        self.assertIn('note.txt', terminal.workspace.modified)
        self.file.unlink()
        terminal.undo()
        self.assertEqual(self.file.read_bytes(), b'original\r\n')
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)

        self.assertNotIn('note.txt', terminal.workspace.deleted_modes)
        self.assertFalse(terminal.workspace.modified)

    def test_empty_file_delete_undo_and_created_then_deleted_net_change(self):
        terminal = Terminal(self.root, write=lambda _: None)
        self.file.write_bytes(b'')
        version = terminal.workspace.zoom('note.txt')['version']
        terminal.workspace.delete_file('note.txt', version)
        patch = terminal.compute_diff()
        terminal.undo()
        self.assertEqual(self.file.read_bytes(), b'')
        checked = subprocess.run(['git','apply','--check','-'],cwd=self.root,input=patch,text=True,capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        terminal.workspace.write_file('new.txt', 'new')
        terminal.workspace.delete_file('new.txt', digest('new'))
        terminal.undo()
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertFalse(terminal.workspace.modified)

    def test_files_profile_has_small_schema_and_enforces_paths_and_no_execution(self):
        runner = self.runner()
        names = {s['function']['name'] for s in schemas_for_profile('files')}
        self.assertEqual(names, {'zoom','read_many','write_file','edit','edit_batch','delete_file','ask_user'})
        for name, args in [('write_file',{'path':'code.py','content':'bad'}),
                           ('write_file',{'path':'requirements.txt','content':'dependency'}),
                           ('run_command',{'action':'run','argv':['rm','note.txt']}),
                           ('run_tests',{}), ('apply_patch',{'patch':'bad'})]:
            with self.subTest(tool=name,args=args):
                self.assertIn('error', json.loads(runner.invoke(name,args)))
        self.assertFalse((self.root / 'code.py').exists())
        with self.assertRaises(ValueError):
            runner.run_tests()

    def test_deletion_diff_displays_original_filename_instead_of_dev_null(self):
        from miser.ui.render import diff_files, render_diff
        patch = '--- a/note.txt\n+++ /dev/null\n@@ -1 +0,0 @@\n-original\n'
        self.assertEqual(diff_files(patch), [{'path':'note.txt','added':0,'removed':1}])
        self.assertIn('note.txt', render_diff(patch, 80))

    def test_compacted_memory_drops_deleted_version_and_clears_tombstone_after_recreation(self):
        from miser.memory import WorkingMemory
        memory = WorkingMemory()
        runner = self.runner(deletion_approval=lambda *_:True)
        args = {'path':'note.txt','level':2}
        read = runner.invoke('zoom', args)
        version = json.loads(read)['version']
        memory.observe('zoom',args,read)
        deletion = {'path':'note.txt','expected_version':version}
        memory.observe('delete_file',deletion,runner.invoke('delete_file',deletion))
        memory.compact()
        record = memory.snapshot()['files'][0]
        self.assertTrue(record['deleted'])
        self.assertNotIn('version', record)
        creation = {'path':'note.txt','content':'recreated'}
        memory.observe('write_file',creation,runner.invoke('write_file',creation))
        record = memory.snapshot()['files'][0]
        self.assertFalse(record.get('deleted'))
        self.assertEqual(record['version'],digest('recreated'))

    def test_deletion_patch_preserves_missing_final_newline_and_is_git_applicable(self):
        terminal = Terminal(self.root, write=lambda _: None)
        self.file.write_bytes(b'no final newline')
        version = terminal.workspace.zoom('note.txt')['version']
        terminal.workspace.delete_file('note.txt', version)
        patch = terminal.compute_diff()
        terminal.undo()
        self.assertEqual(self.file.read_bytes(), b'no final newline')
        checked = subprocess.run(['git','apply','--check','-'],cwd=self.root,input=patch,text=True,capture_output=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_recovery_flush_failure_or_cancellation_never_deletes_source(self):
        version = self.ws.zoom('note.txt')['version']
        with patch('miser.workspace.os.fsync', side_effect=OSError('simulated flush failure')), self.assertRaises(OSError):
            self.ws.delete_file('note.txt', version)
        self.assertTrue(self.file.exists())
        cancelled = []
        original = self.ws._save_deletion_backup
        def cancel_after_backup(*args):
            backup = original(*args)
            cancelled.append(True)
            return backup
        with patch.object(self.ws, '_save_deletion_backup', side_effect=cancel_after_backup), self.assertRaises(KeyboardInterrupt):
            self.ws.delete_file('note.txt', version, cancelled=lambda: bool(cancelled))
        self.assertTrue(self.file.exists())
        self.assertFalse(self.ws.modified)

    def test_recovery_directory_symlink_refuses_before_any_deletion(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.root / '.miser').symlink_to(outside)
            version = self.ws.zoom('note.txt')['version']
            with self.assertRaises(OSError):
                self.ws.delete_file('note.txt', version)
            self.assertTrue(self.file.exists())
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_partial_delete_create_failure_retains_recovery_and_undo(self):
        terminal = Terminal(self.root, write=lambda _: None)
        book = Ledger(self.root / 'partial.json')
        runner = ToolRunner(terminal.workspace, book, [], profile='files', deletion_approval=lambda *_:True)
        version = terminal.workspace.zoom('note.txt')['version']
        removed = json.loads(runner.invoke('delete_file', {'path':'note.txt','expected_version':version}))
        (self.root / 'occupied.txt').write_text('external')
        created = json.loads(runner.invoke('write_file', {'path':'occupied.txt','content':'replacement'}))
        self.assertIn('error', created)
        self.assertFalse(self.file.exists())
        self.assertTrue((self.root / removed['backup']).exists())
        terminal.undo()
        self.assertEqual(self.file.read_bytes(), b'original\r\n')
        self.assertEqual((self.root/'occupied.txt').read_text(), 'external')

    def test_recreate_after_deleted_task_restores_original_session_bytes_and_mode(self):
        terminal = Terminal(self.root, write=lambda _: None)
        version = terminal.workspace.zoom('note.txt')['version']
        terminal.workspace.delete_file('note.txt', version)
        other = Workspace(self.root)
        other.deleted_modes.update(terminal.workspace.deleted_modes)
        other.write_file('note.txt', 'replacement')
        terminal.workspace.last_written['note.txt'] = other.last_written['note.txt']
        terminal.workspace.deleted.discard('note.txt')
        terminal.undo()
        self.assertEqual(self.file.read_bytes(), b'original\r\n')
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o640)
        self.assertNotIn('note.txt', terminal.workspace.deleted_modes)

    def test_delete_create_task_uses_three_simulated_requests_no_tests_and_safe_session_undo(self):
        class Client:
            calls=0
            def complete(inner, messages, tools, **kwargs):
                inner.calls+=1
                self.assertEqual(len(tools), 7)
                if inner.calls==1:
                    return response('zoom',{'path':'note.txt','level':2})
                if inner.calls==2:
                    version=json.loads(messages[-1]['content'])['version']
                    return batch_response(('delete_file',{'path':'note.txt','expected_version':version}),
                                          ('write_file',{'path':'new.txt','content':'A short essay.\n'}))
                result=response()
                result['choices'][0]['message']['content']='Replaced the text file; tests not run.'
                return result
        client=Client()
        terminal=Terminal(self.root, model='simulated/files', write=lambda _:None,
                          client_factory=lambda _:client)
        terminal.prompt_delete_approval=lambda *_:True
        terminal.slash('/files on')
        with patch('miser.tools.ToolRunner.run_tests',side_effect=AssertionError('No acceptance tests in files mode')):
            terminal.task('Delete note.txt and create new.txt with an essay')
        self.assertFalse(self.file.exists())
        self.assertEqual((self.root/'new.txt').read_text(),'A short essay.\n')
        self.assertEqual(client.calls,3)
        self.assertEqual(terminal.last_route,'files')
        self.assertEqual(receipt(terminal.last_ledger.data)['test_runs'],0)
        self.assertEqual(terminal.last_ledger.data['status'],'edited_unverified')
        self.assertIn('+++ /dev/null',terminal.last_diff)
        terminal.undo()
        self.assertEqual(self.file.read_bytes(),b'original\r\n')
        self.assertFalse((self.root/'new.txt').exists())
        terminal.slash('/files off')
        self.assertEqual(terminal.task_mode,'auto')
