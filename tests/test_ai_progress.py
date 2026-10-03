"""Public progress, honest ETA, durable callbacks and immutable revision scope."""
import threading
import unittest
from unittest.mock import Mock,patch
from workos.ai_progress import new_execution,add_event,public_execution,finish_execution,report_progress
from workos.cancellation import OperationRegistry,CancelledError
from tests import test_jobs as jobs_fixture


class ProgressTests(unittest.TestCase):
    def test_operation_reports_public_milestones_and_scope_without_model_percent(self):
        registry=OperationRegistry();entered,release=threading.Event(),threading.Event()
        errors=[]
        def execute(token):
            report_progress('provider','等待选定模型响应')
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic progress barrier timeout')
            report_progress('check','检查公开输出')
            return 'answer'
        def worker():
            try:registry.run('personal','synthetic-progress',execute,kind='meeting',model_id='synthetic-model')
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=worker);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            progress=registry.get('personal','synthetic-progress')
            self.assertEqual(progress['kind'],'meeting');self.assertEqual(progress['stage'],'provider')
            self.assertIsNone(progress['progress_percent']);self.assertTrue(progress['eta']['estimated'])
            self.assertGreater(progress['eta']['max_seconds'],0)
            with self.assertRaises(KeyError):registry.get('demo','synthetic-progress')
        finally:release.set();thread.join(3)
        self.assertFalse(errors)
        completed=registry.get('personal','synthetic-progress')
        self.assertEqual(completed['progress_percent'],100)
        self.assertEqual([event['stage'] for event in completed['events']],['prepare','provider','check','completed'])

    def test_events_are_bounded_redacted_and_internal_reasoning_is_rejected(self):
        execution=new_execution()
        for index in range(100):add_event(execution,'provider','公开阶段 '+str(index))
        self.assertEqual(len(execution['events']),80)
        add_event(execution,'check','API_KEY=synthetic-secret Bearer synthetic-secret C:/private/path.txt')
        self.assertNotIn('synthetic-secret',execution['events'][-1]['detail'])
        self.assertNotIn('C:/private',execution['events'][-1]['detail'])
        with self.assertRaises(ValueError):add_event(execution,'chain_of_thought','PRIVATE REASONING')
        self.assertNotIn('PRIVATE REASONING',str(execution))

    def test_eta_exceeded_is_unknown_and_terminal_time_is_frozen(self):
        with patch('workos.ai_progress.time.time',return_value=1000):
            execution=new_execution('ask');add_event(execution,'provider','Waiting')
        with patch('workos.ai_progress.time.time',return_value=1200):
            exceeded=public_execution(execution,'running')
            self.assertIsNone(exceeded['eta']['max_seconds'])
            self.assertIn('无法',exceeded['eta']['basis'])
            finish_execution(execution,'cancelled')
        with patch('workos.ai_progress.time.time',return_value=1600):
            stopped=public_execution(execution,'cancelled')
            self.assertEqual(stopped['elapsed_ms'],200000)
            self.assertEqual(stopped['eta']['max_seconds'],0)
            self.assertIsNone(stopped['progress_percent'])

    def test_stop_freezes_progress_and_late_callback_cannot_change_it(self):
        registry=OperationRegistry();token=registry.token('personal','synthetic-stop')
        token.report('provider','正在等待模型')
        stopped=registry.cancel('personal','synthetic-stop')
        with self.assertRaises(CancelledError):token.report('save','LATE SAVE')
        self.assertEqual(registry.get('personal','synthetic-stop')['events'],stopped['events'])

    def test_recent_operation_list_is_bounded_scoped_and_does_not_create_records(self):
        registry=OperationRegistry()
        for index in range(35):registry.token('personal','synthetic-'+str(index))
        registry.token('demo','foreign')
        self.assertEqual(len(registry.list('personal')),30)
        self.assertEqual(registry.list('personal',limit=1)[0]['request_id'],'synthetic-34')
        before=len(registry.entries)
        self.assertEqual(registry.list('absent'),[])
        self.assertEqual(len(registry.entries),before)
        self.assertNotIn('foreign',{record['request_id'] for record in registry.list('personal')})
        with self.assertRaises(ValueError):registry.list('personal',limit=1000)


class JobProgressTests(unittest.TestCase):
    setUp=jobs_fixture.WorkflowJobTests.setUp
    tearDown=jobs_fixture.WorkflowJobTests.tearDown
    manager=jobs_fixture.WorkflowJobTests.manager
    request=jobs_fixture.WorkflowJobTests.request
    finished=jobs_fixture.WorkflowJobTests.finished
    blocking_model=jobs_fixture.WorkflowJobTests.blocking_model

    def test_queue_running_provider_and_completion_trace_are_durable(self):
        jobs=self.manager(workers=1);entered,release=threading.Event(),threading.Event()
        self.releases.append(release)
        def model(*args,**kwargs):
            report_progress('provider','等待合成模型响应');entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic job progress timeout')
            return '合成判断仍需核实。[S1]','Synthetic model'
        self.app.local_chat.side_effect=model
        job=jobs.submit('real',self.request())
        self.assertEqual(job['status'],'queued');self.assertIsNone(job['started_at'])
        self.assertIsNone(job['eta']['max_seconds'])
        self.assertTrue(entered.wait(1))
        running=jobs.get('real',job['id'])
        self.assertTrue(running['started_at']);self.assertEqual(running['stage'],'provider')
        self.assertGreater(running['progress_percent'],0)
        self.assertLess(running['progress_percent'],100)
        release.set();done=self.finished(jobs,'real',job['id'])
        self.assertEqual(done['progress_percent'],100)
        self.assertTrue(any(event['stage']=='provider' for event in done['events']))
        jobs.close();reopened=self.manager()
        self.assertEqual(reopened.get('real',job['id'])['events'],done['events'])
        self.assertEqual(reopened.get('real',job['id'])['elapsed_ms'],done['elapsed_ms'])

    def test_revision_parent_is_frozen_and_edit_blocks_stale_job(self):
        store=self.stores['real']
        parent=store.create('deliverables',{'title':'Synthetic original','body':'Original version',
            'project_id':self.projects['real']['id'],'source_ids':[self.docs['real']['id']]})
        with patch('workos.jobs.ThreadPoolExecutor',jobs_fixture.PendingExecutor):jobs=self.manager()
        job=jobs.submit('real',self.request(revision_of=parent['id'],conversation_id='synthetic-conversation'))
        snapshot=jobs._row('real',job['id'])[1]
        self.assertEqual(snapshot['deliverables'][0]['body'],'Original version')
        store.update('deliverables',parent['id'],{'body':'Changed after enqueue'})
        jobs._execute('real',job['id'])
        self.assertEqual(jobs.get('real',job['id'])['status'],'failed')
        self.app.local_chat.assert_not_called()
        self.assertEqual(len(store.list('deliverables')),1)

    def test_revision_parent_rejects_foreign_project_and_unselected_source(self):
        store=self.stores['real']
        other=store.create('projects',{'name':'Foreign project'})
        parent=store.create('deliverables',{'title':'Foreign','body':'Foreign','project_id':other['id']})
        jobs=self.manager()
        with self.assertRaises(ValueError):jobs.submit('real',self.request(revision_of=parent['id']))
        source=store.create('documents',{'title':'Unselected','content':'PRIVATE','project_id':self.projects['real']['id']})
        parent=store.create('deliverables',{'title':'Unselected','body':'PRIVATE','project_id':self.projects['real']['id'],'source_ids':[source['id']]})
        with self.assertRaises(ValueError):jobs.submit('real',self.request(revision_of=parent['id']))
        self.app.local_chat.assert_not_called()


if __name__=='__main__':unittest.main()
