"""Deployment backups must capture active WAL without altering live private files."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from tools.release_backup import backup


class ReleaseBackupTests(unittest.TestCase):
    def test_context_and_archive_ledgers_and_config_are_backed_up(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary); data = root / 'data'; data.mkdir()
            names = ['conversations.sqlite3', 'project-artifacts.sqlite3']
            for name in names:
                with closing(sqlite3.connect(data / name)) as live:
                    live.execute('CREATE TABLE records(value TEXT)')
                    live.execute('INSERT INTO records VALUES (?)', (name,)); live.commit()
            config = {'schema_version': 1, 'roots': [], 'bindings': {}, 'aliases': {}}
            (data / 'project-artifacts.json').write_text(json.dumps(config), encoding='utf-8')
            target = root / 'backup'
            self.assertEqual(backup(data, target), names)
            self.assertEqual(json.loads((target / 'project-artifacts.json').read_text()), config)
            for name in names:
                with closing(sqlite3.connect(target / name)) as restored:
                    self.assertEqual(restored.execute('SELECT value FROM records').fetchone()[0], name)

    def test_active_wal_is_included_and_authentication_is_not_copied(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'data'
            data.mkdir()
            private = data / 'authentication'
            private.mkdir()
            (private / 'account.json').write_text('synthetic-private-account')
            originals = data / 'originals'
            originals.mkdir()
            (originals / 'synthetic').write_bytes(b'synthetic original')
            with closing(sqlite3.connect(data / 'personal.sqlite3')) as live:
                live.execute('PRAGMA journal_mode=WAL')
                live.execute('CREATE TABLE records(value TEXT)')
                live.execute('INSERT INTO records VALUES (?)', ('committed-in-wal',))
                live.commit()
                target = root / 'backup'
                self.assertEqual(backup(data, target), ['personal.sqlite3'])
                with closing(sqlite3.connect(target / 'personal.sqlite3')) as restored:
                    self.assertEqual(restored.execute('SELECT value FROM records').fetchone()[0], 'committed-in-wal')
                self.assertTrue((data / 'personal.sqlite3-wal').exists())
                self.assertFalse((target / 'authentication').exists())
                self.assertFalse((target / 'originals').exists())
                self.assertEqual((private / 'account.json').read_text(), 'synthetic-private-account')
                self.assertEqual((originals / 'synthetic').read_bytes(), b'synthetic original')
                with self.assertRaises(FileExistsError):
                    backup(data, target)


if __name__ == '__main__':
    unittest.main()
