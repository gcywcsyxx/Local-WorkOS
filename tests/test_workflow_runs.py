"""Synthetic workflow retries, provider failures and real loopback HTTP; no external calls."""
from http.server import ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from workos.server import Application, Handler
from workos.workflow_runs import WorkflowRuns, WorkflowBusy, exclusive_model_run


class WorkflowRunCacheTests(unittest.TestCase):
    def test_success_retry_and_workspace_partition(self):
        cache = WorkflowRuns()
        execute = Mock(return_value={'deliverable_id':'synthetic', 'coverage':[]})
        body = {'request_id':'synthetic-request', 'message':'Draft'}
        first = cache.run('personal', body, execute)
        first['coverage'].append('Caller mutation')
        self.assertEqual(cache.run('personal', dict(reversed(list(body.items()))), execute)['coverage'], [])
        self.assertEqual(execute.call_count, 1)
        cache.run('demo', body, execute)
        self.assertEqual(execute.call_count, 2)
        with self.assertRaises(ValueError):
            cache.run('personal', {**body, 'message':'Different request'}, execute)
        self.assertEqual(execute.call_count, 2)

    def test_failed_request_can_retry_and_invalid_ids_never_execute(self):
        cache = WorkflowRuns()
        execute = Mock(side_effect=[ValueError('Synthetic provider failure'), {'deliverable_id':'retried'}])
        body = {'request_id':'synthetic-retry'}
        with self.assertRaises(ValueError):
            cache.run('personal', body, execute)
        self.assertEqual(cache.run('personal', body, execute)['deliverable_id'], 'retried')
        for request_id in ('', 'short', 'x'*101, 'invalid space', 123):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                cache.run('personal', {'request_id':request_id}, execute)
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(cache.run('personal', {}, lambda:'legacy'), 'legacy')

    def test_concurrent_same_id_rejects_without_holding_other_workspaces(self):
        cache = WorkflowRuns()
        started, release = threading.Event(), threading.Event()
        results = []
        def execute():
            started.set()
            if not release.wait(3):
                raise AssertionError('Synthetic worker did not release')
            return {'deliverable_id':'single'}
        body = {'request_id':'synthetic-concurrent', 'message':'Draft'}
        thread = threading.Thread(target=lambda:results.append(cache.run('personal', body, execute)))
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaises(WorkflowBusy):
                cache.run('personal', body, lambda:self.fail('Duplicate executed'))
            with self.assertRaises(ValueError):
                cache.run('personal', {**body, 'message':'Changed'}, lambda:self.fail('Changed request executed'))
            self.assertEqual(cache.run('demo', body, lambda:'independent'), 'independent')
        finally:
            release.set()
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [{'deliverable_id':'single'}])
        self.assertEqual(cache.run('personal', body, lambda:self.fail('Retry executed')), results[0])

    def test_completed_cache_is_bounded_and_clears_with_new_instance(self):
        cache = WorkflowRuns()
        for index in range(35):
            cache.run('personal', {'request_id':f'synthetic-{index}'}, lambda:{'id':'done'})
        self.assertEqual(len(cache._entries), 32)
        self.assertNotIn(('personal', 'synthetic-0'), cache._entries)
        fresh = WorkflowRuns()
        self.assertEqual(fresh.run('personal', {'request_id':'synthetic-34'}, lambda:'new process'), 'new process')

    def test_dsh_busy_denies_before_process_and_failure_releases_lock(self):
        lock = threading.Lock()
        lock.acquire()
        app = SimpleNamespace(dsh_available=True, dsh_lock=lock)
        try:
            with patch('workos.server.subprocess.Popen') as process, self.assertRaises(ValueError):
                Application.dsh_answer(app, 'Synthetic prompt', 'gpt-6-luna')
            process.assert_not_called()
        finally:
            lock.release()
        with self.assertRaises(RuntimeError), exclusive_model_run(lock):
            raise RuntimeError('Synthetic failure')
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()


class WorkflowEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        with patch.dict(os.environ, {'WORKOS_SYNC_ROOT':'', 'WORKOS_PUBLIC_ORIGIN':'', 'WORKOS_PUBLIC_AUTH_MODE':'access'}), \
             patch('workos.server.find_root', return_value=None):
            self.app = Application(Path(self.temporary.name) / 'synthetic-data', port=0)
        self.addCleanup(self.app.close)
        self.app.local_chat = Mock(return_value=('Synthetic grounded result [S1]', 'Synthetic model'))
        self.store = self.app.stores['personal']
        self.doc = self.store.create('documents', {'title':'Synthetic source', 'content':'Synthetic evidence'})
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.app = self.app
        self.app.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval':0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())

    def request(self, body, workspace='personal'):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=4)
        try:
            connection.request('POST', '/api/workflows/run', json.dumps(body).encode(), {
                'Content-Type':'application/json', 'X-Workspace':workspace, 'X-CSRF-Token':self.app.csrf})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def body(self, **changes):
        return {'workflow_key':'brief', 'message':'Summarize the selected source briefly',
                'document_ids':[self.doc['id']], 'mode':'deepseek', 'request_id':'synthetic-http-request', **changes}

    def test_successful_http_retry_returns_same_saved_draft(self):
        status, first = self.request(self.body())
        self.assertEqual(status, 201, first)
        status, second = self.request(self.body())
        self.assertEqual(status, 201, second)
        self.assertEqual(first['deliverable_id'], second['deliverable_id'])
        self.assertEqual(len(self.store.list('deliverables')), 1)
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(self.app.local_chat.call_args.kwargs['timeout'], 95)
        self.assertEqual(self.request(self.body(message='Changed message'))[0], 400)
        self.assertEqual(self.app.local_chat.call_count, 1)

    def test_provider_and_citation_errors_do_not_save_and_id_can_retry(self):
        self.app.local_chat.side_effect = ValueError('Synthetic provider failure')
        status, result = self.request(self.body())
        self.assertEqual(status, 400)
        self.assertIn('Synthetic provider failure', result['error'])
        self.assertEqual(self.store.list('deliverables'), [])
        self.app.local_chat.side_effect = None
        self.app.local_chat.return_value = ('Invalid citation [S99]', 'Synthetic model')
        self.assertEqual(self.request(self.body())[0], 400)
        self.assertEqual(self.store.list('deliverables'), [])
        self.app.local_chat.return_value = ('Valid result [S1]', 'Synthetic model')
        self.assertEqual(self.request(self.body())[0], 201)
        self.assertEqual(len(self.store.list('deliverables')), 1)

    def test_local_mode_memory_and_invalid_id_reject_before_provider(self):
        memory = self.store.create('documents', {'title':'Synthetic memory', 'kind':'memory', 'content':'PRIVATE SENTINEL'})
        for body in (self.body(mode='local'), self.body(document_ids=[memory['id']]),
                     self.body(request_id='bad'), self.body(document_ids=[])):
            with self.subTest(body=body):
                self.assertEqual(self.request(body)[0], 400)
        self.app.local_chat.assert_not_called()
        self.assertEqual(self.store.list('deliverables'), [])

    def test_concurrent_http_repeat_returns_busy_then_same_result(self):
        started, release = threading.Event(), threading.Event()
        def answer(*args, **kwargs):
            started.set()
            if not release.wait(3):
                raise AssertionError('Synthetic provider did not release')
            return 'Valid result [S1]', 'Synthetic model'
        self.app.local_chat.side_effect = answer
        first = []
        thread = threading.Thread(target=lambda:first.append(self.request(self.body())))
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            status, result = self.request(self.body())
            self.assertEqual(status, 409, result)
            self.assertEqual(result['code'], 'workflow_busy')
        finally:
            release.set()
            thread.join(timeout=4)
        self.assertFalse(thread.is_alive())
        self.assertEqual(first[0][0], 201, first)
        retry = self.request(self.body())
        self.assertEqual(retry[1]['deliverable_id'], first[0][1]['deliverable_id'])
        self.assertEqual(self.app.local_chat.call_count, 1)
        self.assertEqual(len(self.store.list('deliverables')), 1)


if __name__ == '__main__':
    unittest.main()
