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
from .cancellation import CancellationToken, OperationRegistry, CancelledError, bind_token, check_cancelled
from .ai_progress import new_execution, add_event, finish_execution, public_execution

STAGES = [('prepare', '准备资料'), ('generate', '生成正文'), ('check', '检查要求'),
          ('review', '复核内容'), ('repair', '修订问题'), ('save', '保存草稿')]
ACTIVE = ('queued', 'running')
PUBLIC_FIELDS = {'workflow_key', 'key', 'message', 'question', 'project_id', 'document_ids',
                 'mode', 'provider', 'model_id', 'quality_mode', 'request_id', 'sender_name',
                 'conversation_id', 'revision_of'}


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))


def _identity(doc):
    # Includes text and metadata used by the model, rather than timestamps alone.
    fields = ('id', 'project_id', 'kind', 'title', 'content', 'filename', 'source_ref',
              'version_label', 'version_family', 'chunks', 'hash')
    return hashlib.sha256(_encoded({key: doc.get(key) for key in fields}).encode()).hexdigest()


class FrozenStore:
    def __init__(self, real, snapshot, generation_id, active_check=None, token=None):
        self.real, self.snapshot, self.generation_id = real, snapshot, generation_id
        self.active_check = active_check
        self.token = token

    def get(self, collection, item_id):
        for item in self.snapshot.get(collection, []):
            if item['id'] == item_id:
                return copy.deepcopy(item)
        raise KeyError('记录不存在')

    def list(self, collection):
        return copy.deepcopy(self.snapshot.get(collection, []))

    def validate_current(self):
        if self.token: self.token.check()
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
        from contextlib import nullcontext
        with (self.token.guard() if self.token else nullcontext()), self.real.lock:
            saved = next((row for row in self.real.list('deliverables')
                          if row.get('generation_id') == self.generation_id), None)
            if not saved:
                self.validate_current()
                saved=self.real.create(collection, {**data, 'generation_id': self.generation_id})
            # This is the workflow's final commit. Stop may acknowledge the
            # saved result, but must not cancel its successful context append.
            if self.token:
                self.token.status='completed'
                self.token.completed_metadata.update(deliverable_id=saved['id'],saved=True)
            return saved


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
        self.cancellations = OperationRegistry(max_active=max_active)
        self.tokens = {}
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
                'conversation_id':record.get('conversation_id') or state.get('conversation_id') or '',
                'warning': '已恢复已保存的草稿；事实仍需核实。'}

    def _write(self, job_id, state):
        execution=state.setdefault('_execution',new_execution('workflow',state.get('model_id',''),state.get('quality_mode','fast'),
            status=state['status'],planned_stages=[key for key,_ in STAGES]))
        execution['stage_statuses']={item['key']:item['status'] for item in state['stages']}
        if state['status'] in ('completed','cancelled','failed','interrupted'):finish_execution(execution,state['status'])
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
            return self._public(self._row(workspace, job_id)[2])

    def _public(self,state):
        result=copy.deepcopy(state)
        execution=result.pop('_execution',None)
        if execution:result.update(public_execution(execution,state['status']))
        return result

    def list(self, workspace):
        if workspace not in self.app.stores: raise ValueError('工作区选择不正确')
        with self.lock:
            return [self._public(json.loads(row[0])) for row in self.db.execute(
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
        conversation_id=body.get('conversation_id','')
        if not isinstance(conversation_id,str) or len(conversation_id)>100:
            raise ValueError('对话编号无效')
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
            revision_of=body.get('revision_of')
            if revision_of:
                if not isinstance(revision_of,str) or len(revision_of)>100:raise ValueError('修订母稿编号无效')
                parent=store.get('deliverables',revision_of)
                if parent.get('project_id','')!=project_id:raise ValueError('修订母稿不属于当前项目')
                selected_ids={doc['id'] for doc in docs}
                if not set(parent.get('source_ids',[])).issubset(selected_ids):
                    raise ValueError('修订母稿引用了未选择的资料；请明确选择原资料后修订')
                snapshot['deliverables']=[parent]
                snapshot.setdefault('context_records',[]).append({'collection':'deliverables','record':parent})
            if len(_encoded(snapshot).encode()) > 12_000_000:
                raise ValueError('本次选定资料超过后台任务12MB文字预算，请分批研究；未截断或发送资料')
        # Conversation validation calls the real Store. Keep its lock outside
        # Store.lock to preserve append's conversation -> Store lock order.
        if conversation_id and hasattr(self.app,'conversations'):
            scope={'project_id':project_id,'purpose':'workflow','source_ids':[doc['id'] for doc in docs]}
            snapshot['conversation']={'id':conversation_id,**scope,
                'signature':self.app.conversations.signature(workspace,conversation_id,**scope)}
        return snapshot

    def _check_conversation(self,workspace,snapshot):
        conversation=snapshot.get('conversation')
        if not conversation:return
        current=self.app.conversations.signature(workspace,conversation['id'],project_id=conversation['project_id'],
            purpose=conversation['purpose'],source_ids=conversation['source_ids'])
        if current!=conversation['signature']:
            raise ValueError('任务对话已新增成功轮次或改变，请重新提交任务；没有使用后来的上下文')

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
                return self._public(json.loads(existing[1]))
            self._capacity()
            token = self.cancellations.token(workspace, request_id)
            token.check()
            snapshot = self._capture(workspace, body)
            token.check()
            job_id = uuid.uuid4().hex
            state = {'id': job_id, 'workflow_key': body.get('workflow_key') or body.get('key'),
                     'project_id': body.get('project_id') or '', 'message': body.get('message') or body.get('question'),
                     'document_ids': [doc['id'] for doc in snapshot['documents']],
                     'model_id': body.get('model_id') or '', 'mode': body.get('mode') or 'deepseek',
                     'quality_mode': body.get('quality_mode') or 'fast', 'status': 'queued', 'stage': 'prepare',
                     'conversation_id':body.get('conversation_id') or '', 'revision_of':body.get('revision_of') or '',
                     'attempt':1,
                     'stages': [{'key': key, 'label': label, 'status': 'pending', 'detail': ''} for key, label in STAGES],
                     'revision': 1, 'created_at': now(), 'updated_at': now(), 'error': '', 'retryable': False,
                     'poll_after_ms': 1500}
            state['_execution']=new_execution('workflow',state['model_id'],state['quality_mode'],status='queued',
                planned_stages=[key for key,_ in STAGES])
            add_event(state['_execution'],'queued','已进入后台任务队列','queued')
            with self.db:
                self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?)',
                    (job_id, workspace, request_id, fingerprint, encoded, _encoded(snapshot), _encoded(state)))
            self.tokens[job_id] = token
            token.pinned = True
            self.executor.submit(self._execute, workspace, job_id)
            return self._public(state)

    def retry(self, workspace, job_id):
        with self.lock:
            payload, snapshot, state = self._row(workspace, job_id)
            payload['_provider_identity'] = snapshot.get('provider_identity')
            if state['status'] not in ('failed', 'interrupted'):
                return self._public(state)
            saved = self._saved(workspace, job_id)
            if saved:
                state.update(status='completed', result=self._recover(saved, state), error='', retryable=False)
                self._write(job_id, state)
                return self._public(state)
            self._capacity()
            self._check_conversation(workspace,snapshot)
            FrozenStore(self.app.stores[workspace], snapshot, job_id).validate_current()
            state.update(status='queued', stage='prepare', error='', retryable=False)
            state['attempt']=state.get('attempt',1)+1
            state['stages'] = [{'key': key, 'label': label, 'status': 'pending', 'detail': ''} for key, label in STAGES]
            state['_execution']=new_execution('workflow',state['model_id'],state['quality_mode'],status='queued',
                planned_stages=[key for key,_ in STAGES])
            add_event(state['_execution'],'queued','重试原任务，等待运行','queued')
            self._write(job_id, state)
            self.tokens[job_id] = CancellationToken(payload['request_id'])
            self.executor.submit(self._execute, workspace, job_id)
            return self._public(state)

    def cancel_request(self, workspace, request_id):
        from .cancellation import validate_request_id
        validate_request_id(request_id)
        if workspace not in self.app.stores: raise ValueError('工作区选择不正确')
        with self.lock:
            row = self.db.execute('SELECT id FROM jobs WHERE workspace=? AND request_id=?',
                                  (workspace, request_id)).fetchone()
        if row: return {'job': self.cancel(workspace, row[0])}
        return self.cancellations.cancel(workspace, request_id)

    def cancel(self, workspace, job_id):
        # Do not hold jobs.lock while waiting for the token/Store commit guard.
        # FrozenStore.create never acquires jobs.lock inside Store.lock.
        with self.lock:
            state = self._row(workspace, job_id)[2]
            if state['status'] not in ACTIVE: return self._public(state)
            token = self.tokens.get(job_id)
        if token: token.cancel()
        with self.lock:
            state = self._row(workspace, job_id)[2]
            if state['status'] not in ACTIVE: return self._public(state)
            saved = self._saved(workspace, job_id)
            if saved:
                state.update(status='completed', result=self._recover(saved, state), error='', retryable=False)
            else:
                state.update(status='cancelled', error='已停止本次工作；草稿未保存', retryable=False)
            for item in state['stages']:
                if item['status'] == 'running':
                    item['status'] = 'completed' if saved else 'cancelled'
            self._write(job_id, state)
            if token: token.pinned = False
            self.tokens.pop(job_id, None)
            result = self._public(state)
        if saved: self.app.sync_workspace(workspace)
        return result

    def _progress(self, workspace, job_id, stage, detail='', status='running'):
        check_cancelled()
        with self.lock:
            if self.closed: raise ValueError('服务重启中断了任务；未保存后台结果')
            state = self._row(workspace, job_id)[2]
            if state['status'] == 'cancelled': raise CancelledError()
            if state['status'] not in ACTIVE: return
            for item in state['stages']:
                if item['key'] == stage:
                    item.update(status=status, detail=str(detail)[:500])
                elif item['status'] == 'running' and status == 'running':
                    item['status'] = 'completed'
            state.update(status='running', stage=stage)
            execution=state.setdefault('_execution',new_execution('workflow',state['model_id'],state['quality_mode'],
                status='running',planned_stages=[key for key,_ in STAGES]))
            add_event(execution,stage,detail,status)
            self._write(job_id, state)

    def _trace(self,workspace,job_id,stage,detail='',status='running'):
        check_cancelled()
        with self.lock:
            if self.closed:raise ValueError('服务重启中断了任务；未保存后台结果')
            state=self._row(workspace,job_id)[2]
            if state['status']=='completed':return
            if state['status'] not in ACTIVE:raise CancelledError()
            add_event(state['_execution'],stage,detail,status)
            self._write(job_id,state)

    def _execute(self, workspace, job_id):
        from .workflows import run_workflow
        with self.lock:
            if self.closed: return
            payload, snapshot, state = self._row(workspace, job_id)
            if state['status'] not in ACTIVE: return
            token = self.tokens.setdefault(job_id, CancellationToken(payload['request_id']))
            token.progress_callback=lambda stage,detail='',status='running':self._trace(workspace,job_id,stage,detail,status)
            payload['_provider_identity'] = snapshot.get('provider_identity')
            # A retry is a distinct visible conversation attempt, while the
            # durable submission/cancellation identity and generation stay fixed.
            if hasattr(self.app,'contextual_call'):
                payload['request_id']='job-'+job_id+'-attempt-'+str(state.get('attempt',1))
            if snapshot.get('conversation'):
                payload['conversation_id']=snapshot['conversation']['id']
                payload['_conversation_signature']=snapshot['conversation']['signature']
        try:
            frozen = FrozenStore(self.app.stores[workspace], snapshot, job_id, active_check=lambda: not self.closed, token=token)
            frozen.validate_current()
            if snapshot.get('provider_identity') != provider_identity(self.app, payload):
                raise ValueError('模型服务配置已变更，请重新创建任务；没有自动切换模型')
            self._check_conversation(workspace,snapshot)
            with bind_token(token):
                with token.guard(): token.status = 'running'
                def execute(prepared):
                    context=prepared.get('_context')
                    if context and prepared.get('conversation_id'):
                        check_cancelled()
                        with self.lock:
                            if self.closed:raise ValueError('服务重启中断了任务；未保存后台结果')
                            current=self._row(workspace,job_id)[2]
                            if current['status'] not in ACTIVE:raise CancelledError()
                            current['conversation_id']=prepared['conversation_id']
                            if not snapshot.get('conversation'):
                                snapshot['conversation']={'id':prepared['conversation_id'],'project_id':prepared.get('project_id',''),
                                    'purpose':'workflow','source_ids':list(prepared.get('document_ids',[])),
                                    'signature':context['context_signature']}
                                with self.db:self.db.execute('UPDATE jobs SET snapshot=? WHERE id=?',(_encoded(snapshot),job_id))
                            self._write(job_id,current)
                    return run_workflow(self.app, frozen, prepared,
                        progress=lambda stage, detail='', status='running': self._progress(workspace, job_id, stage, detail, status))
                result = (self.app.contextual_call(workspace, 'workflow', frozen, payload, execute)
                          if hasattr(self.app, 'contextual_call') else execute(payload))
            with self.lock:
                if self.closed: return
                state = self._row(workspace, job_id)[2]
                if state['status'] not in ACTIVE: return
                state.update(status='completed', stage='save', result=result, retryable=False, error='',
                    conversation_id=result.get('conversation_id') or state.get('conversation_id',''))
                for item in state['stages']:
                    if item['status'] == 'running': item['status'] = 'completed'
                    elif item['status'] == 'pending': item['status'] = 'skipped'
                self._write(job_id, state)
                token.status = 'completed'
                token.pinned = False
                self.tokens.pop(job_id, None)
            self.app.sync_workspace(workspace)
        except Exception as exc:
            logging.warning('Background workflow failed (%s)', type(exc).__name__)
            with self.lock:
                if self.closed: return
                state = self._row(workspace, job_id)[2]
                if state['status'] not in ACTIVE: return
                saved = self._saved(workspace, job_id)
                if saved:
                    state.update(status='completed', result=self._recover(saved, state), retryable=False, error='')
                elif isinstance(exc, CancelledError):
                    state.update(status='cancelled', error='已停止本次工作；草稿未保存', retryable=False)
                    for item in state['stages']:
                        if item['status'] == 'running': item['status'] = 'cancelled'
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
                    token.status = 'failed'
                self._write(job_id, state)
                token.status = state['status']
                token.pinned = False
                self.tokens.pop(job_id, None)

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
