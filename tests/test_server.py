"""Real loopback HTTP tests, ephemeral ports, no browser or external model calls."""
import base64
import html
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from workos.exports import html_report, markdown
from workos.server import Application, Handler


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Prevent discovery of the real workstation memory root altogether.
        with patch('workos.server.find_root', return_value=None):
            self.app = Application(Path(self.tmp.name) / 'data', port=0)
        self.addCleanup(self.close_stores)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.app.port = self.httpd.server_address[1]
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def close_stores(self):
        for store in self.app.stores.values():
            store.close()

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive(), 'HTTP test thread failed to stop')

    def request(self, method, path, body=None, workspace='personal', headers=None, csrf=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=3)
        actual = {'X-Workspace': workspace}
        if csrf:
            actual['X-CSRF-Token'] = self.app.csrf
        if body is not None:
            actual['Content-Type'] = 'application/json'
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        actual.update(headers or {})
        try:
            connection.request(method, path, body=body, headers=actual)
            response = connection.getresponse()
            raw = response.read()
            mime = response.getheader('Content-Type', '')
            parsed = json.loads(raw) if mime.startswith('application/json') else raw.decode('utf-8')
            return response.status, parsed
        finally:
            connection.close()

    def create(self, collection, body, workspace='personal'):
        status, result = self.request('POST', '/api/' + collection, body, workspace=workspace)
        self.assertEqual(status, 201, result)
        return result

    def test_bootstrap_and_crud(self):
        status, boot = self.request('GET', '/api/bootstrap', csrf=False)
        self.assertEqual(status, 200)
        self.assertEqual(boot['csrf'], self.app.csrf)
        self.assertEqual(boot['workspace'], 'personal')
        self.assertFalse(boot['memory_root_available'])
        project = self.create('projects', {'name': 'HTTP合成项目'})
        task = self.create('tasks', {'title': 'HTTP任务', 'project_id': project['id']})
        status, result = self.request('PATCH', '/api/tasks/' + task['id'], {'status': '完成'})
        self.assertEqual(status, 200, result)
        status, state = self.request('GET', '/api/state')
        self.assertEqual(state['tasks'][0]['status'], '完成')
        self.assertEqual(self.request('DELETE', '/api/projects/' + project['id'])[0], 400)
        self.assertEqual(self.request('DELETE', '/api/tasks/' + task['id'])[0], 200)
        self.assertEqual(self.request('DELETE', '/api/projects/' + project['id'])[0], 200)

    def test_csrf_required_for_each_mutation(self):
        project = self.create('projects', {'name': '保留'})
        for method, path, body in [('POST', '/api/projects', {'name': '拒绝'}),
                                   ('PATCH', '/api/projects/' + project['id'], {'name': '拒绝'}),
                                   ('DELETE', '/api/projects/' + project['id'], None),
                                   ('POST', '/api/shutdown', {})]:
            for token in (None, 'wrong-token'):
                with self.subTest(method=method, token=token):
                    # Security validation precedes parsing; omit an unread body to avoid Windows TCP close/reset races.
                    status, result = self.request(method, path, None, csrf=False,
                                                  headers={} if token is None else {'X-CSRF-Token': token})
                    self.assertEqual(status, 403)
                    self.assertIn('error', result)
        self.assertEqual(self.request('GET', '/api/state')[1]['projects'][0]['name'], '保留')

    def test_host_and_origin_validation(self):
        for headers in ({'Host': 'attacker.invalid'}, {'Host': '127.0.0.1:1'},
                        {'Origin': 'https://attacker.invalid'}, {'Origin': 'null'}):
            for method, body in [('GET', None), ('POST', {'name': '拒绝'})]:
                with self.subTest(headers=headers, method=method):
                    path = '/api/state' if method == 'GET' else '/api/projects'
                    self.assertEqual(self.request(method, path, None, headers=headers)[0], 403)
        good = {'Host': 'localhost:' + str(self.app.port), 'Origin': 'http://localhost:' + str(self.app.port)}
        self.assertEqual(self.request('GET', '/api/state', headers=good)[0], 200)

    def test_workspace_isolation_and_restore(self):
        project = self.create('projects', {'name': '个人合成'})
        personal = self.request('GET', '/api/backup')[1]
        demo_before = self.request('GET', '/api/backup', workspace='demo')[1]['data']
        self.assertNotIn(project['id'], {p['id'] for p in demo_before['projects']})
        self.assertEqual(self.request('POST', '/api/tasks', {'title': '跨区', 'project_id': project['id']}, workspace='demo')[0], 400)
        self.assertEqual(self.request('POST', '/api/restore', {'backup': personal, 'confirm': True}, workspace='demo')[0], 400)
        self.request('PATCH', '/api/projects/' + project['id'], {'name': '修改'})
        self.assertEqual(self.request('POST', '/api/restore', {'backup': personal, 'confirm': False})[0], 400)
        self.assertEqual(self.request('POST', '/api/restore', {'backup': personal, 'confirm': True})[0], 200)
        self.assertEqual(self.request('GET', '/api/backup')[1]['data'], personal['data'])
        self.assertEqual(self.request('GET', '/api/backup', workspace='demo')[1]['data'], demo_before)
        before = self.request('GET', '/api/backup')[1]['data']
        self.assertEqual(self.request('POST', '/api/restore', {'backup': {}, 'confirm': True})[0], 400)
        self.assertEqual(self.request('GET', '/api/backup')[1]['data'], before)
        self.assertEqual(self.request('GET', '/api/state', workspace='invalid')[0], 400)

    def test_txt_upload_local_ask_citations_and_selection(self):
        text = '合成星河公司收入为100百万元。收入增长来自合成客户订单。'
        encoded = base64.b64encode(text.encode('utf-8')).decode('ascii')
        status, doc = self.request('POST', '/api/upload', {'name': 'synthetic.txt', 'base64': encoded})
        self.assertEqual(status, 201, doc)
        self.assertEqual(doc['content'], text)
        self.assertTrue(doc['chunks'])
        detail = self.request('GET', '/api/documents/' + doc['id'])[1]
        self.assertEqual(detail['content'], text)
        body = {'question': '星河公司收入', 'document_ids': [doc['id']], 'mode': 'local', 'allow_external': False}
        status, result = self.request('POST', '/api/ask', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['mode'], 'local')
        self.assertTrue(result['citations'], result)
        for citation in result['citations']:
            self.assertEqual(citation['document_id'], doc['id'])
            self.assertIn(citation['quote'], text)
            self.assertIn(citation['id'], {doc['id'] + ':' + chunk['id'] for chunk in doc['chunks']})
            matching = [chunk for chunk in doc['chunks'] if chunk['ordinal'] == citation['ordinal']]
            self.assertTrue(matching)
            self.assertIn(citation['quote'], matching[0]['text'])
        self.assertEqual(self.request('POST', '/api/ask', {**body, 'document_ids': []})[0], 400)
        self.assertEqual(self.request('POST', '/api/ask', body, workspace='demo')[0], 400)
        self.assertEqual(self.request('POST', '/api/ask', {**body, 'mode': 'model'})[0], 400)
        self.assertEqual(self.request('POST', '/api/upload', {'name': 'bad.txt', 'base64': '!!!'})[0], 400)

    def test_selected_memory_file_upload_is_redacted_local_and_deduplicated(self):
        raw = ('个人记忆内容\nAPI_KEY=sk-' + '0123456789abcdef0123456789abcdef').encode('utf-8')
        encoded = base64.b64encode(raw).decode('ascii')
        body = {'name': 'profile.md', 'base64': encoded, 'kind': 'memory', 'source_ref': 'selected/knowledge/profile.md'}
        status, doc = self.request('POST', '/api/upload', body)
        self.assertEqual(status, 201, doc)
        self.assertEqual(doc['kind'], 'memory')
        self.assertTrue(doc['private'])
        self.assertEqual(doc['source_ref'], 'selected/knowledge/profile.md')
        self.assertNotIn('0123456789abcdef0123456789abcdef', doc['content'])
        self.assertIn('含认证信息的原文行已隐藏', doc['content'])
        status, same = self.request('POST', '/api/upload', body)
        self.assertEqual(status, 201, same)
        self.assertEqual(same['id'], doc['id'])
        self.assertTrue(same['unchanged'])
        revised = {'name': 'profile.md', 'base64': base64.b64encode('偏好已更新'.encode()).decode('ascii'), 'kind': 'memory', 'source_ref': body['source_ref']}
        status, updated = self.request('POST', '/api/upload', revised)
        self.assertEqual(status, 201, updated)
        self.assertEqual(updated['id'], doc['id'])
        self.assertTrue(updated['updated'])
        for path in ('C:/Users/<user>/profile.md', '../credentials/key.md', 'folder/.env'):
            self.assertEqual(self.request('POST', '/api/upload', {**body, 'source_ref': path})[0], 400)
        self.assertEqual(self.request('POST', '/api/upload', body, workspace='demo')[0], 400)
        self.app.dsh_available = True
        with patch.object(self.app, 'dsh_answer') as invoke:
            status, _ = self.request('POST', '/api/ask', {'question': '个人偏好是什么？', 'document_ids': [doc['id']], 'mode': 'dsh', 'allow_external': True})
            self.assertEqual(status, 400)
            invoke.assert_not_called()

    def test_memory_import_only_personal_and_temporary_allowlist(self):
        root = Path(self.tmp.name) / 'synthetic_memory'
        file = root / '知识库/memory/profile.md'
        file.parent.mkdir(parents=True)
        file.write_text('合成偏好：证据先行。', encoding='utf-8')
        self.app.memory_root = root
        rel = '知识库/memory/profile.md'
        scan = self.request('GET', '/api/memory/scan')[1]
        self.assertEqual([f['path'] for f in scan['files']], [rel])
        self.assertNotIn('content', scan['files'][0])
        self.assertEqual(self.request('GET', '/api/memory/scan', workspace='demo')[1]['files'], [])
        self.assertEqual(self.request('POST', '/api/memory/import', {'paths': [rel]}, workspace='demo')[0], 400)
        self.assertEqual(self.request('POST', '/api/memory/import', {'paths': ['../profile.md']})[0], 400)
        status, result = self.request('POST', '/api/memory/import', {'paths': [rel]})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['imported'], 1)

    def test_memory_can_be_retrieved_locally_but_never_sent_to_model(self):
        doc = self.create('documents', {'title': '合成个人记忆', 'kind': 'memory', 'content': '合成记忆偏好：证据先行。'})
        research = self.create('documents', {'title': '合成研究', 'content': '合成研究证据先行。'})
        self.app.ai = {'base_url': 'https://model.invalid/v1', 'model': 'fixture', 'api_key': 'synthetic'}
        body = {'question': '证据', 'document_ids': [doc['id']], 'mode': 'local'}
        self.assertEqual(self.request('POST', '/api/ask', body)[0], 200)
        with patch('workos.server.urllib.request.urlopen', side_effect=AssertionError('Network must not be reached')) as network:
            for ids in ([doc['id']], [research['id'], doc['id']]):
                status, result = self.request('POST', '/api/ask', {**body, 'document_ids': ids, 'mode': 'model', 'allow_external': True})
                self.assertEqual(status, 400, result)
                self.assertIn('记忆', result['error'])
            network.assert_not_called()

    def test_invalid_document_content_is_a_client_error(self):
        before = self.request('GET', '/api/backup')[1]['data']
        for content in (123, None, [], {}):
            with self.subTest(content=content):
                status, result = self.request('POST', '/api/documents', {'title': '合成无效', 'content': content})
                self.assertEqual(status, 400, result)
        self.assertEqual(self.request('GET', '/api/backup')[1]['data'], before)

    def test_dsh_chat_requires_consent_and_uses_only_grounded_citations(self):
        doc = self.create('documents', {'title': '合成 DSH 材料', 'content': '合成星河公司收入为100百万元，收入来自合成订单。'})
        self.app.dsh_available = True
        session_root = Path(self.tmp.name) / 'temporary-sessions'
        overlay = self.app._dsh_overlay('gpt-6-luna', session_root)
        self.assertIn('provider: openai-codex', overlay)
        self.assertIn(json.dumps(str(session_root)), overlay)
        self.assertIn('session-log-deepseek', overlay)
        self.assertIn('model: gpt-6-luna', overlay)
        self.assertIn('- id: tool-bash\n  disabled: true', overlay)
        body = {'question': '星河收入是多少？', 'document_ids': [doc['id']], 'mode': 'dsh', 'model_id': 'gpt-6-luna'}
        with patch.object(self.app, 'dsh_answer', return_value='合成结论：收入100百万元。[S1]') as invoke:
            memory = self.create('documents', {'title': '合成记忆', 'kind': 'memory', 'content': '合成个人偏好'})
            status, denied_memory = self.request('POST', '/api/ask', {**body, 'document_ids': [memory['id']]})
            self.assertEqual(status, 400, denied_memory)
            invoke.assert_not_called()
            status, result = self.request('POST', '/api/ask', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['mode'], 'dsh')
        self.assertEqual(result['model'], 'GPT-6 Luna via DSH')
        self.assertTrue(result['citations'])
        self.assertIn('收入为100百万元', invoke.call_args.args[0])
        self.assertIn('星河收入是多少', invoke.call_args.args[0])
        self.assertEqual(invoke.call_args.args[1], 'gpt-6-luna')
        self.assertEqual(self.request('POST', '/api/ask', {**body, 'model_id': 'arbitrary'})[0], 400)

    def test_agent_endpoint_executes_tools_and_blocks_unknown_models(self):
        actions = iter([json.dumps({'action': 'create_note', 'args': {'title': '助手结论', 'body': '合成内容'}, 'say': '保存结论'}),
                        json.dumps({'action': 'final', 'answer': '已保存 1 条结论。'})])
        with patch.object(self.app, 'ai_lock', __import__('threading').RLock()):
            with patch('workos.agent.urllib.request.urlopen') as opened:
                opened.return_value.__enter__.return_value.read.side_effect = lambda *_: json.dumps({'choices': [{'message': {'content': next(actions)}}]}).encode()
                status, result = self.request('POST', '/api/agent', {'message': '存一条结论', 'model_id': 'deepseek-v4.1-flash'})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['answer'], '已保存 1 条结论。')
        self.assertEqual(result['steps'][0]['action'], 'create_note')
        self.assertTrue(any(note['title'] == '助手结论' for note in self.request('GET', '/api/state')[1]['notes']))
        self.assertEqual(self.request('POST', '/api/agent', {'message': 'hi', 'model_id': 'gpt-6-luna'})[0], 400)

    def test_sync_status_and_manual_sync_are_safe_when_not_configured(self):
        status, data = self.request('GET', '/api/sync/status')
        self.assertEqual(status, 200, data)
        self.assertFalse(data['enabled'])
        status, result = self.request('POST', '/api/sync', {})
        self.assertEqual(status, 200, result)
        self.assertFalse(result['enabled'])
        bootstrap = self.request('GET', '/api/bootstrap')[1]
        self.assertFalse(bootstrap['sync']['enabled'])

    def test_valuation_api_is_deterministic_and_nl_parse_runs_without_extra_prompts(self):
        assumptions = {'currency': 'RMB', 'unit': '百万元', 'period': 'FY2025A', 'net_income': 100, 'pe_multiple': 12}
        status, result = self.request('POST', '/api/model/valuation', {'method': 'net_income', 'assumptions': assumptions})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['equity_value'], 1200)
        self.app.dsh_available = True
        proposal = {'assumptions': assumptions, 'clarifications': []}
        with patch.object(self.app, 'dsh_answer', return_value=json.dumps(proposal, ensure_ascii=False)) as invoke:
            body = {'method': 'net_income', 'text': 'FY2025净利润100百万元，P/E 12x', 'model_id': 'gpt-6-luna'}
            status, parsed = self.request('POST', '/api/model/parse-assumptions', body)
        self.assertEqual(status, 200, parsed)
        self.assertEqual(parsed['assumptions'], assumptions)
        self.assertEqual(parsed['missing'], [])
        self.assertIn('确认', parsed['warning'])
        self.assertEqual(invoke.call_args.args[1], 'gpt-6-luna')

    def test_api_key_never_echoed_backed_up_or_persisted(self):
        secret = 'synthetic-secret-never-real-12345'
        status, result = self.request('POST', '/api/ai/settings',
                                      {'base_url': 'http://127.0.0.1:9/v1', 'model': 'fixture', 'api_key': secret})
        self.assertEqual(status, 200, result)
        self.assertNotIn('api_key', result)
        for workspace in ('personal', 'demo'):
            for endpoint in ('/api/bootstrap', '/api/backup', '/api/state'):
                status, data = self.request('GET', endpoint, workspace=workspace)
                self.assertEqual(status, 200)
                self.assertNotIn(secret, json.dumps(data))
                self.assertNotIn('api_key', json.dumps(data))
        for path in self.app.data_dir.iterdir():
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), path.name)

    def test_json_and_ai_settings_validation(self):
        self.assertEqual(self.request('POST', '/api/projects', {'name': 'x'}, headers={'Content-Type': 'text/plain'})[0], 400)
        for base in ('http://external.invalid/v1', 'https://user:pass@example.invalid/v1', 'https://example.invalid/v1?api_key=fixture'):
            self.assertEqual(self.request('POST', '/api/ai/settings', {'base_url': base, 'model': 'fixture'})[0], 400)
        # Wrong field types must be a client error, not a server traceback/500.
        for field in ('base_url', 'model', 'api_key'):
            with self.subTest(field=field):
                self.assertEqual(self.request('POST', '/api/ai/settings', {field: 123})[0], 400)

    def test_export_html_escapes_user_markup(self):
        title = '<script>fixture_title_attack()</script>'
        body = '## <img src=x onerror="fixture_body_attack()">\n<script>fixture_script_attack()</script>\n& raw'
        doc = self.create('deliverables', {'title': title, 'body': body})
        status, result = self.request('GET', '/api/export/' + doc['id'] + '?format=html')
        self.assertEqual(status, 200)
        self.assertNotIn(title, result)
        self.assertNotIn('<img src=x', result)
        self.assertNotIn('<script>fixture_script_attack()', result)
        self.assertIn(html.escape(title), result)
        self.assertIn(html.escape('<img src=x onerror="fixture_body_attack()">'), result)
        self.assertIn('&amp; raw', result)
        self.assertIn('id="report-editor-script"', result)
        self.assertIn('id="report-notes-data"', result)
        self.assertNotIn('contenteditable=', result)
        self.assertNotIn('vendor/editable', result)
        self.assertIn('fixture_script_attack()', markdown(doc))
        self.assertEqual(self.request('GET', '/api/export/' + doc['id'] + '?format=unknown')[0], 400)


if __name__ == '__main__':
    unittest.main()
