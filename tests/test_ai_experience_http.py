"""Real isolated HTTP conversations, revisions, progress and project exports.

All records, folders, credentials and model replies are synthetic. No provider
connection or production directory is used.
"""
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from tests import test_server as server_fixture
from workos.ai_progress import report_progress
from workos.server import Application, Handler


class AiExperienceHttpTests(unittest.TestCase):
    request = server_fixture.ServerTests.request

    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('workos.server.find_root', return_value=None))
        self.stack.enter_context(patch.dict(os.environ, {'WORKOS_SYNC_ROOT': '', 'WORKOS_PUBLIC_ORIGIN': '',
            'WORKOS_PUBLIC_AUTH_MODE': 'access', 'WORKOS_ACCESS_TEAM': '', 'WORKOS_ACCESS_AUD': ''}))
        mirror = Mock(); mirror.status.return_value = {'enabled': False}; mirror.sync.return_value = {'enabled': False}
        self.stack.enter_context(patch('workos.server.OneDriveMirror', return_value=mirror))
        self.app = Application(Path(self.temp.name) / 'runtime', port=0); self.addCleanup(self.app.close)
        self.app.local_chat = Mock(side_effect=AssertionError('Unexpected synthetic provider call'))
        self.app.dsh_answer = Mock(side_effect=AssertionError('Unexpected synthetic DSH call'))
        self.app.dsh_available = True
        self.store = self.app.stores['personal']
        self.project = self.store.create('projects', {'name': 'Synthetic Experience Alpha'})
        self.other = self.store.create('projects', {'name': 'Synthetic Experience Beta'})
        self.doc = self.store.create('documents', {'title': 'Synthetic source A', 'project_id': self.project['id'],
            'content': 'Synthetic company evidence and revenue from explicitly supplied source A.'})
        self.doc2 = self.store.create('documents', {'title': 'Synthetic source B', 'project_id': self.project['id'],
            'content': 'Different synthetic source evidence.'})
        root = Path(self.temp.name) / 'synthetic-projects'; root.mkdir()
        self.project_folder = root / self.project['name']; self.project_folder.mkdir()
        self.app.artifacts.configure([root])
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler); self.httpd.daemon_threads = True
        self.httpd.app = self.app; self.app.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start(); self.addCleanup(self.stop_server)
        self.sequence = 0

    def stop_server(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def post(self, path, body, *, request_id=None, workspace='personal', headers=None):
        actual = dict(headers or {})
        if request_id: actual['X-WorkOS-Request-ID'] = request_id
        return self.request('POST', path, body, workspace=workspace, headers=actual)

    def ask_body(self, **changes):
        return {'question': 'Explain this synthetic company evidence', 'project_id': self.project['id'],
            'document_ids': [self.doc['id']], 'mode': 'deepseek', **changes}

    def conversation(self, conversation_id):
        status, result = self.request('GET', '/api/conversations/' + conversation_id)
        self.assertEqual(status, 200, result)
        return result['conversation']

    def assert_archived(self, receipt):
        self.assertEqual(receipt['status'], 'saved', receipt)
        self.assertEqual(Path(receipt['folder']), self.project_folder)
        self.assertTrue(receipt['files'])
        self.assertTrue(all(Path(item['path']).is_file() for item in receipt['files']))

    def test_two_turn_ask_uses_history_without_automatically_saving_project_files(self):
        self.app.local_chat.side_effect = [('FIRST_TURN_RESULT [S1]', 'Synthetic model'),
                                           ('SECOND_TURN_RESULT [S1]', 'Synthetic model')]
        first_status, first = self.post('/api/ask', self.ask_body(), request_id='synthetic-first-ask')
        self.assertEqual(first_status, 200, first)
        second_status, second = self.post('/api/ask', self.ask_body(question='Make the previous answer shorter',
            conversation_id=first['conversation_id']), request_id='synthetic-second-ask')
        self.assertEqual(second_status, 200, second)
        prompt = self.app.local_chat.call_args.args[3]
        self.assertIn('Explain this synthetic company evidence', prompt)
        self.assertIn('FIRST_TURN_RESULT', prompt)
        self.assertIn('Make the previous answer shorter', prompt)
        self.assertEqual(second['conversation_id'], first['conversation_id'])
        self.assertEqual(second['context']['turn_count'], 2)
        conversation = self.conversation(first['conversation_id'])
        self.assertEqual(len(conversation['turns']), 2)
        self.assertEqual(conversation['purpose'], 'ask')
        self.assertEqual(conversation['source_ids'], [self.doc['id']])
        self.assertEqual(self.app.artifacts.status('personal', self.project)['archives'], [])
        self.assertEqual(self.store.list('deliverables'), [])

    def test_workspace_sources_project_and_purpose_cannot_reuse_foreign_context(self):
        self.app.local_chat.side_effect = None; self.app.local_chat.return_value = ('Scoped answer [S1]', 'Synthetic model')
        status, result = self.post('/api/ask', self.ask_body())
        self.assertEqual(status, 200, result); conversation_id = result['conversation_id']
        for changes in ({'document_ids': [self.doc2['id']]}, {'project_id': self.other['id']}, {'mode': 'deepseek'}):
            if changes == {'mode': 'deepseek'}:
                status, rejected = self.post('/api/model/parse-assumptions', {'method': 'net_income', 'text': 'Synthetic assumptions',
                    'project_id': self.project['id'], 'conversation_id': conversation_id})
            else:
                status, rejected = self.post('/api/ask', self.ask_body(conversation_id=conversation_id, **changes))
            self.assertEqual(status, 400, rejected)
        self.assertEqual(self.request('GET', '/api/conversations/' + conversation_id, workspace='demo')[0], 404)
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.app.dsh_answer.assert_not_called()

    def test_meeting_revisions_use_current_manual_summary_and_archive_each_version(self):
        meeting = self.store.create('meetings', {'title': 'Synthetic expert meeting', 'project_id': self.project['id'],
            'transcript': 'Synthetic transcript: demand is discussed without numerical claims.'})
        replies = [dict(summary='FIRST_MEETING_SUMMARY', experts=[], matrix={}, contents=[]),
                   dict(summary='SECOND_MEETING_SUMMARY', experts=[], matrix={}, contents=[])]
        self.app.local_chat.side_effect = [(json.dumps(reply), 'Synthetic model') for reply in replies]
        body = {'save_meeting_id': meeting['id'], 'project_id': self.project['id'], 'transcript': meeting['transcript'],
                'provider': 'deepseek', 'revision_instructions': 'Organize the supplied transcript'}
        status, first = self.post('/api/meeting-draft', body, request_id='synthetic-meeting-first')
        self.assertEqual(status, 200, first); self.assert_archived(first['archive'])
        status, edited = self.request('PATCH', '/api/meetings/' + meeting['id'], {'summary': 'MANUAL_CURRENT_SUMMARY'})
        self.assertEqual(status, 200, edited)
        status, second = self.post('/api/meeting-draft', {**body, 'conversation_id': first['conversation_id'],
            'revision_instructions': 'LATEST_MEETING_INSTRUCTION keep the manual correction'}, request_id='synthetic-meeting-second')
        self.assertEqual(status, 200, second); self.assert_archived(second['archive'])
        prompt = self.app.local_chat.call_args.args[3]
        for marker in ('FIRST_MEETING_SUMMARY', 'MANUAL_CURRENT_SUMMARY', 'LATEST_MEETING_INSTRUCTION'):
            self.assertIn(marker, prompt)
        self.assertEqual(self.store.get('meetings', meeting['id'])['summary'], 'SECOND_MEETING_SUMMARY')
        self.assertNotEqual(first['archive']['archive_id'], second['archive']['archive_id'])
        self.assertGreater(second['archive']['version_number'], first['archive']['version_number'])
        conversation = self.conversation(first['conversation_id'])
        self.assertEqual(conversation['metadata']['meeting_id'], meeting['id'])
        self.assertEqual(conversation['turns'][-1]['base_snapshot']['summary'], 'MANUAL_CURRENT_SUMMARY')

    def test_valuation_preserves_prior_assumptions_and_requires_same_method(self):
        assumptions = {'currency': 'RMB', 'unit': 'millions', 'period': 'FY2026E', 'net_income': 25, 'pe_multiple': 12}
        changed = {**assumptions, 'net_income': 30, 'pe_multiple': 13}
        self.app.dsh_answer.side_effect = [json.dumps({'assumptions': assumptions}), json.dumps({'assumptions': changed})]
        body = {'method': 'net_income', 'text': 'Synthetic original valuation assumptions', 'model_id': 'gpt-6-luna',
                'project_id': self.project['id']}
        status, first = self.post('/api/model/parse-assumptions', body)
        self.assertEqual(status, 200, first)
        status, second = self.post('/api/model/parse-assumptions', {**body, 'text': 'Change the multiple to 13',
            'conversation_id': first['conversation_id'], 'prior_assumptions': {**assumptions, 'net_income': 30}})
        self.assertEqual(status, 200, second)
        prompt = self.app.dsh_answer.call_args.args[0]
        self.assertIn('Synthetic original valuation assumptions', prompt)
        self.assertIn('"net_income": 30', prompt)
        self.assertEqual(second['assumptions'], changed)
        conversation = self.conversation(first['conversation_id'])
        self.assertEqual(conversation['metadata']['method'], 'net_income')
        self.assertEqual(conversation['turns'][-1]['output_snapshot']['assumptions'], changed)
        status, rejected = self.post('/api/model/parse-assumptions', {**body, 'method': 'ps', 'conversation_id': first['conversation_id']})
        self.assertEqual(status, 400, rejected)
        self.assertEqual(self.app.dsh_answer.call_count, 2)
        self.assertEqual(self.app.artifacts.status('personal', self.project)['archives'], [])

    def test_workflow_revision_reads_current_parent_and_retains_original_with_archive_receipts(self):
        self.app.local_chat.side_effect = [('ORIGINAL_WORKFLOW_BODY [S1]', 'Synthetic model'),
                                           ('REVISED_WORKFLOW_BODY [S1]', 'Synthetic model')]
        body = {'workflow_key': 'brief', 'message': 'Provide a concise synthetic analysis', 'project_id': self.project['id'],
            'document_ids': [self.doc['id']], 'mode': 'deepseek', 'quality_mode': 'fast', 'request_id': 'synthetic-workflow-first'}
        status, first = self.post('/api/workflows/run', body)
        self.assertEqual(status, 201, first); self.assert_archived(first['archive'])
        parent_id = first['deliverable_id']
        status, edited = self.request('PATCH', '/api/deliverables/' + parent_id, {'body': 'MANUAL_CURRENT_PARENT [S1]'})
        self.assertEqual(status, 200, edited)
        revision_body = {**body, 'message': 'LATEST_REVISION_REQUEST make the text concise', 'request_id': 'synthetic-workflow-revision',
                         'conversation_id': first['conversation_id'], 'revision_of': parent_id}
        status, revised = self.post('/api/workflows/run', revision_body)
        self.assertEqual(status, 201, revised); self.assert_archived(revised['archive'])
        prompt = self.app.local_chat.call_args.args[3]
        self.assertIn('MANUAL_CURRENT_PARENT', prompt); self.assertIn('LATEST_REVISION_REQUEST', prompt)
        self.assertEqual(revised['deliverable']['revision_number'], 2)
        self.assertEqual(revised['deliverable']['revision_of'], parent_id)
        self.assertNotEqual(revised['deliverable_id'], parent_id)
        self.assertEqual(self.store.get('deliverables', parent_id)['body'], 'MANUAL_CURRENT_PARENT [S1]')
        status, replay = self.post('/api/workflows/run', revision_body)
        self.assertEqual(status, 201, replay)
        self.assertEqual(replay['deliverable_id'], revised['deliverable_id'])
        self.assertEqual(self.app.local_chat.call_count, 2)
        conversation = self.conversation(first['conversation_id'])
        self.assertEqual(len(conversation['turns']), 2)
        self.assertEqual(conversation['turns'][-1]['parent_artifact']['id'], parent_id)
        self.assertEqual(conversation['turns'][-1]['base_snapshot']['body'], 'MANUAL_CURRENT_PARENT [S1]')

    def test_revision_with_narrower_parent_sources_rejects_before_provider_or_save(self):
        parent = self.store.create('deliverables', {'title': 'Synthetic two-source parent',
            'project_id': self.project['id'], 'body': 'Original parent [S1] [S2]',
            'source_ids': [self.doc['id'], self.doc2['id']], 'workflow_key': 'brief'})
        status, rejected = self.post('/api/workflows/run', {'workflow_key': 'brief',
            'message': 'Revise the parent concisely', 'project_id': self.project['id'],
            'document_ids': [self.doc['id']], 'revision_of': parent['id'], 'mode': 'deepseek',
            'quality_mode': 'fast', 'request_id': 'synthetic-narrower-parent'})
        self.assertEqual(status, 400, rejected)
        self.app.local_chat.assert_not_called(); self.app.dsh_answer.assert_not_called()
        self.assertEqual(self.store.list('deliverables'), [parent])
        self.assertEqual(self.app.conversations.list('personal'), [])
        self.assertEqual(self.app.artifacts.status('personal', self.project)['archives'], [])

    def test_manual_parent_edit_during_sync_revision_prevents_stale_save_and_context(self):
        parent = self.store.create('deliverables', {'title': 'Synthetic revision parent',
            'project_id': self.project['id'], 'body': 'Original revision basis [S1]',
            'source_ids': [self.doc['id']], 'workflow_key': 'brief'})
        chat = self.app.conversations.create('personal', self.project['id'], 'workflow',
            source_ids=[self.doc['id']], metadata={'workflow_key': 'brief'})
        self.app.conversations.append('personal', chat['id'], 'Prior synthetic request',
            'Prior successful synthetic draft [S1]', current_artifact={'collection': 'deliverables', 'id': parent['id']})
        entered, release = threading.Event(), threading.Event(); responses = []

        def reply(*_args, **_kwargs):
            entered.set()
            if not release.wait(5): raise AssertionError('Synthetic revision provider was not released')
            return 'STALE_GENERATED_REVISION [S1]', 'Synthetic model'

        self.app.local_chat.side_effect = reply
        body = {'workflow_key': 'brief', 'message': 'Revise the parent concisely', 'project_id': self.project['id'],
            'document_ids': [self.doc['id']], 'revision_of': parent['id'], 'conversation_id': chat['id'],
            'mode': 'deepseek', 'quality_mode': 'fast', 'request_id': 'synthetic-edited-parent'}
        worker = threading.Thread(target=lambda: responses.append(self.post('/api/workflows/run', body)))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            status, edited = self.request('PATCH', '/api/deliverables/' + parent['id'],
                {'body': 'USER_MANUAL_EDIT_DURING_GENERATION [S1]'})
            self.assertEqual(status, 200, edited); self.assert_archived(edited['archive'])
        finally:
            release.set(); worker.join(5)
        self.assertFalse(worker.is_alive()); self.assertEqual(responses[0][0], 400, responses)
        self.assertEqual(len(self.store.list('deliverables')), 1)
        self.assertEqual(self.store.get('deliverables', parent['id'])['body'], 'USER_MANUAL_EDIT_DURING_GENERATION [S1]')
        self.app.local_chat.assert_called_once()
        self.assertIn('Original revision basis', self.app.local_chat.call_args.args[3])
        history = self.conversation(chat['id'])
        self.assertEqual([turn['status'] for turn in history['turns']], ['completed', 'failed'])
        context = self.app.conversations.context('personal', chat['id'])
        self.assertEqual(len(context['messages']), 2)
        self.assertNotIn('STALE_GENERATED_REVISION', json.dumps(context))
        self.assertEqual(len(self.app.artifacts.status('personal', self.project)['archives']), 1)

    def test_stop_after_sync_final_commit_preserves_successful_history_and_archive(self):
        from workos import workflows
        original = workflows.run_workflow
        committed, release = threading.Event(), threading.Event(); responses = []

        def committed_then_wait(*args, **kwargs):
            result = original(*args, **kwargs)
            committed.set()
            if not release.wait(5): raise AssertionError('Synthetic final-commit barrier was not released')
            return result

        self.app.local_chat.side_effect = None
        self.app.local_chat.return_value = ('COMMITTED_SYNTHETIC_WORKFLOW [S1]', 'Synthetic model')
        request_id = 'synthetic-sync-final-save'
        body = {'workflow_key': 'brief', 'message': 'Provide a concise synthetic analysis', 'project_id': self.project['id'],
            'document_ids': [self.doc['id']], 'mode': 'deepseek', 'quality_mode': 'fast', 'request_id': request_id}
        worker = threading.Thread(target=lambda: responses.append(self.post('/api/workflows/run', body, request_id=request_id)))
        with patch('workos.workflows.run_workflow', side_effect=committed_then_wait):
            worker.start()
            try:
                self.assertTrue(committed.wait(3))
                status, stopped = self.post('/api/operations/' + request_id + '/cancel', {})
                self.assertEqual(status, 200, stopped)
                self.assertEqual(stopped['status'], 'completed', stopped)
                self.assertEqual(len(self.store.list('deliverables')), 1)
            finally:
                release.set(); worker.join(5)
        self.assertFalse(worker.is_alive()); self.assertEqual(responses[0][0], 201, responses)
        result = responses[0][1]; self.assert_archived(result['archive'])
        history = self.conversation(result['conversation_id'])
        self.assertEqual([turn['status'] for turn in history['turns']], ['completed'])
        self.assertEqual(history['turns'][0]['current_artifact']['id'], result['deliverable_id'])
        self.assertEqual(len(self.store.list('deliverables')), 1)
        self.app.local_chat.assert_called_once()

    def test_get_progress_during_held_model_is_bounded_and_hides_model_inputs(self):
        entered, release = threading.Event(), threading.Event(); result = []

        def reply(*_args, **_kwargs):
            report_progress('provider', 'Waiting for the synthetic selected model')
            entered.set()
            if not release.wait(5): raise AssertionError('Synthetic provider was not released')
            return 'Progress answer [S1]', 'Synthetic model'

        self.app.local_chat.side_effect = reply
        request_id = 'synthetic-progress-operation'
        worker = threading.Thread(target=lambda: result.append(self.post('/api/ask', self.ask_body(question='PRIVATE_SYNTHETIC_PROMPT'),
                                                                         request_id=request_id)))
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            status, response = self.request('GET', '/api/operations/' + request_id)
            self.assertEqual(status, 200, response); progress = response['operation']
            self.assertEqual(progress['status'], 'running')
            self.assertEqual(progress['stage'], 'provider')
            self.assertTrue(progress['eta']['estimated'])
            self.assertGreaterEqual(progress['elapsed_ms'], 0)
            self.assertGreaterEqual(progress['eta']['max_seconds'], progress['eta']['min_seconds'])
            self.assertTrue(progress['events'])
            encoded = json.dumps(progress)
            for hidden in ('PRIVATE_SYNTHETIC_PROMPT', self.doc['content'], '_created_ts', '_context', 'api_key', 'reasoning'):
                self.assertNotIn(hidden, encoded)
            self.assertEqual(self.request('GET', '/api/operations/' + request_id, workspace='demo')[0], 404)
        finally:
            release.set(); worker.join(5)
        self.assertFalse(worker.is_alive()); self.assertEqual(result[0][0], 200, result)
        status, completed = self.request('GET', '/api/operations/' + request_id)
        self.assertEqual(status, 200); self.assertEqual(completed['operation']['status'], 'completed')
        self.assertEqual(completed['operation']['eta']['max_seconds'], 0)

    def test_generic_saves_autoarchive_downloads_are_scoped_and_retry_never_calls_model(self):
        for collection in ('notes', 'deliverables'):
            status, record = self.post('/api/' + collection, {'title': 'Synthetic saved ' + collection,
                'project_id': self.project['id'], 'body': 'Explicitly saved synthetic content'})
            self.assertEqual(status, 201, record); self.assert_archived(record['archive'])
            archive = record['archive']; item = next(file for file in archive['files'] if file['format'] == 'html')
            path = f'/api/artifacts/{archive["archive_id"]}/files/{item["index"]}'
            status, downloaded = self.request('GET', path)
            self.assertEqual(status, 200); self.assertIn('Explicitly saved synthetic content', downloaded)
            self.assertEqual(self.request('GET', path, workspace='demo')[0], 404)
            status, retried = self.post('/api/artifacts/archive', {'collection': collection, 'id': record['id']})
            self.assertEqual(status, 200, retried)
            self.assertEqual(retried['archive']['archive_id'], archive['archive_id'])
        self.app.local_chat.assert_not_called(); self.app.dsh_answer.assert_not_called()
        self.app.public_origin = 'https://synthetic.example.invalid'; self.app.public_auth_mode = 'password'
        self.assertEqual(self.request('GET', path, headers={'Host': 'synthetic.example.invalid'})[0], 401)

    def test_binding_changes_require_local_connection_even_for_authenticated_public_user(self):
        target = self.project_folder
        self.app.public_origin = 'https://synthetic.example.invalid'; self.app.public_auth_mode = 'access'
        self.app.access_validator.verify = Mock(return_value={'sub': 'synthetic-user'})
        status, denied = self.post('/api/projects/' + self.project['id'] + '/artifacts/bind', {'path': str(target)},
            headers={'Host': 'synthetic.example.invalid', 'Origin': self.app.public_origin,
                     'Cf-Access-Jwt-Assertion': 'synthetic-access-token'})
        self.assertEqual(status, 403, denied)
        self.assertNotIn(self.project['id'], self.app.artifacts.config['bindings'])
        status, bound = self.post('/api/projects/' + self.project['id'] + '/artifacts/bind', {'path': str(target)})
        self.assertEqual(status, 200, bound); self.assertEqual(bound['source'], 'manual')


if __name__ == '__main__':
    unittest.main()
