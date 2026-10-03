"""Bounded selected-source context contracts; no provider or filesystem calls."""
import copy
import math
import unittest

from workos.engine import chunk_text, selected_context_citations


def document(index, count=12):
    return {'id': f'source-{index}', 'title': f'Synthetic source {index}',
            'chunks': [{'id': f'chunk-{number}', 'ordinal': number + 1,
                        'page': number + 1, 'text': f'Source {index} segment {number}: ' + 'x' * 1000}
                       for number in range(count)]}


class SelectedModelContextTests(unittest.TestCase):
    def test_fair_budget_represents_later_selected_documents(self):
        docs = [document(index, count=50 if index == 0 else 12) for index in range(8)]
        before = copy.deepcopy(docs)
        citations = selected_context_citations(docs, max_chars=1600)
        represented = {item['document_id'] for item in citations}
        self.assertEqual(represented, {doc['id'] for doc in docs})
        for doc in docs:
            quotes = [item['quote'] for item in citations if item['document_id'] == doc['id']]
            self.assertGreater(sum(map(len, quotes)), 0)
            self.assertLessEqual(sum(map(len, quotes)), 1600 // len(docs))
        self.assertLessEqual(sum(len(item['quote']) for item in citations), 1600)
        self.assertEqual(docs, before)
        self.assertEqual(citations, selected_context_citations(docs, max_chars=1600))

    def test_one_long_source_includes_head_middle_and_tail_actual_chunks(self):
        doc = document('long', count=100)
        citations = selected_context_citations([doc])
        ordinals = [item['ordinal'] for item in citations]
        self.assertIn(1, ordinals)
        self.assertIn(100, ordinals)
        self.assertTrue(any(45 <= ordinal <= 55 for ordinal in ordinals))
        self.assertLessEqual(len(citations), math.ceil(24000 / 900))
        chunks = {chunk['ordinal']: chunk for chunk in doc['chunks']}
        for citation in citations:
            original = chunks[citation['ordinal']]
            self.assertEqual(citation['id'], f'{doc["id"]}:{original["id"]}')
            self.assertEqual(citation['page'], original['page'])
            self.assertIn(citation['quote'], original['text'])
            self.assertTrue(0 < len(citation['quote']) <= 900)
        self.assertLessEqual(sum(len(item['quote']) for item in citations), 24000)

    def test_eighty_sources_fit_default_and_minimum_budgets_without_starvation(self):
        docs = [document(index, count=3) for index in range(80)]
        for budget in (80, 24000):
            with self.subTest(budget=budget):
                citations = selected_context_citations(docs, max_chars=budget)
                self.assertEqual({item['document_id'] for item in citations}, {doc['id'] for doc in docs})
                self.assertLessEqual(sum(len(item['quote']) for item in citations), budget)
                self.assertTrue(all(0 < len(item['quote']) <= min(900, budget // 80) for item in citations))

    def test_preserves_locations_and_normalizes_invalid_ordinals_and_pages(self):
        docs = [{'id': 'first', 'title': 'First', 'chunks': [
                    {'id': 'shared', 'ordinal': 17, 'page': 9, 'text': '  Alpha evidence  '},
                    {'ordinal': True, 'page': 0, 'text': 'Beta evidence'}]},
                {'id': 'second', 'title': 'Second', 'chunks': [
                    {'id': 'shared', 'ordinal': 3, 'page': None, 'text': 'Gamma evidence'}]}]
        before = copy.deepcopy(docs)
        citations = selected_context_citations(docs)
        by_id = {item['id']: item for item in citations}
        self.assertEqual(set(by_id), {'first:shared', 'first:paragraph-2', 'second:shared'})
        self.assertEqual((by_id['first:shared']['title'], by_id['first:shared']['ordinal'],
                          by_id['first:shared']['page'], by_id['first:shared']['quote']),
                         ('First', 17, 9, 'Alpha evidence'))
        self.assertEqual((by_id['first:paragraph-2']['ordinal'], by_id['first:paragraph-2']['page']), (2, None))
        self.assertEqual(by_id['second:shared']['document_id'], 'second')
        self.assertEqual(docs, before)

    def test_duplicate_source_or_chunk_identity_does_not_duplicate_citations(self):
        chunk = {'id': 'same-chunk', 'ordinal': 1, 'page': 4, 'text': 'Synthetic repeated evidence'}
        doc = {'id': 'same-source', 'title': 'Same source', 'chunks': [chunk, copy.deepcopy(chunk)]}
        citations = selected_context_citations([doc, copy.deepcopy(doc)])
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]['id'], 'same-source:same-chunk')
        self.assertEqual(citations, selected_context_citations([doc, copy.deepcopy(doc)]))

    def test_missing_chunks_uses_real_content_chunks_without_mutating_source(self):
        content = '\n\n'.join(f'Synthetic section {index}: ' + 'z' * 950 for index in range(6))
        docs = [{'id': 'content-only', 'title': 'Content source', 'content': content}]
        before = copy.deepcopy(docs)
        actual = {f'content-only:{chunk["id"]}': chunk for chunk in chunk_text(content)}
        citations = selected_context_citations(docs)
        self.assertTrue(citations)
        for citation in citations:
            chunk = actual[citation['id']]
            self.assertEqual(citation['ordinal'], chunk['ordinal'])
            self.assertIsNone(citation['page'])
            self.assertIn(citation['quote'], chunk['text'])
        self.assertEqual(docs, before)

    def test_empty_text_and_malformed_chunk_entries_never_manufacture_quotes(self):
        self.assertEqual(selected_context_citations([]), [])
        self.assertEqual(selected_context_citations([{'id': 'empty', 'title': 'Empty', 'content': ' \n\t '}]), [])
        for invalid_id in ('', None, 42):
            self.assertEqual(selected_context_citations([{'id': invalid_id, 'title': 'Missing identity',
                                                         'content': 'Evidence without a source identity'}]), [])
        docs = [{'id': 'invalid-chunks', 'title': 'Invalid entries',
                 'chunks': [None, 'not a chunk', {}, {'text': None}, {'text': 42}, {'text': '  '}]}]
        self.assertEqual(selected_context_citations(docs), [])
        mixed = [{'id': 'mixed', 'title': 'Mixed', 'chunks': [None, {'text': 'Real evidence', 'page': -1}]}]
        citations = selected_context_citations(mixed)
        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]['quote'], 'Real evidence')
        self.assertEqual(citations[0]['ordinal'], 2)
        self.assertIsNone(citations[0]['page'])

    def test_rejects_invalid_container_budget_and_document_fields(self):
        for invalid in (None, {}, 'sources', (document(1),), [None], [document(index) for index in range(81)]):
            with self.subTest(container=type(invalid).__name__), self.assertRaises(ValueError):
                selected_context_citations(invalid)
        for budget in (None, True, False, 0, 79, 24001, 900.0, '900'):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                selected_context_citations([document(1)], max_chars=budget)
        for doc in ({'id': 'invalid', 'title': 42, 'content': 'Evidence'},
                    {'id': 'invalid', 'title': 'Invalid', 'content': {}},
                    {'id': 'invalid', 'title': 'Invalid', 'chunks': {'text': 'Evidence'}}):
            with self.subTest(document=doc), self.assertRaises(ValueError):
                selected_context_citations([doc])


if __name__ == '__main__':
    unittest.main()
