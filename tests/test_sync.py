import json
import tempfile
import unittest
from pathlib import Path
from workos.store import Store
from workos.sync import OneDriveMirror


class OneDriveMirrorTests(unittest.TestCase):
    def test_writes_project_files_and_rebuildable_snapshot_without_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            local = base / 'device-a' / 'personal.sqlite3'
            root = base / 'OneDrive' / 'AI Agent' / 'Local WorkOS'
            store = Store(local)
            project = store.create('projects', {'name': '合成项目'})
            doc = store.create('documents', {'title': '讨论材料', 'project_id': project['id'], 'content': '仅用于同步测试。', 'source_ref': 'source/summary.md'})
            mirror = OneDriveMirror(root)
            status = mirror.sync(store, 'personal')
            self.assertTrue(status['enabled'])
            self.assertEqual(status['workspaces']['personal']['counts']['projects'], 1)
            snapshot = json.loads((root / 'Sync' / 'workspace-personal.json').read_text(encoding='utf-8'))
            self.assertEqual(snapshot['data']['projects'][0]['id'], project['id'])
            project_dir = root / 'Projects' / (project['id'] + '_合成项目')
            self.assertTrue((project_dir / 'project.json').is_file())
            md = next((project_dir / 'Sources').glob('*.md'))
            self.assertIn('仅用于同步测试', md.read_text(encoding='utf-8'))
            md.write_text('本机手动改动，需保留。', encoding='utf-8')
            mirror.sync(store, 'personal')
            conflicts = list((project_dir / 'Sources').glob('*.previous-*.md'))
            self.assertEqual(len(conflicts), 1)
            self.assertIn('本机手动改动', conflicts[0].read_text(encoding='utf-8'))
            self.assertIn('仅用于同步测试', md.read_text(encoding='utf-8'))
            self.assertFalse(list(root.rglob('*.sqlite3')))
            self.assertTrue((root / 'manifest.json').is_file())
            store.close()

    def test_empty_device_restores_snapshot_but_existing_database_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'cloud'; source = Store(base / 'source.sqlite3')
            project = source.create('projects', {'name': '合成公司'})
            OneDriveMirror(root).sync(source, 'personal')
            target = Store(base / 'target.sqlite3')
            self.assertTrue(OneDriveMirror(root).restore_if_empty(target, 'personal'))
            self.assertEqual(target.list('projects')[0]['id'], project['id'])
            keep = target.create('projects', {'name': '本机记录'})
            self.assertFalse(OneDriveMirror(root).restore_if_empty(target, 'personal'))
            self.assertIn(keep['id'], {item['id'] for item in target.list('projects')})
            self.assertEqual(len(target.list('projects')), 2)
            source.close(); target.close()

    def test_disabled_mirror_is_a_safe_noop(self):
        mirror = OneDriveMirror(None)
        self.assertFalse(mirror.status()['enabled'])
        self.assertFalse(mirror.status()['active_sqlite_in_onedrive'])


if __name__ == '__main__':
    unittest.main()
