"""Synthetic quality-cycle integration; never reads personal data or calls models."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from workos.store import Store
from workos.workflows import run_workflow
from workos.quality import extract_constraints

CLEAN = json.dumps({'verdict': 'no_obvious_issues', 'findings': []})


class QualityCycleTests(unittest.TestCase):
    def test_explicit_data_rows_and_excluding_header_are_enforced(self):
        for request in ('只给3行数据的简短表格（不含表头）', '输出3行数据表格，不包括表头'):
            constraints = extract_constraints(request)
            self.assertTrue(constraints['table_required'])
            self.assertEqual(constraints['table_rows'], 3)
            self.assertFalse(constraints['table_rows_include_header'])
        self.assertNotIn('table_rows', extract_constraints('先给3行文字后给表格'))

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'synthetic.sqlite3')
        self.project = self.store.create('projects', {'name': 'Synthetic scope'})
        self.doc = self.store.create('documents', {'title': 'Synthetic memo', 'project_id': self.project['id'],
                                                  'content': 'A is an unconfirmed proposal. B is a risk.'})
        self.app = SimpleNamespace(ai={}, ai_lock=RLock(), local_chat=Mock(), dsh_answer=Mock())
        self.body = {'workflow_key': 'brief', 'message': '只给一个问题', 'project_id': self.project['id'],
                     'document_ids': [self.doc['id']], 'quality_mode': 'thorough'}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def generate(self, *responses):
        self.app.local_chat.side_effect = [(answer, 'Synthetic model') for answer in responses]
        return run_workflow(self.app, self.store, self.body)

    def test_clean_review_has_two_calls_and_never_certifies_truth(self):
        result = self.generate('1. 如何核实风险？[S1]', CLEAN)
        report = result['quality_report']
        self.assertEqual(self.app.local_chat.call_count, 2)
        self.assertEqual(report['repair_count'], 0)
        self.assertFalse(report['facts_verified'])
        self.assertEqual(report['review']['passes'], 1)
        self.assertEqual(self.store.get('deliverables', result['id'])['quality_report'], report)

    def test_constraint_failure_repairs_once_then_rechecks_and_reviews(self):
        result = self.generate('1. 如何核实A？[S1]\n2. 如何核实B？[S1]', CLEAN,
                               '1. 如何核实A？[S1]', CLEAN)
        self.assertEqual(self.app.local_chat.call_count, 4)
        self.assertEqual(result['quality_report']['repair_count'], 1)
        self.assertEqual(result['quality_report']['metrics']['questions'], 1)
        self.assertEqual(result['quality_report']['review']['passes'], 2)

    def test_semantic_blocking_review_triggers_repair(self):
        bad = 'A is executed [S1]'
        issue = json.dumps({'verdict': 'issues_found', 'findings': [{
            'criterion': 'status', 'severity': 'blocking', 'quote': bad, 'explanation': 'Evidence says proposal.',
            'proposed_fix': 'Use proposal status.', 'source_ids': ['S1']}]})
        self.body['message'] = 'Summarize the status.'
        result = self.generate(bad, issue, 'A remains an unconfirmed proposal [S1]', CLEAN)
        self.assertEqual(result['quality_report']['repair_count'], 1)
        self.assertIn('proposal', result['body'])

    def test_failed_repair_cannot_save_or_loop(self):
        bad = '1. 如何核实A？[S1]\n2. 如何核实B？[S1]'
        with self.assertRaisesRegex(ValueError, '没有保存草稿'):
            self.generate(bad, CLEAN, bad, CLEAN)
        self.assertEqual(self.app.local_chat.call_count, 4)
        self.assertEqual(self.store.list('deliverables'), [])

    def test_invalid_reviewer_json_is_failure_not_fake_pass(self):
        with self.assertRaisesRegex(ValueError, '有效JSON'):
            self.generate('1. 如何核实？[S1]', 'I verified everything.')
        self.assertEqual(self.store.list('deliverables'), [])

    def test_review_warnings_are_visible_and_save_as_needs_review(self):
        answer = '1. 如何核实？[S1]'
        warning = json.dumps({'verdict': 'issues_found', 'findings': [{
            'criterion': 'unknown', 'severity': 'warning', 'quote': '', 'explanation': 'The source is limited.',
            'proposed_fix': 'Obtain additional evidence.', 'source_ids': ['S1']}]})
        result = self.generate(answer, warning)
        self.assertEqual(result['quality_report']['status'], 'needs_review')
        self.assertEqual(len(result['quality_report']['review']['issues']), 1)
        self.assertEqual(self.app.local_chat.call_count, 2)

    def test_editing_saved_body_invalidates_quality_claim(self):
        result = self.generate('1. 如何核实？[S1]', CLEAN)
        updated = self.store.update('deliverables', result['id'], {'body': 'Changed answer'})
        self.assertTrue(updated['quality_report']['stale'])
        self.assertFalse(updated['quality_report']['facts_verified'])
        self.assertEqual(updated['quality_report']['checks'], [])

    def test_store_never_accepts_facts_verified_true(self):
        record = self.store.create('deliverables', {'title': 'Synthetic draft', 'quality_report': {'facts_verified': True}})
        self.assertFalse(record['quality_report']['facts_verified'])

    def test_native_dsh_generation_exposes_tool_coverage_without_unselected_material(self):
        self.body.update(mode='dsh', model_id='gpt-6-luna')
        coverage = [{'document_id': self.doc['id'], 'source_id': 'S1', 'title': self.doc['title'],
                     'excerpt_chars': len(self.doc['content']), 'total_chars': len(self.doc['content']), 'truncated': False}]
        self.app.dsh_harness_answer = Mock(return_value=('1. 如何核实？[S1]', {
            'name': 'DSH scoped evidence tools', 'coverage': coverage, 'completion_verified': True,
            'tool_counts': {'workos_read_source': 1, 'workos_check_draft': 1}}))
        self.app.dsh_answer.return_value = CLEAN
        result = run_workflow(self.app, self.store, self.body)
        self.assertEqual(result['coverage'], coverage)
        self.assertEqual(result['quality_report']['harness']['tool_counts']['workos_read_source'], 1)
        args = self.app.dsh_harness_answer.call_args.args
        self.assertNotIn(self.doc['content'], args[1])
        self.assertEqual([row['id'] for row in args[3]], [self.doc['id']])


if __name__ == '__main__':
    unittest.main()
