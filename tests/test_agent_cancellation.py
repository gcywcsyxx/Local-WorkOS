"""Synthetic cancellation races; no accounts, model calls or production data."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, RLock, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

from workos.agent import agent_turn, _agent_tool_result
from workos.cancellation import CancellationToken, CancellationStore, CancelledError, bind_token, record_step
from workos.store import Store


class ModelReply:
    def __init__(self, decision, entered=None, release=None):
        self.decision, self.entered, self.release = decision, entered, release

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        if self.entered:
            self.entered.set()
            if not self.release.wait(5):
                raise TimeoutError('Synthetic reply did not release')
        return json.dumps({'choices': [{'message': {'content': json.dumps(self.decision)}}]}).encode()


class AgentCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.real = Store(Path(self.temp.name) / 'synthetic.sqlite3')
        self.project = self.real.create('projects', {'name': 'Synthetic project'})
        self.token = CancellationToken(request_id='synthetic-agent-request')
        self.store = CancellationStore(self.real, self.token)
        self.app = SimpleNamespace(ai_lock=RLock(), ai={}, meeting_draft=Mock())
        self.body = {'message': 'Create a synthetic action', 'project_id': self.project['id']}
        self.decision = {'action': 'create_task', 'args': {'title': 'Synthetic action'}, 'say': 'Create action'}

    def tearDown(self):
        self.real.close()
        self.temp.cleanup()

    def test_stop_during_blocked_provider_prevents_returned_action(self):
        entered, release = Event(), Event()
        errors = []

        def execute():
            try:
                with bind_token(self.token):
                    agent_turn(self.app, self.store, self.body)
            except Exception as error:
                errors.append(error)

        with patch('workos.agent.urllib.request.urlopen', return_value=ModelReply(self.decision, entered, release)) as provider:
            worker = Thread(target=execute)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                self.token.cancel()
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(provider.call_count, 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], CancelledError)
        self.assertEqual(errors[0].steps, [])
        self.assertEqual(self.real.list('tasks'), [])

    def test_completed_action_receipt_survives_stop_before_next_provider_call(self):
        def completed(step):
            record_step(step)
            self.token.cancel()

        with self.assertRaises(CancelledError) as caught, bind_token(self.token), patch('workos.agent.record_step', side_effect=completed), \
                patch('workos.agent.urllib.request.urlopen', return_value=ModelReply(self.decision)) as provider:
            agent_turn(self.app, self.store, self.body)
        tasks = self.real.list('tasks')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(len(caught.exception.steps), 1)
        self.assertEqual(caught.exception.steps[0]['result']['id'], tasks[0]['id'])

    def test_stop_after_tool_commit_before_receipt_does_not_lose_committed_action(self):
        def tool(*args, **kwargs):
            result = _agent_tool_result(*args, **kwargs)
            self.token.cancel()
            return result

        with self.assertRaises(CancelledError) as caught, bind_token(self.token), patch('workos.agent._agent_tool_result', side_effect=tool), \
                patch('workos.agent.urllib.request.urlopen', return_value=ModelReply(self.decision)) as provider:
            agent_turn(self.app, self.store, self.body)
        tasks = self.real.list('tasks')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(caught.exception.steps[0]['result']['id'], tasks[0]['id'])

    def test_cancellation_wins_over_provider_network_and_http_errors(self):
        for error in (urllib.error.URLError('Synthetic network failure'),
                      urllib.error.HTTPError('http://synthetic.invalid', 503, 'Synthetic provider failure', {}, None)):
            token = CancellationToken(request_id='synthetic-error-request')

            def fail(*_args, **_kwargs):
                token.cancel()
                raise error

            with self.subTest(error=type(error).__name__), self.assertRaises(CancelledError), bind_token(token), \
                    patch('workos.agent.urllib.request.urlopen', side_effect=fail):
                agent_turn(self.app, CancellationStore(self.real, token), self.body)
        self.assertEqual(self.real.list('tasks'), [])

    def test_stop_during_minutes_generation_prevents_meeting_overwrite(self):
        meeting = self.real.create('meetings', {'title': 'Synthetic meeting', 'project_id': self.project['id'],
                                               'transcript': 'Synthetic transcript', 'summary': 'Original summary'})

        def draft(*_args):
            self.token.cancel()
            return {'summary': 'Late generated summary'}

        self.app.meeting_draft.side_effect = draft
        with self.assertRaises(CancelledError), bind_token(self.token):
            _agent_tool_result('generate_minutes', {}, self.store, self.project['id'], self.app,
                               {'meeting_id': meeting['id'], 'provider': 'deepseek'})
        self.assertEqual(self.app.meeting_draft.call_count, 1)
        self.assertEqual(self.real.get('meetings', meeting['id'])['summary'], 'Original summary')


if __name__ == '__main__':
    unittest.main()
