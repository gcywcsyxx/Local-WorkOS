"""CSRF recovery codes are narrow; origin/auth checks cannot be retried as expiry."""
from contextlib import ExitStack
import http.client
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import Mock, patch

from workos.password_auth import SESSION_COOKIE
from workos.server import Application, CsrfExpired, Handler, LocalServer


class CsrfRecoveryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.stack = ExitStack()
        self.stack.enter_context(patch('workos.server.find_root', return_value=None))
        mirror = Mock()
        mirror.status.return_value = {'enabled': False}
        mirror.restore_if_empty.return_value = None
        mirror.sync.return_value = {'enabled': False}
        self.stack.enter_context(patch('workos.server.OneDriveMirror', return_value=mirror))
        self.stack.enter_context(patch.dict(os.environ, {'WORKOS_PUBLIC_ORIGIN': '',
            'WORKOS_PUBLIC_AUTH_MODE': 'access', 'WORKOS_ACCESS_TEAM': '', 'WORKOS_ACCESS_AUD': ''}))
        self.app = Application(Path(self.temp.name) / 'data', port=0)
        self.httpd = LocalServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.app.port = self.httpd.server_address[1]
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever,
            kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.app.parse_model_assumptions = Mock(return_value={'method': 'lbo', 'assumptions': {}})
        self.app.local_chat = Mock(side_effect=AssertionError('No real provider calls in CSRF tests'))
        self.app.dsh_answer = Mock(side_effect=AssertionError('No real DSH calls in CSRF tests'))

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.app.close()
        self.stack.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=3)
        actual = {'X-Workspace': 'personal'}
        if token is not None:
            actual['X-CSRF-Token'] = token
        if body is not None:
            actual['Content-Type'] = 'application/json'
            body = json.dumps(body, ensure_ascii=False).encode()
        actual.update(headers or {})
        try:
            connection.request(method, path, body=body, headers=actual)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def rejected_before_execution(self, path, token, headers=None):
        # Header authorization precedes JSON parsing; no unread body is needed.
        status, result = self.request('POST', path, token=token, headers=headers)
        self.assertEqual(status, 403, result)
        self.assertEqual(result.get('code'), 'csrf_expired')
        self.assertEqual(set(result), {'error', 'code'})
        if token:
            self.assertNotIn(token, json.dumps(result))
        self.assertEqual(self.app.stores['personal'].list('projects'), [])
        self.assertIsNone(self.app._jobs)
        self.app.parse_model_assumptions.assert_not_called()
        self.app.local_chat.assert_not_called()
        self.app.dsh_answer.assert_not_called()

    def test_rotated_process_token_is_recoverable_before_mutation_or_model(self):
        self.assertTrue(issubclass(CsrfExpired, PermissionError))
        status, initial = self.request('GET', '/api/bootstrap')
        self.assertEqual(status, 200)
        previous = initial['csrf']
        self.app.csrf = 'synthetic-new-process-token'
        for path in ('/api/projects', '/api/model/parse-assumptions', '/api/workflows/jobs'):
            with self.subTest(path=path):
                self.rejected_before_execution(path, previous)
        status, refreshed = self.request('GET', '/api/bootstrap')
        self.assertEqual(status, 200)
        self.assertEqual(refreshed['csrf'], self.app.csrf)
        self.assertNotEqual(refreshed['csrf'], previous)
        status, record = self.request('POST', '/api/projects', {'name': 'Synthetic recovered write'}, token=refreshed['csrf'])
        self.assertEqual(status, 201, record)
        self.assertEqual(record['name'], 'Synthetic recovered write')
        status, result = self.request('POST', '/api/model/parse-assumptions', {'method': 'lbo', 'description': 'Synthetic inputs'}, token=refreshed['csrf'])
        self.assertEqual(status, 200, result)
        self.app.parse_model_assumptions.assert_called_once()

    def test_missing_wrong_and_nonascii_tokens_are_narrow_mismatch_errors(self):
        for token in (None, 'synthetic-wrong-token', 'stale-é-token'):
            with self.subTest(token=token):
                self.rejected_before_execution('/api/model/parse-assumptions', token)

    def test_bad_host_origin_or_proxy_cannot_obtain_recovery_flag(self):
        for headers in ({'Host': 'attacker.example.invalid'},
                        {'Origin': 'https://attacker.example.invalid'},
                        {'Origin': 'null'}, {'Cf-Connecting-IP': '198.51.100.1'}):
            with self.subTest(headers=headers):
                status, result = self.request('POST', '/api/model/parse-assumptions', token='stale', headers=headers)
                self.assertEqual(status, 403, result)
                self.assertNotIn('code', result)
        self.app.parse_model_assumptions.assert_not_called()
        self.assertEqual(self.app.stores['personal'].list('projects'), [])

    def test_access_authentication_precedes_csrf_expiry_and_is_not_recoverable(self):
        self.app.public_origin = 'https://workos.synthetic.invalid'
        headers = {'Host': 'workos.synthetic.invalid', 'Origin': self.app.public_origin,
                   'Cf-Access-Jwt-Assertion': 'synthetic-invalid-assertion'}
        with patch.object(self.app.access_validator, 'verify', side_effect=PermissionError('Synthetic access refusal')) as verify:
            status, result = self.request('POST', '/api/model/parse-assumptions', token='stale', headers=headers)
            self.assertEqual(status, 403)
            self.assertNotIn('code', result)
            verify.assert_called_once()
        with patch.object(self.app.access_validator, 'verify', return_value={'sub': 'synthetic'}) as verify:
            self.rejected_before_execution('/api/model/parse-assumptions', 'stale', headers)
            verify.assert_called_once()
        with patch.object(self.app.access_validator, 'verify') as verify:
            status, result = self.request('POST', '/api/model/parse-assumptions', token='stale',
                headers={**headers, 'Origin': 'https://attacker.example.invalid'})
            self.assertEqual(status, 403)
            self.assertNotIn('code', result)
            verify.assert_not_called()

    def password_cookie(self):
        nonce = self.app.password_auth.issue_challenge('synthetic-peer')
        token, _ = self.app.password_auth.login(self.app.password_auth.username,
            'Synthetic-CSRF-Password-2026!', 'synthetic-peer', nonce, nonce)
        return SESSION_COOKIE + '=' + token

    def test_password_session_token_mismatch_is_distinct_from_expired_login(self):
        self.app.public_origin = 'https://workos.synthetic.invalid'
        self.app.public_auth_mode = 'password'
        self.app.password_auth.configure_password('Synthetic-CSRF-Password-2026!')
        headers = {'Host': 'workos.synthetic.invalid', 'Origin': self.app.public_origin}
        first_cookie = self.password_cookie()
        status, first_boot = self.request('GET', '/api/bootstrap', headers={**headers, 'Cookie': first_cookie})
        self.assertEqual(status, 200)
        second_cookie = self.password_cookie()
        second_headers = {**headers, 'Cookie': second_cookie}
        self.rejected_before_execution('/api/model/parse-assumptions', first_boot['csrf'], second_headers)
        status, fresh_boot = self.request('GET', '/api/bootstrap', headers=second_headers)
        self.assertEqual(status, 200)
        self.assertNotEqual(fresh_boot['csrf'], first_boot['csrf'])
        self.assertNotEqual(fresh_boot['csrf'], self.app.csrf)
        self.assertTrue(fresh_boot['auth']['public_login'])
        self.app.csrf = 'synthetic-rotated-process-token'
        # A valid password session retains its own token after process rotation.
        status, result = self.request('POST', '/api/model/parse-assumptions',
            {'method': 'lbo', 'description': 'Synthetic inputs'}, token=fresh_boot['csrf'], headers=second_headers)
        self.assertEqual(status, 200, result)
        self.app.parse_model_assumptions.assert_called_once()
        for cookie in ('', SESSION_COOKIE + '=synthetic-invalid-session'):
            with self.subTest(cookie=cookie):
                status, result = self.request('POST', '/api/projects', token=first_boot['csrf'],
                    headers={**headers, 'Cookie': cookie})
                self.assertEqual(status, 401)
                self.assertNotIn('code', result)
        status, result = self.request('POST', '/api/projects', token='stale',
            headers={**second_headers, 'Origin': 'https://attacker.example.invalid'})
        self.assertEqual(status, 403)
        self.assertNotIn('code', result)
        self.assertEqual(self.app.stores['personal'].list('projects'), [])

    def test_other_permission_and_input_errors_never_request_token_recovery(self):
        self.app.parse_model_assumptions.side_effect = PermissionError('Synthetic provider policy refusal')
        status, result = self.request('POST', '/api/model/parse-assumptions',
            {'method': 'lbo', 'description': 'Synthetic inputs'}, token=self.app.csrf)
        self.assertEqual(status, 403)
        self.assertNotIn('code', result)
        self.app.parse_model_assumptions.assert_called_once()
        status, result = self.request('POST', '/api/projects', {'name': 42}, token=self.app.csrf)
        self.assertEqual(status, 400)
        self.assertNotIn('code', result)


if __name__ == '__main__':
    unittest.main()
