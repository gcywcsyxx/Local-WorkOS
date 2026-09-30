"""Persistence/restore regressions; all databases are disposable fixtures."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from workos.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'personal.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: self.store.close())

    def test_crud_persists_after_reopen(self):
        project = self.store.create('projects', {'name': '合成公司'})
        task = self.store.create('tasks', {'title': '合成任务', 'project_id': project['id']})
        self.store.update('tasks', task['id'], {'status': '完成'})
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.get('tasks', task['id'])['status'], '完成')
        self.store.delete('tasks', task['id'])
        self.store.delete('projects', project['id'])
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.list('projects'), [])
        self.assertEqual(self.store.list('tasks'), [])

    def test_all_collection_roundtrips(self):
        for col in ('projects', 'tasks', 'documents', 'meetings', 'notes', 'deliverables'):
            with self.subTest(collection=col):
                field = 'name' if col == 'projects' else 'title'
                obj = self.store.create(col, {field: '初始'})
                self.assertEqual(self.store.get(col, obj['id'])[field], '初始')
                self.assertEqual(self.store.update(col, obj['id'], {field: '已改'})[field], '已改')
                self.assertEqual(self.store.delete(col, obj['id']), {'deleted': True})
                with self.assertRaises(KeyError):
                    self.store.get(col, obj['id'])

    def test_linked_deletion_is_rejected_not_cascaded(self):
        project = self.store.create('projects', {'name': '合成项目'})
        doc = self.store.create('documents', {'title': '证据', 'project_id': project['id']})
        meeting = self.store.create('meetings', {'title': '会议', 'project_id': project['id']})
        note = self.store.create('notes', {'title': '结论', 'document_id': doc['id']})
        task = self.store.create('tasks', {'title': '行动', 'meeting_id': meeting['id']})
        for col, obj in [('projects', project), ('documents', doc), ('meetings', meeting)]:
            with self.subTest(collection=col), self.assertRaises(ValueError):
                self.store.delete(col, obj['id'])
            self.assertEqual(self.store.get(col, obj['id']), obj)
        self.store.delete('notes', note['id'])
        self.store.delete('tasks', task['id'])
        self.store.delete('documents', doc['id'])
        self.store.delete('meetings', meeting['id'])
        self.store.delete('projects', project['id'])

    def test_bad_fields_and_associations_leave_database_unchanged(self):
        before = self.store.backup('personal')['data']
        fixtures = [('projects', {'name': ''}), ('tasks', {'title': 'x', 'project_id': 'missing'}),
                    ('tasks', {'title': 'x', 'status': 'invalid'}), ('tasks', {'title': 'x', 'due': '2025-02-30'}),
                    ('projects', {'name': 'x', 'unknown': 'field'}), ('documents', {'title': 'x', 'private': 'yes'})]
        for col, fields in fixtures:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.create(col, fields)
            self.assertEqual(before, self.store.backup('personal')['data'])

    def test_document_summary_does_not_expose_content(self):
        doc = self.store.create('documents', {'title': 'fixture', 'content': '合成正文', 'chunks': [{'text': '合成正文'}]})
        self.assertNotIn('content', self.store.state()['documents'][0])
        self.assertNotIn('chunks', self.store.state()['documents'][0])
        self.assertEqual(self.store.get('documents', doc['id'])['content'], '合成正文')

    def test_restore_roundtrip_and_previous_database_copy(self):
        project = self.store.create('projects', {'name': '备份时'})
        backup = self.store.backup('personal')
        self.store.update('projects', project['id'], {'name': '恢复前'})
        result = self.store.restore(backup, 'personal')
        self.assertTrue(result['restored'])
        self.assertEqual(self.store.backup('personal')['data'], backup['data'])
        old = Store(Path(result['previous_backup']))
        try:
            self.assertEqual(old.get('projects', project['id'])['name'], '恢复前')
        finally:
            old.close()

    def test_invalid_backups_do_not_modify_original(self):
        self.store.create('projects', {'name': '保留'})
        good = self.store.backup('personal')
        cases = [None, {}, {**good, 'workspace': 'demo'}, {**good, 'version': 999}]
        missing = copy.deepcopy(good)
        del missing['data']['tasks']
        cases.append(missing)
        duplicate = copy.deepcopy(good)
        duplicate['data']['projects'] *= 2
        cases.append(duplicate)
        dangling = copy.deepcopy(good)
        task = self.store.create('tasks', {'title': '临时'})
        self.store.delete('tasks', task['id'])
        task['project_id'] = 'missing'
        dangling['data']['tasks'] = [task]
        cases.append(dangling)
        before = self.store.backup('personal')['data']
        for bad in cases:
            with self.subTest(backup=bad), self.assertRaises(ValueError):
                self.store.restore(bad, 'personal')
            self.assertEqual(self.store.backup('personal')['data'], before)

    def test_workspace_databases_do_not_share_records(self):
        other = Store(Path(self.tmp.name) / 'demo.sqlite3')
        try:
            project = self.store.create('projects', {'name': '个人合成'})
            self.assertEqual(other.list('projects'), [])
            with self.assertRaises(ValueError):
                other.create('tasks', {'title': '跨区关联', 'project_id': project['id']})
            with self.assertRaises(ValueError):
                other.restore(self.store.backup('personal'), 'demo')
        finally:
            other.close()

    def test_cross_project_links_rejected_on_create_and_restore(self):
        a = self.store.create('projects', {'name': 'A'})
        b = self.store.create('projects', {'name': 'B'})
        doc = self.store.create('documents', {'title': 'A资料', 'project_id': a['id']})
        with self.assertRaises(ValueError):
            self.store.create('notes', {'title': 'B结论', 'project_id': b['id'], 'document_id': doc['id']})
        note = self.store.create('notes', {'title': 'A结论', 'project_id': a['id'], 'document_id': doc['id']})
        backup = self.store.backup('personal')
        backup['data']['notes'][0]['project_id'] = b['id']
        before = self.store.backup('personal')['data']
        with self.assertRaises(ValueError):
            self.store.restore(backup, 'personal')
        self.assertEqual(self.store.backup('personal')['data'], before)


if __name__ == '__main__':
    unittest.main()
