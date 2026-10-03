"""Selected-model ask behavior through actual HTTP, using synthetic evidence only."""
import copy
import json
import threading
import unittest
from unittest.mock import Mock

from workos.engine import chunk_text, retrieve
from tests import test_jobs_http as http_fixture


class AskModelHttpTests(unittest.TestCase):
    setUp = http_fixture.AsyncJobsHttpTests.setUp
    tearDown = http_fixture.AsyncJobsHttpTests.tearDown
    request = http_fixture.AsyncJobsHttpTests.request

    def normal_model(self, *args, **kwargs):
        self.app.completion_meta.finish_reason = 'stop'
        return '选定材料描述了一个经营主体，更多公司判断仍需核实。[S1]', args[1]

    def body(self, workspace='personal', **overrides):
        return {'question':'What drives this business?', 'mode':'deepseek',
            'model_id':'deepseek-v4-pro', 'project_id':self.projects[workspace]['id'],
            'document_ids':[self.docs[workspace]['id']], **overrides}

    def source(self, title, text, *, pages=None, project_id=None, **extra):
        return self.app.stores['personal'].create('documents', {'title':title,'content':text,
            'chunks':chunk_text(text,pages),'project_id':project_id or self.projects['personal']['id'],**extra})

    def assert_citations_are_real(self, citations, documents):
        docs = {doc['id']:doc for doc in documents}
        for citation in citations:
            self.assertIn(citation['document_id'],docs)
            doc = docs[citation['document_id']]
            chunks = doc.get('chunks') or chunk_text(doc['content'])
            self.assertIn(citation['id'],{doc['id']+':'+chunk['id'] for chunk in chunks})
            matching = [chunk for chunk in chunks if chunk['ordinal']==citation['ordinal']
                and chunk.get('page')==citation.get('page')]
            self.assertTrue(matching,citation)
            self.assertTrue(citation['quote'].strip())
            self.assertTrue(any(citation['quote'] in chunk['text'] for chunk in matching),citation)
            self.assertIn(citation['quote'],doc['content'])

    def test_no_keyword_hit_calls_each_selected_provider_exactly_once(self):
        body = self.body()
        self.assertEqual(retrieve(body['question'],[self.docs['personal']]),[])
        providers = [('dsh','gpt-6-sol'),('deepseek','deepseek-v4-pro'),
            ('local-models','glm-5.2'),('model','synthetic-configured-model')]
        for mode,model in providers:
            with self.subTest(mode=mode):
                self.model.reset_mock()
                self.app.dsh_answer = Mock(return_value='这里只能作简短草稿解释，事实仍需核实。[S1]')
                self.app.ai = {'base_url':'https://synthetic-provider.invalid/v1',
                    'model':'synthetic-configured-model','api_key':''}
                status,result = self.request('POST','/api/ask',{**body,'mode':mode,'model_id':model})
                self.assertEqual(status,200,result)
                self.assertIs(result['model_called'],True)
                self.assertEqual(result['retrieval_basis'],'selected_excerpt')
                self.assertIn('草稿' if mode=='dsh' else '经营主体',result['answer'])
                self.assertTrue(result['model'])
                self.assertTrue(result['citations'])
                if mode=='dsh':
                    self.app.dsh_answer.assert_called_once()
                    self.assertEqual(self.app.dsh_answer.call_args.args[1],model)
                    prompt = self.app.dsh_answer.call_args.args[0]
                    self.model.assert_not_called()
                else:
                    self.model.assert_called_once()
                    self.assertEqual(self.model.call_args.args[1],model)
                    prompt = '\n'.join(self.model.call_args.args[2:4])
                    self.app.dsh_answer.assert_not_called()
                self.assertIn(body['question'],prompt)
                self.assertIn(self.docs['personal']['content'],prompt)

    def test_empty_selected_material_calls_model_without_fake_citations(self):
        empty = self.source('Synthetic empty source','')
        self.model.side_effect = lambda *args,**kwargs:('选中的材料暂无可提取文字，无法判断该公司的情况。请补充原文。',args[1])
        status,result = self.request('POST','/api/ask',self.body(document_ids=[empty['id']]))
        self.assertEqual(status,200,result)
        self.assertEqual(result['retrieval_basis'],'empty_context')
        self.assertIs(result['model_called'],True)
        self.assertEqual(result['citations'],[])
        self.assertIn('暂无可提取文字',result['answer'])
        self.model.assert_called_once()
        prompt = '\n'.join(self.model.call_args.args[2:4])
        self.assertNotRegex(prompt,r'\[S[1-9][0-9]*\]\s+Synthetic empty source')
        self.model.side_effect = lambda *args,**kwargs:('虚构引用。[S1]',args[1])
        status,result = self.request('POST','/api/ask',self.body(document_ids=[empty['id']]))
        self.assertEqual(status,400,result)
        self.assertIn('引用',result['error'])

    def test_explicit_local_miss_still_never_calls_model(self):
        status,result = self.request('POST','/api/ask',self.body(mode='local'))
        self.assertEqual(status,200,result)
        self.assertEqual(result['mode'],'local')
        self.assertIs(result['model_called'],False)
        self.assertEqual(result['citations'],[])
        self.model.assert_not_called()
        self.app.dsh_answer.assert_not_called()

    def test_empty_context_uses_selected_gpt_and_other_compatible_providers(self):
        empty = self.source('Synthetic blank material','')
        explanation = '所选材料没有可提取文字，无法对公司事实作出判断。'
        for mode,model in (('dsh','gpt-6-sol'),('local-models','glm-5.2'),
                           ('model','synthetic-configured-model')):
            with self.subTest(mode=mode):
                self.app.ai = {'base_url':'https://synthetic-provider.invalid/v1',
                    'model':'synthetic-configured-model','api_key':''}
                self.model.reset_mock()
                self.model.side_effect = lambda *args,**kwargs:(explanation,args[1])
                self.app.dsh_answer = Mock(return_value=explanation)
                status,result = self.request('POST','/api/ask',self.body(mode=mode,model_id=model,
                    document_ids=[empty['id']]))
                self.assertEqual(status,200,result)
                self.assertEqual(result['retrieval_basis'],'empty_context')
                self.assertEqual(result['citations'],[])
                self.assertIs(result['model_called'],True)
                self.assertEqual(result['answer'],explanation)
                if mode=='dsh':
                    self.app.dsh_answer.assert_called_once()
                    self.assertEqual(self.app.dsh_answer.call_args.args[1],model)
                    self.model.assert_not_called()
                else:
                    self.model.assert_called_once()
                    self.assertEqual(self.model.call_args.args[1],model)
                    self.app.dsh_answer.assert_not_called()

    def test_fallback_scope_and_real_page_ordinal_quote_identity(self):
        pages = [{'page':3,'text':'SYNTHETIC SELECTED ALPHA: route fees and fleet utilization.'},
                 {'page':9,'text':'SYNTHETIC SELECTED ALPHA: infrastructure capacity and per-trip costs.'}]
        selected = self.source('Synthetic selected source','\n\n'.join(page['text'] for page in pages),pages=pages,page_count=9)
        unselected = self.source('Synthetic unselected source','UNSELECTED PRIVATE MARKER DO NOT SEND')
        foreign_project = self.app.stores['personal'].create('projects',{'name':'Synthetic foreign project'})
        foreign = self.source('Synthetic foreign source','FOREIGN PROJECT MARKER DO NOT SEND',project_id=foreign_project['id'])
        memory = self.app.stores['personal'].create('documents',{'title':'Synthetic memory',
            'kind':'memory','content':'MEMORY PRIVATE MARKER DO NOT SEND'})
        before = copy.deepcopy(self.app.stores['personal'].backup('personal')['data'])
        body = self.body(document_ids=[selected['id'],selected['id']])
        self.assertEqual(retrieve(body['question'],[selected]),[])
        status,result = self.request('POST','/api/ask',body)
        self.assertEqual(status,200,result)
        self.assertEqual(result['retrieval_basis'],'selected_excerpt')
        self.assert_citations_are_real(result['citations'],[selected])
        self.assertTrue(all(cite['page'] in (3,9) for cite in result['citations']))
        prompt = '\n'.join(self.model.call_args.args[2:4])
        for marker in ('UNSELECTED PRIVATE MARKER','FOREIGN PROJECT MARKER','MEMORY PRIVATE MARKER'):
            self.assertNotIn(marker,prompt)
        self.assertEqual(self.app.stores['personal'].backup('personal')['data'],before)
        self.model.reset_mock()
        for ids,workspace in (([foreign['id']],'personal'),([memory['id']],'personal'),
                              ([selected['id'],memory['id']],'personal'),([selected['id']],'demo'),([], 'personal')):
            status,result = self.request('POST','/api/ask',{**body,'document_ids':ids},workspace=workspace)
            self.assertEqual(status,400,result)
        self.model.assert_not_called()

    def test_large_fallback_is_bounded_and_covers_late_selected_sources(self):
        documents = [self.source('Synthetic selected '+str(index),
            ('SOURCE-'+str(index)+' ROUTE NETWORK EFFICIENCY.\n')*170) for index in range(20)]
        body = self.body(document_ids=[doc['id'] for doc in documents])
        self.assertEqual(retrieve(body['question'],documents),[])
        status,result = self.request('POST','/api/ask',body)
        self.assertEqual(status,200,result)
        self.assertEqual(result['retrieval_basis'],'selected_excerpt')
        citations = result['citations']
        self.assertEqual({cite['document_id'] for cite in citations},{doc['id'] for doc in documents})
        self.assertLessEqual(sum(len(cite['quote']) for cite in citations),24000)
        self.assert_citations_are_real(citations,documents)
        prompt = self.model.call_args.args[3]
        self.assertIn('SOURCE-19',prompt)

    def test_brief_prompt_distinguishes_general_explanation_from_missing_company_facts(self):
        source = self.source('Synthetic financial excerpt','公司营业收入为100百万元，费用为40百万元。')
        body = self.body(question='经营现金净流入应该怎么看？',document_ids=[source['id']])
        self.assertEqual(retrieve(body['question'],[source]),[])
        self.model.side_effect = lambda *args,**kwargs:('一般而言，需要核对现金收支和营运资本。所选节选未提供经营现金净流入，无法判断该公司金额。[S1]',args[1])
        status,result = self.request('POST','/api/ask',body)
        self.assertEqual(status,200,result)
        prompt = '\n'.join(self.model.call_args.args[2:4])
        self.assertRegex(prompt,r'2.{0,12}4|3.{0,10}(点|条)')
        self.assertRegex(prompt,r'通用|一般|常识')
        self.assertRegex(prompt,r'未提供|未知|无法|不支持')
        self.assertNotIn('100百万元',result['answer'])
        self.assertEqual(result['retrieval_basis'],'selected_excerpt')

    def test_keyword_hit_keeps_existing_retrieval_and_model_calls(self):
        source = self.source('Synthetic financial source','公司营业收入为100百万元，费用为40百万元。')
        body = self.body(question='营业收入是多少？',document_ids=[source['id']])
        self.assertTrue(retrieve(body['question'],[source]))
        status,result = self.request('POST','/api/ask',body)
        self.assertEqual(status,200,result)
        self.assertEqual(result['retrieval_basis'],'keyword_match')
        self.assertIs(result['model_called'],True)
        self.model.assert_called_once()
        self.assert_citations_are_real(result['citations'],[source])

    def test_no_hit_validates_model_choice_configuration_and_csrf_before_provider(self):
        for mode,model in (('dsh','arbitrary'),('deepseek','arbitrary'),
                           ('local-models','deepseek-v4-pro'),('model','unused')):
            status,result = self.request('POST','/api/ask',self.body(mode=mode,model_id=model))
            self.assertEqual(status,400,result)
        status,result = self.request('POST','/api/ask',self.body(),csrf=False)
        self.assertEqual(status,403,result)
        self.model.assert_not_called()
        self.app.dsh_answer.assert_not_called()

    def test_invalid_fallback_reference_is_rejected_without_saving(self):
        before = copy.deepcopy(self.app.stores['personal'].backup('personal')['data'])
        for label in ('[S999]','[S0]'):
            self.model.side_effect = lambda *args,**kwargs:('虚构来源'+label,args[1])
            status,result = self.request('POST','/api/ask',self.body())
            self.assertEqual(status,400,result)
            self.assertIn('引用',result['error'])
        self.assertEqual(self.app.stores['personal'].backup('personal')['data'],before)

    def test_accepted_question_length_does_not_fail_a_shorter_retrieval_limit(self):
        question = 'Please explain this source briefly. '+('?'*3300)
        self.assertGreater(len(question),3000)
        self.assertLess(len(question),4000)
        status,result = self.request('POST','/api/ask',self.body(question=question))
        self.assertEqual(status,200,result)
        self.assertIs(result['model_called'],True)
        self.model.assert_called_once()
        self.assertIn(question,self.model.call_args.args[3])

    def test_cancelled_fallback_discards_late_model_answer_and_never_saves(self):
        entered,release = threading.Event(),threading.Event()
        self.releases.append(release)
        def answer(*args,**kwargs):
            entered.set()
            if not release.wait(3):raise RuntimeError('Synthetic fallback provider barrier timeout')
            return 'LATE SYNTHETIC FALLBACK ANSWER [S1]',args[1]
        self.model.side_effect = answer
        results = []
        before = copy.deepcopy(self.app.stores['personal'].backup('personal')['data'])
        worker = threading.Thread(target=lambda:results.append(self.request('POST','/api/ask',self.body(),
            headers={'X-WorkOS-Request-ID':'synthetic-fallback-stop'})))
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            status,stopped = self.request('POST','/api/operations/synthetic-fallback-stop/cancel',{})
            self.assertEqual(status,200,stopped)
            self.assertEqual(stopped['status'],'cancelled')
        finally:release.set();worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0][0],409,results)
        self.assertEqual(results[0][1]['code'],'request_cancelled')
        self.assertNotIn('LATE SYNTHETIC FALLBACK ANSWER',json.dumps(results[0][1]))
        self.model.assert_called_once()
        self.assertEqual(self.app.stores['personal'].backup('personal')['data'],before)


if __name__=='__main__':unittest.main()
