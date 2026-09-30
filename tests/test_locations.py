"""Location discovery uses only synthetic folders and explicit configuration."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workos.memory import find_root, scan


class LocationTests(unittest.TestCase):
    def test_unconfigured_never_discovers_ancestors_or_cloud(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.md').write_text('synthetic', encoding='utf-8')
            app = root / 'nested' / 'app'
            app.mkdir(parents=True)
            with patch.dict(os.environ, {'OneDrive': str(root), 'OneDriveCommercial': str(root)}, clear=True):
                with patch('workos.memory.Path.home', side_effect=AssertionError('No home discovery')):
                    self.assertIsNone(find_root(app))
                    self.assertEqual(scan(find_root(app))['files'], [])
                    self.assertFalse(scan(find_root(app))['root_available'])

    def test_explicit_generic_folder_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.md').write_text('synthetic', encoding='utf-8')
            with patch.dict(os.environ, {'WORKOS_MEMORY_ROOT': str(root)}, clear=True):
                self.assertEqual(find_root(root / 'unused'), root.resolve())
                self.assertEqual(scan(find_root(root))['files'][0]['path'], 'notes.md')

    def test_invalid_empty_relative_and_file_configuration_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / 'note.md'
            file.write_text('synthetic', encoding='utf-8')
            for configured in ['', '  ', 'relative-notes', str(root / 'missing'), str(file)]:
                with self.subTest(configured=configured), patch.dict(os.environ, {'WORKOS_MEMORY_ROOT': configured}, clear=True):
                    self.assertIsNone(find_root(root))

    def test_linked_root_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'target'
            target.mkdir()
            link = root / 'link'
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError:
                self.skipTest('Symbolic links unavailable')
            with patch.dict(os.environ, {'WORKOS_MEMORY_ROOT': str(link)}, clear=True):
                self.assertIsNone(find_root(root))


if __name__ == '__main__':
    unittest.main()
