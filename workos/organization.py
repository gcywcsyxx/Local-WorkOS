"""Local, bounded classification of project material; never changes source content.

The metadata is deliberately carried on existing records so version 1 backups remain
readable. Rules inspect filenames/titles and a short excerpt, without uploading files
or executing instructions contained in them.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

ORGANIZED_COLLECTIONS = ('documents', 'meetings', 'notes', 'deliverables', 'tasks')
ORGANIZATION_FIELDS = {
    'task_group', 'task_group_source', 'material_type', 'version_family',
    'version_label', 'organization_reason',
}
EMPTY_ORGANIZATION = dict(task_group='', task_group_source='automatic',
                          material_type='', version_family='', version_label='',
                          organization_reason='')
BUILTIN_GROUPS = ('投委会材料', '交易协议', '专家访谈', '基本面研究',
                  '财务与估值', '会议整理', '项目资料', '项目任务')

# Title evidence outweighs body evidence: an IC memo mentioning a financial model
# is still an IC memo. English words require boundaries to avoid matching fragments.
RULES = (
    ('交易协议', '协议', ('协议', '合同', '条款清单', 'term sheet', 'agreement',
                         'contract', 'spa', 'sha', 'nda', 'loi', '签署', '法律文件')),
    ('投委会材料', 'Memo', ('memo', 'memorandum', '投委', 'ic', 'ic memo', 'investment committee',
                          '投资备忘录', 'discussion material', 'posting', '投资建议书')),
    ('专家访谈', '访谈记录', ('专家访谈', '专家会', '访谈', 'expert interview',
                            'expert call', 'interview', 'channel check', '专家纪要')),
    ('财务与估值', '财务模型', ('财务模型', '估值', '测算', '财务预测', 'financial model',
                            'valuation', 'dcf', 'lbo', 'returns', '财务分析', '财务报表')),
    ('会议整理', '会议纪要', ('会议纪要', '会议记录', 'meeting notes', 'meeting minutes',
                            'minutes', '会议整理', 'management meeting')),
    ('基本面研究', '研究材料', ('基本面', '行业研究', '行业分析', '竞争格局', '市场研究',
                            '尽调', 'due diligence', 'research', '经营分析', '调研', '研究简报')),
)

_EXTENSION = re.compile(r'\.(?:docx?|pptx?|xlsx?|pdf|txt|md|csv|rtf|html?|json)$', re.I)
_DATE = re.compile(r'(?<!\d)(?:20\d{2}[年./_-](?:0?[1-9]|1[0-2])[月./_-](?:0?[1-9]|[12]\d|3[01])日?|20\d{6})(?!\d)')
_VERSION = re.compile(
    r'(?:(?<![a-z0-9])(?:v(?:ersion)?\s*\d+(?:\.\d+)*|rev(?:ision)?\s*[-_]?\s*[a-z0-9]+|'
    r'final(?:\s+version)?|revised|updated|draft(?:\s*\d+)?|redline|clean|signed)(?![a-z0-9])|'
    r'第?\s*[一二三四五六七八九十百\d]+\s*版|初稿|初版|草稿|修订稿|修订版|修改稿|修改版|'
    r'更新版|最终稿|最终版|终稿|终版|定稿|签署版|清洁版|对比版|修订|修改)', re.I)


def _text(value):
    return value if isinstance(value, str) else ''


def _contains(text, keyword):
    if keyword.isascii():
        return bool(re.search(r'(?<![a-z0-9])' + re.escape(keyword) + r'(?![a-z0-9])', text, re.I))
    return keyword in text


def evidence(record):
    name = ' '.join(_text(record.get(key))[:1000] for key in ('title', 'filename', 'attachment_name', 'category'))
    # Ingestion may be very large. Only a bounded prefix participates in rules.
    body = '\n'.join(_text(record.get(key))[:6000] for key in ('content', 'body', 'summary', 'transcript', 'description'))[:12000]
    return unicodedata.normalize('NFKC', name).lower(), unicodedata.normalize('NFKC', body).lower()


def version_identity(record):
    """Return a project-scoped stable family and readable version markers.

    Only suffix markers are removed. A date or the word "final" in the middle of
    a substantive name is not erased. Originals retain their title and filename.
    """
    raw = _text(record.get('filename')) or _text(record.get('attachment_name')) or _text(record.get('title'))
    # Both Windows and POSIX paths can occur in imported filenames.
    raw = raw.replace('\\', '/').rsplit('/', 1)[-1]
    raw = unicodedata.normalize('NFKC', raw).strip()
    raw = _EXTENSION.sub('', raw).strip()
    base = raw
    labels = []
    trim = ' \t._-—–()[]{}【】（）'
    for _ in range(16):
        stripped = base.rstrip(trim)
        candidates = [match for pattern in (_DATE, _VERSION) for match in pattern.finditer(stripped)
                      if match.end() == len(stripped)]
        if not candidates:
            base = stripped
            break
        marker = min(candidates, key=lambda match: match.start())
        labels.insert(0, marker.group(0).strip())
        base = stripped[:marker.start()].rstrip(trim)
    # Conservative fallback avoids grouping a nameless "v1" and "v2" together.
    if not base:
        base = raw
    base = re.sub(r'[\s_.—–-]+', ' ', base).strip().casefold()
    project = _text(record.get('project_id'))
    family = hashlib.sha256((project + '\x1f' + base).encode('utf-8')).hexdigest()[:24] if project and base else ''
    return family, ' · '.join(labels) or '原始版本'


def _custom_group(name, body, project_tasks):
    def phrase(value):
        normalized = unicodedata.normalize('NFKC', _text(value)).casefold()
        return re.sub(r'[\s_—–-]+', ' ', normalized).strip()

    name, body = phrase(name), phrase(body)
    candidates = []
    for task in project_tasks:
        group = _text(task.get('task_group')).strip()
        if task.get('task_group_source') != 'manual' or not group or group in BUILTIN_GROUPS:
            continue
        # Match a complete group/title phrase. Individual company names or common
        # task words (e.g. "Synthetic" / "Commercial") must not absorb a project.
        terms = {phrase(group), phrase(task.get('title'))}
        score = max((8 if _contains(name, term) else 6 if _contains(body, term) else 0
                     for term in terms if len(term) >= 2), default=0)
        if score >= 6:
            candidates.append((score, group))
    return sorted(candidates, key=lambda value: (-value[0], value[1]))[0][1] if candidates else ''


def organize_record(collection, record, project_tasks=(), linked=None):
    """Compute metadata only, honoring explicit group overrides within a project."""
    if collection not in ORGANIZED_COLLECTIONS:
        return {}
    if not record.get('project_id') or (collection == 'documents' and record.get('kind') == 'memory'):
        return dict(EMPTY_ORGANIZATION)
    name, body = evidence(record)
    ranked = []
    for group, material_type, keywords in RULES:
        matched_name = [keyword for keyword in keywords if _contains(name, keyword)]
        matched_body = [keyword for keyword in keywords if _contains(body, keyword)]
        score = len(matched_name) * 8 + min(len(matched_body), 4)
        if score:
            ranked.append((score, group, material_type, (matched_name or matched_body)[0]))
    if ranked:
        # Rules are stable for equal scores; filename/title clues are preferred.
        _, group, material_type, clue = max(ranked, key=lambda item: item[0])
        reason = '根据' + ('名称' if _contains(name, clue) else '正文') + '中的“' + clue + '”自动归类'
    else:
        group = {'notes': '基本面研究', 'meetings': '会议整理', 'tasks': '项目任务',
                 'deliverables': '基本面研究'}.get(collection, '项目资料')
        material_type = {'notes': 'Notes', 'meetings': '会议纪要', 'tasks': '任务',
                         'deliverables': '研究材料'}.get(collection, '资料')
        if _contains(name, 'notes') or '笔记' in name:
            material_type = 'Notes'
        reason = '根据资料类型自动归类'
    if collection == 'deliverables' and record.get('kind') == '会议纪要' and not ranked:
        group, material_type = '会议整理', '会议纪要'
    custom = _custom_group(name, body, project_tasks)
    if custom:
        group, reason = custom, '根据名称或正文自动归入项目内的子任务“' + custom + '”'
    elif linked and linked.get('project_id') == record.get('project_id') and linked.get('task_group'):
        group, reason = linked['task_group'], '沿用关联资料或会议的子任务'
    manual = record.get('task_group_source') == 'manual' and bool(_text(record.get('task_group')).strip())
    if manual:
        group, reason = record['task_group'].strip(), '已指定此项目内的子任务'
    family, label = version_identity(record) if collection in ('documents', 'notes', 'deliverables') else ('', '')
    return dict(task_group=group, task_group_source='manual' if manual else 'automatic',
                material_type=material_type, version_family=family, version_label=label,
                organization_reason=reason)
