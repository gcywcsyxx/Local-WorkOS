"""Short-lived workflow retry guard; no source text or results are written to disk."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import re
import threading


class WorkflowBusy(ValueError):
    """The same request is already executing; callers can retry its original id."""


@contextmanager
def exclusive_model_run(lock):
    """Reject a busy DSH process instead of queuing beyond the HTTP deadline."""
    if not lock.acquire(blocking=False):
        raise ValueError('GPT 模型正在处理另一项工作，请稍后重试；尚未调用模型')
    try:
        yield
    finally:
        lock.release()


class WorkflowRuns:
    """Partition retries by workspace; completed entries clear on process restart."""
    def __init__(self, limit=32):
        self.limit = limit
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def run(self, workspace, body, execute):
        if not isinstance(body, dict):
            raise ValueError('工作流要求必须是对象')
        request_id = body.get('request_id')
        if request_id is None:
            return execute()
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', request_id):
            raise ValueError('工作请求编号需为8至100位字母、数字、下划线或连字符')
        payload = {key: value for key, value in body.items() if key != 'request_id'}
        try:
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError('工作流参数必须为有效JSON') from exc
        fingerprint = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        key = (workspace, request_id)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                if entry['fingerprint'] != fingerprint:
                    raise ValueError('工作请求编号已用于不同内容；修改工作要求后请使用新的编号')
                if entry['running']:
                    raise WorkflowBusy('这项工作仍在生成；请稍后使用原请求重试，避免重复草稿')
                return deepcopy(entry['result'])
            self._entries[key] = {'fingerprint': fingerprint, 'running': True}
        # No lock is held during provider calls, source validation, saving or mirror sync.
        try:
            result = execute()
            cached = deepcopy(result)
        except BaseException:
            with self._lock:
                self._entries.pop(key, None)
            raise
        with self._lock:
            self._entries[key] = {'fingerprint': fingerprint, 'running': False, 'result': cached}
            self._entries.move_to_end(key)
            finished = [item for item, value in self._entries.items() if not value['running']]
            for expired in finished[:-self.limit]:
                del self._entries[expired]
        return result
