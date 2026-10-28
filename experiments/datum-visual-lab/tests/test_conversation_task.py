import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import conversation_experiment as conversation
import task_domain
import task_interface
import task_experiment
from task_store import TaskStore


class ConversationTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env=patch.dict(os.environ, {'DATUM_TASK_DB':str(Path(self.tmp.name)/'task.sqlite')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store=TaskStore()
        self.params={'machine_id':'BC-01','strategy':'baseline','allow_substitutes':False}
        self.task=self.store.create('repair_investigation',self.params,'agent')
        self.task=self.store.evaluate(self.task['task_id'],self.params,task_domain.evaluate_task('repair_investigation',self.params),'agent')

    def test_revision_ignores_audit_but_changes_with_evaluation_and_review(self):
        tid=self.task['task_id']
        self.assertEqual(self.task['revision'],1)
        self.store.record_tool_invocation(tid,'test','agent')
        self.assertEqual(self.store.get(tid,reopen=True)['revision'],1)
        latest=self.task['evaluations'][-1]['evaluation_id']
        self.assertEqual(self.store.review(tid,'reviewed','synthetic','human',latest)['revision'],2)

    def test_stale_view_cannot_overwrite_a_newer_result(self):
        tid=self.task['task_id']
        updated=conversation.datum_conversation_update(tid,'delivery',False,1)
        self.assertFalse(updated.is_error)
        self.assertEqual(updated.structured_content['revision'],2)
        stale=conversation.datum_conversation_evaluate(tid,'baseline',True,1)
        self.assertTrue(stale.is_error)
        self.assertIn('Stale task revision',stale.content[0].text)
        state=self.store.get(tid)
        self.assertEqual(state['parameters']['strategy'],'delivery')
        self.assertEqual(len(state['evaluations']),2)
        fresh=conversation.datum_conversation_evaluate(tid,'baseline',True,2)
        self.assertFalse(fresh.is_error)
        self.assertEqual(fresh.structured_content['revision'],3)

    def test_two_task_identifiers_do_not_share_state(self):
        conflict=self.store.create('supplier_conflict_review',{'part_id':'CP-09-ALT'},'agent')
        a=conversation.datum_conversation_open(self.task['task_id']).structured_content
        b=conversation.datum_conversation_open(conflict['task_id']).structured_content
        self.assertNotEqual(a['task_id'],b['task_id'])
        self.assertEqual(a['revision'],1)
        self.assertEqual(b['revision'],0)
        self.assertNotIn('source_hashes',a)

    def test_existing_task_view_submits_its_revision(self):
        tid=self.task['task_id']
        view=task_interface.build_interface(self.task)
        self.assertEqual(view['data']['parameters']['action']['arguments']['expected_revision'],1)
        self.assertFalse(conversation.datum_conversation_update(tid,'delivery',False,1).is_error)
        stale=task_experiment.datum_task_ui_evaluate(tid,'BC-01','baseline',False,expected_revision=1)
        self.assertTrue(stale.is_error)
        self.assertEqual(self.store.get(tid)['parameters']['strategy'],'delivery')

    def test_strict_revision_validation(self):
        result=task_domain.evaluate_task('repair_investigation',self.params)
        for revision in (-1, True, '1'):
            with self.assertRaises(ValueError):
                self.store.evaluate(self.task['task_id'],self.params,result,'agent',expected_revision=revision)


if __name__=='__main__': unittest.main()
