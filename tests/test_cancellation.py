"""Cancellation ordering and late-result regressions with synthetic records."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from workos.cancellation import (CancellationToken, CancellationStore, OperationRegistry,
    CancelledError, OperationConflict, bind_token, check_cancelled, record_step)
from workos.jobs import FrozenStore
from workos.store import Store
from tests import test_jobs as jobs_fixture


class CancellationRegistryTests(unittest.TestCase):
    def test_stop_before_arrival_is_scoped_and_never_executes_request(self):
        registry = OperationRegistry()
        cancelled = registry.cancel('personal', 'synthetic-id')
        self.assertEqual(cancelled['status'], 'cancelled')
        execute = Mock(return_value='done')
        with self.assertRaises(CancelledError):
            registry.run('personal', 'synthetic-id', execute)
        execute.assert_not_called()
        self.assertEqual(registry.run('demo', 'synthetic-id', execute), 'done')
        self.assertEqual(registry.cancel('demo', 'synthetic-id')['status'], 'completed')

    def test_cancelled_response_preserves_committed_step_and_discards_late_answer(self):
        registry, entered, release = OperationRegistry(), threading.Event(), threading.Event()
        outcomes = []
        def execute(token):
            record_step({'action': 'create_task', 'result': {'id': 'synthetic-record'}})
            entered.set()
            self.assertTrue(release.wait(3))
            return 'LATE ANSWER'
        def worker():
            try: outcomes.append(registry.run('personal', 'synthetic-id', execute))
            except Exception as exc: outcomes.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            response = registry.cancel('personal', 'synthetic-id')
            self.assertEqual(response['steps'][0]['result']['id'], 'synthetic-record')
        finally:
            release.set();thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(outcomes[0], CancelledError)
        self.assertEqual(outcomes[0].steps, response['steps'])

    def test_completed_request_id_is_not_executed_twice_and_invalid_ids_rejected(self):
        registry, execute = OperationRegistry(), Mock(return_value='result')
        registry.run('personal', 'synthetic-id', execute)
        with self.assertRaises(OperationConflict):registry.run('personal', 'synthetic-id', execute)
        self.assertEqual(execute.call_count, 1)
        for request_id in ('../synthetic-id', [], '', 'a'*101):
            with self.assertRaises(ValueError):registry.cancel('personal', request_id)

    def test_tombstones_are_bounded_and_shutdown_blocks_new_work(self):
        registry = OperationRegistry(max_finished=4)
        for index in range(40):registry.cancel('personal', 'synthetic-'+str(index))
        self.assertLessEqual(len(registry.entries), 5)
        registry.shutdown()
        with self.assertRaises(ValueError):registry.run('personal', 'new-request', Mock())

    def test_precreated_pending_ids_cannot_bypass_atomic_running_capacity(self):
        registry = OperationRegistry(max_active=2)
        for index in range(3):registry.token('personal','synthetic-pending-'+str(index))
        entered = [threading.Event(),threading.Event()]
        release = threading.Event()
        outcomes = []
        def execute(index):
            def provider(token):
                entered[index].set()
                if not release.wait(3):raise RuntimeError('Synthetic capacity barrier timeout')
                return 'complete'
            outcomes.append(registry.run('personal','synthetic-pending-'+str(index),provider))
        threads = [threading.Thread(target=execute,args=(index,)) for index in range(2)]
        for thread in threads:thread.start()
        try:
            for event in entered:self.assertTrue(event.wait(1))
            provider = Mock(return_value='unexpected')
            with self.assertRaisesRegex(ValueError,'已满'):
                registry.run('personal','synthetic-pending-2',provider)
            provider.assert_not_called()
            self.assertEqual(registry.entries[('personal','synthetic-pending-2')].status,'pending')
            # Stop-before-arrival remains available when actual provider slots are full.
            self.assertEqual(registry.cancel('personal','synthetic-stop-when-full')['status'],'cancelled')
        finally:
            release.set()
            for thread in threads:thread.join(3)
        self.assertEqual(len(outcomes),2)
        self.assertEqual(registry.run('personal','synthetic-pending-2',Mock(return_value='after capacity')),'after capacity')

    def test_store_guard_prevents_all_late_mutations_including_organization(self):
        with TemporaryDirectory() as temp:
            store = Store(Path(temp)/'synthetic.sqlite3')
            try:
                token = CancellationToken('synthetic-id')
                guarded = CancellationStore(store, token)
                project = guarded.create('projects', {'name':'Synthetic'})
                task = guarded.create('tasks', {'title':'Committed','project_id':project['id']})
                token.cancel()
                for operation in (lambda:guarded.create('tasks',{'title':'Late'}),
                    lambda:guarded.update('tasks',task['id'],{'title':'Late'}),
                    lambda:guarded.delete('tasks',task['id']),
                    lambda:guarded.organize_project(project['id'])):
                    with self.assertRaises(CancelledError):operation()
                self.assertEqual(store.get('tasks',task['id'])['title'], 'Committed')
                self.assertEqual(len(store.list('tasks')), 1)
            finally:store.close()

    def test_cancellation_waits_for_local_commit_and_thread_binding_does_not_leak(self):
        token = CancellationToken('synthetic-id')
        entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
        def commit():
            with token.guard():
                entered.set();self.assertTrue(release.wait(3))
        def cancel():token.cancel();stopped.set()
        thread = threading.Thread(target=commit);thread.start()
        self.assertTrue(entered.wait(1))
        cancel_thread = threading.Thread(target=cancel);cancel_thread.start()
        try:self.assertFalse(stopped.wait(.05))
        finally:release.set();thread.join(3);cancel_thread.join(3)
        self.assertTrue(stopped.is_set())
        with self.assertRaises(CancelledError):
            with bind_token(token):pass
        check_cancelled()  # The previous failing binding has been removed.


class WorkflowJobCancellationTests(unittest.TestCase):
    setUp = jobs_fixture.WorkflowJobTests.setUp
    tearDown = jobs_fixture.WorkflowJobTests.tearDown
    manager = jobs_fixture.WorkflowJobTests.manager
    request = jobs_fixture.WorkflowJobTests.request
    finished = jobs_fixture.WorkflowJobTests.finished
    blocking_model = jobs_fixture.WorkflowJobTests.blocking_model

    def test_running_cancel_is_terminal_and_late_provider_cannot_review_or_save(self):
        jobs = self.manager(workers=1)
        entered, release = self.blocking_model()
        job = jobs.submit('real', self.request(quality_mode='thorough'))
        self.assertTrue(entered.wait(1))
        stopped = jobs.cancel('real', job['id'])
        self.assertEqual(stopped['status'], 'cancelled')
        revision = stopped['revision']
        self.assertEqual(jobs.retry('real', job['id'])['status'], 'cancelled')
        self.assertEqual(jobs.submit('real', self.request(quality_mode='thorough'))['id'], job['id'])
        release.set();jobs.executor.shutdown(wait=True)
        state = jobs.get('real', job['id'])
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(state['revision'], revision)
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(self.stores['real'].list('deliverables'), [])
        self.app.sync_workspace.assert_not_called()

    def test_queued_cancel_and_pre_ack_tombstone_skip_provider_and_survive_restart(self):
        with patch('workos.jobs.ThreadPoolExecutor', jobs_fixture.PendingExecutor):jobs = self.manager()
        job = jobs.submit('real', self.request())
        with self.assertRaises(KeyError):jobs.cancel('demo', job['id'])
        self.assertEqual(jobs.cancel('real', job['id'])['status'], 'cancelled')
        jobs._execute('real', job['id'])
        self.app.local_chat.assert_not_called()
        jobs.cancel_request('real', 'synthetic-before-ack')
        with self.assertRaises(CancelledError):
            jobs.submit('real', self.request(request_id='synthetic-before-ack'))
        self.assertEqual(len(jobs.list('real')), 1)
        # Same random request ID remains valid in a different workspace.
        demo = jobs.submit('demo', self.request('demo', request_id='synthetic-before-ack'))
        self.assertEqual(demo['status'], 'queued')
        jobs.close()
        reopened = self.manager()
        self.assertEqual(reopened.get('real', job['id'])['status'], 'cancelled')
        self.assertEqual(reopened.retry('real', job['id'])['status'], 'cancelled')
        self.assertEqual(self.stores['real'].list('deliverables'), [])

    def test_committed_deliverable_wins_stop_race_without_duplicate_save(self):
        jobs = self.manager(workers=1)
        committed, release = threading.Event(), threading.Event()
        self.releases.append(release)
        original = FrozenStore.create
        def create(frozen, collection, data):
            record = original(frozen, collection, data)
            committed.set()
            if not release.wait(3):raise RuntimeError('Synthetic save barrier timeout')
            return record
        with patch.object(FrozenStore, 'create', create):
            job = jobs.submit('real', self.request())
            self.assertTrue(committed.wait(1))
            stopped = jobs.cancel('real', job['id'])
            self.assertEqual(stopped['status'], 'completed')
            self.assertTrue(stopped['result']['deliverable_id'])
            revision = stopped['revision']
            release.set();jobs.executor.shutdown(wait=True)
        self.assertEqual(jobs.get('real', job['id'])['revision'], revision)
        self.assertEqual(len(self.stores['real'].list('deliverables')), 1)

    def test_cancel_during_review_prevents_repair_provider_and_save(self):
        jobs = self.manager(workers=1)
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        def model(*args, **kwargs):
            calls.append(args)
            if len(calls) == 1:return '合成判断仍需核实。[S1]', 'Synthetic model'
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic reviewer barrier timeout')
            return '{"verdict":"needs_revision","findings":[]}', 'Synthetic model'
        self.app.local_chat.side_effect = model
        job = jobs.submit('real', self.request(quality_mode='thorough'))
        self.assertTrue(entered.wait(1))
        jobs.cancel('real', job['id'])
        release.set();jobs.executor.shutdown(wait=True)
        self.assertEqual(jobs.get('real', job['id'])['status'], 'cancelled')
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.stores['real'].list('deliverables'), [])

    def test_old_queued_token_stays_linked_under_tombstone_pruning(self):
        with patch('workos.jobs.ThreadPoolExecutor', jobs_fixture.PendingExecutor):jobs = self.manager()
        jobs.cancellations.max_finished = 2
        body = self.request()
        job = jobs.submit('real',body)
        token = jobs.tokens[job['id']]
        token.touched -= 1000
        for index in range(20):jobs.cancellations.cancel('real','synthetic-tombstone-'+str(index))
        self.assertIs(jobs.cancellations.entries[('real',body['request_id'])],token)
        self.assertTrue(token.pinned)
        jobs.cancellations.cancel('real',body['request_id'])
        jobs._execute('real',job['id'])
        self.assertEqual(jobs.get('real',job['id'])['status'],'cancelled')
        self.app.local_chat.assert_not_called()
        self.assertFalse(token.pinned)


if __name__ == '__main__':unittest.main()
