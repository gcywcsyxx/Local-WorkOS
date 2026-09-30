"""Public exports use synthetic text and independently authored inline assets."""
import html
import io
import re
import unittest
from unittest.mock import patch
from workos.exports import html_report, markdown, docx_report


class PublicExportTests(unittest.TestCase):
    def test_standalone_html_and_escaped_external_text(self):
        attack = '</script><img src=x onerror="window.syntheticXSS=1"> &'
        result = html_report({'title': attack, 'body': '## ' + attack + '\n' + attack})
        self.assertIn(html.escape(attack), result)
        self.assertNotIn(attack, result)
        self.assertIn('id="s0"', result)
        self.assertIn('id="p1"', result)
        self.assertIn('id="report-notes-data"', result)
        self.assertIn('id="report-editor-script"', result)
        self.assertNotRegex(result, r'<script[^>]+src=')
        self.assertNotIn('contenteditable=', result)
        self.assertNotIn('vendor', result)
        self.assertEqual(len(re.findall(r'<script\b', result)), 2)
        self.assertIn('Local WorkOS', result)

    def test_only_public_editor_asset_is_read(self):
        from workos import exports
        original = exports.Path.read_text
        paths = []
        def read(path, *args, **kwargs):
            paths.append(path)
            return original(path, *args, **kwargs)
        with patch.object(exports.Path, 'read_text', read):
            html_report({'title': '合成报告', 'body': '合成正文'})
        self.assertEqual(paths, [exports.ROOT / 'web' / 'report-editor.js'])

    def test_markdown_contract(self):
        record = {'title': '合成报告', 'body': '## 合成正文\n原始内容 & <tag>'}
        self.assertTrue(markdown(record).startswith('# 合成报告\n\n' + record['body']))
        self.assertIn('Local WorkOS', markdown(record))

    def test_docx_contract_when_available(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest('Optional python-docx is unavailable')
        result = docx_report({'title': '合成报告', 'body': '## 合成标题\n合成正文'})
        text = '\n'.join(p.text for p in Document(io.BytesIO(result)).paragraphs)
        self.assertIn('合成报告', text)
        self.assertIn('合成正文', text)


if __name__ == '__main__':
    unittest.main()
