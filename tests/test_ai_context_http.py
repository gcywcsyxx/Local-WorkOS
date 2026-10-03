"""Actual HTTP progress and durable multi-turn jobs with synthetic sources only."""
import threading
import unittest
from unittest.mock import Mock,patch
from workos.ai_progress import report_progress
from workos.server import Application
from workos.jobs import FrozenStore
from tests import test_jobs_http as fixture
from tests.test_jobs import PendingExecutor


class AIContextHttpTests(unittest.TestCase):
    setUp=fixture.AsyncJobsHttpTests.setUp
    tearDown=fixture.AsyncJobsHttpTests.tearDown
    request=fixture.AsyncJobsHttpTests.request
    body=fixture.AsyncJobsHttpTests.body
    submitted=fixture.AsyncJobsHttpTests.submitted
    finished=fixture.AsyncJobsHttpTests.finished
    normal_model=fixture.AsyncJobsHttpTests.normal_model

    def chat(self,purpose='workflow',workspace='personal'):
        return self.app.conversations.create(workspace,self.projects[workspace]['id'],purpose,
            [self.docs[workspace]['id']],metadata={'workflow_key':'brief'} if purpose=='workflow' else {})

    def test_two_turn_jobs_reopen_and_revision_use_latest_edited_parent_once(self):
        self.model.side_effect=lambda *args,**kwargs:('FIRST synthetic draft; 判断仍需核实。[S1]','Synthetic model')
        first=self.finished(self.submitted()['id'])
        self.assertEqual(first['status'],'completed',first)
        conversation_id=first['result']['conversation_id'];parent_id=first['result']['deliverable_id']
        self.assertEqual(first['conversation_id'],conversation_id)
        self.assertTrue(any(event['stage']=='archive' for event in first['events']))
        self.app.stores['personal'].update('deliverables',parent_id,{'body':'USER EDITED current original. [S1]'})
        self.app.close();self.app=Application(self.data_dir,self.httpd.server_address[1]);self.httpd.app=self.app
        self.app.local_chat=Mock(return_value=('SECOND revised draft; 判断仍需核实。[S1]','Synthetic model'))
        second_body=self.body(request_id='synthetic-revision',conversation_id=conversation_id,
            revision_of=parent_id,message='按当前编辑的原稿继续修订')
        second=self.finished(self.submitted(second_body)['id'])
        self.assertEqual(second['status'],'completed',second)
        self.assertEqual(second['result']['conversation_id'],conversation_id)
        self.app.local_chat.assert_called_once()
        prompt=self.app.local_chat.call_args.args[3]
        self.assertIn('FIRST synthetic draft',prompt);self.assertIn('USER EDITED current original',prompt)
        saved=self.app.stores['personal'].get('deliverables',second['result']['deliverable_id'])
        self.assertEqual(saved['revision_of'],parent_id);self.assertEqual(saved['revision_number'],2)
        history=self.app.conversations.get('personal',conversation_id)
        self.assertEqual(history['turns_total'],2)
        self.assertIn('FIRST synthetic draft',history['turns'][0]['output_snapshot']['body'])
        self.assertEqual(history['turns'][1]['base_snapshot']['body'],'USER EDITED current original. [S1]')
        self.assertEqual(history['turns'][1]['parent_artifact']['id'],parent_id)
        self.assertEqual(self.submitted(second_body)['id'],second['id'])
        self.assertEqual(self.app.conversations.get('personal',conversation_id)['turns_total'],2)

    def test_failed_retry_resumes_same_chat_and_failure_does_not_enter_context(self):
        self.model.side_effect=ValueError('PRIVATE_SYNTHETIC_PROVIDER_DETAIL')
        job=self.submitted();failed=self.finished(job['id'])
        self.assertEqual(failed['status'],'failed',failed)
        conversation_id=failed['conversation_id'];self.assertTrue(conversation_id)
        self.assertEqual(self.app.conversations.context('personal',conversation_id)['messages'],[])
        self.model.side_effect=self.normal_model
        code,response=self.request('POST','/api/workflows/jobs/'+job['id']+'/retry',{})
        self.assertEqual(code,202,response)
        done=self.finished(job['id']);self.assertEqual(done['status'],'completed',done)
        self.assertEqual(done['result']['conversation_id'],conversation_id)
        history=self.app.conversations.get('personal',conversation_id)
        self.assertEqual([turn['status'] for turn in history['turns']],['failed','completed'])
        self.assertEqual(len(self.app.conversations.context('personal',conversation_id)['messages']),2)
        self.assertNotIn('PRIVATE_SYNTHETIC_PROVIDER_DETAIL',self.model.call_args.args[3])

    def test_queued_job_rejects_new_successful_context_before_provider_and_retry(self):
        chat=self.chat()
        with patch('workos.jobs.ThreadPoolExecutor',PendingExecutor):job=self.submitted(self.body(conversation_id=chat['id']))
        self.app.conversations.append('personal',chat['id'],'A newer request','Newer answer')
        self.app.jobs()._execute('personal',job['id'])
        done=self.finished(job['id'])
        self.assertEqual(done['status'],'failed',done);self.assertIn('对话',done['error'])
        self.model.assert_not_called();self.assertEqual(self.app.stores['personal'].list('deliverables'),[])
        code,response=self.request('POST','/api/workflows/jobs/'+job['id']+'/retry',{})
        self.assertEqual(code,400,response)
        self.assertIn('对话',response['error'])

    def test_operation_progress_recovers_known_chat_and_stop_never_commits_context(self):
        entered,release=threading.Event(),threading.Event();self.releases.append(release)
        responses=[]
        def blocked(*args,**kwargs):
            report_progress('provider','等待合成模型响应');entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic HTTP context barrier timeout')
            return self.normal_model(*args,**kwargs)
        self.model.side_effect=blocked
        body={'question':'Explain this business briefly','mode':'deepseek','model_id':'deepseek-v4-pro',
            'project_id':self.projects['personal']['id'],'document_ids':[self.docs['personal']['id']]}
        thread=threading.Thread(target=lambda:responses.append(self.request('POST','/api/ask',body,
            headers={'X-WorkOS-Request-ID':'synthetic-ask-progress'})))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            code,response=self.request('GET','/api/operations/synthetic-ask-progress',csrf=False)
            self.assertEqual(code,200,response);operation=response['operation']
            self.assertEqual(operation['stage'],'provider');self.assertTrue(operation['conversation_id'])
            self.assertIsNone(operation['progress_percent']);self.assertTrue(operation['eta']['estimated'])
            self.assertEqual(self.request('GET','/api/operations/synthetic-ask-progress',workspace='demo',csrf=False)[0],404)
            code,listing=self.request('GET','/api/operations',csrf=False)
            self.assertEqual(code,200,listing)
            self.assertIn('synthetic-ask-progress',{row['request_id'] for row in listing['operations']})
            code,stopped=self.request('POST','/api/operations/synthetic-ask-progress/cancel',{})
            self.assertEqual(code,200,stopped)
        finally:release.set();thread.join(4)
        self.assertFalse(thread.is_alive());self.assertEqual(responses[0][0],409,responses)
        history=self.app.conversations.get('personal',operation['conversation_id'])
        self.assertEqual([turn['status'] for turn in history['turns']],['cancelled'])
        self.assertEqual(self.app.conversations.context('personal',operation['conversation_id'])['messages'],[])

    def test_stop_after_final_commit_preserves_successful_context_and_archive(self):
        committed,release=threading.Event(),threading.Event();self.releases.append(release)
        original=FrozenStore.create
        def committed_then_wait(store,*args,**kwargs):
            result=original(store,*args,**kwargs);committed.set()
            if not release.wait(3):raise RuntimeError('Synthetic final-commit barrier timeout')
            return result
        archive=Mock(wraps=self.app.archive_record);self.app.archive_record=archive
        with patch.object(FrozenStore,'create',committed_then_wait):
            job=self.submitted()
            try:
                self.assertTrue(committed.wait(1))
                code,response=self.request('POST','/api/workflows/jobs/'+job['id']+'/cancel',{})
                self.assertEqual(code,200,response)
                self.assertEqual(response['job']['status'],'completed',response)
            finally:release.set()
            self.app.jobs().executor.shutdown(wait=True)
        done=self.finished(job['id']);conversation_id=done['result']['conversation_id']
        self.assertTrue(conversation_id)
        history=self.app.conversations.get('personal',conversation_id)
        self.assertEqual([turn['status'] for turn in history['turns']],['completed'])
        self.assertEqual(history['turns'][0]['current_artifact']['id'],done['result']['deliverable_id'])
        self.assertEqual(len(self.app.conversations.context('personal',conversation_id)['messages']),2)
        self.assertEqual(len(self.app.stores['personal'].list('deliverables')),1)
        self.model.assert_called_once();archive.assert_called_once()


if __name__=='__main__':unittest.main()
