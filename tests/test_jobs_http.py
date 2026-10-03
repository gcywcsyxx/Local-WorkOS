"""Real loopback integration for durable jobs; synthetic data, no external models."""
from contextlib import ExitStack
import http.client
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

from workos.server import Application, Handler, LocalServer


class AsyncJobsHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(patch('workos.server.find_root', return_value=None))
        # Do not discover, read or write the user's real OneDrive mirror.
        self.mirror = Mock()
        self.mirror.status.return_value = {'enabled': False, 'reason': 'Synthetic HTTP test'}
        self.mirror.restore_if_empty.return_value = None
        self.mirror.sync.return_value = {'enabled': False}
        self.stack.enter_context(patch('workos.server.OneDriveMirror', return_value=self.mirror))
        self.stack.enter_context(patch.dict(os.environ, {'WORKOS_PUBLIC_ORIGIN': '',
            'WORKOS_PUBLIC_AUTH_MODE': 'access', 'WORKOS_ACCESS_TEAM': '', 'WORKOS_ACCESS_AUD': ''}))
        self.data_dir = Path(self.temp.name) / 'data'
        self.app = Application(self.data_dir, port=0)
        self.httpd = LocalServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.app.port = self.httpd.server_address[1]
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever,
            kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.releases = []
        self.projects, self.docs = {}, {}
        for workspace, store in self.app.stores.items():
            self.projects[workspace] = store.create('projects', {'name': 'Synthetic HTTP ' + workspace})
            self.docs[workspace] = store.create('documents', {'title': 'Synthetic memo v1',
                'content': 'Selected synthetic evidence ' + workspace,
                'project_id': self.projects[workspace]['id']})
        self.model = Mock(side_effect=self.normal_model)
        self.app.local_chat = self.model
        self.app.dsh_answer = Mock(side_effect=AssertionError('No DSH call permitted in HTTP tests'))

    def tearDown(self):
        for event in self.releases:
            event.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.app.close()  # Workers are released before closing their SQLite stores.
        self.stack.close()
        self.temp.cleanup()

    def normal_model(self, *args, **kwargs):
        self.app.completion_meta.finish_reason = 'stop'
        return '合成判断仍需核实。[S1]', 'Synthetic model'

    def request(self, method, path, body=None, workspace='personal', csrf=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=3)
        actual = {'X-Workspace': workspace}
        if csrf:
            actual['X-CSRF-Token'] = self.app.csrf
        if body is not None:
            body = json.dumps(body, ensure_ascii=False).encode()
            actual['Content-Type'] = 'application/json'
        actual.update(headers or {})
        try:
            connection.request(method, path, body=body, headers=actual)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw)
        finally:
            connection.close()

    def body(self, workspace='personal', **overrides):
        return {'request_id': 'synthetic-http-request', 'workflow_key': 'brief',
                'message': '分析这一份材料', 'project_id': self.projects[workspace]['id'],
                'document_ids': [self.docs[workspace]['id']], 'mode': 'deepseek', **overrides}

    def submitted(self, body=None, workspace='personal'):
        code, response = self.request('POST', '/api/workflows/jobs', body or self.body(workspace), workspace)
        self.assertEqual(code, 202, response)
        return response['job']

    def finished(self, job_id, workspace='personal'):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status, response = self.request('GET', '/api/workflows/jobs/' + job_id, workspace=workspace, csrf=False)
            self.assertEqual(status, 200, response)
            if response['job']['status'] not in ('queued', 'running'):
                return response['job']
            time.sleep(.01)
        self.fail('Synthetic HTTP background job did not finish within four seconds')

    def test_post_and_retry_require_csrf_before_creating_jobs(self):
        for route in ('/api/workflows/jobs', '/api/workflows/jobs/' + 'a' * 32 + '/retry'):
            for token in (None, 'wrong-token'):
                with self.subTest(route=route, token=token):
                    # Avoid unread-body close/reset races: security precedes JSON parsing.
                    code, response = self.request('POST', route, csrf=False,
                        headers={} if token is None else {'X-CSRF-Token': token})
                    self.assertEqual(code, 403, response)
        self.assertIsNone(self.app._jobs)
        self.model.assert_not_called()
        self.assertEqual(self.request('GET', '/api/workflows/jobs', csrf=False), (200, {'jobs': []}))

    def test_accepts_while_model_blocked_deduplicates_and_isolates_workspaces(self):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('Synthetic HTTP model synchronization timed out')
            return self.normal_model(*args, **kwargs)

        self.model.side_effect = blocked
        start = time.monotonic()
        personal = self.submitted()
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertFalse(release.is_set(), 'HTTP submit must return before model completion')
        self.assertTrue(entered.wait(1))
        duplicate = self.submitted()
        self.assertEqual(duplicate['id'], personal['id'])
        demo = self.submitted(workspace='demo')
        self.assertNotEqual(demo['id'], personal['id'])
        self.assertEqual(self.request('GET', '/api/workflows/jobs/' + personal['id'], workspace='demo')[0], 404)
        self.assertEqual(self.request('POST', '/api/workflows/jobs/' + personal['id'] + '/retry', {}, workspace='demo')[0], 404)
        for workspace, own, foreign in (('personal', personal, demo), ('demo', demo, personal)):
            code, response = self.request('GET', '/api/workflows/jobs', workspace=workspace, csrf=False)
            self.assertEqual(code, 200)
            ids = {row['id'] for row in response['jobs']}
            self.assertIn(own['id'], ids)
            self.assertNotIn(foreign['id'], ids)
        self.assertEqual(self.request('POST', '/api/workflows/jobs', {**self.body(), 'message': '不同工作要求'})[0], 400)
        release.set()
        for workspace, job in (('personal', personal), ('demo', demo)):
            done = self.finished(job['id'], workspace)
            self.assertEqual(done['status'], 'completed', done.get('error'))
            saved = self.app.stores[workspace].get('deliverables', done['result']['deliverable_id'])
            self.assertEqual(saved['source_ids'], [self.docs[workspace]['id']])
            self.assertEqual(saved['quality_report'], done['result']['quality_report'])
            self.assertFalse(saved['quality_report']['facts_verified'])
            self.assertEqual(saved['quality_report']['checks'][0]['status'], 'pass')
            self.assertEqual(sum(row.get('generation_id') == job['id']
                for row in self.app.stores[workspace].list('deliverables')), 1)
        self.assertEqual(self.model.call_count, 2)

    def test_completed_job_quality_and_idempotency_survive_application_restart(self):
        original = self.submitted()
        done = self.finished(original['id'])
        self.assertEqual(done['status'], 'completed')
        saved_id, saved_quality = done['result']['deliverable_id'], done['result']['quality_report']
        self.app.close()
        self.app = Application(self.data_dir, self.httpd.server_address[1])
        self.app.local_chat = Mock(side_effect=AssertionError('Recovered job must not regenerate'))
        self.httpd.app = self.app
        recovered = self.finished(original['id'])
        self.assertEqual(recovered['result']['deliverable_id'], saved_id)
        self.assertEqual(recovered['result']['quality_report'], saved_quality)
        self.assertEqual(self.submitted()['id'], original['id'])
        self.app.local_chat.assert_not_called()
        self.assertEqual(sum(row.get('generation_id') == original['id']
            for row in self.app.stores['personal'].list('deliverables')), 1)

    def test_failed_job_retry_is_scoped_and_saves_once(self):
        self.model.side_effect = ValueError('PRIVATE_PROVIDER_RESPONSE_SENTINEL')
        original = self.submitted()
        failed = self.finished(original['id'])
        self.assertEqual(failed['status'], 'failed')
        self.assertTrue(failed['retryable'])
        self.assertNotIn('PRIVATE_PROVIDER_RESPONSE_SENTINEL', failed['error'])
        self.assertEqual(self.submitted()['status'], 'failed')
        self.model.side_effect = self.normal_model
        code, response = self.request('POST', '/api/workflows/jobs/' + original['id'] + '/retry', {})
        self.assertEqual(code, 202)
        self.assertEqual(response['job']['id'], original['id'])
        done = self.finished(original['id'])
        self.assertEqual(done['status'], 'completed', done.get('error'))
        self.assertEqual(self.model.call_count, 2)
        self.assertEqual(sum(row.get('generation_id') == original['id']
            for row in self.app.stores['personal'].list('deliverables')), 1)

    def test_real_chat_provider_completion_gate_never_saves_truncated_output(self):
        self.app.local_chat = Application.local_chat.__get__(self.app, Application)
        for reason in ('length', 'content_filter', 'tool_calls', 'max_tokens', 'stop', None):
            with self.subTest(finish_reason=reason), patch('workos.server.urllib.request.urlopen') as opened:
                opened.return_value.__enter__.return_value.read.return_value = json.dumps({
                    'choices': [{'finish_reason': reason, 'message': {'content': '合成输出 [S1]'}}]}).encode()
                job = self.submitted(self.body(request_id='provider-' + str(reason)))
                done = self.finished(job['id'])
                saved = [row for row in self.app.stores['personal'].list('deliverables')
                         if row.get('generation_id') == job['id']]
                if reason in ('stop', None):
                    self.assertEqual(done['status'], 'completed', done.get('error'))
                    self.assertEqual(len(saved), 1)
                    self.assertFalse(saved[0]['quality_report']['facts_verified'])
                    expected = 'pass' if reason == 'stop' else 'not_checked'
                    self.assertEqual(saved[0]['quality_report']['checks'][0]['status'], expected)
                else:
                    self.assertEqual(done['status'], 'failed')
                    self.assertEqual(saved, [])
                    self.assertNotIn('合成输出', done['error'])
                self.assertEqual(opened.call_count, 1)


if __name__ == '__main__':
    unittest.main()
