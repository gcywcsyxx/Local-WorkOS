"""Unified model choices through real isolated HTTP, without live providers."""
from datetime import datetime,timedelta,timezone
import json
import unittest
from unittest.mock import Mock,patch
from workos.model_catalog import resolve_selection,selection_identity,LOCAL_AI_PRESETS
from workos.server import Application
from tests import test_jobs_http as fixture


class Response:
    def __init__(self,payload):self.raw=json.dumps(payload,ensure_ascii=False).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return None
    def read(self,maximum=-1):return self.raw if maximum<0 else self.raw[:maximum]


class ModelSelectionHttpTests(unittest.TestCase):
    setUp=fixture.AsyncJobsHttpTests.setUp
    tearDown=fixture.AsyncJobsHttpTests.tearDown
    request=fixture.AsyncJobsHttpTests.request
    normal_model=fixture.AsyncJobsHttpTests.normal_model

    def transport(self,reply):
        self.reply=reply;self.calls=[]
        self.app.ai={'base_url':'https://synthetic-custom.invalid/v1','model':'synthetic-custom-model','api_key':'PRIVATE_SYNTHETIC_KEY'}
        self.app.dsh_available=True
        self.app.local_chat=Application.local_chat.__get__(self.app,Application)
        def compatible(request,timeout=None):
            payload=json.loads(request.data)
            self.calls.append({'mode':'compatible','model':payload['model'],'url':request.full_url,
                'headers':dict(request.header_items()),'payload':payload})
            answer=self.reply(payload) if callable(self.reply) else self.reply
            return Response({'choices':[{'finish_reason':'stop','message':{'content':answer}}]})
        def dsh(prompt,model):
            self.calls.append({'mode':'dsh','model':model,'prompt':prompt})
            return self.reply(prompt) if callable(self.reply) else self.reply
        self.app.dsh_answer=Mock(side_effect=dsh)
        self.stack.enter_context(patch('urllib.request.urlopen',side_effect=compatible))

    def choices(self):
        return [('dsh','gpt-6-sol'),('deepseek','deepseek-v4-pro'),
            ('local-models','kimi-k2.7'),('model','synthetic-custom-model')]

    def body(self,surface,mode,model,**overrides):
        body={'mode':mode,'provider':mode,'model_id':model,'project_id':self.projects['personal']['id']}
        if surface=='ask':body.update(question='Explain the selected source briefly',document_ids=[self.docs['personal']['id']])
        elif surface=='valuation':body.update(method='net_income',text='Synthetic CNY million FY2025A net income100, PE12')
        elif surface=='meeting':body.update(transcript='ONLY_SYNTHETIC_TRANSCRIPT',revision_instructions='整理原文')
        elif surface=='actions':body.update(message='只回复收到',document_ids=[self.docs['personal']['id']])
        elif surface=='workflow':body.update(workflow_key='brief',message='分析这一份合成材料',quality_mode='fast',
            document_ids=[self.docs['personal']['id']],request_id='selection-'+mode)
        return {**body,**overrides}

    def post(self,surface,body):
        route={'ask':'ask','valuation':'model/parse-assumptions','meeting':'meeting-draft',
               'actions':'agent','workflow':'workflows/run'}[surface]
        return self.request('POST','/api/'+route,body)

    def assert_exact_dispatch(self,mode,model):
        self.assertEqual(len(self.calls),1,self.calls)
        call=self.calls[0];self.assertEqual(call['model'],model)
        if mode=='dsh':
            self.assertEqual(call['mode'],'dsh');self.app.dsh_answer.assert_called_once()
        else:
            self.assertEqual(call['mode'],'compatible');self.app.dsh_answer.assert_not_called()
            expected=(self.app.ai['base_url'] if mode=='model' else LOCAL_AI_PRESETS['deepseek' if mode=='deepseek' else 'local']['base_url'])
            self.assertEqual(call['url'],expected+'/chat/completions')
            authorization=next((value for key,value in call['headers'].items() if key.lower()=='authorization'),None)
            self.assertEqual(authorization,'Bearer PRIVATE_SYNTHETIC_KEY' if mode=='model' else None)

    def test_all_four_providers_dispatch_exact_selected_identity_on_all_five_surfaces(self):
        replies={'ask':'合成说明，仍需核实。[S1]',
            'valuation':json.dumps({'assumptions':{'currency':'CNY','unit':'million','period':'2025A','net_income':100,'pe_multiple':12}}),
            'meeting':json.dumps({'title':'Synthetic notes','summary':'合成纪要正文。','experts':[],'matrix':{},'contents':[]}),
            'actions':json.dumps({'action':'final','answer':'合成收到。'}),
            'workflow':'合成研究结论，仍需核实。[S1]'}
        self.transport('unused')
        for surface,reply in replies.items():
            for mode,model in self.choices():
                with self.subTest(surface=surface,mode=mode):
                    self.reply=reply;self.calls.clear();self.app.dsh_answer.reset_mock()
                    code,result=self.post(surface,self.body(surface,mode,model))
                    self.assertEqual(code,201 if surface=='workflow' else 200,result)
                    self.assert_exact_dispatch(mode,model)
                    self.assertIn('GPT-6 Sol' if mode=='dsh' and surface!='actions' else model,result['model'])
                    if surface=='valuation':self.assertEqual(result['assumptions']['pe_multiple'],12)
                    if surface=='meeting':self.assertEqual(result['summary'],'合成纪要正文。')
                    if surface=='workflow':self.assertEqual(result['deliverable']['source_ids'],[self.docs['personal']['id']])

    def test_selected_models_are_preserved_through_real_agent_mutation_rounds(self):
        for mode,model in self.choices():
            with self.subTest(mode=mode):
                self.transport('unused');rounds=[]
                def reply(_):
                    rounds.append(1)
                    return json.dumps({'action':'create_note','args':{'title':'Synthetic saved '+mode,'body':'Synthetic statement'}}
                        if len(rounds)==1 else {'action':'final','answer':'已保存。'},ensure_ascii=False)
                self.reply=reply
                code,result=self.post('actions',self.body('actions',mode,model,message='保存一条合成结论'))
                self.assertEqual(code,200,result);self.assertEqual(len(self.calls),2)
                self.assertTrue(all(call['model']==model for call in self.calls))
                self.assertEqual(len(result['steps']),1)
                note=self.app.stores['personal'].get('notes',result['steps'][0]['result']['id'])
                self.assertEqual(note['project_id'],self.projects['personal']['id'])

    def test_non_ai_rules_and_local_excerpts_bypass_all_providers_and_context(self):
        self.transport('MUST NOT CALL')
        before=self.app.conversations.backup('personal')
        code,result=self.post('ask',{'mode':'local','question':'selected','project_id':self.projects['personal']['id'],
            'document_ids':[self.docs['personal']['id']]})
        self.assertEqual(code,200,result);self.assertFalse(result['model_called'])
        for extra in ({'model_id':'gpt-6-sol'},{'mode':'local','model_id':'gpt-6-sol'}):
            code,result=self.post('meeting',{'provider':'rules','transcript':'合成专家说明。',**extra})
            self.assertEqual(code,200,result)
        self.assertEqual(self.calls,[]);self.app.dsh_answer.assert_not_called()
        self.assertEqual(self.app.conversations.backup('personal'),before)

    def test_nested_agent_meeting_generation_preserves_gpt_and_custom_choices(self):
        for mode,model in (('dsh','gpt-6-sol'),('model','synthetic-custom-model')):
            with self.subTest(mode=mode):
                self.transport('unused');rounds=[]
                meeting=self.app.stores['personal'].create('meetings',{'title':'Synthetic nested '+mode,
                    'project_id':self.projects['personal']['id'],'transcript':'SYNTHETIC_SELECTED_MEETING_TRANSCRIPT'})
                def reply(_):
                    rounds.append(1)
                    return json.dumps({'action':'generate_minutes','args':{}} if len(rounds)==1 else
                        {'title':'Synthetic minutes','summary':'Synthetic saved summary','experts':[],'matrix':{},'contents':[]}
                        if len(rounds)==2 else {'action':'final','answer':'已整理纪要。'},ensure_ascii=False)
                self.reply=reply
                code,result=self.post('actions',self.body('actions',mode,model,
                    meeting_id=meeting['id'],message='整理已选会议纪要'))
                self.assertEqual(code,200,result)
                self.assertEqual(len(self.calls),3);self.assertTrue(all(call['model']==model for call in self.calls))
                saved=self.app.stores['personal'].get('meetings',meeting['id'])
                self.assertEqual(saved['summary'],'Synthetic saved summary')
                sent=json.dumps(self.calls,ensure_ascii=False)
                self.assertIn('SYNTHETIC_SELECTED_MEETING_TRANSCRIPT',sent)

    def test_get_models_and_bootstrap_do_not_probe_or_read_business_records(self):
        self.transport('MUST NOT CALL')
        store=self.app.stores['personal']
        with patch.object(store,'get',side_effect=AssertionError('Catalog must not read documents')),\
             patch.object(store,'list',side_effect=AssertionError('Catalog must not scan records')):
            code,catalog=self.request('GET','/api/models',csrf=False)
            self.assertEqual(code,200,catalog)
            code,boot=self.request('GET','/api/bootstrap',csrf=False)
            self.assertEqual(code,200,boot);self.assertEqual(boot['models'],catalog)
        self.assertEqual(self.calls,[])
        encoded=json.dumps(catalog)
        self.assertNotIn('PRIVATE_SYNTHETIC_KEY',encoded);self.assertNotIn('synthetic-custom.invalid',encoded)

    def test_model_check_sends_only_static_probe_and_saves_nonsecret_status(self):
        self.transport('{"ok":true}');store=self.app.stores['personal']
        before=self.app.conversations.backup('personal')
        for mode,model in self.choices():
            self.calls.clear();self.app.dsh_answer.reset_mock()
            with self.subTest(mode=mode),patch.object(store,'get',side_effect=AssertionError('Probe must not read sources')),\
                 patch.object(store,'list',side_effect=AssertionError('Probe must not read memory')):
                body={'mode':mode,'model_id':model,'document_ids':[self.docs['personal']['id']],
                    'text':'PRIVATE_BUSINESS_SENTINEL','api_key':'CLIENT_PRIVATE_SENTINEL'}
                code,result=self.request('POST','/api/models/check',body)
                self.assertEqual(code,200,result);self.assertEqual(result['model']['status'],'verified')
                self.assert_exact_dispatch(mode,model)
                sent=json.dumps(self.calls,ensure_ascii=False)
                self.assertNotIn('PRIVATE_BUSINESS_SENTINEL',sent);self.assertNotIn('CLIENT_PRIVATE_SENTINEL',sent)
                self.assertNotIn(self.docs['personal']['id'],sent)
        self.assertEqual(self.app.conversations.backup('personal'),before)
        cached=self.app.model_health_path.read_text(encoding='utf-8')
        for secret in ('PRIVATE_SYNTHETIC_KEY','CLIENT_PRIVATE_SENTINEL','PRIVATE_BUSINESS_SENTINEL'):
            self.assertNotIn(secret,cached)

    def test_probe_cache_is_scoped_to_current_endpoint_and_one_day(self):
        self.transport('{"ok":true}')
        choice=resolve_selection({'mode':'deepseek','model_id':'deepseek-v4-pro'},self.app.ai)
        identity='deepseek:deepseek-v4-pro';now=datetime.now(timezone.utc)
        def status(age=0,fingerprint=None):
            return {'status':'verified','checked_at':(now-timedelta(seconds=age)).isoformat(),
                'endpoint_identity':fingerprint or selection_identity(choice),'reason':'Synthetic response accepted'}
        def model():
            code,result=self.request('GET','/api/models',csrf=False);self.assertEqual(code,200,result)
            return next(item for group in result['groups'] for item in group['models'] if item['selection_id']==identity)
        for cached,expected in ((status(),'verified'),(status(age=86401),'not_checked'),
            (status(age=-100),'not_checked'),(status(fingerprint='unrelated-endpoint'),'not_checked')):
            with self.subTest(expected=expected):
                self.app.model_health={identity:cached};self.assertEqual(model()['status'],expected)
        self.app.model_health={identity:status()};self.app.ai['base_url']='http://127.0.0.1:19999/v1'
        self.assertEqual(model()['status'],'not_checked')
        self.app.dsh_available=False
        code,result=self.request('GET','/api/models',csrf=False)
        dsh=[item for group in result['groups'] for item in group['models'] if item['mode']=='dsh']
        self.assertTrue(dsh);self.assertTrue(all(not item['available'] and item['status']=='runtime_unavailable' for item in dsh))
        self.assertEqual(self.calls,[])

    def test_failed_probe_never_falls_back_or_persists_raw_output_and_csrf_precedes_call(self):
        self.transport('PRIVATE_SYNTHETIC_NON_JSON_OUTPUT')
        code,result=self.request('POST','/api/models/check',csrf=False)
        self.assertEqual(code,403,result);self.assertEqual(self.calls,[])
        self.assertEqual(self.app.model_health,{})
        for mode,model in (('dsh','gpt-6-sol'),('deepseek','deepseek-v4-pro')):
            self.calls.clear();self.app.dsh_answer.reset_mock()
            with self.subTest(mode=mode):
                code,result=self.request('POST','/api/models/check',{'mode':mode,'model_id':model})
                self.assertEqual(code,200,result)
                self.assertEqual(result['model']['status'],'unavailable')
                self.assertFalse(result['model']['available'])
                self.assert_exact_dispatch(mode,model)
                self.assertNotIn('PRIVATE_SYNTHETIC_NON_JSON_OUTPUT',json.dumps(result))
        self.assertNotIn('PRIVATE_SYNTHETIC_NON_JSON_OUTPUT',self.app.model_health_path.read_text(encoding='utf-8'))

    def test_selection_mismatches_fail_before_provider_or_record_mutation_on_every_surface(self):
        self.transport('MUST NOT CALL');store=self.app.stores['personal']
        meeting=store.create('meetings',{'title':'Synthetic protected original',
            'project_id':self.projects['personal']['id'],'transcript':'Original synthetic transcript','summary':'Original saved summary'})
        before=store.backup('personal');history=self.app.conversations.backup('personal')
        for surface in ('ask','valuation','meeting','actions','workflow'):
            for changes in ({'mode':'deepseek','model_id':'gpt-6-sol'},
                {'mode':'model','provider':'model','model_id':'unconfigured-custom'},
                {'mode':'dsh','provider':'deepseek','model_id':'gpt-6-sol'},
                {'mode':'dsh','provider':'rules','model_id':'gpt-6-sol'},
                {'mode':'local-models','provider':'local-models','model_id':'codewise-completions'}):
                with self.subTest(surface=surface,changes=changes):
                    body={**self.body(surface,'deepseek','deepseek-v4-pro'),**changes}
                    if surface=='meeting':body['save_meeting_id']=meeting['id']
                    code,result=self.post(surface,body)
                    self.assertEqual(code,400,result)
        self.assertEqual(self.calls,[])
        self.assertEqual(store.backup('personal'),before)
        self.assertEqual(self.app.conversations.backup('personal'),history)


if __name__=='__main__':unittest.main()
