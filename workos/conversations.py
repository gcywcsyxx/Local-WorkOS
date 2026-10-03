"""Durable explicit-scope conversation history and artifact revision snapshots."""
from __future__ import annotations
import copy
import hashlib
import json
import re
import sqlite3
import threading
import uuid
from .store import now

PURPOSES={'ask','actions','meeting','valuation','workflow'}
STATUSES={'completed','cancelled','failed','interrupted'}
ARTIFACT_COLLECTIONS={'documents','notes','tasks','meetings','deliverables'}
SECRET_KEYS={'api_key','authorization','password','credentials','access_token','refresh_token'}


def _text(value,label,maximum,empty=True):
    if not isinstance(value,str) or len(value)>maximum or (not empty and not value.strip()):
        raise ValueError(label+'格式无效或超过限制')
    return value


def _ids(values):
    if not isinstance(values,(list,tuple)) or len(values)>80 or any(not isinstance(value,str) or not value or len(value)>100 for value in values):
        raise ValueError('对话资料范围无效；最多80份明确选定资料')
    return sorted(set(values))


def _json(value,maximum=20000):
    if not isinstance(value,dict):raise ValueError('对话元数据或快照必须是对象')
    def visit(item,depth=0):
        if depth>14:raise ValueError('对话快照层级过深')
        if isinstance(item,dict):
            if any(not isinstance(key,str) or key.casefold() in SECRET_KEYS for key in item):
                raise ValueError('凭证不能写入对话记录')
            for nested in item.values():visit(nested,depth+1)
        elif isinstance(item,list):
            for nested in item:visit(nested,depth+1)
    visit(value)
    try:raw=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    except (ValueError,TypeError) as exc:raise ValueError('对话快照必须是有限JSON数据') from exc
    if len(raw.encode())>maximum:raise ValueError('对话快照超过大小限制')
    return json.loads(raw)


class Conversations:
    def __init__(self,path,stores=None):
        self.stores=stores
        self.lock=threading.RLock()
        self.db=sqlite3.connect(path,check_same_thread=False,timeout=20)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, '
            'project_id TEXT NOT NULL, purpose TEXT NOT NULL, payload TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS conversation_turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, '
            'workspace TEXT NOT NULL, sequence INTEGER NOT NULL, request_id TEXT, payload TEXT NOT NULL, '
            'UNIQUE(conversation_id,request_id))')
        if 'status' not in [row[1] for row in self.db.execute('PRAGMA table_info(conversation_turns)')]:
            self.db.execute("ALTER TABLE conversation_turns ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
            for item_id,raw in self.db.execute('SELECT id,payload FROM conversation_turns').fetchall():
                self.db.execute('UPDATE conversation_turns SET status=? WHERE id=?',(json.loads(raw)['status'],item_id))
        if 'message_chars' not in [row[1] for row in self.db.execute('PRAGMA table_info(conversation_turns)')]:
            self.db.execute('ALTER TABLE conversation_turns ADD COLUMN message_chars INTEGER NOT NULL DEFAULT 0')
            for item_id,raw in self.db.execute('SELECT id,payload FROM conversation_turns').fetchall():
                turn=json.loads(raw)
                self.db.execute('UPDATE conversation_turns SET message_chars=? WHERE id=?',
                    (len(turn['user_message'])+len(turn['assistant_message']),item_id))
        self.db.commit()

    def _workspace(self,workspace):
        _text(workspace,'工作区',40,False)
        if self.stores is not None and workspace not in self.stores:raise ValueError('工作区选择不正确')

    def _sources(self,workspace,project_id,source_ids):
        self._workspace(workspace)
        _text(project_id,'项目编号',100)
        source_ids=_ids(source_ids)
        if self.stores is not None:
            store=self.stores[workspace]
            if project_id:store.get('projects',project_id)
            for item_id in source_ids:
                document=store.get('documents',item_id)
                if document.get('kind')=='memory':raise ValueError('个人记忆不能加入模型对话上下文')
                if project_id and document.get('project_id') not in ('',project_id):raise ValueError('对话资料不属于当前项目')
        return source_ids

    def _artifact(self,workspace,project_id,source_ids,value):
        value=_json(value)
        if not value:return value
        if set(value)-{'collection','id','version','revision','updated_at'}:raise ValueError('交付物引用字段无效')
        if not isinstance(value.get('collection'),str) or value.get('collection') not in ARTIFACT_COLLECTIONS:raise ValueError('交付物引用类型无效')
        _text(value.get('id'),'交付物编号',100,False)
        for key in ('version','revision'):
            if key in value and not ((isinstance(value[key],str) and len(value[key])<=100) or
                                     (type(value[key]) is int and value[key]>=0)):
                raise ValueError('交付物版本无效')
        if 'updated_at' in value:_text(value['updated_at'],'交付物时间',80)
        if self.stores is not None:
            item=self.stores[workspace].get(value['collection'],value['id'])
            if item.get('project_id','')!=project_id:raise ValueError('交付物不属于当前对话项目')
            if item.get('kind')=='memory':raise ValueError('个人记忆不能作为模型对话交付物')
            linked=item.get('source_ids',[])+([item['document_id']] if item.get('document_id') else [])
            if not set(linked).issubset(source_ids):raise ValueError('交付物引用了当前对话未选择的资料')
        return value

    def _record(self,workspace,conversation_id):
        self._workspace(workspace)
        _text(conversation_id,'对话编号',100,False)
        row=self.db.execute('SELECT payload FROM conversations WHERE workspace=? AND id=?',(workspace,conversation_id)).fetchone()
        if not row:raise KeyError('对话不存在')
        return json.loads(row[0])

    def _scope(self,record,project_id=None,purpose=None,source_ids=None):
        if project_id is not None and project_id!=record['project_id']:raise ValueError('对话项目范围已改变，请开始新对话')
        if purpose is not None and purpose!=record['purpose']:raise ValueError('对话用途不同，请开始新对话')
        if source_ids is not None and _ids(source_ids)!=record['source_ids']:raise ValueError('选定资料范围已改变，请开始新对话')
        self._sources(record['workspace'],record['project_id'],record['source_ids'])

    def create(self,workspace,project_id='',purpose='ask',source_ids=(),title='',metadata=None):
        if not isinstance(purpose,str) or purpose not in PURPOSES:raise ValueError('对话用途无效')
        sources=self._sources(workspace,project_id,source_ids)
        timestamp=now()
        metadata=_json({} if metadata is None else metadata)
        if metadata.get('current_artifact'):
            metadata['current_artifact']=self._artifact(workspace,project_id,sources,metadata['current_artifact'])
        record={'id':uuid.uuid4().hex,'workspace':workspace,'project_id':project_id,'purpose':purpose,
            'source_ids':sources,'title':_text(title,'对话标题',200),'metadata':metadata,
            'created_at':timestamp,'updated_at':timestamp}
        with self.lock,self.db:
            self.db.execute('INSERT INTO conversations VALUES (?,?,?,?,?)',
                (record['id'],workspace,project_id,purpose,json.dumps(record,ensure_ascii=False)))
        return {**copy.deepcopy(record),'turns_total':0,'turns':[],'history_truncated':False}

    def list(self,workspace,project_id=None,purpose=None,limit=50,source_ids=None):
        self._workspace(workspace)
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('对话列表上限无效')
        if purpose is not None and (not isinstance(purpose,str) or purpose not in PURPOSES):raise ValueError('对话用途无效')
        clauses=['workspace=?'];args=[workspace]
        if project_id is not None:clauses.append('project_id=?');args.append(_text(project_id,'项目编号',100))
        if purpose is not None:clauses.append('purpose=?');args.append(purpose)
        with self.lock:
            rows=self.db.execute('SELECT payload FROM conversations WHERE '+' AND '.join(clauses)+' ORDER BY rowid DESC',args).fetchall()
            records=[json.loads(row[0]) for row in rows]
            if source_ids is not None:records=[record for record in records if record['source_ids']==_ids(source_ids)]
            return [{**record,'turns_total':self.db.execute('SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?',
                (record['id'],)).fetchone()[0]} for record in records[:limit]]

    def get(self,workspace,conversation_id,project_id=None,purpose=None,source_ids=None,max_turns=50):
        if type(max_turns) is not int or not 1<=max_turns<=100:raise ValueError('历史显示上限无效')
        with self.lock:
            record=self._record(workspace,conversation_id)
            self._scope(record,project_id,purpose,source_ids)
            total=self.db.execute('SELECT COUNT(*) FROM conversation_turns WHERE conversation_id=?',(conversation_id,)).fetchone()[0]
            turns=[json.loads(row[0]) for row in self.db.execute('SELECT payload FROM conversation_turns WHERE conversation_id=? '
                'ORDER BY sequence DESC LIMIT ?',(conversation_id,max_turns))][::-1]
            return {**record,'turns':turns,'turns_total':total,'history_truncated':total>len(turns)}

    def append(self,workspace,conversation_id,user_message,assistant_message='',status='completed',request_id='',source_ids=None,
               parent_artifact=None,current_artifact=None,base_snapshot=None,output_snapshot=None,metadata=None):
        if not isinstance(status,str) or status not in STATUSES:raise ValueError('对话轮次状态无效')
        _text(user_message,'用户要求',200000,False);_text(assistant_message,'助手答复',1500000)
        if status=='completed' and not assistant_message.strip():raise ValueError('已完成轮次必须包含助手结果')
        if not isinstance(request_id,str) or (request_id and not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',request_id)):
            raise ValueError('对话请求编号无效')
        with self.lock:
            record=self._record(workspace,conversation_id);self._scope(record,source_ids=source_ids)
            sources=record['source_ids']
            parent=self._artifact(workspace,record['project_id'],sources,{} if parent_artifact is None else parent_artifact)
            artifact=self._artifact(workspace,record['project_id'],sources,{} if current_artifact is None else current_artifact)
            payload={'status':status,'user_message':user_message,'assistant_message':assistant_message,
                'source_ids':sources,'parent_artifact':parent,'current_artifact':artifact,
                'base_snapshot':_json({} if base_snapshot is None else base_snapshot,2000000),
                'output_snapshot':_json({} if output_snapshot is None else output_snapshot,2000000),
                'metadata':_json({} if metadata is None else metadata)}
            existing=self.db.execute('SELECT payload FROM conversation_turns WHERE conversation_id=? AND request_id=?',
                (conversation_id,request_id)).fetchone() if request_id else None
            if existing:
                original=json.loads(existing[0])
                if any(original[key]!=value for key,value in payload.items()):raise ValueError('该请求编号已用于不同对话结果')
                return original
            sequence=self.db.execute('SELECT COALESCE(MAX(sequence),0)+1 FROM conversation_turns WHERE conversation_id=?',
                (conversation_id,)).fetchone()[0]
            turn={**payload,'id':uuid.uuid4().hex,'conversation_id':conversation_id,'sequence':sequence,
                  'request_id':request_id,'created_at':now()}
            record['updated_at']=now()
            if status=='completed' and artifact:record['metadata']['current_artifact']=artifact
            if not record['title']:record['title']=user_message.strip().splitlines()[0][:80]
            with self.db:
                self.db.execute('INSERT INTO conversation_turns '
                    '(id,conversation_id,workspace,sequence,request_id,payload,status,message_chars) VALUES (?,?,?,?,?,?,?,?)',
                    (turn['id'],conversation_id,workspace,sequence,request_id or None,
                     json.dumps(turn,ensure_ascii=False,allow_nan=False),status,len(user_message)+len(assistant_message)))
                self.db.execute('UPDATE conversations SET payload=? WHERE id=?',(json.dumps(record,ensure_ascii=False),conversation_id))
            return copy.deepcopy(turn)

    def context(self,workspace,conversation_id,project_id=None,purpose=None,source_ids=None,max_chars=24000,max_turns=12):
        if type(max_chars) is not int or not 500<=max_chars<=48000:raise ValueError('上下文预算无效')
        if type(max_turns) is not int or not 1<=max_turns<=40:raise ValueError('上下文轮次上限无效')
        with self.lock:
            record=self._record(workspace,conversation_id);self._scope(record,project_id,purpose,source_ids)
            completed=[json.loads(row[0]) for row in self.db.execute('SELECT payload FROM conversation_turns WHERE conversation_id=? '
                "AND status='completed' ORDER BY sequence DESC LIMIT ?",(conversation_id,max_turns))]
            total,total_chars=self.db.execute("SELECT COUNT(*),COALESCE(SUM(message_chars),0) FROM conversation_turns "
                "WHERE conversation_id=? AND status='completed'",(conversation_id,)).fetchone()
            latest=completed[0] if completed else None
        chosen=[];used=0;omitted_chars=0
        for turn in completed[:max_turns]:
            size=len(turn['user_message'])+len(turn['assistant_message'])
            if used+size<=max_chars:chosen.append(turn);used+=size
            else:break
        # Preserve the most recent pair even if its output is long; disclose the
        # exact truncation rather than silently sending half an older discussion.
        messages=[]
        if not chosen and completed:
            turn=completed[0];user=turn['user_message'][:max_chars//3]
            assistant=turn['assistant_message'][:max_chars-len(user)]
            omitted_chars=len(turn['user_message'])+len(turn['assistant_message'])-len(user)-len(assistant)
            messages=[{'role':'user','content':user},{'role':'assistant','content':assistant}]
            chosen=[turn]
        else:
            for turn in reversed(chosen):messages.extend([{'role':'user','content':turn['user_message']},
                {'role':'assistant','content':turn['assistant_message']}])
        omitted_turns=total-len(chosen)
        omitted_chars=total_chars-sum(len(message['content']) for message in messages)
        truncated=bool(omitted_turns or omitted_chars)
        warning='历史答复是未经独立核实的草稿；当前要求和明确选定资料优先。'
        if truncated:warning+=' 上下文达到预算，省略了'+str(omitted_turns)+'个早期成功轮次，共'+str(omitted_chars)+'个字符未纳入本次上下文。'
        output_snapshot=latest['output_snapshot'] if latest else {}
        identity={'scope':{key:record[key] for key in ('workspace','project_id','purpose','source_ids','metadata')},
            'completed_turns':total,'messages':messages,'output_snapshot':output_snapshot}
        signature=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        return {'conversation_id':conversation_id,'messages':messages,'truncated':truncated,'omitted_turns':omitted_turns,
            'omitted_chars':omitted_chars,'warning':warning,'source_ids':record['source_ids'],
            'current_artifact':record['metadata'].get('current_artifact',{}),
            'output_snapshot':copy.deepcopy(output_snapshot),'context_signature':signature}

    def signature(self,workspace,conversation_id,project_id=None,purpose=None,source_ids=None):
        return self.context(workspace,conversation_id,project_id,purpose,source_ids)['context_signature']

    def backup(self,workspace):
        self._workspace(workspace)
        with self.lock:
            conversations=[json.loads(row[0]) for row in self.db.execute('SELECT payload FROM conversations WHERE workspace=?',(workspace,))]
            turns=[json.loads(row[0]) for row in self.db.execute('SELECT payload FROM conversation_turns WHERE workspace=?',(workspace,))]
        return {'format':'workos-conversations','version':1,'workspace':workspace,'conversations':conversations,'turns':turns}

    def restore(self,workspace,backup):
        self._workspace(workspace)
        backup=_json(backup,64000000)
        if backup.get('format')!='workos-conversations' or type(backup.get('version')) is not int or backup['version']!=1:
            raise ValueError('对话备份格式无效')
        if backup.get('workspace')!=workspace:raise ValueError('对话备份不能跨工作区恢复')
        records=backup.get('conversations');turns=backup.get('turns')
        if not isinstance(records,list) or not isinstance(turns,list) or len(records)>10000 or len(turns)>50000:
            raise ValueError('对话备份大小或结构无效')
        mapped={}
        for record in records:
            if not isinstance(record,dict) or set(record)!={'id','workspace','project_id','purpose','source_ids','title','metadata','created_at','updated_at'}:
                raise ValueError('对话备份记录字段无效')
            item_id=_text(record['id'],'对话编号',100,False)
            if item_id in mapped or record['workspace']!=workspace:raise ValueError('对话编号重复或工作区不匹配')
            if not isinstance(record['purpose'],str) or record['purpose'] not in PURPOSES:raise ValueError('对话用途无效')
            record['source_ids']=self._sources(workspace,record['project_id'],record['source_ids'])
            _text(record['title'],'对话标题',200)
            for key in ('created_at','updated_at'):_text(record[key],'对话时间',80,False)
            record['metadata']=_json(record['metadata'])
            if record['metadata'].get('current_artifact'):
                self._artifact(workspace,record['project_id'],record['source_ids'],record['metadata']['current_artifact'])
            mapped[item_id]=record
        seen=set();requests=set();sequences=set()
        for turn in turns:
            if not isinstance(turn,dict) or set(turn)!={'status','user_message','assistant_message','source_ids','parent_artifact',
                'current_artifact','base_snapshot','output_snapshot','metadata','id','conversation_id','sequence','request_id','created_at'}:
                raise ValueError('对话备份轮次字段无效')
            _text(turn['id'],'轮次编号',100,False)
            _text(turn['conversation_id'],'对话编号',100,False)
            parent=mapped.get(turn['conversation_id'])
            if not parent or turn['id'] in seen or not isinstance(turn['status'],str) or turn['status'] not in STATUSES:
                raise ValueError('对话备份轮次关联无效')
            seen.add(turn['id'])
            if type(turn['sequence']) is not int or turn['sequence']<1 or (parent['id'],turn['sequence']) in sequences:
                raise ValueError('对话轮次顺序无效')
            sequences.add((parent['id'],turn['sequence']))
            _text(turn['user_message'],'用户要求',200000,False)
            _text(turn['assistant_message'],'助手答复',1500000,turn['status']!='completed')
            _text(turn['created_at'],'轮次时间',80,False)
            if _ids(turn['source_ids'])!=parent['source_ids']:raise ValueError('对话轮次资料范围不同')
            if not isinstance(turn['request_id'],str) or (turn['request_id'] and not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',turn['request_id'])):
                raise ValueError('对话请求编号无效')
            if turn['request_id']:
                request=(parent['id'],turn['request_id'])
                if request in requests:raise ValueError('对话请求编号重复')
                requests.add(request)
            for key in ('parent_artifact','current_artifact'):
                self._artifact(workspace,parent['project_id'],parent['source_ids'],turn[key])
            for key in ('base_snapshot','output_snapshot'):_json(turn[key],2000000)
            _json(turn['metadata'])
        with self.lock,self.db:
            for item_id in mapped:
                row=self.db.execute('SELECT workspace FROM conversations WHERE id=?',(item_id,)).fetchone()
                if row and row[0]!=workspace:raise ValueError('对话编号属于另一工作区')
            for turn in turns:
                row=self.db.execute('SELECT workspace FROM conversation_turns WHERE id=?',(turn['id'],)).fetchone()
                if row and row[0]!=workspace:raise ValueError('轮次编号属于另一工作区')
            self.db.execute('DELETE FROM conversation_turns WHERE workspace=?',(workspace,))
            self.db.execute('DELETE FROM conversations WHERE workspace=?',(workspace,))
            for record in records:self.db.execute('INSERT INTO conversations VALUES (?,?,?,?,?)',
                (record['id'],workspace,record['project_id'],record['purpose'],json.dumps(record,ensure_ascii=False)))
            for turn in turns:self.db.execute('INSERT INTO conversation_turns '
                '(id,conversation_id,workspace,sequence,request_id,payload,status,message_chars) VALUES (?,?,?,?,?,?,?,?)',
                (turn['id'],turn['conversation_id'],workspace,turn['sequence'],turn['request_id'] or None,
                 json.dumps(turn,ensure_ascii=False),turn['status'],len(turn['user_message'])+len(turn['assistant_message'])))
        return {'conversations':len(records),'turns':len(turns)}

    def close(self):
        with self.lock:self.db.close()
