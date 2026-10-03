"""Cooperative cancellation; committed actions are kept, late effects are blocked."""
from __future__ import annotations
import copy
from collections import OrderedDict
from contextlib import contextmanager
import re
import threading
import time
from .ai_progress import new_execution, add_event, finish_execution, public_execution, bind_progress, report_progress

_current = threading.local()


class CancelledError(ValueError):
    def __init__(self, steps=()):
        super().__init__('已停止本次工作')
        self.steps = copy.deepcopy(list(steps))


class OperationConflict(ValueError):
    pass


def validate_request_id(request_id):
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', request_id):
        raise ValueError('请求编号不正确')
    return request_id


class CancellationToken:
    def __init__(self, request_id=''):
        self.request_id = request_id
        self.lock = threading.RLock()
        self.event = threading.Event()
        self.status = 'pending'
        self.steps = []
        self.completed_metadata = {}
        self.provisional_receipts = {}
        self.pinned = False
        self.touched = time.monotonic()
        self.execution = new_execution()
        self.progress_callback = None

    def check(self):
        if self.event.is_set():
            raise CancelledError(self.steps)

    @contextmanager
    def guard(self):
        # Cancellation and a local commit have a single ordering. Never hold this
        # lock across a model request, or acquire a job-manager lock inside it.
        with self.lock:
            self.check()
            yield

    def cancel(self):
        with self.lock:
            if self.status not in ('completed', 'failed'):
                self.event.set()
                self.status = 'cancelled'
                finish_execution(self.execution,'cancelled')
            self.touched = time.monotonic()
            return self.public()

    def public(self):
        return {**public_execution(self.execution,self.status),'request_id': self.request_id, 'status': self.status,
                'steps': copy.deepcopy(self.steps), **self.completed_metadata}

    def report(self,stage,detail='',status='running'):
        with self.lock:
            self.check()
            add_event(self.execution,stage,detail,status)
            callback=self.progress_callback
        if callback:callback(stage,detail,status)


@contextmanager
def bind_token(token):
    previous = getattr(_current, 'token', None)
    _current.token = token
    try:
        token.check()
        with bind_progress(token.report):yield token
        token.check()
    finally:
        _current.token = previous


def check_cancelled():
    token = getattr(_current, 'token', None)
    if token is not None:
        token.check()


def record_step(step):
    token = getattr(_current, 'token', None)
    if token is not None:
        with token.lock:
            # Agent is bounded to six rounds. Record an already committed action
            # even when a stop arrives between the commit and this receipt.
            key = _receipt_key(step)
            index = token.provisional_receipts.pop(key, None)
            if index is not None:
                token.steps[index] = copy.deepcopy(step)
            elif len(token.steps) < 6:
                token.steps.append(copy.deepcopy(step))


def _receipt_key(step):
    result = step.get('result') if isinstance(step, dict) else None
    if not isinstance(result, dict): return None
    item_id = result.get('id') or result.get('document_id')
    if isinstance(item_id, str) and item_id: return ('record', item_id)
    if step.get('action') == 'organize_project' and result.get('project_id'):
        return ('organize', result['project_id'])
    return None


def _committed_step(token, method, args, kwargs, result):
    # This receipt is recorded before releasing the commit guard. The full
    # agent step later enriches it, but Stop can already report the saved ID.
    if method == 'organize_project':
        step = {'action':'organize_project', 'args':{}, 'result':dict(result), 'say':'项目整理已完成'}
    else:
        collection = args[0] if args else kwargs.get('col')
        item_id = result.get('id') if isinstance(result, dict) else None
        if method == 'delete': item_id = args[1] if len(args)>1 else kwargs.get('id')
        if not isinstance(item_id, str) or not item_id: return
        title = str(result.get('name') or result.get('title') or '')[:200] if isinstance(result, dict) else ''
        action = ({'projects':'create_project', 'tasks':'create_task', 'notes':'create_note',
                   'meetings':'create_meeting', 'documents':'import_text', 'deliverables':'draft_deliverable'}
                  .get(collection, 'create_record')) if method == 'create' else method+'_'+str(collection)
        summary = {'id':item_id, 'summary':title}
        if method == 'delete': summary['deleted'] = True
        if collection == 'documents': summary.update(document_id=item_id, title=title)
        step = {'action':action, 'args':{}, 'result':summary, 'say':title or '记录已保存'}
    if len(token.steps) < 6:
        token.provisional_receipts[_receipt_key(step)] = len(token.steps)
        token.steps.append(step)


def cancellation_progress(callback=None):
    def progress(event):
        check_cancelled()
        result = callback(event) if callback else None
        check_cancelled()
        return result
    return progress


class CancellationStore:
    def __init__(self, real, token):
        self.real, self.token = real, token

    def __getattr__(self, name):
        value = getattr(self.real, name)
        if name in ('create', 'update', 'delete', 'organize_project'):
            def mutate(*args, **kwargs):
                with self.token.guard(), self.real.lock:
                    result = value(*args, **kwargs)
                    _committed_step(self.token, name, args, kwargs, result)
                    return result
            return mutate
        return value


class OperationRegistry:
    def __init__(self, max_active=32, max_finished=256, ttl=600):
        self.lock = threading.RLock()
        self.entries = OrderedDict()
        self.max_active, self.max_finished, self.ttl = max_active, max_finished, ttl
        self.closed = False

    def _prune(self):
        cutoff = time.monotonic() - self.ttl
        for key, token in list(self.entries.items()):
            if not token.pinned and token.status != 'running' and token.touched < cutoff:
                self.entries.pop(key)
        finished = [key for key, token in self.entries.items() if not token.pinned and token.status != 'running']
        for key in finished[:-self.max_finished]:
            self.entries.pop(key)

    def token(self, workspace, request_id):
        validate_request_id(request_id)
        with self.lock:
            if self.closed:
                raise ValueError('服务正在关闭，请稍后重试')
            self._prune()
            key = (workspace, request_id)
            if key not in self.entries:
                self.entries[key] = CancellationToken(request_id)
            return self.entries[key]

    def cancel(self, workspace, request_id):
        # A bounded tombstone handles Stop arriving before the request itself.
        return self.token(workspace, request_id).cancel()

    def get(self, workspace, request_id):
        validate_request_id(request_id)
        with self.lock:
            token=self.entries.get((workspace,request_id))
        if token is None:raise KeyError('执行记录不存在')
        with token.lock:return token.public()

    def list(self, workspace, limit=30):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('执行记录列表上限无效')
        with self.lock:
            tokens = [token for (scope, _), token in self.entries.items() if scope == workspace]
        records = []
        for index, token in enumerate(tokens):
            with token.lock:
                records.append((token.touched, index, token.public()))
        return [record for _, _, record in sorted(records, key=lambda item:(item[0],item[1]), reverse=True)[:limit]]

    def run(self, workspace, request_id, execute, *, kind='ask', model_id=''):
        if request_id is None:
            check_cancelled()
            return execute(None)
        with self.lock:
            token = self.token(workspace, request_id)
            with token.guard():
                if token.status != 'pending':
                    raise OperationConflict('该请求已开始或完成；请使用新的请求编号')
                if sum(t.status == 'running' for t in self.entries.values()) >= self.max_active:
                    raise ValueError('运行中的工作已满，请稍后重试')
                token.status = 'running'
                token.execution=new_execution(kind,model_id,status='running')
                add_event(token.execution,'prepare','开始处理本次工作')
        try:
            with bind_token(token):
                result = execute(token)
            with token.guard():
                token.status = 'completed'
                finish_execution(token.execution,'completed')
                token.touched = time.monotonic()
                return result
        except BaseException:
            with token.lock:
                if token.status != 'cancelled':
                    token.status = 'failed'
                    finish_execution(token.execution,'failed')
                token.touched = time.monotonic()
            raise

    def shutdown(self):
        with self.lock:
            self.closed = True
            tokens = list(self.entries.values())
        for token in tokens:
            token.cancel()
