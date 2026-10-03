"""Actual HTTP cancel protocol with blocked synthetic providers, no private data."""
import json
import threading
import time
import unittest
from unittest.mock import Mock, patch
from workos.server import Application
from workos.cancellation import CancellationToken, CancelledError, bind_token
from workos.agent import _agent_tool_result
from tests import test_jobs_http as http_fixture


class CancellationHttpTests(unittest.TestCase):
    setUp = http_fixture.AsyncJobsHttpTests.setUp
    tearDown = http_fixture.AsyncJobsHttpTests.tearDown
    request = http_fixture.AsyncJobsHttpTests.request
    body = http_fixture.AsyncJobsHttpTests.body
    normal_model = http_fixture.AsyncJobsHttpTests.normal_model
    finished = http_fixture.AsyncJobsHttpTests.finished

    def ask_body(self, workspace='personal', **overrides):
        return {'question':'Selected synthetic evidence', 'mode':'deepseek',
            'project_id':self.projects[workspace]['id'],
            'document_ids':[self.docs[workspace]['id']], **overrides}

    def test_stop_before_ask_arrival_and_csrf_validation_preserve_scope(self):
        operation = 'synthetic-http-before-ack'
        path = '/api/operations/'+operation+'/cancel'
        status, response = self.request('POST',path,{},csrf=False)
        self.assertEqual(status,403,response)
        self.assertNotIn(('personal',operation),self.app.operations.entries)
        status, response = self.request('POST',path,{})
        self.assertEqual(status,200,response)
        self.assertEqual(response['status'],'cancelled')
        status, response = self.request('POST','/api/ask',self.ask_body(),
            headers={'X-WorkOS-Request-ID':operation})
        self.assertEqual(status,409,response)
        self.assertEqual(response['code'],'request_cancelled')
        self.model.assert_not_called()
        status, response = self.request('POST','/api/ask',self.ask_body('demo',mode='local'),
            workspace='demo',headers={'X-WorkOS-Request-ID':operation})
        self.assertEqual(status,200,response)
        status, response = self.request('POST',path,{},workspace='demo')
        self.assertEqual(response['status'],'completed')

    def test_cancel_acknowledges_while_real_urllib_waits_and_discards_late_text(self):
        self.app.local_chat = Application.local_chat.__get__(self.app,Application)
        entered,release = threading.Event(),threading.Event()
        self.releases.append(release)
        response = Mock()
        def read(limit):
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic HTTP barrier timeout')
            return json.dumps({'choices':[{'message':{'content':'LATE ANSWER [S1]'},
                                          'finish_reason':'stop'}]}).encode()
        response.read.side_effect=read
        transport=Mock();transport.__enter__=Mock(return_value=response);transport.__exit__=Mock(return_value=False)
        results=[]
        with patch('workos.server.urllib.request.urlopen',return_value=transport):
            worker=threading.Thread(target=lambda:results.append(self.request('POST','/api/ask',self.ask_body(),
                headers={'X-WorkOS-Request-ID':'synthetic-blocked-http'})))
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                started=time.monotonic()
                status,stopped=self.request('POST','/api/operations/synthetic-blocked-http/cancel',{})
                self.assertLess(time.monotonic()-started,.8)
                self.assertEqual(status,200,stopped)
                self.assertEqual(stopped['status'],'cancelled')
                self.assertTrue(worker.is_alive()) # Socket read may still be in flight.
            finally:release.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        status,result=results[0]
        self.assertEqual(status,409,result)
        self.assertEqual(result['code'],'request_cancelled')
        self.assertNotIn('LATE ANSWER',json.dumps(result))

    def test_operation_replay_does_not_repeat_and_bad_ids_reject_before_provider(self):
        headers={'X-WorkOS-Request-ID':'synthetic-once-only'}
        status,response=self.request('POST','/api/ask',self.ask_body(),headers=headers)
        self.assertEqual(status,200,response)
        status,response=self.request('POST','/api/ask',self.ask_body(),headers=headers)
        self.assertEqual(status,409,response)
        self.assertEqual(response['code'],'operation_conflict')
        self.assertEqual(self.model.call_count,1)
        status,response=self.request('POST','/api/ask',self.ask_body(),
            headers={'X-WorkOS-Request-ID':'../bad-id'})
        self.assertEqual(status,400,response)
        self.assertEqual(self.model.call_count,1)

    def test_durable_cancel_before_ack_and_running_cancel_do_not_save(self):
        status,response=self.request('POST','/api/workflows/jobs/cancel',{'request_id':'synthetic-job-pre-ack'})
        self.assertEqual(status,200,response)
        status,response=self.request('POST','/api/workflows/jobs',self.body(request_id='synthetic-job-pre-ack'))
        self.assertEqual(status,409,response)
        self.assertEqual(response['code'],'request_cancelled')
        self.model.assert_not_called()
        entered,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def generate(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic HTTP barrier timeout')
            return self.normal_model(*args,**kwargs)
        self.model.side_effect=generate
        status,response=self.request('POST','/api/workflows/jobs',self.body(quality_mode='thorough'))
        self.assertEqual(status,202,response)
        job=response['job']
        self.assertTrue(entered.wait(1))
        status,response=self.request('POST','/api/workflows/jobs/'+job['id']+'/cancel',{},workspace='demo')
        self.assertEqual(status,404,response)
        status,response=self.request('POST','/api/workflows/jobs/cancel',{'request_id':'synthetic-http-request'})
        self.assertEqual(status,200,response)
        self.assertEqual(response['job']['status'],'cancelled')
        release.set();self.app.jobs().executor.shutdown(wait=True)
        status,response=self.request('POST','/api/workflows/jobs/'+job['id']+'/retry',{})
        self.assertEqual(response['job']['status'],'cancelled')
        self.assertEqual(self.app.stores['personal'].list('deliverables'),[])
        self.assertEqual(self.model.call_count,1)

    def test_dsh_application_adapters_supply_cancellation_to_heartbeat(self):
        self.app.dsh_answer=Application.dsh_answer.__get__(self.app,Application)
        token=CancellationToken('synthetic-dsh')
        def runner(app,prompt,model,models,**kwargs):
            token.cancel()
            kwargs['progress_callback']({'stage':'dsh','event':'heartbeat'})
            raise AssertionError('Cancelled callback must prevent a late DSH answer')
        with patch('workos.dsh_harness.run',side_effect=runner) as native:
            for execute in (lambda:self.app.dsh_answer('Synthetic','gpt-6-luna'),
                lambda:self.app.dsh_harness_answer('Synthetic','Synthetic','gpt-6-luna',[],[],Mock())):
                token=CancellationToken('synthetic-dsh')
                with self.assertRaises(CancelledError):
                    with bind_token(token):execute()
            self.assertEqual(native.call_count,2)

    def meeting(self):
        return self.app.stores['personal'].create('meetings',{'title':'Synthetic meeting',
            'project_id':self.projects['personal']['id'],'transcript':'Original transcript',
            'summary':'Original summary'})

    def meeting_body(self,meeting,**overrides):
        return {'provider':'deepseek','save_meeting_id':meeting['id'],
            'project_id':meeting['project_id'],'transcript':'Synthetic newly supplied transcript',**overrides}

    def synthetic_meeting_model(self,*args,**kwargs):
        return json.dumps({'summary':'- Synthetic 3 – 4\no Detail\n➤ Evidence',
            'experts':[],'matrix':{},'contents':[]}), 'Synthetic model'

    def test_meeting_cancel_while_provider_blocked_does_not_save_or_replace_transcript(self):
        meeting=self.meeting()
        entered,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def generate(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic meeting barrier timeout')
            return self.synthetic_meeting_model(*args,**kwargs)
        self.model.side_effect=generate
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.request('POST','/api/meeting-draft',
            self.meeting_body(meeting),headers={'X-WorkOS-Request-ID':'synthetic-meeting-stop'})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            status,stopped=self.request('POST','/api/operations/synthetic-meeting-stop/cancel',{})
            self.assertEqual(stopped['status'],'cancelled')
        finally:release.set();worker.join(3)
        self.assertEqual(results[0][0],409,results)
        self.assertEqual(self.app.stores['personal'].get('meetings',meeting['id']),meeting)

    def test_meeting_save_wins_stop_race_and_reports_saved_id(self):
        meeting=self.meeting()
        self.model.side_effect=self.synthetic_meeting_model
        committed,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def sync(workspace):
            committed.set()
            if not release.wait(3):raise RuntimeError('Synthetic meeting sync barrier timeout')
        self.app.sync_workspace=Mock(side_effect=sync)
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.request('POST','/api/meeting-draft',
            self.meeting_body(meeting),headers={'X-WorkOS-Request-ID':'synthetic-meeting-saved'})))
        worker.start()
        try:
            self.assertTrue(committed.wait(1))
            status,stopped=self.request('POST','/api/operations/synthetic-meeting-saved/cancel',{})
            self.assertEqual(status,200,stopped)
            self.assertEqual(stopped['status'],'completed')
            self.assertTrue(stopped['saved'])
            self.assertEqual(stopped['meeting_id'],meeting['id'])
        finally:release.set();worker.join(3)
        self.assertEqual(results[0][0],200,results)
        self.assertTrue(results[0][1]['saved'])
        saved=self.app.stores['personal'].get('meetings',meeting['id'])
        self.assertEqual(saved['summary'],'• Synthetic 3-4\no Detail\n➢ Evidence')
        self.assertEqual(saved['transcript'],'Synthetic newly supplied transcript')

    def test_meeting_scope_validation_precedes_provider_and_concurrent_edit_is_preserved(self):
        meeting=self.meeting()
        status,response=self.request('POST','/api/meeting-draft',self.meeting_body(meeting),workspace='demo')
        self.assertEqual(status,404,response)
        status,response=self.request('POST','/api/meeting-draft',self.meeting_body(meeting,project_id='foreign-project'))
        self.assertEqual(status,400,response)
        self.model.assert_not_called()
        entered,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def generate(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic meeting edit barrier timeout')
            return self.synthetic_meeting_model(*args,**kwargs)
        self.model.side_effect=generate
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.request('POST','/api/meeting-draft',
            self.meeting_body(meeting),headers={'X-WorkOS-Request-ID':'synthetic-meeting-edit'})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.app.stores['personal'].update('meetings',meeting['id'],{'summary':'New human edit'})
        finally:release.set();worker.join(3)
        self.assertEqual(results[0][0],400,results)
        self.assertIn('已变更',results[0][1]['error'])
        self.assertEqual(self.app.stores['personal'].get('meetings',meeting['id'])['summary'],'New human edit')

    def test_stop_ack_has_committed_agent_receipt_before_tool_returns(self):
        committed,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def tool(*args,**kwargs):
            result=_agent_tool_result(*args,**kwargs)
            committed.set()
            if not release.wait(3):raise RuntimeError('Synthetic action receipt barrier timeout')
            return result
        response=Mock()
        decision={'action':'create_task','args':{'title':'Synthetic committed action'},'say':'Create task'}
        response.read.return_value=json.dumps({'choices':[{'message':{'content':json.dumps(decision)}}]}).encode()
        transport=Mock();transport.__enter__=Mock(return_value=response);transport.__exit__=Mock(return_value=False)
        results=[]
        with patch('workos.agent._agent_tool_result',side_effect=tool), \
            patch('workos.agent.urllib.request.urlopen',return_value=transport) as provider:
            worker=threading.Thread(target=lambda:results.append(self.request('POST','/api/agent',
                {'message':'Create a synthetic task','project_id':self.projects['personal']['id']},
                headers={'X-WorkOS-Request-ID':'synthetic-commit-before-receipt'})))
            worker.start()
            try:
                self.assertTrue(committed.wait(1))
                status,stopped=self.request('POST','/api/operations/synthetic-commit-before-receipt/cancel',{})
                self.assertEqual(status,200,stopped)
                self.assertEqual(stopped['status'],'cancelled')
                self.assertEqual(len(stopped['steps']),1)
                tasks=[row for row in self.app.stores['personal'].list('tasks') if row['title']=='Synthetic committed action']
                self.assertEqual(len(tasks),1)
                self.assertEqual(stopped['steps'][0]['result']['id'],tasks[0]['id'])
                self.assertEqual(stopped['steps'][0]['result']['summary'],'Synthetic committed action')
            finally:release.set();worker.join(3)
            self.assertEqual(provider.call_count,1)
        self.assertEqual(results[0][0],409,results)
        self.assertEqual(len(results[0][1]['steps']),1) # Full receipt enriches, never duplicates.
        self.assertEqual(results[0][1]['steps'][0]['say'],'Create task')


if __name__=='__main__':unittest.main()
