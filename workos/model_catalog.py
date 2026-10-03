"""Reviewed model identities and one nonsecret provider-selection contract.

Discovery and probes describe availability; they never expand the allowlist or
change the requested provider. Transport, credentials and cancellation remain
with Application's adapters.
"""
from __future__ import annotations
import ipaddress
import hashlib
import json
import re
from urllib.parse import urlsplit
from .ai_progress import safe_detail

DSH_MODELS = {
    'gpt-6-luna': ('GPT-6 Luna', 272000, 128000),
    'gpt-6-sol': ('GPT-6 Sol', 272000, 128000),
    'gpt-6-astra': ('GPT-6 Astra', 272000, 128000),
    'gpt-5.6-luna': ('GPT-5.6 Luna', 272000, 128000),
    'gpt-5.6-sol': ('GPT-5.6 Sol', 272000, 128000),
    'gpt-5.6-terra': ('GPT-5.6 Terra', 272000, 128000),
    'gpt-5.5': ('GPT-5.5', 272000, 128000),
    'gpt-5.3-codex-spark': ('GPT-5.3 Codex Spark', 128000, 128000),
}
LOCAL_AI_PRESETS = {
    'deepseek': {
        'label': 'DeepSeek（本地桥接）', 'base_url': 'http://127.0.0.1:8787/v1',
        'models': [
            ('deepseek-v4.1-flash', 'DeepSeek V4.1 Flash · 最快最省', 131072),
            ('deepseek-v4-pro', 'DeepSeek V4 Pro · 重活', 131072),
            ('deepseek-v3-2-volc', 'DeepSeek V3.2', 96000),
            ('deepseek-v3-1-volc', 'DeepSeek V3.1 · Volc 桥接', None),
            ('deepseek-v3-1-lkeap', 'DeepSeek V3.1 · LKEAP 桥接', None),
            ('deepseek-v3-1', 'DeepSeek V3.1', None),
            ('deepseek-v3-0324-lkeap', 'DeepSeek V3 · 0324 LKEAP', None),
            ('deepseek-r1-0528-lkeap', 'DeepSeek R1 · 0528 LKEAP', None),
        ],
    },
    'local': {
        'label': '本机其他模型', 'base_url': 'http://127.0.0.1:8787/v1',
        'models': [
            ('glm-5.2', 'GLM-5.2', 200000),
            ('kimi-k2.7', 'Kimi K2.7', 131072),
            ('hy3', 'Hunyuan 3', 200000),
            ('hunyuan-2.0-instruct', 'Hunyuan 2.0 Instruct', 128000),
            ('glm-4.7', 'GLM-4.7', None),
            ('glm-4.6', 'GLM-4.6', None),
            ('kimi-k2-instruct-taiji', 'Kimi K2 Instruct · Taiji', None),
            ('hunyuan-chat', 'Hunyuan Chat', None),
            ('hunyuan-turbos-vision', 'Hunyuan Turbos Vision', None),
            ('hunyuan-t1-vision', 'Hunyuan T1 Vision', None),
            ('completion-gf', 'Completion GF · 聊天接口', None),
            ('default', '账户默认模型（桥接别名）', None),
            ('default-1.1', 'Default 1.1（桥接别名）', None),
            ('default-1.2', 'Default 1.2（桥接别名）', None),
        ],
    },
}
LOCAL_DEFAULT_MODEL = 'deepseek-v4.1-flash'
MODES = {'dsh', 'deepseek', 'local-models', 'model'}
ALIASES = {'local-models': 'local-models', 'deepseek': 'deepseek', 'dsh': 'dsh', 'model': 'model',
           'local': 'local', 'rules': 'local'}
MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/@+\-]{0,199}')
# The installed bridge's static capability map marks these as completion-only.
# They stay visible for catalog completeness and are never selectable chat IDs.
UNSUPPORTED_MODELS = {
    'hunyuan-3b':'Hunyuan 3B', 'hunyuan-7b-dense':'Hunyuan 7B Dense',
    'codewise-7b-021':'Codewise 7B 021', 'codewise-completions':'Codewise Completions',
    'deepseek-r1-0528':'DeepSeek R1 0528（补全）',
    'deepseek-v3-0324-taco-completion':'DeepSeek V3 0324 Taco Completion',
    'deepseek-v3-0324':'DeepSeek V3 0324（补全）',
    'codewise-navi-v1-2-taco':'Codewise Navi V1.2 Taco',
}


def _model_id(value):
    if not isinstance(value, str) or not MODEL_ID.fullmatch(value):
        raise ValueError('模型编号格式无效')
    return value


def _mode(value):
    if value is None or value == '':
        return None
    if not isinstance(value, str) or value not in ALIASES:
        raise ValueError('请选择有效的模型服务')
    return ALIASES[value]


def endpoint_url(value):
    """Validate an already configured endpoint, without DNS or network access."""
    if not isinstance(value, str) or not value or len(value) > 2048 or re.search(r'[\s\x00-\x1f\x7f]', value):
        raise ValueError('模型服务地址无效')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise ValueError('模型服务地址无效') from exc
    if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError('模型服务地址需为不含凭证或查询参数的 HTTP/HTTPS 地址')
    if parsed.scheme == 'http' and not is_loopback_url(value):
        raise ValueError('非本机模型服务需要 HTTPS')
    return value.rstrip('/')


def is_loopback_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        parsed.port
        if (parsed.scheme not in ('http', 'https') or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or not host):
            return False
        return host.casefold() == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _local_entries():
    return [(mode, item) for key, mode in (('deepseek', 'deepseek'), ('local', 'local-models'))
            for item in LOCAL_AI_PRESETS[key]['models']]


def _infer_mode(model_id, config):
    if model_id in DSH_MODELS:
        return 'dsh'
    for mode, item in _local_entries():
        if item[0] == model_id:
            return mode
    if model_id and model_id == config.get('model'):
        return 'model'
    raise ValueError('所选模型不在允许列表中')


def resolve_selection(body, config=None, *, default_mode='deepseek', allow_local=False):
    """Canonical choice for every surface; never infer a different explicit mode."""
    if not isinstance(body, dict) or (config is not None and not isinstance(config, dict)):
        raise ValueError('模型选择或配置必须是对象')
    config = config or {}
    mode, provider = _mode(body.get('mode')), _mode(body.get('provider'))
    if mode and provider and mode != provider:
        raise ValueError('模型选择的服务字段不一致')
    model_id = body.get('model_id')
    if model_id is not None and model_id != '':
        model_id = _model_id(model_id)
    else:
        model_id = ''
    mode = mode or provider or (_infer_mode(model_id, config) if model_id else _mode(default_mode))
    if mode == 'local':
        if not allow_local:
            raise ValueError('本地规则模式不会调用模型；请明确选择 AI 模型')
        if model_id:
            raise ValueError('本地规则模式不能同时指定 AI 模型')
        return {'mode': 'local', 'provider': 'local', 'model_id': '', 'name': '本地规则', 'base_url': '', 'context': None}
    if mode not in MODES:
        raise ValueError('请选择可用的 AI 模型服务')
    if mode!='model' and model_id in UNSUPPORTED_MODELS:
        raise ValueError('该桥接模型仅支持代码补全，不能用于当前聊天或工作材料生成')
    if mode == 'dsh':
        model_id = model_id or 'gpt-6-luna'
        if model_id not in DSH_MODELS:
            raise ValueError('所选 GPT 模型不在允许列表中')
        name, context, _ = DSH_MODELS[model_id]
        return {'mode': mode, 'provider': mode, 'model_id': model_id, 'name': name, 'base_url': '', 'context': context}
    if mode == 'model':
        configured_model = config.get('model')
        if not config.get('base_url') or not configured_model:
            raise ValueError('请先配置模型服务；没有自动切换模型')
        configured_model = _model_id(configured_model)
        if model_id and model_id != configured_model:
            raise ValueError('所选模型与已配置模型不同；没有自动切换模型')
        return {'mode': mode, 'provider': mode, 'model_id': configured_model, 'name': configured_model,
                'base_url': endpoint_url(config['base_url']), 'context': None}
    preset = LOCAL_AI_PRESETS['deepseek' if mode == 'deepseek' else 'local']
    model_id = model_id or (LOCAL_DEFAULT_MODEL if mode == 'deepseek' else preset['models'][0][0])
    entry = next((item for item in preset['models'] if item[0] == model_id), None)
    if entry is None:
        raise ValueError('所选模型不在当前服务的允许列表中')
    base_url = preset['base_url']
    configured = config.get('base_url')
    if configured and is_loopback_url(configured):
        base_url = endpoint_url(configured)
    return {'mode': mode, 'provider': mode, 'model_id': model_id, 'name': entry[1], 'base_url': base_url, 'context': entry[2]}


def selection_body(selection_id, config=None):
    if not isinstance(selection_id, str) or ':' not in selection_id:
        raise ValueError('模型选择编号无效')
    mode, model_id = selection_id.split(':', 1)
    choice = resolve_selection({'mode': mode, 'model_id': model_id}, config)
    return {key: choice[key] for key in ('mode', 'provider', 'model_id')}


def selection_identity(choice):
    return hashlib.sha256(json.dumps([choice['mode'],choice['base_url'],choice['model_id']],ensure_ascii=False).encode()).hexdigest()


def _brand(model_id):
    if model_id.startswith('glm-'):return 'glm', 'GLM'
    if model_id.startswith('kimi-'):return 'kimi', 'Kimi'
    if model_id.startswith('hunyuan-') or model_id == 'hy3':return 'hunyuan', 'Hunyuan'
    return 'bridge', '账户默认 / 代码桥接'


def build_catalog(config=None, *, dsh_available=False, bridge_model_ids=None, model_statuses=None):
    """Return reviewed choices; stale discovery omissions do not disable aliases."""
    if config is not None and not isinstance(config, dict):raise ValueError('模型配置必须是对象')
    if model_statuses is not None and not isinstance(model_statuses, dict):raise ValueError('模型状态必须是对象')
    statuses=model_statuses or {}
    if bridge_model_ids is not None and (not isinstance(bridge_model_ids,(list,tuple,set)) or
            any(not isinstance(item,str) for item in bridge_model_ids)):
        raise ValueError('模型发现结果必须是编号列表')
    advertised=set(bridge_model_ids or ())
    groups=[];indexed={}
    def add(group_id,label,mode,model_id,name,unsupported=False):
        selection_id=mode+':'+model_id
        status='not_checked';available=True
        if mode=='dsh' and not dsh_available:status='runtime_unavailable';available=False
        elif model_id in advertised and mode in ('deepseek','local-models'):status='advertised'
        elif mode=='model':status='configured'
        # Only an actual checked result may make a present adapter unavailable.
        checked=statuses.get(selection_id)
        if isinstance(checked,dict) and checked.get('status') in ('verified','rejected','unavailable','not_checked'):
            status=checked['status'];available=status not in ('rejected','unavailable')
            if mode=='dsh' and not dsh_available:status='runtime_unavailable';available=False
        if unsupported:status='unsupported';available=False
        if group_id not in indexed:
            indexed[group_id]={'id':group_id,'label':label,'models':[]};groups.append(indexed[group_id])
        model={'id':model_id,'name':name,'mode':mode,'provider':mode,
            'selection_id':selection_id,'available':available,'status':status}
        if isinstance(checked,dict) and status==checked.get('status'):
            timestamp=checked.get('checked_at')
            if isinstance(timestamp,str) and len(timestamp)<=80 and not re.search(r'[\x00-\x1f\x7f]',timestamp):
                model['checked_at']=timestamp
            reason=checked.get('reason')
            if isinstance(reason,str) and len(reason)<=200:model['reason']=safe_detail(reason)
        if unsupported:model['reason']='桥接能力表标记为补全专用，不支持当前 AI 工作入口'
        indexed[group_id]['models'].append(model)
    for model_id,item in DSH_MODELS.items():add('dsh','GPT（OpenAI / DSH）','dsh',model_id,item[0])
    for mode,item in _local_entries():
        brand,label=('deepseek','DeepSeek') if mode=='deepseek' else _brand(item[0])
        add(brand,label,mode,item[0],item[1])
    for model_id,name in UNSUPPORTED_MODELS.items():add('completion','补全专用模型（不支持 AI 聊天）','local-models',model_id,name,True)
    config=config or {}
    if config.get('base_url') and config.get('model'):
        try:choice=resolve_selection({'mode':'model'},config)
        except ValueError:choice=None
        if choice:add('model','已配置兼容接口','model',choice['model_id'],choice['name'])
    return {'groups':groups,'default_selection_id':'deepseek:'+LOCAL_DEFAULT_MODEL}
