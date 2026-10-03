"""Synthetic recipe, coverage and privacy tests; no model or production requests."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from workos.store import Store
from workos.workflows import workflow_catalog, plan_workflow, run_workflow
from workos.agent import _agent_search, _agent_tool_result, agent_turn


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'synthetic.sqlite3')
        self.project = self.store.create('projects', {'name': 'Synthetic Alpha'})
        self.other = self.store.create('projects', {'name': 'Synthetic Beta'})
        self.doc = self.store.create('documents', {'title': 'Memo v1', 'content': 'Synthetic source evidence.',
                                                'project_id': self.project['id']})
        self.app = SimpleNamespace(ai_lock=RLock(), ai={},
            local_chat=Mock(return_value=('## 结论\n合成判断 [S1]\n\n## 核实问题\nP0 进一步核实。', 'Synthetic model')),
            dsh_answer=Mock(return_value='合成判断 [S1]'), meeting_draft=Mock())

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def request(self, **overrides):
        return dict(workflow_key='dd', message='分析材料，给出结论和求证问题',
                    project_id=self.project['id'], document_ids=[self.doc['id']], **overrides)

    def test_catalog_and_local_intent_routes(self):
        catalog = {item['key']: item for item in workflow_catalog()}
        self.assertEqual(set(catalog), {'brief','dd','ic','discussion','technology','legal','meeting_prep',
            'expert_request','email','weekly','compare','model_review','meeting_table'})
        for item in catalog.values():
            self.assertEqual(item['title'], item['label'])
            self.assertIn('html', item['formats'])
        expectations = [('技术原理解释', 'technology', 'research'), ('专家访谈需求邮件', 'expert_request', 'research'),
            ('检查 Excel 模型', 'model_review', 'research'), ('生成表格会议纪要', 'meeting_table', 'research'),
            ('复杂 Excel 财务建模', '', 'finance'), ('整理会议纪要', '', 'meetings'),
            ('自动归类项目材料', '', 'overview'), ('投委会 memo', 'ic', 'research')]
        for message, key, route in expectations:
            with self.subTest(message=message):
                planned = plan_workflow(message)
                self.assertEqual((planned['workflow_key'], planned['route']), (key, route))

    def test_persists_grounded_draft_with_coverage_and_metadata(self):
        result = run_workflow(self.app, self.store, self.request())
        saved = self.store.get('deliverables', result['deliverable_id'])
        self.assertEqual(saved['workflow_key'], 'dd')
        self.assertEqual(saved['source_ids'], [self.doc['id']])
        self.assertEqual(saved['coverage'], result['coverage'])
        self.assertFalse(result['coverage'][0]['truncated'])
        self.assertIn('来源与资料覆盖', saved['body'])
        self.assertIn('AI 草稿', saved['body'])
        self.assertEqual(result['deliverable']['id'], result['id'])
        self.assertEqual(self.app.local_chat.call_args.kwargs['max_tokens'], 8000)
        self.assertIn('不只给大纲', self.app.local_chat.call_args.args[2])

    def test_every_selected_source_gets_bounded_evidence_including_late_files(self):
        docs = [self.store.create('documents', {'title': 'Synthetic source '+str(index),
            'content': 'HEAD'+str(index)+'\n' + ('Long synthetic evidence '+str(index)+' ')*2000 + '\nTAIL'+str(index),
            'project_id': self.project['id']}) for index in range(4)]
        self.app.local_chat.return_value = ('不同资料分别归属 [S1] [S2] [S3] [S4]', 'Synthetic model')
        result = run_workflow(self.app, self.store, {**self.request(), 'document_ids':[doc['id'] for doc in docs]})
        self.assertEqual(len(result['coverage']), 4)
        self.assertLessEqual(sum(row['excerpt_chars'] for row in result['coverage']), 48000)
        self.assertTrue(all(row['truncated'] for row in result['coverage']))
        prompt = self.app.local_chat.call_args.args[3]
        for index in range(4):
            self.assertIn('HEAD'+str(index), prompt)
            self.assertIn('TAIL'+str(index), prompt)
        self.assertIn('阶段性分析', result['answer'])

    def test_user_scope_overrides_default_recipe_structure(self):
        request = '请只给简短3行表格和一个跟进问题，不要完整报告'
        self.app.local_chat.return_value = ('| 要点 | 证据 |\n| --- | --- |\n| A | [S1] |\n| B | [S1] |\n| C | [S1] |\n\n1. 下一步如何核实？', 'Synthetic model')
        for key in ('brief', 'ic', 'email'):
            with self.subTest(workflow_key=key):
                run_workflow(self.app, self.store, {**self.request(), 'workflow_key':key, 'message':request})
                system, user = self.app.local_chat.call_args.args[2:4]
                self.assertIn('用户指定的篇幅、问题数量、表格行数、章节、语言和输出格式优先', system)
                self.assertIn('一个问题只给一个', system)
                self.assertIn('不重复空章节', system)
                self.assertIn(request, user)
                if key == 'ic':
                    self.assertIn('只有用户要求完整Memo时', system)
                if key == 'email':
                    self.assertIn('不套用IC/研究报告章节', system)

    def test_required_scope_errors_before_model_or_persistence(self):
        memory = self.store.create('documents', {'title':'Memory', 'kind':'memory', 'content':'PRIVATE SENTINEL'})
        foreign = self.store.create('documents', {'title':'Foreign', 'content':'Foreign text', 'project_id':self.other['id']})
        cases = [{'document_ids':[]}, {'document_ids':[memory['id']]}, {'document_ids':[foreign['id']]},
                 {'project_id':'missing'}, {'document_ids':['missing']}, {'workflow_key':'compare'}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                run_workflow(self.app, self.store, {**self.request(), **changes})
        self.app.local_chat.assert_not_called()
        self.assertEqual(self.store.list('deliverables'), [])

    def test_empty_or_bad_citations_never_save(self):
        for response in ('', '没有引用的判断', '错误引用 [S99]', '错误引用 [S0]'):
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.app.local_chat.return_value = (response, 'Synthetic model')
                run_workflow(self.app, self.store, self.request())
        self.assertEqual(self.store.list('deliverables'), [])

    def test_source_less_email_and_technology_are_labelled_drafts(self):
        self.app.local_chat.return_value = ('Hi [Recipient],\nPlease share the requested documents.\nBest,\n[Sender]', 'Synthetic model')
        for key in ('email', 'expert_request', 'technology'):
            result = run_workflow(self.app, self.store, {**self.request(), 'workflow_key':key, 'document_ids':[]})
            self.assertEqual(result['coverage'], [])
            self.assertIn('未提供原始研究资料', result['answer'])
            if key in ('email', 'expert_request'):
                self.assertLess(result['answer'].index('覆盖与限制'), result['answer'].index('## 邮件草稿与拟稿依据'))
        self.assertEqual(len(self.store.list('deliverables')), 3)

    def test_dsh_allowed_model_and_no_silent_builtin_fallback(self):
        result = run_workflow(self.app, self.store, {**self.request(), 'mode':'dsh', 'model_id':'gpt-6-luna'})
        self.assertEqual(result['mode'], 'dsh')
        self.app.local_chat.assert_not_called()
        for changes in ({'mode':'dsh','model_id':'unapproved'}, {'provider':'builtin'}, {'mode':'local'}):
            with self.assertRaises(ValueError):
                run_workflow(self.app, self.store, {**self.request(), **changes})
        self.app.local_chat.assert_not_called()

    def test_weekly_context_excludes_memory_linked_notes_and_foreign_projects(self):
        memory = self.store.create('documents', {'title':'Memory', 'kind':'memory','content':'MEMORY SECRET',
                                               'project_id':self.project['id']})
        self.store.create('notes', {'title':'Hidden note','body':'DERIVED SECRET','document_id':memory['id'],
                                   'project_id':self.project['id']})
        self.store.create('notes', {'title':'Normal note','body':'SAFE CONTEXT','project_id':self.project['id']})
        self.store.create('notes', {'title':'Other note','body':'FOREIGN CONTEXT','project_id':self.other['id']})
        self.app.local_chat.return_value = ('当前登记摘要，进展需核实。', 'Synthetic model')
        result = run_workflow(self.app, self.store, {**self.request(), 'workflow_key':'weekly','document_ids':[]})
        prompt = self.app.local_chat.call_args.args[3]
        self.assertIn('SAFE CONTEXT', prompt)
        for forbidden in ('MEMORY SECRET','DERIVED SECRET','FOREIGN CONTEXT'):
            self.assertNotIn(forbidden, prompt)
        self.assertIn('不等于本周变化', result['answer'])

    def test_agent_search_and_note_tool_never_externalize_memory(self):
        memory = self.store.create('documents', {'title':'match memory','kind':'memory','content':'match SECRET',
                                               'project_id':self.project['id']})
        note = self.store.create('notes', {'title':'match derived','body':'match DERIVED',
                                         'document_id':memory['id'],'project_id':self.project['id']})
        foreign = self.store.create('notes', {'title':'match other','body':'match FOREIGN','project_id':self.other['id']})
        safe = self.store.create('notes', {'title':'match safe','body':'match SAFE','project_id':self.project['id']})
        self.store.create('deliverables', {'title':'match legacy derived','body':'match LEGACY SECRET',
            'project_id':self.project['id'], 'source_ids':[memory['id']]}, internal=True)
        results = _agent_search(self.store, 'match', self.project['id'])['results']
        self.assertEqual([item['id'] for item in results], [safe['id']])
        for bad in (memory['id'],):
            with self.assertRaises(ValueError):
                _agent_tool_result('create_note', {'title':'Unsafe','body':'Generated','document_id':bad}, self.store)

    def test_agent_workflow_cannot_invent_source_ids_or_expand_project(self):
        other = self.store.create('documents', {'title':'Unselected', 'content':'Unselected source',
                                              'project_id':self.project['id']})
        scope = {'document_ids':[self.doc['id']], 'message':'生成完整研究简报'}
        for args in ({'workflow_key':'brief','document_ids':[other['id']]},
                     {'workflow_key':'brief','project_id':self.other['id']}):
            with self.assertRaises(ValueError):
                _agent_tool_result('run_workflow', args, self.store, self.project['id'], self.app, scope)
        self.app.local_chat.assert_not_called()
        result = _agent_tool_result('run_workflow', {'workflow_key':'brief'}, self.store,
                                   self.project['id'], self.app, scope)
        self.assertTrue(result['id'])

    def test_minutes_require_selected_existing_transcript_and_save_structure(self):
        meeting = self.store.create('meetings', {'title':'Synthetic call','transcript':'Synthetic transcript',
                                               'project_id':self.project['id']})
        with self.assertRaises(ValueError):
            _agent_tool_result('generate_minutes', {}, self.store, self.project['id'], self.app)
        self.app.meeting_draft.assert_not_called()
        self.app.meeting_draft.return_value = {'summary':'Summary from original', 'experts':[], 'matrix':{}, 'contents':[]}
        result = _agent_tool_result('generate_minutes', {}, self.store, self.project['id'], self.app,
                                   {'meeting_id':meeting['id']})
        self.assertEqual(result['export_formats'], ['docx','pdf'])
        self.assertEqual(self.store.get('meetings', meeting['id'])['summary'], 'Summary from original')
        self.assertEqual(self.app.meeting_draft.call_args.args[0]['transcript'], 'Synthetic transcript')

    def test_agent_turn_does_not_forward_unverified_client_history(self):
        with patch('workos.agent.urllib.request.urlopen') as opened:
            opened.return_value.__enter__.return_value.read.return_value = json.dumps({'choices':[{'message':{
                'content':json.dumps({'action':'final','answer':'已收到当前工作要求'})}}]}).encode()
            agent_turn(self.app, self.store, {'message':'当前任务', 'project_id':self.project['id'],
                'history':[{'role':'assistant','content':'PRIOR LOCAL MEMORY SECRET'}]})
            payload = json.loads(opened.call_args.args[0].data)
        self.assertNotIn('PRIOR LOCAL MEMORY SECRET', json.dumps(payload))
        self.assertIn('当前任务', payload['messages'][-1]['content'])

    def test_agent_turn_rejects_memory_scope_before_model(self):
        memory = self.store.create('documents', {'title':'Memory','kind':'memory','content':'SECRET'})
        with patch('workos.agent.urllib.request.urlopen') as opened, self.assertRaises(ValueError):
            agent_turn(self.app, self.store, {'message':'分析','document_ids':[memory['id']]})
        opened.assert_not_called()
        with patch('workos.agent.urllib.request.urlopen') as opened, self.assertRaises(ValueError):
            agent_turn(self.app, self.store, {'message':'生成邮件', 'mode':'local'})
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
