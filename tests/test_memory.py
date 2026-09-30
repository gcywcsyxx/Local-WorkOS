"""Only synthetic files under TemporaryDirectory are scanned or imported."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import stat
from types import SimpleNamespace
from unittest.mock import patch

from workos import memory
from workos.store import Store


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'fixture.sqlite3')
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)

    def fixture(self, relative, text='合成记忆，偏好简洁且标注来源。'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_scan_allowlist_and_excluded_directories_without_contents(self):
        allowed = ['profile.md', 'methods/method.md', 'daily/session.md', 'other/notes.MD']
        excluded = ['.hidden.md', 'archive/old.md', 'secrets/key.md', 'credentials/key.md',
                    'node_modules/note.md', '.env/config.md', '.git/config.md',
                    'notes/password.md', '知识库/memory/_凭据_敏感勿外发/key.md',
                    '知识库/memory/99-原始归档/old.md', '知识库/ai-knowhow/.git/config.md',
                    '知识库/memory/corpus/source.md', '知识库/memory/_历史版本/old.md',
                    '知识库/memory/password.txt', '知识库/memory/勿外发.md',
                    '知识库/memory/environment.md', '知识库/memory/Environment-local.md',
                    '知识库/ai-knowhow/机器环境与工具链.md']
        for rel in allowed + excluded:
            self.fixture(rel)
        result = memory.scan(self.root)
        self.assertEqual({row['path'] for row in result['files']}, set(allowed))
        self.assertTrue(result['root_available'])
        for row in result['files']:
            self.assertNotIn('content', row)
            self.assertIn('modified', row)
        self.assertEqual(memory.scan(None)['files'], [])

    def test_import_deduplicates_updates_and_never_changes_source(self):
        rel = '知识库/memory/profile.md'
        path = self.fixture(rel)
        original = path.read_bytes()
        result = memory.import_memories(self.root, [rel, rel], self.store)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(path.read_bytes(), original)
        doc = self.store.list('documents')[0]
        self.assertEqual(doc['source_ref'], rel)
        self.assertEqual(doc['category'], '偏好')
        self.assertTrue(doc['private'])
        self.assertTrue(doc['hash'])
        self.assertTrue(doc['chunks'])
        self.assertEqual(memory.import_memories(self.root, [rel], self.store)['unchanged'], 1)
        path.write_text('合成更新记忆。', encoding='utf-8')
        self.assertEqual(memory.import_memories(self.root, [rel], self.store)['updated'], 1)
        self.assertEqual(self.store.list('documents')[0]['id'], doc['id'])

    def test_traversal_absolute_and_nonallowlisted_paths_rejected_atomically(self):
        rel = '知识库/memory/allowed.md'
        self.fixture(rel)
        outside = self.fixture('.hidden.md', '合成文件不允许导入')
        for bad in ['../unlisted.md', '知识库/memory/../../unlisted.md', str(outside), '.hidden.md', 123]:
            with self.subTest(path=bad), self.assertRaises(ValueError):
                memory.import_memories(self.root, [rel, bad], self.store)
            self.assertEqual(self.store.list('documents'), [])
        for paths in (None, [], 'not-a-list', [rel] * 151):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                memory.import_memories(self.root, paths, self.store)

    def test_credentials_filtered_from_content_and_chunks(self):
        secrets = ['sk-' + 'A' * 30, 'B' * 24, 'fixture-password-123',
                   'eyJabcdefghijk.lmnopqrstuv.wxyzabcdefghi', 'fixture-api-key-123']
        text = ('公开合成记忆\n' + secrets[0] + '\nBearer ' + secrets[1] +
                '\npassword: ' + secrets[2] + '\n' + secrets[3] + '\napi_key=' + secrets[4])
        rel = '知识库/memory/method.md'
        path = self.fixture(rel, text)
        memory.import_memories(self.root, [rel], self.store)
        doc = self.store.list('documents')[0]
        encoded = str(self.store.backup('personal'))
        for secret in secrets:
            self.assertNotIn(secret, doc['content'])
            self.assertNotIn(secret, str(doc['chunks']))
            self.assertNotIn(secret, encoded)
        self.assertIn('公开合成记忆', doc['content'])
        self.assertEqual(path.read_text(encoding='utf-8'), text)

    def test_disabled_import_and_personal_details_redacted(self):
        with self.assertRaises(ValueError):
            memory.import_memories(None, ['notes.md'], self.store)
        text = 'synthetic@example.invalid\nC:\\Users\\synthetic-user\\private\\note.md\n/home/synthetic-user/notes.md'
        sanitized = memory.sanitize(text)
        for value in ['synthetic@example.invalid', 'synthetic-user']:
            self.assertNotIn(value, sanitized)

    def test_link_and_windows_reparse_metadata_rejected_without_privileges(self):
        for info in [SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0),
                     SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)]:
            with self.subTest(info=info), patch.object(Path, 'lstat', return_value=info):
                self.assertTrue(memory._linked(self.root))
                self.assertIsNone(memory._safe_root(self.root))
        linked = self.fixture('linked.md')
        linked_folder = self.root / 'linked-folder'
        linked_folder.mkdir()
        self.fixture('linked-folder/notes.md')
        real_linked = memory._linked
        # Windows CI may use an 8.3 TEMP alias while _safe_root resolves it.
        blocked = {linked.resolve(), linked_folder.resolve()}
        with patch('workos.memory._linked', side_effect=lambda path: path.resolve() in blocked or real_linked(path)):
            self.assertEqual(memory.candidates(self.root), {})
            with self.assertRaises(ValueError):
                memory.import_memories(self.root, ['linked.md'], self.store)

    def test_internal_file_and_directory_symlinks_rejected(self):
        target = self.fixture('notes.md')
        folder = self.root / 'linked-folder'
        file = self.root / 'linked.md'
        try:
            file.symlink_to(target)
            folder.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest('Symbolic links unavailable')
        self.assertEqual(set(memory.candidates(self.root)), {'notes.md'})
        for rel in ['linked.md', 'linked-folder/notes.md']:
            with self.assertRaises(ValueError):
                memory.import_memories(self.root, [rel], self.store)

    def test_oversized_memory_is_not_allowlisted(self):
        self.fixture('知识库/memory/large.md', 'x' * 2_000_001)
        self.assertEqual(memory.scan(self.root)['files'], [])

    def test_symlink_outside_root_is_not_allowlisted(self):
        with TemporaryDirectory() as outside:
            target = Path(outside) / 'synthetic.md'
            target.write_text('合成外部文件', encoding='utf-8')
            link = self.root / '知识库/memory/link.md'
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(target)
            except OSError as exc:
                self.skipTest('系统不允许创建测试符号链接: ' + str(exc))
            self.assertEqual(memory.scan(self.root)['files'], [])


if __name__ == '__main__':
    unittest.main()
