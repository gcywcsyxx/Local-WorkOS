"""Structured model persistence and scenario economics; all data are synthetic."""
import copy
import http.client
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from openpyxl import load_workbook
from workos.model_records import compare_scenarios
from workos.server import Application, Handler
from workos.store import Store
from workos.valuation import calculate_valuation


def pe_assumptions():
    return {'currency': 'RMB', 'unit': 'millions', 'period': 'FY2026E',
            'net_income': 25, 'pe_multiple': 12}


def dcf_assumptions():
    return {'currency': 'RMB', 'unit': 'millions', 'valuation_date': '2025-12-31',
            'wacc': .10, 'discount_timing': 'year_end', 'terminal_method': 'perpetuity',
            'terminal_growth': .02, 'net_debt': 10, 'minority_interest': 0, 'tax_rate': .25,
            'forecasts': [{'year': '2026E', 'ebit': 25, 'da': 3, 'capex': 4, 'delta_nwc': 2},
                          {'year': '2027E', 'ebit': 30, 'da': 4, 'capex': 5, 'delta_nwc': 2}]}


class ModelRecordTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'models.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(lambda: self.store.close())
        self.project = self.store.create('projects', {'name': '合成模型项目'})

    def save(self, **fields):
        return self.store.create('deliverables', {'title': '合成估值模型', 'kind': '自定义',
                            'project_id': self.project['id'], 'method': 'net_income',
                            'assumptions': pe_assumptions(), **fields})

    def test_saved_model_recomputes_cache_and_survives_reopen_edit_restore(self):
        record = self.save(result={'equity_value': 999999}, body='已核对的合成假设')
        self.assertEqual(record['result']['equity_value'], 300)
        self.assertEqual(record['task_group'], '财务与估值')
        self.assertEqual(record['material_type'], '财务模型')
        self.store.close()
        self.store = Store(self.path)
        loaded = self.store.get('deliverables', record['id'])
        self.assertEqual(loaded, record)
        assumptions = {**loaded['assumptions'], 'pe_multiple': 14}
        edited = self.store.update('deliverables', record['id'], {'assumptions': assumptions})
        self.assertEqual(edited['result']['equity_value'], 350)
        self.assertEqual(edited['id'], record['id'])
        self.assertEqual(edited['created_at'], record['created_at'])
        backup = self.store.backup('personal')
        self.store.update('deliverables', record['id'], {'assumptions': pe_assumptions()})
        self.store.restore(backup, 'personal')
        self.assertEqual(self.store.get('deliverables', record['id']), edited)

    def test_legacy_body_only_records_stay_readable(self):
        legacy = self.store.create('deliverables', {'title': '旧模型文字', 'kind': '自定义',
                                                   'body': '净利润和倍数尚未形成结构化输入'})
        self.assertEqual(legacy['method'], '')
        self.assertEqual(legacy['assumptions'], {})
        self.assertEqual(legacy['body'], '净利润和倍数尚未形成结构化输入')
        backup = self.store.backup('personal')
        for record in backup['data']['deliverables']:
            for field in ('method', 'assumptions', 'result', 'workflow_key', 'source_ids', 'coverage', 'review_comments'):
                record.pop(field, None)
        self.store.restore(backup, 'personal')
        self.assertEqual(self.store.get('deliverables', legacy['id'])['body'], legacy['body'])

    def test_bad_model_values_leave_database_unchanged(self):
        before = self.store.backup('personal')['data']
        cases = ({'method': 'unsupported'}, {'assumptions': []}, {'result': {'x': float('inf')}},
                 {'assumptions': {**pe_assumptions(), 'net_income': True}},
                 {'assumptions': {**pe_assumptions(), 'unit': ''}},
                 {'assumptions': {**pe_assumptions(), 'unknown_driver': 1}},
                 {'assumptions': {key: value for key, value in pe_assumptions().items() if key != 'period'}})
        for fields in cases:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.save(**fields)
            self.assertEqual(self.store.backup('personal')['data'], before)

    def test_workflow_sources_coverage_and_review_comments_are_typed_and_scoped(self):
        source = self.store.create('documents', {'title': '合成来源', 'project_id': self.project['id'], 'content': 'source'})
        coverage = [{'document_id': source['id'], 'source_id': 'S1', 'title': source['title'],
                     'excerpt_chars': 6, 'total_chars': 6, 'truncated': False}]
        comment = {'id': 'c1', 'body': '请核对净利润期间', 'author': 'Reviewer',
                   'created_at': '2026-10-03T10:00:00+00:00', 'status': 'open', 'version_label': 'v1'}
        record = self.save(workflow_key='valuation', source_ids=[source['id']], coverage=coverage,
                           review_comments=[comment])
        self.assertEqual(record['coverage'], coverage)
        self.assertEqual(record['review_comments'], [comment])
        with self.assertRaises(ValueError):
            self.store.delete('documents', source['id'])
        for fields in ({'source_ids': [source['id'], source['id']]},
                       {'coverage': [{**coverage[0], 'truncated': 'yes'}]},
                       {'coverage': [{**coverage[0], 'excerpt_chars': 7}]},
                       {'review_comments': [{'body': 'x', 'status': 'pending'}]},
                       {'review_comments': [{'body': 'x', 'created_at': 'not a date'}]}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.update('deliverables', record['id'], fields)
        memory = self.store.create('documents', {'title': '合成记忆', 'kind': 'memory'})
        with self.assertRaises(ValueError):
            self.save(source_ids=[memory['id']])
        other = self.store.create('projects', {'name': '另一合成项目'})
        with self.assertRaises(ValueError):
            self.store.update('documents', source['id'], {'project_id': other['id']})
        bad_backup = self.store.backup('personal')
        bad_backup['data']['deliverables'][0]['source_ids'] = ['missing']
        bad_backup['data']['deliverables'][0]['coverage'] = []
        with self.assertRaises(ValueError):
            self.store.restore(bad_backup, 'personal')


class ScenarioTests(unittest.TestCase):
    def test_each_case_recomputes_real_driver_without_changing_baseline(self):
        assumptions = pe_assumptions()
        original = copy.deepcopy(assumptions)
        result = compare_scenarios('net_income', assumptions,
                  [{'name': '较低倍数', 'overrides': {'pe_multiple': 9.6}},
                   {'name': '较高倍数', 'overrides': {'pe_multiple': 14.4}}])
        self.assertEqual(assumptions, original)
        self.assertEqual(result['baseline']['equity_value'], 300)
        self.assertEqual([case['result']['equity_value'] for case in result['scenarios']], [240, 360])
        self.assertEqual(result['unit'], 'millions')
        self.assertEqual(result['currency'], 'RMB')

    def test_dcf_corners_and_later_forecast_change_propagate(self):
        assumptions = dcf_assumptions()
        later = copy.deepcopy(assumptions['forecasts'])
        later[-1]['ebit'] = 40
        result = compare_scenarios('dcf', assumptions,
                    [{'name': '低WACC', 'overrides': {'wacc': .08}},
                     {'name': '高WACC', 'overrides': {'wacc': .12}},
                     {'name': '末期改善', 'overrides': {'forecasts': later}}])
        base = result['baseline']['equity_value']
        values = [case['result']['equity_value'] for case in result['scenarios']]
        self.assertGreater(values[0], base)
        self.assertLess(values[1], base)
        self.assertGreater(values[2], base)
        self.assertEqual(result['baseline'], calculate_valuation('dcf', assumptions))

    def test_invalid_scenario_schema_units_periods_and_missing_inputs_are_rejected(self):
        invalid = ([], [{'name': 'x', 'overrides': {}}],
                   [{'name': 'x', 'overrides': {'unit': 'thousands'}}],
                   [{'name': 'x', 'overrides': {'currency': 'USD'}}],
                   [{'name': 'x', 'overrides': {'period': 'FY2027'}}],
                   [{'name': 'x', 'overrides': {'unknown': 1}}],
                   [{'name': 'x', 'overrides': {'net_income': None}}],
                   [{'name': 'x', 'overrides': {'pe_multiple': float('nan')}}],
                   [{'name': 'x', 'overrides': {'pe_multiple': True}}],
                   [{'name': 'same', 'overrides': {'pe_multiple': 10}}, {'name': 'SAME', 'overrides': {'pe_multiple': 14}}],
                   [{'name': str(index), 'overrides': {'pe_multiple': 10}} for index in range(9)])
        for scenarios in invalid:
            with self.subTest(scenarios=scenarios), self.assertRaises(ValueError):
                compare_scenarios('net_income', pe_assumptions(), scenarios)
        with self.assertRaises(ValueError):
            compare_scenarios('dcf', dcf_assumptions(), [{'name': '坏终值', 'overrides': {'wacc': .01}}])
        with self.assertRaises(ValueError):
            compare_scenarios('dcf', dcf_assumptions(), [{'name': '缺预测', 'overrides': {'forecasts': [{'year': '2026'}]}}])


class ModelRecordHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch('workos.server.find_root', return_value=None), patch.dict(os.environ, {'WORKOS_SYNC_ROOT': ''}):
            self.app = Application(Path(self.tmp.name) / 'data', port=0)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.httpd.daemon_threads = True
        self.app.port = self.httpd.server_address[1]
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(3)
        for store in self.app.stores.values():
            store.close()

    def request(self, method, path, body=None):
        headers = {'X-Workspace': 'personal', 'X-CSRF-Token': self.app.csrf}
        if body is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(body).encode('utf-8')
        connection = http.client.HTTPConnection('127.0.0.1', self.app.port, timeout=5)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
        finally:
            connection.close()

    def test_save_reopen_load_edit_recompute_and_formula_xlsx_export(self):
        status, project = self.request('POST', '/api/projects', {'name': 'HTTP合成模型'})
        self.assertEqual(status, 201)
        status, saved = self.request('POST', '/api/deliverables',
            {'title': '合成净利润估值', 'project_id': project['id'], 'method': 'net_income',
             'assumptions': pe_assumptions(), 'result': {'equity_value': 9999}, 'body': '合成模型记录'})
        self.assertEqual(status, 201, saved)
        self.assertEqual(saved['result']['equity_value'], 300)
        old_store = self.app.stores['personal']
        path = old_store.path
        old_store.close()
        self.app.stores['personal'] = Store(path)
        status, state = self.request('GET', '/api/state')
        self.assertEqual(status, 200)
        loaded = next(record for record in state['deliverables'] if record['id'] == saved['id'])
        edited_inputs = {**loaded['assumptions'], 'pe_multiple': 14}
        status, edited = self.request('PATCH', '/api/deliverables/' + saved['id'], {'assumptions': edited_inputs})
        self.assertEqual(status, 200, edited)
        self.assertEqual(edited['result']['equity_value'], 350)
        status, result = self.request('POST', '/api/model/valuation', {'method': edited['method'], 'assumptions': edited['assumptions']})
        self.assertEqual(status, 200, result)
        self.assertEqual(result, edited['result'])
        status, binary = self.request('POST', '/api/model/export-xlsx',
                                      {'method': edited['method'], 'assumptions': edited['assumptions'], 'title': edited['title']})
        self.assertEqual(status, 200)
        workbook = load_workbook(io.BytesIO(binary), data_only=False)
        summary = workbook['Summary']
        self.assertTrue(str(summary['B7'].value).startswith('='))
        self.assertEqual(summary['C7'].value, 350)
        self.assertEqual(workbook['Assumptions']['B5'].value, 25)

    def test_scenario_endpoint_recomputes_and_rejects_currency_relabeling(self):
        body = {'method': 'net_income', 'assumptions': pe_assumptions(),
                'scenarios': [{'name': 'Lower multiple', 'overrides': {'pe_multiple': 10}}]}
        status, result = self.request('POST', '/api/model/scenarios', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['scenarios'][0]['result']['equity_value'], 250)
        body['scenarios'][0]['overrides'] = {'currency': 'USD'}
        self.assertEqual(self.request('POST', '/api/model/scenarios', body)[0], 400)


if __name__ == '__main__':
    unittest.main()
