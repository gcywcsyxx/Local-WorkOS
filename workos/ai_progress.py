"""Public execution milestones and explicitly approximate timing, never reasoning."""
from __future__ import annotations
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import math
import re
import threading
import time

MAX_EVENTS = 80
_current = threading.local()
LABELS = {'pending':'等待请求', 'queued':'等待运行', 'prepare':'准备资料', 'context':'读取对话上下文',
    'read':'读取选定资料', 'provider':'等待模型响应', 'generate':'生成正文', 'check':'检查输出',
    'review':'复核内容', 'repair':'修订问题', 'save':'保存结果', 'action':'执行已授权操作', 'archive':'同步项目交付物',
    'dsh':'运行受限研究工具', 'completed':'已完成', 'cancelled':'已停止', 'failed':'处理失败',
    'interrupted':'服务中断'}
TERMINAL = {'completed','cancelled','failed','interrupted'}
RANGES = {'ask':(8,60), 'actions':(15,180), 'agent':(15,180), 'meeting':(15,150),
          'valuation':(8,90), 'workflow':(20,120), 'plan':(1,5), 'model-check':(2,90)}


def _iso(timestamp):
    return datetime.fromtimestamp(timestamp,timezone.utc).isoformat(timespec='milliseconds')


def safe_detail(detail):
    if not isinstance(detail,str):raise ValueError('执行进度只接受公开的简短说明')
    text = re.sub(r'[\x00-\x1f\x7f]', ' ', detail)
    text = re.sub(r'(?i)\b(?:api[_-]?key|authorization|password|access_token)\s*[=:]\s*\S+', '[凭证隐藏]', text)
    text = re.sub(r'(?i)\bbearer\s+\S+|\bsk-[a-z0-9_-]{8,}', '[凭证隐藏]', text)
    text = re.sub(r'[A-Za-z]:[\\/][^\s;，。]+', '[本机路径隐藏]', text)
    return text.strip()[:200]


def new_execution(kind='ask',model_id='',quality_mode='fast',status='pending',planned_stages=()):
    timestamp=time.time()
    return {'kind':str(kind)[:40], 'model_id':str(model_id)[:100], 'quality_mode':quality_mode,
        '_created_ts':timestamp, '_started_ts':None, '_finished_ts':None, '_stage_ts':timestamp,
        'started_at':None, 'finished_at':None, 'stage':status, 'stage_label':LABELS.get(status,status),
        'status':status, 'events':[], 'event_sequence':0,
        'stage_statuses':{stage:'pending' for stage in planned_stages}}


def add_event(execution,stage,detail='',status='running'):
    if not isinstance(stage,str) or stage not in LABELS:raise ValueError('执行阶段无效；不能公开模型内部推理')
    if status not in ('pending','queued','running','completed','skipped','cancelled','failed','interrupted'):
        raise ValueError('执行阶段状态无效')
    text=safe_detail(detail)
    timestamp=time.time()
    if execution.get('_finished_ts') is not None:return
    if status=='running' and execution.get('_started_ts') is None:
        execution['_started_ts']=timestamp;execution['started_at']=_iso(timestamp)
    if execution.get('stage')!=stage:execution['_stage_ts']=timestamp
    execution.update(stage=stage,stage_label=LABELS[stage])
    if stage in execution.get('stage_statuses',{}):execution['stage_statuses'][stage]=status
    execution['event_sequence']=execution.get('event_sequence',0)+1
    elapsed=max(0,round((timestamp-execution['_created_ts'])*1000))
    event={'sequence':execution['event_sequence'],'at':_iso(timestamp),'elapsed_ms':elapsed,
           'stage':stage,'label':LABELS[stage],'status':status,'detail':text}
    # Native heartbeats may repeat a phase; record each new meaningful detail
    # once and keep the sequence/timing of actual callbacks bounded.
    events=execution.setdefault('events',[])
    if not events or any(events[-1].get(key)!=event[key] for key in ('stage','status','detail')):
        events.append(event);del events[:-MAX_EVENTS]


def finish_execution(execution,status):
    if status not in TERMINAL:raise ValueError('结束状态无效')
    if execution.get('_finished_ts') is None:
        add_event(execution,status,LABELS[status],status)
        execution['_finished_ts']=time.time()
        execution['finished_at']=_iso(execution['_finished_ts'])
    execution['status']=status


def public_execution(execution,status=None):
    state=copy.deepcopy(execution)
    status=status or state.get('status','pending')
    current=state.get('_finished_ts') or time.time()
    elapsed=max(0,round((current-state['_created_ts'])*1000))
    low,high=RANGES.get(state.get('kind'),(10,120))
    if state.get('kind')=='workflow' and state.get('quality_mode')=='thorough':low,high=60,300
    if str(state.get('model_id','')).startswith('gpt-'):low,high=low*1.5,high*1.5
    if status in TERMINAL:
        eta={'min_seconds':0,'max_seconds':0,'estimated':True,'basis':'工作已经结束'}
    elif status in ('queued','pending'):
        eta={'min_seconds':None,'max_seconds':None,'estimated':True,'basis':'排队时间未知；尚未开始模型调用'}
    else:
        factor={'check':.25,'save':.06,'review':.55,'repair':.8}.get(state.get('stage'),1)
        phase_elapsed=max(0,current-state.get('_stage_ts',current))
        remaining_high=max(0,math.ceil(high*factor-phase_elapsed))
        eta={'min_seconds':max(0,math.floor(low*factor-phase_elapsed)),
             'max_seconds':remaining_high or None,'estimated':True,
             'basis':'按任务类型估计，会随执行阶段更新；受模型速度与资料规模影响'}
        if not remaining_high:eta['basis']='已超过初始估计；模型仍在运行，目前无法可靠预计剩余时间'
    stages=state.get('stage_statuses',{})
    done=sum(value in ('completed','skipped') for value in stages.values())
    percent=100 if status=='completed' else (round(100*done/len(stages)) if stages else None)
    return {'kind':state.get('kind','ask'),'status':status,'started_at':state.get('started_at'),
        'finished_at':state.get('finished_at'),'elapsed_ms':elapsed,'eta':eta,
        'stage':state.get('stage','pending'),'stage_label':state.get('stage_label','等待请求'),
        'progress_percent':percent,'progress_basis':'已完成的执行阶段；不代表模型token进度' if stages else '模型内部进度未知',
        'events':state.get('events',[]),'logs':state.get('events',[])}


@contextmanager
def bind_progress(reporter):
    previous=getattr(_current,'reporter',None)
    _current.reporter=reporter
    try:yield
    finally:_current.reporter=previous


def report_progress(stage,detail='',status='running'):
    """Called only with server-authored summaries, never model streams/tool args."""
    reporter=getattr(_current,'reporter',None)
    if reporter:reporter(stage,detail,status)
