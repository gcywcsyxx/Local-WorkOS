"""One reviewed model selection contract, honest status and durable capture."""
import copy
import json
import unittest
from unittest.mock import patch
from workos.model_catalog import (DSH_MODELS,LOCAL_AI_PRESETS,LOCAL_DEFAULT_MODEL,UNSUPPORTED_MODELS,
    build_catalog,resolve_selection,selection_body,selection_identity,is_loopback_url,endpoint_url)
from tests import test_jobs as fixture


class ModelCatalogTests(unittest.TestCase):
    def models(self,**options):
        return [model for group in build_catalog(**options)['groups'] for model in group['models']]

    def test_every_selectable_catalog_item_round_trips_through_same_allowlist(self):
        models=self.models(dsh_available=True)
        identities=[model['selection_id'] for model in models]
        self.assertEqual(len(identities),len(set(identities)))
        self.assertEqual(len([model for model in models if model['available']]),30)
        self.assertEqual(len(models),38)
        for model in models:
            if not model['available']:continue
            with self.subTest(selection=model['selection_id']):
                body=selection_body(model['selection_id'])
                choice=resolve_selection(body)
                self.assertEqual(choice['model_id'],model['id'])
                self.assertEqual(choice['mode'],model['mode'])
                self.assertEqual(body['provider'],model['provider'])
        self.assertIn('deepseek:'+LOCAL_DEFAULT_MODEL,identities)

    def test_inference_preserves_legacy_known_model_ids_and_explicit_defaults(self):
        for model,mode in (('gpt-6-sol','dsh'),('gpt-5.3-codex-spark','dsh'),
            ('deepseek-v3-1-lkeap','deepseek'),('glm-5.2','local-models'),('kimi-k2.7','local-models')):
            with self.subTest(model=model):self.assertEqual(resolve_selection({'model_id':model})['mode'],mode)
        self.assertEqual(resolve_selection({})['model_id'],LOCAL_DEFAULT_MODEL)
        self.assertEqual(resolve_selection({},default_mode='dsh')['model_id'],'gpt-6-luna')
        self.assertEqual(DSH_MODELS['gpt-5.3-codex-spark'][1:],(128000,128000))
        with self.assertRaises(ValueError):resolve_selection({'model_id':'gpt-6.1-sol'})

    def test_explicit_provider_mode_or_model_conflicts_reject_without_fallback(self):
        for body in ({'mode':'dsh','provider':'deepseek','model_id':'gpt-6-sol'},
            {'mode':'deepseek','model_id':'glm-5.2'},{'mode':'local-models','model_id':'deepseek-v4-pro'},
            {'mode':'dsh','model_id':'arbitrary'},{'mode':[]},{'provider':[]},{'model_id':[]},{'model_id':False}):
            with self.subTest(body=body),self.assertRaises(ValueError):resolve_selection(body)
        self.assertEqual(resolve_selection({'provider':'local-models','model_id':'glm-5.2'})['mode'],'local-models')

    def test_local_rules_is_explicit_non_ai_and_cannot_have_a_model(self):
        with self.assertRaises(ValueError):resolve_selection({'provider':'rules'})
        self.assertEqual(resolve_selection({'provider':'rules'},allow_local=True)['mode'],'local')
        with self.assertRaises(ValueError):resolve_selection({'mode':'local','model_id':'gpt-6-sol'},allow_local=True)

    def test_custom_endpoint_only_uses_configured_model_and_never_leaks_credentials(self):
        config={'base_url':'https://synthetic-provider.invalid/v1','model':'vendor/model:revision',
            'api_key':'DO_NOT_LEAK_SYNTHETIC_KEY'}
        body={'mode':'model','model_id':config['model'],'base_url':'https://unrequested.invalid/v1','api_key':'CLIENT_SECRET'}
        choice=resolve_selection(body,config)
        self.assertEqual(choice['base_url'],config['base_url'])
        self.assertEqual(selection_body('model:'+config['model'],config)['model_id'],config['model'])
        catalog=build_catalog(config,dsh_available=True)
        for value in (choice,catalog):
            encoded=json.dumps(value)
            self.assertNotIn('SYNTHETIC_KEY',encoded);self.assertNotIn('CLIENT_SECRET',encoded)
        with self.assertRaises(ValueError):resolve_selection({'mode':'model','model_id':'different'},config)
        with self.assertRaises(ValueError):resolve_selection({'mode':'model'})

    def test_loopback_endpoint_parsing_cannot_be_tricked_by_hostname_prefix(self):
        for endpoint in ('http://127.0.0.1.evil.invalid/v1','http://localhost.evil.invalid/v1',
            'http://127.0.0.1@evil.invalid/v1','http://user:pass@localhost/v1','file:///private','http://localhost:bad/v1'):
            with self.subTest(endpoint=endpoint):self.assertFalse(is_loopback_url(endpoint))
        fixed=LOCAL_AI_PRESETS['deepseek']['base_url']
        self.assertEqual(resolve_selection({'mode':'deepseek'},{'base_url':'https://127.0.0.1.evil.invalid/v1'})['base_url'],fixed)
        for endpoint in ('http://127.0.0.2:8787/v1','https://localhost:8787/v1','http://[::1]:8787/v1'):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(is_loopback_url(endpoint))
                self.assertEqual(resolve_selection({'mode':'deepseek'},{'base_url':endpoint})['base_url'],endpoint)
        for endpoint in ('http://remote.invalid/v1','https://user:pass@host.invalid/v1',
            'https://host.invalid/v1?api_key=secret','https://host.invalid/v1#fragment','https://host.invalid/\nvalue'):
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):endpoint_url(endpoint)

    def test_stale_discovery_does_not_disable_newer_aliases_or_enable_arbitrary_ids(self):
        models={model['selection_id']:model for model in self.models(dsh_available=True,
            bridge_model_ids=['deepseek-v3-2-volc','arbitrary-unreviewed-model'])}
        self.assertEqual(models['deepseek:deepseek-v3-2-volc']['status'],'advertised')
        for identity in ('deepseek:deepseek-v4.1-flash','local-models:glm-5.2','local-models:hy3'):
            self.assertTrue(models[identity]['available']);self.assertEqual(models[identity]['status'],'not_checked')
        self.assertNotIn('arbitrary-unreviewed-model',{model['id'] for model in models.values()})

    def test_probe_status_is_separate_from_installed_adapter_and_redacts_details(self):
        statuses={'deepseek:deepseek-v4-pro':{'status':'verified','checked_at':'2026-10-04T00:00:00Z','reason':'合成响应已返回'},
            'local-models:glm-5.2':{'status':'rejected','reason':'API_KEY=synthetic-secret C:/private/path'},
            'dsh:gpt-6-sol':{'status':'verified'}}
        models={model['selection_id']:model for model in self.models(model_statuses=statuses,dsh_available=False)}
        self.assertTrue(models['deepseek:deepseek-v4-pro']['available'])
        self.assertEqual(models['deepseek:deepseek-v4-pro']['status'],'verified')
        self.assertEqual(models['deepseek:deepseek-v4-pro']['checked_at'],'2026-10-04T00:00:00Z')
        self.assertFalse(models['local-models:glm-5.2']['available'])
        self.assertNotIn('synthetic-secret',models['local-models:glm-5.2']['reason'])
        self.assertFalse(models['dsh:gpt-6-sol']['available'])
        self.assertEqual(models['dsh:gpt-6-sol']['status'],'runtime_unavailable')

    def test_completion_only_models_are_visible_but_never_chat_allowlist_choices(self):
        models={model['selection_id']:model for model in self.models(dsh_available=True,
            model_statuses={'local-models:codewise-completions':{'status':'verified'}})}
        for model_id in UNSUPPORTED_MODELS:
            with self.subTest(model=model_id):
                item=models['local-models:'+model_id]
                self.assertFalse(item['available']);self.assertEqual(item['status'],'unsupported')
                with self.assertRaisesRegex(ValueError,'补全'):resolve_selection({'mode':'local-models','model_id':model_id})
        # A separately configured remote deployment does not inherit a local
        # bridge's capability map just because its user-chosen name is equal.
        config={'base_url':'https://synthetic.invalid/v1','model':'deepseek-v3-0324'}
        self.assertEqual(resolve_selection({'mode':'model'},config)['model_id'],config['model'])

    def test_nonsecret_capture_identity_changes_for_provider_url_or_model_only(self):
        body={'mode':'model'};configuration={'base_url':'https://synthetic.invalid/v1','model':'synthetic-model','api_key':'old'}
        initial=selection_identity(resolve_selection(body,configuration))
        self.assertEqual(initial,selection_identity(resolve_selection(body,{**configuration,'api_key':'new'})))
        for changes in ({'base_url':'https://another.invalid/v1'},{'model':'another-model'}):
            self.assertNotEqual(initial,selection_identity(resolve_selection(body,{**configuration,**changes})))

    def test_catalog_results_are_independent_mutable_public_copies(self):
        before=copy.deepcopy(DSH_MODELS)
        result=build_catalog(dsh_available=True);result['groups'][0]['models'][0]['name']='Client mutation'
        self.assertEqual(DSH_MODELS,before)
        self.assertNotEqual(build_catalog(dsh_available=True)['groups'][0]['models'][0]['name'],'Client mutation')


class JobModelSelectionTests(unittest.TestCase):
    setUp=fixture.WorkflowJobTests.setUp
    tearDown=fixture.WorkflowJobTests.tearDown
    manager=fixture.WorkflowJobTests.manager
    request=fixture.WorkflowJobTests.request

    def test_legacy_gpt_id_without_mode_is_canonically_frozen_not_defaulted_to_deepseek(self):
        with patch('workos.jobs.ThreadPoolExecutor',fixture.PendingExecutor):jobs=self.manager()
        body=self.request(model_id='gpt-6-sol');body.pop('mode')
        job=jobs.submit('real',body)
        payload,snapshot,state=jobs._row('real',job['id'])
        self.assertEqual(payload['mode'],'dsh');self.assertEqual(payload['provider'],'dsh')
        self.assertEqual(snapshot['model_selection'],{'mode':'dsh','provider':'dsh','model_id':'gpt-6-sol'})
        self.assertEqual(state['mode'],'dsh');self.assertEqual(state['model_id'],'gpt-6-sol')
        self.assertEqual(jobs.submit('real',copy.deepcopy(body))['id'],job['id'])
        self.app.local_chat.assert_not_called()

    def test_provider_only_local_choice_preserves_exact_selected_model(self):
        with patch('workos.jobs.ThreadPoolExecutor',fixture.PendingExecutor):jobs=self.manager()
        body=self.request(provider='local-models',model_id='kimi-k2.7');body.pop('mode')
        job=jobs.submit('real',body)
        payload,snapshot,_=jobs._row('real',job['id'])
        self.assertEqual(payload['mode'],'local-models');self.assertEqual(payload['model_id'],'kimi-k2.7')
        self.assertNotIn('base_url',snapshot['model_selection'])

    def test_explicit_conflicts_cannot_create_jobs_or_capture_credentials(self):
        with patch('workos.jobs.ThreadPoolExecutor',fixture.PendingExecutor):jobs=self.manager()
        self.app.ai={'base_url':'http://127.0.0.1:9/v1','model':'configured-model','api_key':'PRIVATE_SYNTHETIC_KEY'}
        for changes in ({'mode':'dsh','provider':'deepseek','model_id':'gpt-6-sol'},
            {'mode':'model','model_id':'different-model'},{'mode':'local-models','model_id':'codewise-completions'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):jobs.submit('real',self.request(**changes))
        self.assertEqual(jobs.list('real'),[])
        job=jobs.submit('real',self.request(mode='model'))
        payload,snapshot,state=jobs._row('real',job['id'])
        self.assertEqual(payload['model_id'],'configured-model')
        self.assertNotIn('PRIVATE_SYNTHETIC_KEY',json.dumps([payload,snapshot,state]))
        self.app.local_chat.assert_not_called()


if __name__=='__main__':unittest.main()
