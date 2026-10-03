"""Durable, workspace-scoped background work with immutable input snapshots.

Only explicit evidence is captured. A generation ID bridges the two databases
so a process restart after saving cannot create a duplicate deliverable.
"""
from __future__ import annotations
import copy
import hashlib
import json
import logging
import re
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from .store import now
from .workflows import RECIPES, _selected_documents, _project_context, provider_identity

STAGES = [('prepare', '准备资料'), ('generate', '生成正文'), ('check', '检查要求'),
          ('review', '复核内容'), ('repair', '修订问题'), ('save', '保存草稿')]
ACTIVE = ('queued', 'running')
PUBLIC_FIELDS = {'workflow_key', 'key', 'message', 'question', 'project_id', 'document_ids',
                 'mode', 'provider', 'model_id', 'quality_mode', 'request_id', 'sender_name'}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def _identity(doc):
    # Includes text and metadata used by the model, rather than timestamps alone.
    fields = ('id', 'project_id', 'kind', 'title', 'content', 'filename', 'source_ref',
              'version_label', 'version_family', 'chunks', 'hash')
    return hashlib.sha256(_encoded({key: doc.get(key) for key in fields}).encode()).hexdigest()


class FrozenStore:
    def __init__(self, real, snapshot, generation_id, active_check=None):
        self.real, self.snapshot, self.generation_id = real, snapshot, generation_id
        self.active_check = active_check

    def get(self, collection, item_id):
        for item in self.snapshot.get(collection, []):
            if item['id'] == item_id:
                return copy.deepcopy(item)
        raise KeyError('记录不存在')

    def list(self, collection):
        return copy.deepcopy(self.snapshot.get(collection, []))

    def validate_current(self):
        if self.active_check and not self.active_check():
            raise ValueError('服务重启中断了任务；未保存后台结果')
        if self.snapshot.get('projects'):
            self.real.get('projects', self.snapshot['projects'][0]['id'])
        for original in self.snapshot.get('documents', []):
            try:
                current = self.real.get('documents', original['id'])
            except KeyError as exc:
                raise ValueError('任务资料已删除，请重新选择资料并创建任务') from exc
            if _identity(original) != _identity(current):
                raise ValueError('任务资料已变更，请重新选择资料并创建任务；未保存过期资料引用')
        for entry in self.snapshot.get('context_records', []):
            try: current = self.real.get(entry['collection'], entry['record']['id'])
            except KeyError as exc: raise ValueError('任务项目记录已删除，请重新创建任务') from exc
            if current != entry['record']:
                raise ValueError('任务项目记录已变更，请重新创建任务；未保存过期项目更新')
        for entry in self.snapshot.get('context_sources', []):
            try: current = self.real.get('documents', entry['id'])
            except KeyError as exc: raise ValueError('项目记录关联资料已删除，请重新创建任务') from exc
            if _identity(current) != entry['identity'] or current.get('kind') == 'memory':
                raise ValueError('项目记录关联资料已变更，请重新创建任务')

    def create(self, collection, data):
        if collection != 'deliverables':
            raise ValueError('后台工作只能保存交付草稿')
        with self.real.lock:
            saved = next((row for row in self.real.list('deliverables')
                          if row.get('generation_id') == self.generation_id), None)
            if saved:
                return saved
            self.validate_current()
            return self.real.create(collection, {**data, 'generation_id': self.generation_id})


class WorkflowJobs:
    def __init__(self, app, path, workers=2, max_active=8):
        self.app, self.max_active = app, max_active
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, '
                        'request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, '
                        'snapshot TEXT NOT NULL, state TEXT NOT NULL, UNIQUE(workspace,request_id))')
        self.db.commit()
        self.closed = False
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='workos-draft')
        with self.lock:
            for job_id, workspace, raw in self.db.execute('SELECT id,workspace,state FROM jobs').fetchall():
                state = json.loads(raw)
                if state['status'] not in ACTIVE:
                    continue
                saved = self._saved(workspace, job_id)
                if saved:
                    state.update(status='completed', stage='save', result=self._recover(saved, state),
                                 error='', retryable=False)
                    for stage in state['stages']:
                        if stage['status'] == 'running': stage['status'] = 'completed'
                else:
                    state.update(status='interrupted', error='服务重启中断了任务；可重试原任务，避免重复保存', retryable=True)
                    for stage in state['stages']:
                        if stage['status'] == 'running': stage['status'] = 'interrupted'
                self._write(job_id, state)

    def _saved(self, workspace, job_id):
        return next((row for row in self.app.stores[workspace].list('deliverables')
                     if row.get('generation_id') == job_id), None)

    def _recover(self, record, state):
        return {'answer': record['body'], 'body': record['body'], 'title': record['title'],
                'id': record['id'], 'deliverable_id': record['id'], 'deliverable': record,
                'quality_report': record.get('quality_report', {}), 'workflow_key': record.get('workflow_key'),
                'source_ids': record.get('source_ids', []), 'coverage': record.get('coverage', []),
                'citations': [], 'question': state['message'], 'project_id': state['project_id'],
                'model': state['model_id'], 'mode': state['mode'],
                'warning': '已恢复已保存的草稿；事实仍需核实。'}

    def _write(self, job_id, state):
        state['updated_at'] = now()
        state['revision'] = state.get('revision', 0) + 1
        with self.db:
            self.db.execute('UPDATE jobs SET state=? WHERE id=?', (_encoded(state), job_id))

    def _row(self, workspace, job_id):
        if workspace not in self.app.stores: raise ValueError('工作区选择不正确')
        row = self.db.execute('SELECT payload,snapshot,state FROM jobs WHERE workspace=? AND id=?',
                              (workspace, job_id)).fetchone()
        if not row: raise KeyError('任务不存在')
        return tuple(json.loads(value) for value in row)

    def get(self, workspace, job_id):
        with self.lock:
            return self._row(workspace, job_id)[2]

    def list(self, workspace):
        if workspace not in self.app.stores: raise ValueError('工作区选择不正确')
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(
                'SELECT state FROM jobs WHERE workspace=? ORDER BY rowid DESC LIMIT 30', (workspace,))]

    def _capture(self, workspace, body):
        if not isinstance(body, dict): raise ValueError('工作流要求必须是对象')
        key = body.get('workflow_key') or body.get('key')
        message = body.get('message') or body.get('question') or ''
        if not isinstance(key, str) or key not in RECIPES: raise ValueError('请选择有效的工作类型')
        if not isinstance(message, str) or not message.strip() or len(message) > 12000:
            raise ValueError('请输入1至12000字的工作要求')
        if body.get('quality_mode', 'fast') not in ('fast', 'thorough'):
            raise ValueError('质量模式无效')
        if body.get('mode', 'deepseek') not in ('deepseek', 'local-models', 'model', 'dsh'):
            raise ValueError('请选择可用的AI模型')
        store = self.app.stores[workspace]
        with store.lock:
            project_id, docs = _selected_documents(store, body)
            if RECIPES[key][3] and not docs: raise ValueError('这项工作需要明确选择研究资料')
            if key == 'compare' and len(docs) < 2: raise ValueError('版本对照至少需要两份材料')
            project = [store.get('projects', project_id)] if project_id else []
            context = _project_context(store, project_id) if key == 'weekly' else ''
            if key == 'weekly' and not docs and not context: raise ValueError('项目更新需要已有记录或选定材料')
            # Freeze only the records this recipe reads; no memory is captured.
            snapshot = {'documents': docs, 'projects': project, 'project_context': context}
            snapshot['provider_identity'] = provider_identity(self.app, body)
            if key == 'weekly' and project_id:
                memory_ids = {doc['id'] for doc in store.list('documents') if doc.get('kind') == 'memory'}
                records = []
                for collection in ('notes', 'tasks', 'meetings'):
                    for row in store.list(collection):
                        if row.get('project_id') == project_id and row.get('document_id') not in memory_ids:
                            records.append({'collection': collection, 'record': row})
                snapshot['context_records'] = records[:40]
                source_ids = {entry['record'].get('document_id') for entry in records[:40] if entry['record'].get('document_id')}
                snapshot['context_sources'] = [{'id': source_id, 'identity': _identity(store.get('documents', source_id))}
                                               for source_id in sorted(source_ids)]
            if len(_encoded(snapshot).encode()) > 12_000_000:
                raise ValueError('本次选定资料超过后台任务12MB文字预算，请分批研究；未截断或发送资料')
        return snapshot

    def _capacity(self):
        if self.closed: raise ValueError('服务正在关闭，请稍后重试')
        count = sum(json.loads(row[0])['status'] in ACTIVE for row in self.db.execute('SELECT state FROM jobs'))
        if count >= self.max_active: raise ValueError('后台任务已满，请等待已有任务完成')

    def submit(self, workspace, body):
        if workspace not in self.app.stores: raise ValueError('工作区选择不正确')
        if not isinstance(body, dict): raise ValueError('工作流要求必须是对象')
        if set(body) - PUBLIC_FIELDS: raise ValueError('后台任务包含不支持的字段；凭证不能写入任务')
        request_id = body.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', request_id):
            raise ValueError('后台任务需要有效的请求编号')
        encoded = _encoded(body)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        with self.lock:
            existing = self.db.execute('SELECT fingerprint,state FROM jobs WHERE workspace=? AND request_id=?',
                                       (workspace, request_id)).fetchone()
            if existing:
                if existing[0] != fingerprint: raise ValueError('请求编号已用于不同工作要求，请创建新任务')
                return json.loads(existing[1])
            self._capacity()
            snapshot = self._capture(workspace, body)
            job_id = uuid.uuid4().hex
            state = {'id': job_id, 'workflow_key': body.get('workflow_key') or body.get('key'),
                     'project_id': body.get('project_id') or '', 'message': body.get('message') or body.get('question'),
                     'document_ids': [doc['id'] for doc in snapshot['documents']],
                     'model_id': body.get('model_id') or '', 'mode': body.get('mode') or 'deepseek',
                     'quality_mode': body.get('quality_mode') or 'fast', 'status': 'queued', 'stage': 'prepare',
                     'stages': [{'key': key, 'label': label, 'status': 'pending', 'detail': ''} for key, label in STAGES],
                     'revision': 1, 'created_at': now(), 'updated_at': now(), 'error': '', 'retryable': False,
                     'poll_after_ms': 1500}
            with self.db:
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                    (job_id, workspace, request_id, fingerprint, encoded, _encoded(snapshot), _encoded(state)))
            self.executor.submit(self._execute, workspace, job_id)
            return copy.deepcopy(state)

    def retry(self, workspace, job_id):
        with self.lock:
            payload, snapshot, state = self._row(workspace, job_id)
            payload['_provider_identity'] = snapshot.get('provider_identity')
            if state['status'] not in ('failed', 'interrupted'):
                return state
            saved = self._saved(workspace, job_id)
            if saved:
                state.update(status='completed', result=self._recover(saved, state), error='', retryable=False)
                self._write(job_id, state)
                return state
            self._capacity()
            FrozenStore(self.app.stores[workspace], snapshot, job_id).validate_current()
            state.update(status='queued', stage='prepare', error='', retryable=False)
            state['stages'] = [{'key': key, 'label': label, 'status': 'pending', 'detail': ''} for key, label in STAGES]
            self._write(job_id, state)
            self.executor.submit(self._execute, workspace, job_id)
            return copy.deepcopy(state)

    def _progress(self, workspace, job_id, stage, detail='', status='running'):
        with self.lock:
            if self.closed: raise ValueError('服务重启中断了任务；未保存后台结果')
            state = self._row(workspace, job_id)[2]
            if state['status'] not in ACTIVE: return
            for item in state['stages']:
                if item['key'] == stage:
                    item.update(status=status, detail=str(detail)[:500])
                elif item['status'] == 'running' and status == 'running':
                    item['status'] = 'completed'
            state.update(status='running', stage=stage)
            self._write(job_id, state)

    def _execute(self, workspace, job_id):
        from .workflows import run_workflow
        with self.lock:
            if self.closed: return
            payload, snapshot, state = self._row(workspace, job_id)
            payload['_provider_identity'] = snapshot.get('provider_identity')
        try:
            frozen = FrozenStore(self.app.stores[workspace], snapshot, job_id, active_check=lambda: not self.closed)
            frozen.validate_current()
            if snapshot.get('provider_identity') != provider_identity(self.app, payload):
                raise ValueError('模型服务配置已变更，请重新创建任务；没有自动切换模型')
            result = run_workflow(self.app, frozen, payload,
                progress=lambda stage, detail='', status='running': self._progress(workspace, job_id, stage, detail, status))
            with self.lock:
                if self.closed: return
                state = self._row(workspace, job_id)[2]
                state.update(status='completed', stage='save', result=result, retryable=False, error='')
                for item in state['stages']:
                    if item['status'] == 'running': item['status'] = 'completed'
                    elif item['status'] == 'pending': item['status'] = 'skipped'
                self._write(job_id, state)
            self.app.sync_workspace(workspace)
        except Exception as exc:
            logging.warning('Background workflow failed (%s)', type(exc).__name__)
            with self.lock:
                if self.closed: return
                state = self._row(workspace, job_id)[2]
                saved = self._saved(workspace, job_id)
                if saved:
                    state.update(status='completed', result=self._recover(saved, state), retryable=False, error='')
                else:
                    # Never surface provider internals, prompts, credentials or source excerpts.
                    if state['stage'] in ('prepare', 'save') and isinstance(exc, (ValueError, KeyError)):
                        safe = str(exc)[:700]
                    elif isinstance(exc, ValueError) and str(exc).startswith(('模型服务配置已变更', '审阅模型没有返回有效JSON', '复核仍有阻断问题', '正文未通过明确要求校验')):
                        safe = str(exc)[:700]
                    else:
                        safe = '模型生成或复核未完成，草稿未保存；请减少范围或更换模型后重试。'
                    state.update(status='failed', error=safe, retryable=True)
                    for item in state['stages']:
                        if item['status'] == 'running': item['status'] = 'failed'
                self._write(job_id, state)

    def begin_shutdown(self):
        with self.lock:
            if self.closed: return
            self.closed = True
            for job_id, workspace, raw in self.db.execute('SELECT id,workspace,state FROM jobs').fetchall():
                state = json.loads(raw)
                if state['status'] not in ACTIVE: continue
                saved = self._saved(workspace, job_id)
                if saved:
                    state.update(status='completed', result=self._recover(saved, state), retryable=False, error='')
                else:
                    state.update(status='interrupted', retryable=True, error='服务重启中断了任务；可按原任务重试')
                    for item in state['stages']:
                        if item['status'] == 'running': item['status'] = 'interrupted'
                self._write(job_id, state)

    def close(self):
        self.begin_shutdown()
        self.executor.shutdown(wait=True)
        with self.lock: self.db.close()
