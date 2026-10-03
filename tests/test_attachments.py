import hashlib
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from workos.attachments import original_path, read_original, save_original
from workos.store import Store
from workos.sync import OneDriveMirror


class OriginalTests(unittest.TestCase):
    def test_original_survives_text_edits_and_duplicate_uploads(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            raw = '合成 Memo v1\r\n原文'.encode('utf-8')
            fields = save_original(base, 'personal', raw, 'Memo_v1.txt')
            self.assertEqual(fields, save_original(base, 'personal', raw, 'Memo_v1.txt'))
            record = {'kind': 'research', 'content': '提取文字已经修改', **fields}
            self.assertEqual(read_original(base, 'personal', record), raw)
            self.assertEqual(len(list((base / 'originals' / 'personal').iterdir())), 1)
            with self.assertRaises(KeyError):
                read_original(base, 'demo', record)
            with self.assertRaises(KeyError):
                read_original(base, 'personal', {**record, 'kind': 'memory'})

    def test_path_and_integrity_checks(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            fields = save_original(base, 'personal', b'synthetic', '../contract.txt')
            self.assertEqual(fields['attachment_name'], 'contract.txt')
            for digest in ('../outside', 'x' * 64, 'A' * 64, None):
                with self.assertRaises(ValueError):
                    original_path(base, 'personal', digest)
            with self.assertRaises(ValueError):
                original_path(base, '../demo', fields['attachment_ref'])
            original_path(base, 'personal', fields['attachment_ref']).write_bytes(b'tampered')
            with self.assertRaises(ValueError):
                read_original(base, 'personal', {'kind': 'research', **fields})

    def test_mirror_and_empty_host_restore_preserve_originals(self):
        with TemporaryDirectory() as tmp, ExitStack() as resources:
            base = Path(tmp)
            source = Store(base / 'source' / 'personal.sqlite3')
            target = Store(base / 'target' / 'personal.sqlite3')
            resources.callback(source.close)
            resources.callback(target.close)
            project = source.create('projects', {'name': '合成项目'})
            raw = b'Synthetic IC memo v2'
            fields = save_original(source.path.parent, 'personal', raw, 'IC_memo_v2.txt')
            doc = source.create('documents', {'title': 'IC_memo_v2', 'filename': 'IC_memo_v2.txt',
                'content': raw.decode(), 'project_id': project['id'], 'hash': hashlib.sha256(raw).hexdigest(), **fields})
            mirror = OneDriveMirror(base / 'mirror')
            mirror.sync(source, 'personal')
            self.assertEqual(read_original(mirror.root, 'personal', doc), raw)
            self.assertTrue(mirror.restore_if_empty(target, 'personal'))
            restored = target.get('documents', doc['id'])
            self.assertEqual(read_original(target.path.parent, 'personal', restored), raw)
            self.assertEqual(restored['task_group'], doc['task_group'])
            self.assertTrue(list((mirror.root / 'Projects').glob('*/organization.md')))

    def test_missing_mirror_original_is_retried_after_snapshot_restore(self):
        with TemporaryDirectory() as tmp, ExitStack() as resources:
            base = Path(tmp)
            source = Store(base / 'source' / 'personal.sqlite3')
            target = Store(base / 'target' / 'personal.sqlite3')
            resources.callback(source.close)
            resources.callback(target.close)
            raw = b'Synthetic delayed OneDrive original'
            fields = save_original(source.path.parent, 'personal', raw, 'Memo.txt')
            doc = source.create('documents', {'title': 'Memo', **fields})
            mirror = OneDriveMirror(base / 'mirror')
            mirror.sync(source, 'personal')
            original_path(mirror.root, 'personal', fields['attachment_ref']).unlink()
            self.assertTrue(mirror.restore_if_empty(target, 'personal'))
            self.assertEqual(mirror.status()['missing_originals'], 1)
            save_original(mirror.root, 'personal', raw, 'Memo.txt')
            mirror.sync(target, 'personal')
            self.assertEqual(mirror.status()['missing_originals'], 0)
            self.assertEqual(read_original(target.path.parent, 'personal', doc), raw)

    def test_normal_sync_skips_unchanged_and_duplicate_originals(self):
        with TemporaryDirectory() as tmp, ExitStack() as resources:
            base = Path(tmp)
            store = Store(base / 'local' / 'personal.sqlite3')
            resources.callback(store.close)
            raw = b'Synthetic shared immutable original'
            fields = save_original(store.path.parent, 'personal', raw, 'memo.txt')
            for title in ('Memo v1', 'Memo v1 copy'):
                store.create('documents', {'title': title, **fields})
            mirror = OneDriveMirror(base / 'mirror')
            with patch('workos.attachments.read_original', wraps=read_original) as read:
                mirror.sync(store, 'personal')
                self.assertEqual(read.call_count, 1)
                read.reset_mock()
                store.create('notes', {'title': 'Small edit', 'body': 'Synthetic'})
                mirror.sync(store, 'personal')
                self.assertEqual(read.call_count, 0)
                original_path(mirror.root, 'personal', fields['attachment_ref']).write_bytes(b'tampered')
                mirror.sync(store, 'personal')
                self.assertEqual(read.call_count, 1)
                self.assertEqual(read_original(mirror.root, 'personal', {'kind': 'research', **fields}), raw)


if __name__ == '__main__':
    unittest.main()
