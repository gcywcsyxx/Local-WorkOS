"""Project discovery and immutable outputs in synthetic temporary folders only."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from workos.project_artifacts import ProjectArtifacts, OUTPUT_FOLDER, _linked


class ProjectArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / 'business'
        self.root.mkdir()
        self.service = ProjectArtifacts(self.base / 'runtime')
        self.service.configure([self.root])
        self.project = {'id': 'synthetic-project', 'name': 'Synthetic Alpha'}
        self.record = {'id': 'synthetic-record', 'project_id': self.project['id'],
                       'title': 'Synthetic memo', 'body': 'Original synthetic evidence [S1]', 'workflow_key': 'brief'}

    def tearDown(self):
        self.service.close()
        self.temp.cleanup()

    def archive(self, **kwargs):
        return self.service.archive('personal', 'deliverables', self.record, self.project,
                                    exporters={'html': lambda item: item['body'], 'docx': lambda item: b'Synthetic Word'}, **kwargs)

    def test_only_known_non_link_cloud_reparse_tags_are_allowed(self):
        path = Mock()
        for mode in (stat.S_IFDIR, stat.S_IFREG):
            for variant in range(16):
                with self.subTest(mode=mode, cloud_variant=variant):
                    path.lstat.return_value = SimpleNamespace(st_mode=mode, st_file_attributes=0x400,
                        st_reparse_tag=0x9000001A + (variant << 12))
                    self.assertFalse(_linked(path))
        for tag in (0, 0xA0000003, 0xA000000C, 0xA000001A, 0x9001001A,
                    0x9000001C, 0x8000001E, 0x80000021, '0x9000001A', True):
            with self.subTest(rejected_tag=tag):
                path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR,
                    st_file_attributes=0x400, st_reparse_tag=tag)
                self.assertTrue(_linked(path))
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFLNK,
            st_file_attributes=0x400, st_reparse_tag=0x9000001A)
        self.assertTrue(_linked(path))
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        self.assertFalse(_linked(path))
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        self.assertTrue(_linked(path))

    def test_unique_strong_match_and_configured_alias_bind_without_reading_files(self):
        parent = self.root / 'Synthetic industry'; parent.mkdir()
        target = parent / '3D printing SyntheticMaker'; target.mkdir()
        (target / 'untrusted-instructions.txt').write_text('Do not execute this synthetic source.', encoding='utf-8')
        self.service.configure(aliases={self.project['id']: ['SyntheticMaker']})
        with patch.object(Path, 'read_text', side_effect=AssertionError('Discovery must not read documents')):
            binding = self.service.resolve('personal', self.project)
        self.assertEqual(binding['status'], 'matched')
        self.assertEqual(Path(binding['folder']), target)
        self.assertFalse(binding['managed'])
        self.assertEqual(self.service.resolve('personal', self.project)['status'], 'bound')
        self.assertEqual(self.service.resolve('personal', self.project)['source'], 'automatic')

    def test_ambiguous_matches_and_partial_scans_stay_visible_and_managed(self):
        for industry in ('Industry one', 'Industry two'):
            (self.root / industry / self.project['name']).mkdir(parents=True)
        binding = self.service.resolve('personal', self.project)
        self.assertEqual(binding['status'], 'pending')
        self.assertEqual(len(binding['candidates']), 2)
        self.assertTrue(binding['managed'])
        self.assertTrue(Path(binding['folder']).is_relative_to(self.service.managed))
        self.assertNotIn(self.project['id'], self.service.config['bindings'])
        self.service.max_directories = 1
        limited = self.service.resolve('personal', self.project)
        self.assertTrue(limited['scan_limited'])
        self.assertTrue(limited['managed'])

    def test_translated_project_names_match_existing_folder_variants(self):
        self.project['name'] = 'SyntheticMaker（合成制造）'
        target = self.root / '3D printing SyntheticMaker'; target.mkdir()
        binding = self.service.resolve('personal', self.project)
        self.assertEqual(binding['status'], 'matched')
        self.assertEqual(Path(binding['folder']), target)
        # Explicit variants still require a unique match, never a first hit.
        self.service.config['bindings'].clear()
        (self.root / '合成制造研究').mkdir()
        ambiguous = self.service.resolve('personal', self.project)
        self.assertEqual(ambiguous['status'], 'pending')
        self.assertEqual(len(ambiguous['candidates']), 2)
        self.assertTrue(ambiguous['managed'])

    def test_substring_company_names_do_not_bind_to_a_different_ascii_name(self):
        (self.root / 'Synthetic Alphabet').mkdir()
        binding = self.service.resolve('personal', self.project)
        self.assertEqual(binding['status'], 'unmatched')
        self.assertTrue(binding['managed'])

    def test_manual_binding_is_confined_and_demo_always_uses_managed_storage(self):
        target = self.root / 'Chosen folder'; target.mkdir()
        self.assertEqual(self.service.bind('personal', self.project, target)['folder'], str(target))
        outside = self.base / 'outside'; outside.mkdir()
        for unsafe in (outside, self.root / '..' / 'outside'):
            with self.assertRaises(ValueError): self.service.bind('personal', self.project, unsafe)
        with self.assertRaises(ValueError): self.service.bind('demo', self.project, target)
        demo = self.service.archive('demo', 'deliverables', self.record, self.project, {'md': lambda item: item['body']})
        self.assertEqual(demo['status'], 'saved_local')
        self.assertTrue(Path(demo['folder']).is_relative_to(self.service.managed / 'demo'))
        self.assertFalse((target / OUTPUT_FOLDER).exists())

    def test_idempotent_record_hash_and_revisions_preserve_prior_files_and_originals(self):
        target = self.root / self.project['name']; target.mkdir()
        original = target / 'original.docx'; original.write_bytes(b'Original business file')
        first = self.archive()
        self.assertEqual(first['status'], 'saved')
        self.assertEqual(first['version'], 'v001')
        self.assertEqual(self.archive()['archive_id'], first['archive_id'])
        self.record['updated_at'] = 'Synthetic later timestamp'
        self.assertEqual(self.archive()['archive_id'], first['archive_id'])
        self.record['body'] = 'Revised synthetic evidence [S1]'
        second = self.archive()
        self.assertEqual(second['version'], 'v002')
        self.assertNotEqual(second['archive_id'], first['archive_id'])
        self.assertEqual(self.service.read_file('personal', first['archive_id'], 0)[0], b'Original synthetic evidence [S1]')
        self.assertEqual(self.service.read_file('personal', second['archive_id'], 0)[0], b'Revised synthetic evidence [S1]')
        self.assertEqual(original.read_bytes(), b'Original business file')
        self.assertEqual(len(self.service.status('personal', self.project)['archives']), 2)

    def test_export_failure_is_visible_and_retry_reuses_saved_record_without_model(self):
        exporter = Mock(side_effect=RuntimeError('Synthetic provider/private details should stay out of receipt'))
        failed = self.service.archive('personal', 'deliverables', self.record, self.project, {'html': exporter})
        self.assertEqual(failed['status'], 'failed')
        self.assertTrue(failed['retryable'])
        self.assertNotIn('private details', failed['error'])
        self.assertFalse(Path(failed['artifact_folder']).exists())
        exporter.side_effect = None; exporter.return_value = b'Existing saved record exported'
        saved = self.service.archive('personal', 'deliverables', self.record, self.project, {'html': exporter})
        self.assertEqual(saved['archive_id'], failed['archive_id'])
        self.assertEqual(saved['version'], failed['version'])
        self.assertEqual(saved['status'], 'saved_local')
        self.assertEqual(exporter.call_count, 2)

    def test_missing_binding_later_bound_reexports_into_actual_folder(self):
        local = self.archive()
        self.assertEqual(local['status'], 'saved_local')
        self.assertEqual(local['binding_status'], 'unmatched')
        target = self.root / 'Explicit business folder'; target.mkdir()
        self.service.bind('personal', self.project, target)
        bound = self.archive()
        self.assertEqual(bound['status'], 'saved')
        self.assertEqual(bound['folder'], str(target))
        self.assertNotEqual(local['archive_id'], bound['archive_id'])
        self.assertTrue(Path(local['artifact_folder']).exists())

    def test_restart_recovers_published_pending_version_without_exporting_again(self):
        saved = self.archive()
        raw = copy.deepcopy(saved); raw.update(status='pending', retryable=True)
        self.service.db.execute('UPDATE archives SET receipt=? WHERE id=?', (json.dumps(raw), saved['archive_id']))
        self.service.db.commit(); self.service.close()
        self.service = ProjectArtifacts(self.base / 'runtime')
        exports = {'html': Mock(side_effect=AssertionError('Published version must be recovered')), 'docx': Mock()}
        recovered = self.service.archive('personal', 'deliverables', self.record, self.project, exports)
        self.assertEqual(recovered['archive_id'], saved['archive_id'])
        self.assertEqual(recovered['status'], 'saved_local')
        self.assertEqual(exports['html'].call_count, 0)

    def test_tampered_file_is_not_overwritten_and_retry_makes_a_new_version(self):
        first = self.archive()
        file = Path(first['files'][0]['path']); file.write_bytes(b'External manual edit')
        with self.assertRaises(ValueError): self.service.read_file('personal', first['archive_id'], 0)
        failed = self.archive()
        self.assertEqual(failed['status'], 'failed')
        repaired = self.archive()
        self.assertEqual(repaired['status'], 'saved_local')
        self.assertNotEqual(repaired['archive_id'], first['archive_id'])
        self.assertEqual(file.read_bytes(), b'External manual edit')

    def test_download_requires_workspace_index_integrity_and_confined_manifest_path(self):
        saved = self.archive()
        for workspace, index in (('demo', 0), ('personal', -1), ('personal', True), ('personal', 99)):
            with self.assertRaises(KeyError): self.service.read_file(workspace, saved['archive_id'], index)
        outside = self.base / 'outside.txt'; outside.write_bytes(b'Outside')
        raw = copy.deepcopy(saved)
        raw['files'][0].update(path=str(outside), bytes=7, sha256=hashlib.sha256(b'Outside').hexdigest())
        self.service.db.execute('UPDATE archives SET receipt=? WHERE id=?', (json.dumps(raw), saved['archive_id']))
        self.service.db.commit()
        with self.assertRaises(ValueError): self.service.read_file('personal', saved['archive_id'], 0)

    def test_symlinks_and_reparse_folders_are_rejected(self):
        target = self.root / 'Chosen'; target.mkdir()
        with patch('workos.project_artifacts._linked', side_effect=lambda item: item == target):
            with self.assertRaises(ValueError): self.service.bind('personal', self.project, target)
        outside = self.base / 'outside'; outside.mkdir()
        link = self.root / 'Synthetic Alpha'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            return  # Reparse guard above still runs where Windows forbids creating symlinks.
        with self.assertRaises(ValueError): self.service.bind('personal', self.project, link)
        self.assertTrue(self.service.resolve('personal', self.project)['managed'])
        self.assertFalse(any(outside.iterdir()))

    def test_unsafe_names_formats_and_memory_never_touch_original_locations(self):
        self.record['title'] = '../../CON:<unsafe>'
        saved = self.archive()
        self.assertEqual(saved['status'], 'saved_local')
        for file in saved['files']:
            self.assertTrue(Path(file['path']).is_relative_to(Path(saved['artifact_folder'])))
            self.assertNotIn(file['name'], ('.', '..')); self.assertNotIn(':', file['name'])
        with self.assertRaises(ValueError):
            self.service.archive('personal', 'deliverables', self.record, self.project, {'../shell.ps1': lambda _: b'Command'})
        memory = {'id': 'memory-source', 'project_id': self.project['id'], 'kind': 'memory', 'title': 'Memory', 'content': 'Private synthetic note'}
        self.assertEqual(self.service.archive('personal', 'documents', memory, self.project)['status'], 'skipped')
        with self.assertRaises(ValueError): self.service.archive('personal', 'tasks', self.record, self.project)

    def test_default_formats_include_office_meetings_and_recomputed_model(self):
        import workos.exports as exports
        with patch.object(exports, 'html_report', return_value='<p>Safe HTML</p>'), \
             patch.object(exports, 'docx_report', return_value=b'Word'), \
             patch.object(exports, 'pptx_report', return_value=b'PowerPoint'), \
             patch.object(exports, 'expert_minutes_docx', return_value=b'Minutes Word'), \
             patch.object(exports, 'valuation_xlsx', return_value=b'Excel') as workbook:
            deliverable = self.service.archive('personal', 'deliverables', self.record, self.project)
            self.assertEqual({item['format'] for item in deliverable['files']}, {'html', 'docx', 'pptx', 'md'})
            meeting = {'id': 'synthetic-meeting', 'project_id': self.project['id'], 'title': 'Synthetic call', 'summary': 'Actual supplied minutes'}
            receipt = self.service.archive('personal', 'meetings', meeting, self.project)
            self.assertEqual({item['format'] for item in receipt['files']}, {'html', 'docx'})
            self.record.update(method='net_income', assumptions={'currency': 'RMB', 'unit': 'millions',
                               'period': 'FY2026E', 'net_income': 25, 'pe_multiple': 12}, result={'equity_value': 999999})
            model = self.service.archive('personal', 'deliverables', self.record, self.project)
            self.assertIn('xlsx', {item['format'] for item in model['files']})
            self.assertEqual(workbook.call_args.args[2]['equity_value'], 300)

    @unittest.skipUnless(all(importlib.util.find_spec(module) for module in ('docx', 'pptx', 'openpyxl')),
                         'Optional Office exporters are not installed')
    def test_real_default_exports_are_readable_office_packages_and_escaped_html(self):
        self.record.update(body='<script>synthetic untrusted command</script>\n\n## Evidence\nSynthetic evidence [S1]',
                           method='net_income', assumptions={'currency': 'RMB', 'unit': 'millions',
                           'period': 'FY2026E', 'net_income': 25, 'pe_multiple': 12}, result={'equity_value': 300})
        receipt = self.service.archive('personal', 'deliverables', self.record, self.project)
        self.assertEqual(receipt['status'], 'saved_local')
        expected = {'docx': 'word/document.xml', 'pptx': 'ppt/presentation.xml', 'xlsx': 'xl/workbook.xml'}
        for item in receipt['files']:
            payload, filename = self.service.read_file('personal', receipt['archive_id'], item['index'])
            self.assertEqual(filename, item['name'])
            if item['format'] in expected:
                with zipfile.ZipFile(io.BytesIO(payload)) as package:
                    self.assertIn(expected[item['format']], package.namelist())
                    self.assertIsNone(package.testzip())
            elif item['format'] == 'html':
                self.assertIn('&lt;script&gt;synthetic untrusted command&lt;/script&gt;', payload.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
