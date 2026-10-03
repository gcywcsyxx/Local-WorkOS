"""Conversation scope, persistent revisions and bounded model context."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from workos.conversations import Conversations
from workos.store import Store


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();root=Path(self.temp.name)
        self.path=root/'conversations.sqlite3'
        self.stores={workspace:Store(root/(workspace+'.sqlite3')) for workspace in ('personal','demo')}
        self.projects={};self.docs={}
        for workspace,store in self.stores.items():
            self.projects[workspace]=store.create('projects',{'name':'Synthetic '+workspace})
            self.docs[workspace]=store.create('documents',{'title':'Synthetic source','content':'Synthetic explicit evidence',
                'project_id':self.projects[workspace]['id']})
        self.service=Conversations(self.path,self.stores)

    def tearDown(self):
        self.service.close()
        for store in self.stores.values():store.close()
        self.temp.cleanup()

    def create(self,workspace='personal',**overrides):
        return self.service.create(workspace,self.projects[workspace]['id'],'ask',[self.docs[workspace]['id']],**overrides)

    def test_scopes_are_exact_and_projectless_requires_same_explicit_sources(self):
        conversation=self.create();demo=self.create('demo')
        self.service.append('personal',conversation['id'],'Question','Synthetic answer')
        with self.assertRaises(KeyError):self.service.get('demo',conversation['id'])
        for changes in ({'project_id':self.projects['demo']['id']},{'purpose':'actions'},{'source_ids':[]}):
            with self.assertRaises(ValueError):self.service.context('personal',conversation['id'],**changes)
        self.assertEqual([row['id'] for row in self.service.list('personal',project_id=conversation['project_id'],purpose='ask')],[conversation['id']])
        self.assertEqual(self.service.get('demo',demo['id'])['turns'],[])
        global_chat=self.service.create('personal','','ask',[self.docs['personal']['id']])
        with self.assertRaises(ValueError):self.service.context('personal',global_chat['id'],project_id=conversation['project_id'])
        self.assertEqual(self.service.context('personal',global_chat['id'],project_id='',source_ids=global_chat['source_ids'])['messages'],[])

    def test_only_completed_turns_enter_model_context(self):
        conversation=self.create()
        for status in ('failed','cancelled','interrupted'):
            self.service.append('personal',conversation['id'],'FAILED '+status,'INCOMPLETE '+status,status=status)
        self.service.append('personal',conversation['id'],'Completed question','Completed answer')
        context=self.service.context('personal',conversation['id'])
        self.assertEqual(context['messages'],[{'role':'user','content':'Completed question'},{'role':'assistant','content':'Completed answer'}])
        self.assertEqual(self.service.get('personal',conversation['id'])['turns_total'],4)

    def test_restart_restores_messages_and_request_idempotency(self):
        conversation=self.create()
        turn=self.service.append('personal',conversation['id'],'Question','Answer',request_id='synthetic-request')
        self.assertEqual(self.service.append('personal',conversation['id'],'Question','Answer',request_id='synthetic-request')['id'],turn['id'])
        with self.assertRaises(ValueError):self.service.append('personal',conversation['id'],'Different','Answer',request_id='synthetic-request')
        self.service.close();self.service=Conversations(self.path,self.stores)
        self.assertEqual(self.service.get('personal',conversation['id'])['turns_total'],1)
        self.assertEqual(self.service.context('personal',conversation['id'])['messages'][1]['content'],'Answer')

    def test_context_budget_and_turn_limit_are_disclosed(self):
        conversation=self.create()
        for index in range(20):self.service.append('personal',conversation['id'],'Question '+str(index),'Answer '+str(index))
        context=self.service.context('personal',conversation['id'],max_turns=3)
        self.assertTrue(context['truncated']);self.assertEqual(context['omitted_turns'],17)
        self.assertEqual(context['messages'][0]['content'],'Question 17')
        self.assertEqual(context['omitted_chars'],sum(len('Question '+str(index))+len('Answer '+str(index)) for index in range(17)))
        self.service.append('personal',conversation['id'],'U'*800,'A'*1600)
        context=self.service.context('personal',conversation['id'],max_chars=500)
        self.assertTrue(context['truncated']);self.assertGreater(context['omitted_chars'],0)
        self.assertLessEqual(sum(len(message['content']) for message in context['messages']),500)
        self.assertIn('预算',context['warning'])

    def test_revision_snapshots_are_immutable_and_failed_turn_does_not_change_current_artifact(self):
        conversation=self.create();store=self.stores['personal']
        parent=store.create('deliverables',{'title':'Synthetic original','body':'VERSION ONE',
            'project_id':conversation['project_id'],'source_ids':conversation['source_ids']})
        output=store.create('deliverables',{'title':'Synthetic revision','body':'VERSION TWO',
            'project_id':conversation['project_id'],'source_ids':conversation['source_ids']})
        ref=lambda record:{'collection':'deliverables','id':record['id'],'updated_at':record['updated_at']}
        turn=self.service.append('personal',conversation['id'],'Revise prior answer','Revised answer',
            parent_artifact=ref(parent),current_artifact=ref(output),base_snapshot=parent,output_snapshot=output)
        turn['base_snapshot']['body']='CLIENT MUTATION'
        store.update('deliverables',parent['id'],{'body':'EDITED LATER'})
        self.service.append('personal',conversation['id'],'Failed revision','Partial',status='failed',current_artifact=ref(parent))
        history=self.service.get('personal',conversation['id'])
        self.assertEqual(history['turns'][0]['base_snapshot']['body'],'VERSION ONE')
        self.assertEqual(history['turns'][0]['output_snapshot']['body'],'VERSION TWO')
        self.assertEqual(self.service.context('personal',conversation['id'])['current_artifact']['id'],output['id'])

    def test_memory_foreign_sources_and_later_memory_reclassification_are_rejected(self):
        store=self.stores['personal']
        memory=store.create('documents',{'title':'Synthetic private memory','kind':'memory','content':'PRIVATE'})
        foreign=store.create('projects',{'name':'Other synthetic project'})
        source=store.create('documents',{'title':'Foreign','content':'FOREIGN','project_id':foreign['id']})
        for item in (memory,source):
            with self.assertRaises(ValueError):self.service.create('personal',self.projects['personal']['id'],'ask',[item['id']])
        conversation=self.create()
        store.update('documents',self.docs['personal']['id'],{'kind':'memory'})
        with self.assertRaises(ValueError):self.service.context('personal',conversation['id'])

    def test_source_scope_change_and_foreign_artifact_cannot_be_appended(self):
        conversation=self.create()
        with self.assertRaises(ValueError):self.service.append('personal',conversation['id'],'Q','A',source_ids=[])
        foreign=self.stores['personal'].create('projects',{'name':'Foreign synthetic project'})
        artifact=self.stores['personal'].create('notes',{'title':'Foreign note','body':'FOREIGN','project_id':foreign['id']})
        with self.assertRaises(ValueError):self.service.append('personal',conversation['id'],'Q','A',current_artifact={'collection':'notes','id':artifact['id']})
        self.assertEqual(self.service.get('personal',conversation['id'])['turns_total'],0)

    def test_credentials_nonfinite_and_invalid_fields_do_not_persist(self):
        conversation=self.create();before=self.service.backup('personal')
        for changes in ({'metadata':{'api_key':'synthetic-secret'}},{'output_snapshot':{'result':float('nan')}},
            {'current_artifact':{'collection':[],'id':'x'}},{'status':[]},{'request_id':[]},
            {'metadata':[]},{'base_snapshot':[]},{'output_snapshot':[]},{'parent_artifact':[]}):
            with self.assertRaises(ValueError):self.service.append('personal',conversation['id'],'Question','Answer',**changes)
        with self.assertRaises(ValueError):self.service.create('personal',purpose=[])
        self.assertEqual(self.service.backup('personal'),before)

    def test_signature_tracks_successful_context_and_latest_snapshot_not_failed_attempts(self):
        conversation=self.create();scope={'project_id':conversation['project_id'],'purpose':'ask','source_ids':conversation['source_ids']}
        initial=self.service.signature('personal',conversation['id'],**scope)
        self.service.append('personal',conversation['id'],'Failed','Partial',status='failed')
        self.assertEqual(self.service.signature('personal',conversation['id'],**scope),initial)
        self.service.append('personal',conversation['id'],'Success','Answer',output_snapshot={'method':'synthetic','assumptions':{'value':3}})
        successful=self.service.context('personal',conversation['id'],**scope)
        self.assertNotEqual(successful['context_signature'],initial)
        for index in range(51):self.service.append('personal',conversation['id'],'Failed '+str(index),'Partial',status='cancelled')
        self.assertEqual(self.service.context('personal',conversation['id'])['output_snapshot'],successful['output_snapshot'])
        self.assertEqual(self.service.signature('personal',conversation['id'],**scope),successful['context_signature'])

    def test_backup_restore_is_atomic_and_keeps_other_workspace(self):
        conversation=self.create();demo=self.create('demo')
        self.service.append('personal',conversation['id'],'Q','A',request_id='synthetic-request')
        backup=self.service.backup('personal');demo_backup=self.service.backup('demo')
        self.service.create('personal',purpose='meeting')
        self.assertEqual(self.service.restore('personal',backup),{'conversations':1,'turns':1})
        self.assertEqual(self.service.backup('demo'),demo_backup)
        before=self.service.backup('personal')
        invalid=copy.deepcopy(backup);invalid['turns'].append(copy.deepcopy(invalid['turns'][0]))
        with self.assertRaises(ValueError):self.service.restore('personal',invalid)
        self.assertEqual(self.service.backup('personal'),before)
        with self.assertRaises(ValueError):self.service.restore('demo',backup)
        self.assertEqual(self.service.get('demo',demo['id'])['turns_total'],0)


if __name__=='__main__':unittest.main()
