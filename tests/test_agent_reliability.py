"""Deterministic protocol/context/failed-loop regressions, no network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from miser.agent import run_agent, compact_digest, DIGEST_LIMIT
from miser.ledger import Ledger, receipt
from miser.memory import WorkingMemory
from miser.tools import ToolRunner
from miser.workspace import Workspace
from test_agent import response

class ReliabilityTests(unittest.TestCase):
    def test_malformed_envelopes_stop_actionably_before_any_tool_and_keep_reported_usage(self):
        valid=response('zoom',{'path':'app.py'})
        variants=[]
        for choices in ([], None, 'bad', [None], [{'message':None}], [{'message':{'content':42}}],
                        [{'message':{'tool_calls':[None]}}]):
            item=copy.deepcopy(valid); item['choices']=choices; variants.append(item)
        bad=copy.deepcopy(valid); bad['choices'][0]['message']['tool_calls']*=2; variants.append(bad)
        for item in variants:
            with self.subTest(item=item), tempfile.TemporaryDirectory() as directory:
                book=Ledger(Path(directory)/'ledger.json')
                runner=ToolRunner(Workspace(directory),book,[],profile='inspect')
                class Client:
                    def complete(self,*a,**k):return item
                with patch.object(runner,'invoke',side_effect=AssertionError('No tool may execute')):
                    status=run_agent('Explain app.py',Client(),runner,book)
                self.assertEqual(status,'invalid_model_response')
                self.assertIn('Invalid model response',book.data['agent_message'])
                self.assertEqual(receipt(book.data)['total_tokens'],120)
                self.assertEqual(receipt(book.data)['model_calls'],1)

    def test_batched_read_compaction_keeps_exact_versions_and_explicit_omission_count(self):
        reads=[{'path':f'file{i}.py','version':str(i)*64,'text':'large source '*100} for i in range(8)]
        result=compact_digest(json.dumps({'reads':reads}))
        self.assertLessEqual(len(result),DIGEST_LIMIT)
        digest=json.loads(result)
        self.assertGreater(len(digest['reads']),0)
        self.assertEqual(len(digest['reads'])+digest['omitted_reads'],8)
        for item in digest['reads']:
            original=next(row for row in reads if row['path']==item['path'])
            self.assertEqual(item['version'],original['version'])
            self.assertNotIn('text',item)
        memory=WorkingMemory()
        memory.observe('read_many',{},json.dumps({'reads':reads}))
        memory.compact()
        self.assertEqual(len(memory.snapshot()['files']),8)
        self.assertEqual(memory.snapshot()['files'][0]['version'],reads[0]['version'])

    def test_three_identical_failed_turns_stop_before_spending_the_whole_step_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            book=Ledger(Path(directory)/'ledger.json')
            runner=ToolRunner(Workspace(directory),book,[],profile='inspect')
            class Client:
                calls=0
                def complete(self,*a,**k):
                    self.calls+=1
                    return response('nonexistent_tool',{'path':'app.py'})
            client=Client()
            status=run_agent('Explain app.py',client,runner,book,max_steps=10)
            self.assertEqual(status,'tool_loop')
            self.assertEqual(client.calls,3)
            self.assertEqual(receipt(book.data)['total_tokens'],360)
            self.assertIn('identical',book.data['agent_message'])

    def test_successful_repeats_and_changing_failed_arguments_can_continue(self):
        for successful in (True,False):
            with self.subTest(successful=successful), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); (root/'app.py').write_text('value = 1\n')
                book=Ledger(root/'ledger.json')
                runner=ToolRunner(Workspace(root),book,[],profile='inspect')
                class Client:
                    calls=0
                    def complete(inner,*a,**k):
                        inner.calls+=1
                        if inner.calls==5:return response()
                        return response('zoom' if successful else 'missing_tool',
                                        {'path':'app.py' if successful else str(inner.calls)})
                client=Client()
                self.assertEqual(run_agent('Explain app.py',client,runner,book,max_steps=8),'answered')
                self.assertEqual(client.calls,5)

    def test_question_malformed_response_keeps_valid_usage_and_invalid_usage_is_unknown(self):
        from miser.terminal import Terminal
        for usage,known in [({'prompt_tokens':100,'completion_tokens':20,'total_tokens':120},True),
                            (['bad'],False),({'prompt_tokens':True,'completion_tokens':False,'total_tokens':True},False)]:
            with self.subTest(usage=usage), tempfile.TemporaryDirectory() as directory:
                class Client:
                    def complete(self,*a,**k):return {'choices':[None],'usage':usage}
                output=[]
                terminal=Terminal(directory,model='simulated',write=output.append,client_factory=lambda _:Client())
                terminal.task('how are you?')
                self.assertEqual(terminal.session_provider_tokens,120 if known else 0)
                self.assertEqual(terminal.session_unknown_usage,0 if known else 1)
                self.assertIn('Invalid model response','\n'.join(output))

    def test_nonobject_agent_response_is_actionable_with_unknown_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            book=Ledger(Path(directory)/'ledger.json')
            runner=ToolRunner(Workspace(directory),book,[],profile='inspect')
            class Client:
                def complete(self,*a,**k):return None
            self.assertEqual(run_agent('Explain app.py',Client(),runner,book),'invalid_model_response')
            self.assertFalse(receipt(book.data)['usage_complete'])
            self.assertEqual(receipt(book.data)['model_calls'],0)

    def test_malformed_architect_reply_is_skipped_without_losing_known_usage(self):
        from miser.agent import plan_task
        with tempfile.TemporaryDirectory() as directory:
            book=Ledger(Path(directory)/'ledger.json')
            class Client:
                def complete(self,*a,**k):
                    result=response(); result['choices']=[None]; return result
            self.assertIsNone(plan_task('Fix app.py',Client(),book,24000))
            self.assertEqual(receipt(book.data)['total_tokens'],120)
            self.assertTrue(receipt(book.data)['usage_complete'])
