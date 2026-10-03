"""Automatic project organization uses only disposable local fixtures."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workos.organization import ORGANIZATION_FIELDS, version_identity
from workos.store import COLLECTIONS, Store


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'organization.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: self.store.close())
        self.project = self.store.create('projects', {'name': '合成项目'})

    def doc(self, title, **fields):
        return self.store.create('documents', {'title': title, 'project_id': self.project['id'], **fields})

    def test_english_and_chinese_versions_share_stable_project_family(self):
        examples = (
            ('Atlas IC Memo v1.docx', 'Atlas IC Memo v2 revised 2026-09-30.pdf', 'Atlas IC Memo FINAL.pptx'),
            ('合成项目投委Memo第一版.docx', '合成项目投委Memo第二版.pdf', '合成项目投委Memo_最终稿_2026年9月30日.docx', '合成项目投委Memo_修订.docx'),
            ('Atlas-SPA-v1.docx', 'Atlas-SPA-revA.docx', 'Atlas-SPA-signed_20260930.pdf'),
        )
        for filenames in examples:
            with self.subTest(filenames=filenames):
                documents = [self.doc('导入资料', filename=name) for name in filenames]
                self.assertEqual(len({doc['version_family'] for doc in documents}), 1)
                self.assertEqual(len({doc['task_group'] for doc in documents}), 1)
                self.assertTrue(all(doc['version_label'] != '原始版本' for doc in documents))
                self.assertEqual([doc['filename'] for doc in documents], list(filenames))
        first = self.doc('Atlas IC Memo v1')
        another = self.store.create('projects', {'name': '另一项目'})
        second = self.store.create('documents', {'title': 'Atlas IC Memo v2', 'project_id': another['id']})
        self.assertNotEqual(first['version_family'], second['version_family'])
        self.assertNotEqual(version_identity({'title': 'Final assembly report v1', 'project_id': 'p'})[0],
                            version_identity({'title': 'assembly report v2', 'project_id': 'p'})[0])

    def test_content_classifies_unnamed_material_without_changing_sources(self):
        fixtures = [('条款约定：双方签署本协议。', '交易协议'),
                    ('本投资备忘录供投委会讨论。', '投委会材料'),
                    ('专家访谈记录，包括专家对竞争格局的观点。', '专家访谈'),
                    ('valuation and DCF financial model', '财务与估值'),
                    ('行业研究及市场研究的证据整理。', '基本面研究')]
        for content, expected in fixtures:
            with self.subTest(expected=expected):
                source = {'content': content, 'category': '自定义来源类型', 'hash': 'original-hash',
                          'chunks': [{'text': content, 'page': 1}], 'attachment_ref': 'original.docx'}
                doc = self.doc('文件 001', **source)
                self.assertEqual(doc['task_group'], expected)
                for field, value in source.items():
                    self.assertEqual(doc[field], value)
        # Strong filename evidence wins over incidental references in a memo.
        doc = self.doc('Atlas IC Memo v2', content='估值、财务模型、DCF、财务预测和财务分析。')
        self.assertEqual(doc['task_group'], '投委会材料')

    def test_memory_and_projectless_material_are_excluded(self):
        memory = self.doc('专家访谈 Memo v1', kind='memory', content='协议 财务模型')
        inbox = self.store.create('documents', {'title': 'Memo v1', 'content': '投委会材料'})
        for item in (memory, inbox):
            for field in ORGANIZATION_FIELDS - {'task_group_source'}:
                self.assertEqual(item[field], '')
        self.store.organize_project(self.project['id'])
        self.assertEqual(self.store.get('documents', memory['id'])['task_group'], '')
        with self.assertRaises(ValueError):
            self.store.create('tasks', {'title': '无项目子任务', 'task_group': '子任务'})

    def test_source_updates_reclassify_and_project_move_changes_family(self):
        doc = self.doc('Atlas Memo v1', content='原始文字')
        original = {key: doc[key] for key in ('id', 'created_at', 'hash', 'chunks')}
        changed = self.store.update('documents', doc['id'], {'title': 'Atlas NDA v2', 'content': '协议正文'})
        self.assertEqual(changed['task_group'], '交易协议')
        self.assertEqual(changed['version_label'], 'v2')
        self.assertNotEqual(changed['version_family'], doc['version_family'])
        other = self.store.create('projects', {'name': '另一合成项目'})
        moved = self.store.update('documents', doc['id'], {'project_id': other['id']})
        self.assertNotEqual(moved['version_family'], changed['version_family'])
        for field, value in original.items():
            self.assertEqual(moved[field], value)
        with self.assertRaises(ValueError):
            self.store.update('documents', doc['id'], {'project_id': 'missing'})
        self.assertEqual(self.store.get('documents', doc['id']), moved)

    def test_manual_override_persists_until_cleared_and_is_project_scoped(self):
        doc = self.doc('Atlas Memo v1', task_group='特殊投委会讨论')
        self.assertEqual(doc['task_group_source'], 'manual')
        changed = self.store.update('documents', doc['id'], {'title': 'Atlas SPA v2'})
        self.store.organize_project(self.project['id'])
        self.assertEqual(changed['task_group'], '特殊投委会讨论')
        self.assertEqual(self.store.get('documents', doc['id'])['task_group'], '特殊投委会讨论')
        automatic = self.store.update('documents', doc['id'], {'task_group': ''})
        self.assertEqual(automatic['task_group'], '交易协议')
        self.assertEqual(automatic['task_group_source'], 'automatic')
        self.store.update('documents', doc['id'], {'task_group': '特殊协议讨论'})
        other = self.store.create('projects', {'name': '另一合成项目'})
        moved = self.store.update('documents', doc['id'], {'project_id': other['id']})
        self.assertEqual(moved['task_group'], '交易协议')
        self.assertEqual(moved['task_group_source'], 'automatic')

    def test_named_project_subtasks_automatically_absorb_matching_material(self):
        before = self.doc('供应链复盘 Notes v1', content='供应链情况')
        task = self.store.create('tasks', {'title': '供应链复盘', 'task_group': '供应链复盘',
                                          'project_id': self.project['id']})
        self.assertEqual(task['task_group_source'], 'manual')
        self.assertEqual(self.store.get('documents', before['id'])['task_group'], '供应链复盘')
        after = self.doc('供应链复盘 Notes v2')
        self.assertEqual(after['task_group'], '供应链复盘')
        self.assertEqual(after['task_group_source'], 'automatic')
        unnamed = self.doc('导入 002', content='本文记录供应链复盘的核心结论和下一步行动。')
        self.assertEqual(unnamed['task_group'], '供应链复盘')
        other = self.store.create('projects', {'name': '另一合成项目'})
        separate = self.store.create('documents', {'title': '供应链复盘 Notes v1', 'project_id': other['id']})
        self.assertEqual(separate['task_group'], '项目资料')
        unrelated = self.doc('Atlas Memo v1')
        self.assertEqual(unrelated['task_group'], '投委会材料')
        self.store.delete('tasks', task['id'])
        self.assertEqual(self.store.get('documents', before['id'])['task_group'], '项目资料')

    def test_linked_notes_and_meeting_tasks_inherit_and_remain_valid(self):
        doc = self.doc('Atlas Memo v1')
        note = self.store.create('notes', {'title': '核心结论', 'project_id': self.project['id'], 'document_id': doc['id']})
        self.assertEqual(note['task_group'], '投委会材料')
        self.store.update('documents', doc['id'], {'title': 'Atlas 协议'})
        self.assertEqual(self.store.get('notes', note['id'])['task_group'], '交易协议')
        other = self.store.create('projects', {'name': '另一合成项目'})
        with self.assertRaises(ValueError):
            self.store.update('documents', doc['id'], {'project_id': other['id']})
        meeting = self.store.create('meetings', {'title': '专家访谈', 'project_id': self.project['id']})
        task = self.store.create('tasks', {'title': '跟进问题', 'project_id': self.project['id'], 'meeting_id': meeting['id']})
        self.assertEqual(task['task_group'], '专家访谈')

    def test_custom_subtasks_do_not_match_individual_shared_title_tokens(self):
        documents = [self.doc('Synthetic Alpha IC Memo v1'),
                     self.doc('Synthetic Alpha SPA v1'),
                     self.doc('Synthetic Alpha Commercial research',
                              content='Commercial forecasts from Synthetic Alpha management.'),
                     self.doc('Synthetic Alpha interview notes',
                              content='Synthetic experts discussed commercial contracts.')]
        original = {doc['id']: {field: doc[field] for field in
                               ('task_group', 'material_type', 'version_family', 'version_label')}
                    for doc in documents}
        self.store.create('tasks', {'title': 'Synthetic ESG diligence',
                                   'task_group': 'Synthetic ESG diligence', 'project_id': self.project['id']})
        self.store.create('tasks', {'title': 'Commercial DD', 'task_group': 'Commercial DD',
                                   'project_id': self.project['id']})
        self.store.organize_project(self.project['id'])
        for doc in documents:
            updated = self.store.get('documents', doc['id'])
            self.assertEqual({field: updated[field] for field in original[doc['id']]}, original[doc['id']])
        exact = self.doc('Synthetic_ESG-diligence IC Memo v1')
        self.assertEqual(exact['task_group'], 'Synthetic ESG diligence')
        self.assertEqual(exact['material_type'], 'Memo')
        body_match = self.doc('导入 003', content='The Commercial DD workstream covered customer retention.')
        self.assertEqual(body_match['task_group'], 'Commercial DD')

    def test_custom_subtask_can_match_distinct_full_task_title_phrase(self):
        self.store.create('tasks', {'title': 'Synthetic ESG diligence', 'task_group': '可持续性尽调',
                                   'project_id': self.project['id']})
        partial = self.doc('Synthetic Alpha Memo v1')
        exact = self.doc('Synthetic ESG diligence Memo v1')
        self.assertEqual(partial['task_group'], '投委会材料')
        self.assertEqual(exact['task_group'], '可持续性尽调')
        self.assertEqual(exact['material_type'], 'Memo')

    def test_old_backup_restore_and_restart_upgrade_preserve_originals(self):
        doc = self.doc('Atlas Memo v1', content='合成正文', chunks=[{'text': '合成正文'}], hash='hash-a')
        self.store.create('notes', {'title': 'Notes', 'body': '合成笔记', 'project_id': self.project['id']})
        backup = self.store.backup('personal')
        old_backup = copy.deepcopy(backup)
        for items in old_backup['data'].values():
            for item in items:
                for field in ORGANIZATION_FIELDS:
                    item.pop(field, None)
        self.assertEqual(set(old_backup['data']), set(COLLECTIONS))
        self.store.restore(old_backup, 'personal')
        restored = self.store.get('documents', doc['id'])
        self.assertEqual(restored['task_group'], '投委会材料')
        for field, value in old_backup['data']['documents'][0].items():
            self.assertEqual(restored[field], value)
        # Simulate an existing database predating the metadata migration.
        original = old_backup['data']['documents'][0]
        with self.store.db:
            self.store.db.execute('UPDATE records SET payload=? WHERE collection=? AND id=?',
                                  (json.dumps(original, ensure_ascii=False), 'documents', doc['id']))
        self.store.close()
        self.store = Store(self.path)
        upgraded = self.store.get('documents', doc['id'])
        self.assertEqual(upgraded, restored)
        self.assertEqual(self.store.organize_project(self.project['id'])['organized'], 0)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get('documents', doc['id']), upgraded)

    def test_metadata_validation_rejects_invalid_values_without_writing(self):
        before = self.store.backup('personal')['data']
        for fields in ({'task_group': 'x' * 101}, {'task_group': 'a\nb'}, {'task_group': []},
                       {'task_group_source': 'broken'}, {'version_family': 'foreign-project'},
                       {'organization_reason': ['not text']}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.doc('素材', **fields)
            self.assertEqual(self.store.backup('personal')['data'], before)


if __name__ == '__main__':
    unittest.main()
