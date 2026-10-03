"""Typed saved models and explicit, deterministic scenario comparisons."""
from __future__ import annotations

import copy
from datetime import datetime
import json
import math
import re

from .valuation import ASSUMPTION_SCHEMAS, calculate_valuation

MODEL_FIELDS = {'method', 'assumptions', 'result'}
WORKFLOW_FIELDS = {'workflow_key', 'source_ids', 'coverage'}


def validate_object(value, label, maximum_bytes=500_000):
    if not isinstance(value, dict):
        raise ValueError(label + '必须是对象')
    visited = 0

    def visit(item, depth=0):
        nonlocal visited
        visited += 1
        if visited > 20_000 or depth > 12:
            raise ValueError(label + '结构过大或过深')
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 200:
                    raise ValueError(label + '字段名必须为文本且不能超过200字')
                visit(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError(label + '必须使用有限数值')
        elif not isinstance(item, (str, int, float, bool, type(None))):
            raise ValueError(label + '存在不支持的值类型')

    visit(value)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(label + '必须是可序列化的有限数据') from exc
    if len(encoded.encode('utf-8')) > maximum_bytes:
        raise ValueError(label + '超过体积限制')
    return value


def canonical_model(record):
    """Compute a saved result from its authoritative assumptions, never a cache."""
    method = record.get('method', '')
    if not isinstance(method, str) or (method and method not in ASSUMPTION_SCHEMAS):
        raise ValueError('不支持的估值方法')
    assumptions = validate_object(record.get('assumptions', {}), '模型假设')
    validate_object(record.get('result', {}), '模型结果')
    if not method:
        if assumptions or record.get('result'):
            raise ValueError('结构化模型必须指定估值方法')
        return None
    try:
        result = calculate_valuation(method, assumptions)
    except (TypeError, KeyError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('模型假设格式或数值超出可计算范围') from exc
    validate_object(result, '模型计算结果')
    return result


def validate_source_ids(value):
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError('资料来源编号最多200项')
    if any(not isinstance(item, str) or not item or len(item) > 100 for item in value):
        raise ValueError('资料来源编号必须为非空文本')
    if len(value) != len(set(value)):
        raise ValueError('资料来源编号不能重复')


def validate_coverage(value):
    keys = {'document_id', 'source_id', 'title', 'excerpt_chars', 'total_chars', 'truncated'}
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError('资料覆盖记录最多200项')
    for row in value:
        if not isinstance(row, dict) or set(row) != keys:
            raise ValueError('资料覆盖字段不完整或不支持')
        for key, limit in (('document_id', 100), ('source_id', 40), ('title', 200)):
            if not isinstance(row[key], str) or not row[key] or len(row[key]) > limit:
                raise ValueError('资料覆盖 ' + key + ' 格式无效')
        if any(type(row[key]) is not int or not 0 <= row[key] <= 2_000_000 for key in ('excerpt_chars', 'total_chars')):
            raise ValueError('资料覆盖字符数必须为非负整数')
        if row['excerpt_chars'] > row['total_chars'] or not isinstance(row['truncated'], bool):
            raise ValueError('资料覆盖长度或截断状态无效')
    ids = [row['document_id'] for row in value]
    if len(ids) != len(set(ids)):
        raise ValueError('资料覆盖记录不能重复')


def validate_review_comments(value):
    allowed = {'id', 'body', 'author', 'created_at', 'status', 'version_label'}
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError('审阅意见最多200项')
    for comment in value:
        if not isinstance(comment, dict) or set(comment) - allowed:
            raise ValueError('审阅意见字段无效')
        if not isinstance(comment.get('body'), str) or not comment['body'].strip() or len(comment['body']) > 8000:
            raise ValueError('审阅意见正文不能为空且最多8000字')
        for key, limit in (('id', 100), ('author', 200), ('created_at', 50), ('version_label', 200)):
            if key in comment and (not isinstance(comment[key], str) or len(comment[key]) > limit):
                raise ValueError('审阅意见 ' + key + ' 格式无效')
        if 'status' in comment and comment['status'] not in ('open', 'resolved'):
            raise ValueError('审阅意见状态无效')
        if comment.get('created_at'):
            try:
                datetime.fromisoformat(comment['created_at'].replace('Z', '+00:00'))
            except ValueError as exc:
                raise ValueError('审阅意见时间格式无效') from exc


def compare_scenarios(method, assumptions, scenarios):
    """Recompute up to eight explicit cases without mutating baseline inputs."""
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 8:
        raise ValueError('请提供1至8个具名场景')
    validate_object(assumptions, '基准假设')
    baseline = canonical_model({'method': method, 'assumptions': assumptions})
    if baseline is None:
        raise ValueError('请选择估值方法')
    schema = ASSUMPTION_SCHEMAS[method]
    # Comparisons share one currency/unit/timeline. Converting these labels alone
    # would relabel amounts rather than change economics and is therefore unsafe.
    fixed = {'currency', 'unit', 'period', 'valuation_date', 'entry_date', 'exit_date',
             'as_of_date', 'source_notes'}
    allowed = (set(schema['required']) | set(schema['optional'])) - fixed
    names = set()
    results = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or set(scenario) != {'name', 'overrides'}:
            raise ValueError('每个场景必须包含 name 和 overrides')
        name = scenario['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('场景名称不能为空且最多100字')
        name = name.strip()
        if name.casefold() in names:
            raise ValueError('场景名称不能重复')
        names.add(name.casefold())
        overrides = validate_object(scenario['overrides'], '场景覆盖假设')
        if not overrides:
            raise ValueError('场景必须明确至少一个经济假设变化')
        unknown = sorted(set(overrides) - allowed)
        if unknown:
            raise ValueError('场景不能修改以下字段或单位/期间：' + '、'.join(unknown))
        case = {**copy.deepcopy(assumptions), **copy.deepcopy(overrides)}
        try:
            result = canonical_model({'method': method, 'assumptions': case})
        except ValueError as exc:
            raise ValueError('场景“' + name + '”：' + str(exc)) from exc
        results.append({'name': name, 'overrides': copy.deepcopy(overrides), 'result': result})
    return {'method': method, 'currency': baseline['currency'], 'unit': baseline['unit'],
            'baseline': baseline, 'scenarios': results,
            'warning': '每个场景均由相同本地公式独立重新计算；币种、单位和期间沿用基准。模型范围及简化沿用基准结果中的说明。'}
