"""Durability, idempotency and evidence-scope regressions using synthetic stores."""
from __future__ import annotations
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from workos.jobs import FrozenStore, WorkflowJobs
from workos.store import Store


class PendingExecutor:
    """Simulate a process ending after durable enqueue, before worker execution."""
    def __init__(self, *args, **kwargs):
        self.submitted = []

    def submit(self, *args):
        self.submitted.append(args)

    def shutdown(self, wait=True):
        pass


class WorkflowJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.path = root / 'jobs.sqlite3'
        self.stores = {name: Store(root / (name + '.sqlite3')) for name in ('real', 'demo')}
        self.projects, self.docs = {}, {}
        for name, store in self.stores.items():
            self.projects[name] = store.create('projects', {'name': 'Synthetic ' + name})
            self.docs[name] = store.create('documents', {'title': 'Memo v1',
                'content': 'SYNTHETIC SELECTED ' + name, 'project_id': self.projects[name]['id']})
        self.app = SimpleNamespace(stores=self.stores, ai_lock=threading.RLock(), ai={},
            completion_meta=SimpleNamespace(finish_reason='stop'),
            local_chat=Mock(return_value=('合成判断仍需核实。[S1]', 'Synthetic model')),
            sync_workspace=Mock(), dsh_answer=Mock())
        self.managers, self.releases = [], []

    def tearDown(self):
        for event in self.releases:
            event.set()
        for jobs in reversed(self.managers):
            if not jobs.closed:
                jobs.close()
        for store in self.stores.values():
            store.close()
        self.temp.cleanup()

    def manager(self, **kwargs):
        jobs = WorkflowJobs(self.app, self.path, **kwargs)
        self.managers.append(jobs)
        return jobs

    def request(self, workspace='real', **overrides):
        return {'request_id': 'synthetic-request', 'workflow_key': 'brief',
                'message': '分析这一份材料', 'project_id': self.projects[workspace]['id'],
                'document_ids': [self.docs[workspace]['id']], 'mode': 'deepseek', **overrides}

    def finished(self, jobs, workspace, job_id):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            state = jobs.get(workspace, job_id)
            if state['status'] not in ('queued', 'running'):
                return state
            time.sleep(.01)
        self.fail('Synthetic background job did not finish within four seconds')

    def blocking_model(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def generate(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Synthetic test synchronization timed out')
            return ('合成判断仍需核实。[S1]' if '[S1]' in args[3] else '登记摘要，业务变化仍需核实。', 'Synthetic model')

        self.app.local_chat.side_effect = generate
        return entered, release

    def test_concurrent_repeat_requests_save_once_and_workspaces_are_isolated(self):
        jobs = self.manager(workers=2)
        entered, release = self.blocking_model()
        body = self.request()
        submitted = jobs.submit('real', body)
        self.assertTrue(entered.wait(1))
        same = jobs.submit('real', copy.deepcopy(body))
        self.assertEqual(submitted['id'], same['id'])
        with self.assertRaises(ValueError):
            jobs.submit('real', {**body, 'message': '不同工作要求'})
        demo = jobs.submit('demo', self.request('demo'))
        self.assertNotEqual(submitted['id'], demo['id'])
        with self.assertRaises(KeyError):
            jobs.get('demo', submitted['id'])
        release.set()
        for workspace, job in (('real', submitted), ('demo', demo)):
            done = self.finished(jobs, workspace, job['id'])
            self.assertEqual(done['status'], 'completed', done)
            self.assertEqual(len(self.stores[workspace].list('deliverables')), 1)
            self.assertEqual(done['result']['deliverable']['project_id'], self.projects[workspace]['id'])
            self.assertEqual(jobs.submit(workspace, self.request(workspace))['id'], job['id'])
        self.assertEqual(self.app.local_chat.call_count, 2)
        self.assertEqual({call.args[0] for call in self.app.sync_workspace.call_args_list}, {'real', 'demo'})

    def test_source_changed_during_generation_never_saves_and_cannot_retry_old_snapshot(self):
        jobs = self.manager(workers=1)
        entered, release = self.blocking_model()
        queued = jobs.submit('real', self.request())
        self.assertTrue(entered.wait(1))
        self.stores['real'].update('documents', self.docs['real']['id'], {'content': 'CHANGED SOURCE'})
        release.set()
        done = self.finished(jobs, 'real', queued['id'])
        self.assertEqual(done['status'], 'failed')
        self.assertIn('变更', done['error'])
        self.assertEqual(self.stores['real'].list('deliverables'), [])
        self.assertIn('SYNTHETIC SELECTED real', self.app.local_chat.call_args.args[3])
        self.assertNotIn('CHANGED SOURCE', self.app.local_chat.call_args.args[3])
        with self.assertRaises(ValueError):
            jobs.retry('real', queued['id'])

    def test_queued_changed_sources_are_rejected_before_any_model_call(self):
        jobs = self.manager(workers=1)
        entered, release = self.blocking_model()
        first = jobs.submit('real', self.request())
        self.assertTrue(entered.wait(1))
        doc = self.stores['real'].create('documents', {'title': 'Second', 'content': 'OLD SECOND SOURCE',
                                                      'project_id': self.projects['real']['id']})
        second = jobs.submit('real', self.request(request_id='queued-second', document_ids=[doc['id']]))
        self.stores['real'].update('documents', doc['id'], {'kind': 'memory'})
        release.set()
        self.assertEqual(self.finished(jobs, 'real', first['id'])['status'], 'completed')
        self.assertEqual(self.finished(jobs, 'real', second['id'])['status'], 'failed')
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(len(self.stores['real'].list('deliverables')), 1)

    def test_memory_foreign_sources_and_unselected_materials_never_enter_snapshot(self):
        store = self.stores['real']
        memory = store.create('documents', {'title': 'Memory', 'kind': 'memory', 'content': 'PRIVATE MEMORY SENTINEL'})
        other = store.create('projects', {'name': 'Other synthetic project'})
        foreign = store.create('documents', {'title': 'Foreign', 'content': 'FOREIGN SOURCE', 'project_id': other['id']})
        store.create('documents', {'title': 'Unselected', 'content': 'UNSELECTED SENTINEL', 'project_id': self.projects['real']['id']})
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager()
        for bad in (memory, foreign):
            with self.subTest(source=bad['title']), self.assertRaises(ValueError):
                jobs.submit('real', self.request(document_ids=[bad['id']]))
        queued = jobs.submit('real', self.request())
        _, snapshot, _ = jobs._row('real', queued['id'])
        snapshot_text = str(snapshot)
        for forbidden in ('PRIVATE MEMORY SENTINEL', 'FOREIGN SOURCE', 'UNSELECTED SENTINEL'):
            self.assertNotIn(forbidden, snapshot_text)
        frozen = FrozenStore(store, snapshot, queued['id'])
        with self.assertRaises(KeyError):
            frozen.get('documents', memory['id'])
        self.app.local_chat.assert_not_called()

    def test_restart_marks_unstarted_job_interrupted_then_retry_completes_once(self):
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            original = self.manager()
            queued = original.submit('real', self.request())
            original.close()
        restarted = self.manager()
        interrupted = restarted.get('real', queued['id'])
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertTrue(interrupted['retryable'])
        retried = restarted.retry('real', queued['id'])
        self.assertEqual(retried['id'], queued['id'])
        done = self.finished(restarted, 'real', queued['id'])
        self.assertEqual(done['status'], 'completed', done)
        self.assertEqual(len(self.stores['real'].list('deliverables')), 1)
        restarted.close()
        reopened = self.manager()
        self.assertEqual(reopened.submit('real', self.request())['status'], 'completed')
        self.assertEqual(self.app.local_chat.call_count, 1)

    def test_crash_after_save_before_job_checkpoint_recovers_without_duplicate_or_model(self):
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            original = self.manager()
            queued = original.submit('real', self.request())
            _, snapshot, _ = original._row('real', queued['id'])
            frozen = FrozenStore(self.stores['real'], snapshot, queued['id'])
            saved = frozen.create('deliverables', {'title': 'Synthetic draft', 'body': 'Saved draft [S1]',
                                                  'project_id': self.projects['real']['id'], 'workflow_key': 'brief',
                                                  'source_ids': [self.docs['real']['id']]})
            self.assertEqual(frozen.create('deliverables', {'title': 'Duplicate candidate'})['id'], saved['id'])
            original.close()
        recovered = self.manager()
        done = recovered.get('real', queued['id'])
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['result']['deliverable_id'], saved['id'])
        self.assertEqual(recovered.retry('real', queued['id'])['status'], 'completed')
        self.assertEqual(len(self.stores['real'].list('deliverables')), 1)
        self.app.local_chat.assert_not_called()

    def test_capacity_bound_and_request_schema_fail_before_capture_or_model(self):
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager(max_active=1)
        for changes in ({'request_id': 'bad identifier'}, {'workflow_key': []}, {'workflow_key': {}},
                        {'document_ids': 'not a list'}, {'message': ''}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                jobs.submit('real', self.request(**changes))
        queued = jobs.submit('real', self.request())
        self.assertEqual(jobs.submit('real', self.request())['id'], queued['id'])
        with self.assertRaises(ValueError):
            jobs.submit('demo', self.request('demo'))
        self.assertEqual(jobs.list('demo'), [])
        self.app.local_chat.assert_not_called()

    def test_queued_weekly_context_becoming_memory_linked_is_rejected_before_model(self):
        jobs = self.manager(workers=1)
        entered, release = self.blocking_model()
        first = jobs.submit('real', self.request())
        self.assertTrue(entered.wait(1))
        store = self.stores['real']
        memory = store.create('documents', {'title': 'Memory', 'kind': 'memory', 'content': 'PRIVATE MEMORY',
                                            'project_id': self.projects['real']['id']})
        note = store.create('notes', {'title': 'Registered context', 'body': 'CONTEXT NOW MADE PRIVATE',
                                      'project_id': self.projects['real']['id']})
        weekly = jobs.submit('real', self.request(request_id='weekly-synthetic', workflow_key='weekly', document_ids=[]))
        store.update('notes', note['id'], {'document_id': memory['id']})
        release.set()
        self.assertEqual(self.finished(jobs, 'real', first['id'])['status'], 'completed')
        failed = self.finished(jobs, 'real', weekly['id'])
        self.assertEqual(failed['status'], 'failed', failed)
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(len(store.list('deliverables')), 1)

    def test_provider_failure_does_not_disclose_provider_body_or_source_in_job_error(self):
        self.app.local_chat.side_effect = ValueError('PRIVATE PROVIDER DETAIL API_KEY_SENTINEL SOURCE_SENTINEL')
        jobs = self.manager()
        queued = jobs.submit('real', self.request())
        failed = self.finished(jobs, 'real', queued['id'])
        self.assertEqual(failed['status'], 'failed')
        for secret in ('PRIVATE PROVIDER', 'API_KEY_SENTINEL', 'SOURCE_SENTINEL'):
            self.assertNotIn(secret, failed['error'])
        self.assertEqual(self.stores['real'].list('deliverables'), [])

    def test_queued_configured_model_change_cannot_silently_switch_requested_provider(self):
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager()
        for mode in ('model', 'deepseek'):
            with self.subTest(mode=mode):
                self.app.ai = {'base_url': 'http://127.0.0.1:18080/v1', 'model': 'synthetic-model-A',
                               'api_key': 'DO_NOT_PERSIST_API_KEY'}
                queued = jobs.submit('real', self.request(mode=mode, request_id='provider-identity-' + mode))
                _, snapshot, _ = jobs._row('real', queued['id'])
                self.assertNotIn('DO_NOT_PERSIST_API_KEY', str(snapshot))
                with self.app.ai_lock:
                    self.app.ai.update(base_url='http://127.0.0.1:19090/v1', model='synthetic-model-B')
                jobs._execute('real', queued['id'])
                self.assertEqual(jobs.get('real', queued['id'])['status'], 'failed')
        self.app.local_chat.assert_not_called()
        self.assertEqual(self.stores['real'].list('deliverables'), [])

    def test_provider_cannot_change_between_generation_and_independent_review(self):
        self.app.ai = {'base_url': 'http://127.0.0.1:18080/v1', 'model': 'synthetic-model-A'}
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager()
        queued = jobs.submit('real', self.request(mode='model', quality_mode='thorough'))

        def first_call(*args, **kwargs):
            with self.app.ai_lock:
                self.app.ai.update(base_url='http://127.0.0.1:19090/v1', model='synthetic-model-B')
            return '合成判断仍需核实。[S1]', 'Synthetic model'

        self.app.local_chat.side_effect = first_call
        jobs._execute('real', queued['id'])
        self.assertEqual(jobs.get('real', queued['id'])['status'], 'failed')
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(self.stores['real'].list('deliverables'), [])

    def test_credential_rotation_does_not_change_model_identity_and_secrets_are_not_durable(self):
        self.app.ai = {'base_url': 'http://127.0.0.1:18080/v1', 'model': 'synthetic-model-A',
                       'api_key': 'OLD_DO_NOT_PERSIST_API_KEY'}
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager()
        queued = jobs.submit('real', self.request(mode='model'))
        with self.app.ai_lock:
            self.app.ai['api_key'] = 'NEW_DO_NOT_PERSIST_API_KEY'
        jobs._execute('real', queued['id'])
        done = jobs.get('real', queued['id'])
        self.assertEqual(done['status'], 'completed', done)
        self.assertEqual(self.app.local_chat.call_args.args[:2], ('http://127.0.0.1:18080/v1', 'synthetic-model-A'))
        for row in jobs.db.execute('SELECT payload,snapshot,state FROM jobs').fetchall():
            for encoded in row:
                self.assertNotIn('DO_NOT_PERSIST_API_KEY', encoded)

    def test_public_requests_reject_credentials_and_internal_override_fields_before_persistence(self):
        with patch('workos.jobs.ThreadPoolExecutor', PendingExecutor):
            jobs = self.manager()
        for field, value in (('api_key', 'API_KEY_REQUEST_SENTINEL'),
                             ('_provider_identity', 'a' * 64)):
            with self.subTest(field=field), self.assertRaises(ValueError) as rejected:
                jobs.submit('real', {**self.request(), field: value})
            self.assertNotIn(value, str(rejected.exception))
        self.assertEqual(jobs.db.execute('SELECT count(*) FROM jobs').fetchone()[0], 0)
        self.assertEqual(jobs.list('real'), [])
        self.app.local_chat.assert_not_called()

    def test_shutdown_interruption_blocks_old_worker_save_and_checkpoint_after_new_retry(self):
        old = self.manager(workers=1)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def late_old_model(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Synthetic shutdown test timed out')
            return 'OLD LATE DRAFT [S1]', 'Synthetic old model'

        self.app.local_chat.side_effect = late_old_model
        job = old.submit('real', self.request())
        self.assertTrue(entered.wait(1))
        old.begin_shutdown()
        interrupted = old.get('real', job['id'])
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertTrue(interrupted['retryable'])
        self.assertEqual(self.stores['real'].list('deliverables'), [])
        with self.assertRaises(ValueError):
            old.submit('real', self.request(request_id='after-shutdown'))
        # Another manager represents a newly started process while the old
        # provider call still awaits a response and old SQLite remains open.
        restarted = self.manager(workers=1)
        self.app.local_chat.side_effect = None
        self.app.local_chat.return_value = ('NEW RETRY DRAFT [S1]', 'Synthetic new model')
        restarted.retry('real', job['id'])
        before_old_returns = self.finished(restarted, 'real', job['id'])
        self.assertEqual(before_old_returns['status'], 'completed')
        self.assertIn('NEW RETRY DRAFT', before_old_returns['result']['body'])
        revision = before_old_returns['revision']
        saved_id = before_old_returns['result']['deliverable_id']
        release.set()
        old.close()  # Joins the released old worker before asserting durable state.
        after_old_returns = restarted.get('real', job['id'])
        self.assertEqual(after_old_returns['revision'], revision)
        self.assertEqual(after_old_returns['status'], 'completed')
        self.assertEqual(after_old_returns['result']['deliverable_id'], saved_id)
        saved = self.stores['real'].list('deliverables')
        self.assertEqual(len(saved), 1)
        self.assertIn('NEW RETRY DRAFT', saved[0]['body'])
        self.assertNotIn('OLD LATE DRAFT', str(saved))
        self.assertEqual(self.app.sync_workspace.call_count, 1)


if __name__ == '__main__':
    unittest.main()
