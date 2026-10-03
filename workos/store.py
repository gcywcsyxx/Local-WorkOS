"""Validated, transactional SQLite records. No external dependencies."""
from __future__ import annotations
import hashlib
import json
import math
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from .organization import (EMPTY_ORGANIZATION, ORGANIZATION_FIELDS,
                           ORGANIZED_COLLECTIONS, BUILTIN_GROUPS, organize_record)
from .model_records import (MODEL_FIELDS, WORKFLOW_FIELDS, canonical_model,
                            validate_object, validate_source_ids, validate_coverage,
                            validate_review_comments)

COLLECTIONS = ('projects','tasks','documents','meetings','notes','deliverables','activity')
FIELDS = {
 'projects': {'name','sector','stage','priority','thesis','next_step','owner','valuation','tags'},
 'tasks': {'title','project_id','status','priority','owner','due','description','meeting_id'},
 'documents': {'title','project_id','kind','category','source_ref','content','filename','private','page_count','hash','chunks','attachment_ref','attachment_hash','attachment_name'},
 'meetings': {'title','project_id','date','participants','transcript','summary','experts','matrix','contents'},
 'notes': {'title','project_id','body','status','document_id','source_quote'},
 'deliverables': {'title','project_id','kind','body'},
 'activity': {'title','kind','project_id'},
}
for _collection_name in ORGANIZED_COLLECTIONS:
 FIELDS[_collection_name] |= ORGANIZATION_FIELDS
FIELDS['deliverables'] |= MODEL_FIELDS | WORKFLOW_FIELDS | {'quality_report','generation_id','revision_of','revision_number','conversation_id'}
for _collection_name in ('documents','meetings','notes','deliverables'):
 FIELDS[_collection_name].add('review_comments')
ENUMS = {
 ('projects','stage'):('线索','初筛','尽调','投委会','投后','归档'),
 ('projects','priority'):('高','中','低'), ('tasks','priority'):('高','中','低'),
 ('tasks','status'):('待办','进行中','完成'),
 ('documents','kind'):('research','memory'),
 ('notes','status'):('待核实','已核实','暂不采用'),
 ('deliverables','kind'):('研究简报','会议纪要','项目周报','自定义'),
}
DEFAULTS = {
 'projects':dict(stage='线索',priority='中',sector='',thesis='',next_step='',owner='',valuation='',tags=''),
 'tasks':dict(status='待办',priority='中',project_id='',owner='',due='',description='',meeting_id=''),
 'documents':dict(project_id='',kind='research',category='',source_ref='',content='',filename='',private=True,page_count=1,hash='',chunks=[],attachment_ref='',attachment_hash='',attachment_name=''),
 'meetings':dict(project_id='',date='',participants='',transcript='',summary='',experts=[],matrix={},contents=[]),
 'notes':dict(project_id='',body='',status='待核实',document_id='',source_quote=''),
 'deliverables':dict(project_id='',kind='自定义',body=''),
 'activity':dict(project_id='',kind='change'),
}
for _collection_name in ORGANIZED_COLLECTIONS:
 DEFAULTS[_collection_name].update(EMPTY_ORGANIZATION)
DEFAULTS['deliverables'].update(method='',assumptions={},result={},workflow_key='',source_ids=[],coverage=[],quality_report={},generation_id='',revision_of='',revision_number=1,conversation_id='')
for _collection_name in ('documents','meetings','notes','deliverables'):
 DEFAULTS[_collection_name]['review_comments']=[]

def now():
 return datetime.now(timezone.utc).isoformat(timespec='seconds')

def ensure_json(data):
 try:
  encoded=json.dumps(data,ensure_ascii=False,allow_nan=False)
 except (TypeError,ValueError) as exc:
  raise ValueError('数据必须是有限数值和可序列化内容') from exc
 if len(encoded.encode('utf-8'))>28_000_000:
  raise ValueError('数据体积超过限制')
 return encoded

class Store:
 def __init__(self, path: Path, demo=False):
  self.path=Path(path)
  self.path.parent.mkdir(parents=True,exist_ok=True)
  self.lock=threading.RLock()
  self.db=sqlite3.connect(self.path,check_same_thread=False,timeout=20)
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.execute('CREATE TABLE IF NOT EXISTS records (collection TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(collection,id))')
  self.db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT)')
  self.db.commit()
  if demo and not self.db.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
   from .demo import demo_data
   seed=demo_data()
   with self.lock,self.db:
    for col in COLLECTIONS:
     for obj in seed.get(col,[]):
      self.create(col,obj,log=False,internal=True)
    self.db.execute("INSERT INTO meta VALUES ('seeded','1')")
  # Upgrade older SQLite files in place. Only derived metadata is changed;
  # source payloads, IDs, timestamps and version 1 backup topology stay intact.
  with self.lock,self.db:
   self._organize_existing()

 def list(self,col):
  self._collection(col)
  with self.lock:
   return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM records WHERE collection=? ORDER BY rowid DESC',(col,))]

 def get(self,col,id):
  self._collection(col)
  with self.lock:
   row=self.db.execute('SELECT payload FROM records WHERE collection=? AND id=?',(col,id)).fetchone()
  if not row: raise KeyError('记录不存在')
  return json.loads(row[0])

 def _collection(self,col):
  if col not in COLLECTIONS: raise ValueError('不支持的数据类型')

 def _validate(self,col,obj,internal=False):
  self._collection(col)
  if not isinstance(obj,dict): raise ValueError('记录必须是对象')
  allowed=FIELDS[col]|{'id','created_at','updated_at'}
  extra=set(obj)-allowed
  if extra: raise ValueError('存在不支持的字段：'+', '.join(sorted(extra)))
  for key,value in obj.items():
   if col=='deliverables' and key=='revision_number':
    if type(value) is not int or not 1<=value<=100000:raise ValueError('草稿版本号不正确')
   elif col=='deliverables' and key in ('revision_of','conversation_id'):
    if not isinstance(value,str) or (value and not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',value)):raise ValueError('修订或对话编号不正确')
    if key=='revision_of' and value and not internal:
     parent=self.get('deliverables',value)
     if parent.get('project_id','')!=obj.get('project_id',''):raise ValueError('修订稿必须与原稿属于同一项目')
   elif col=='deliverables' and key=='quality_report':
    validate_object(value,'质量检查结果')
    if value:value['facts_verified']=False
   elif col=='deliverables' and key=='generation_id':
    if not isinstance(value,str) or (value and not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',value)):raise ValueError('生成任务编号无效')
   elif col=='deliverables' and key in ('assumptions','result'):
    validate_object(value,'模型假设' if key=='assumptions' else '模型结果')
   elif col=='deliverables' and key=='source_ids':
    validate_source_ids(value)
   elif col=='deliverables' and key=='coverage':
    validate_coverage(value)
   elif key=='review_comments':
    validate_review_comments(value)
   elif key=='chunks':
    if not isinstance(value,list) or len(value)>4000: raise ValueError('资料段落超过限制')
    for chunk in value:
     if not isinstance(chunk,dict) or not isinstance(chunk.get('text'),str): raise ValueError('段落格式不正确')
     if len(chunk['text'])>30000: raise ValueError('单段内容超过限制')
   elif col=='meetings' and key=='experts':
    if not isinstance(value,list) or len(value)>40:raise ValueError('专家列表最多40项')
    for expert in value:
     if not isinstance(expert,dict) or set(expert)-{'institution','title','date','background','comments','content'}:raise ValueError('专家记录字段无效')
     for field,text in expert.items():
      if field=='comments':
       if not isinstance(text,list) or len(text)>20 or any(not isinstance(x,str) or len(x)>2000 for x in text):raise ValueError('专家点评格式无效')
      elif not isinstance(text,str) or len(text)>(200000 if field=='content' else 8000):raise ValueError('专家文本无效或超过限制')
   elif col=='meetings' and key=='contents':
    if not isinstance(value,list) or len(value)>80 or any(not isinstance(x,str) or len(x)>400 for x in value):raise ValueError('目录格式无效')
   elif col=='meetings' and key=='matrix':
    if not isinstance(value,dict) or set(value)-{'topics','experts','cells'}:raise ValueError('比较矩阵格式无效')
    topics=value.get('topics',[]);columns=value.get('experts',[]);cells=value.get('cells',[])
    if not all(isinstance(x,list) for x in (topics,columns,cells)) or len(topics)>80 or len(columns)>40:raise ValueError('比较矩阵过大或格式无效')
    if any(not isinstance(x,str) or len(x)>200 for x in topics):raise ValueError('议题格式无效')
    count=len(obj.get('experts',[]))
    if any(type(x) is not int or not 0<=x<count for x in columns) or len(set(columns))!=len(columns):raise ValueError('专家索引无效')
    if len(cells)!=len(topics) or any(not isinstance(row,list) or len(row)!=len(columns) or any(not isinstance(x,str) or len(x)>8000 for x in row) for row in cells):raise ValueError('矩阵单元格与议题或专家数量不一致')
   elif key=='private':
    if not isinstance(value,bool): raise ValueError('资料隐私状态必须为布尔值')
   elif key=='page_count':
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=2000: raise ValueError('页数不正确')
   else:
    if not isinstance(value,str): raise ValueError(key+' 必须为文本')
    limit=2_000_000 if key in ('content','transcript','summary','body') else 8000
    if len(value)>limit: raise ValueError(key+' 内容超过限制')
  title_key='name' if col=='projects' else 'title'
  if not obj.get(title_key,'').strip(): raise ValueError('名称不能为空')
  if len(obj.get(title_key,''))>200: raise ValueError('名称最多200字')
  for (table,key),options in ENUMS.items():
   if table==col and obj.get(key) not in options: raise ValueError('无效的'+key)
  if col in ORGANIZED_COLLECTIONS:
   if obj.get('task_group_source','automatic') not in ('automatic','manual'):raise ValueError('无效的子任务分类来源')
   if len(obj.get('task_group',''))>100 or '\n' in obj.get('task_group','') or '\r' in obj.get('task_group',''):raise ValueError('子任务名称最多100字且不能换行')
   if obj.get('task_group') and not obj.get('project_id'):raise ValueError('子任务必须关联项目')
   if len(obj.get('version_label',''))>200 or len(obj.get('organization_reason',''))>500:raise ValueError('整理说明超过限制')
   if obj.get('version_family') and not re.fullmatch(r'[a-f0-9]{24}',obj['version_family']):raise ValueError('版本族编号格式无效')
  for field in ('date','due'):
   if obj.get(field):
    try: datetime.strptime(obj[field],'%Y-%m-%d')
    except ValueError: raise ValueError('日期格式应为 YYYY-MM-DD')
  for key,table in [('project_id','projects'),('document_id','documents'),('meeting_id','meetings')]:
   if obj.get(key) and not internal:
    try: linked=self.get(table,obj[key])
    except KeyError: raise ValueError('关联记录不存在')
    if key in ('document_id','meeting_id') and obj.get('project_id') and linked.get('project_id') and obj['project_id']!=linked['project_id']:
     raise ValueError('关联资料或会议属于另一个项目')
  if col=='deliverables':
   if obj.get('workflow_key') and not re.fullmatch(r'[a-z][a-z0-9_-]{0,99}',obj['workflow_key']):raise ValueError('工作流类型格式无效')
   source_ids=obj.get('source_ids',[])
   if any(row['document_id'] not in source_ids for row in obj.get('coverage',[])):raise ValueError('资料覆盖记录必须来自来源编号列表')
   if not internal:
    for source_id in source_ids:
     try:linked=self.get('documents',source_id)
     except KeyError:raise ValueError('来源资料不存在')
     if linked.get('kind')=='memory':raise ValueError('个人记忆不能作为交付物资料来源')
     if obj.get('project_id') and linked.get('project_id') and obj['project_id']!=linked['project_id']:raise ValueError('来源资料属于另一个项目')
   canonical=canonical_model(obj)
   if canonical is not None:obj['result']=canonical
  ensure_json(obj)

 def _organization(self,col,record,data=None,current=None,internal=False):
  if col not in ORGANIZED_COLLECTIONS:return record
  incoming=data or {}
  if not internal:
   if 'task_group' in incoming:
    if not isinstance(incoming['task_group'],str):raise ValueError('task_group 必须为文本')
    record['task_group']=incoming['task_group'].strip()
    record['task_group_source']='manual' if record['task_group'] else 'automatic'
   elif current and current.get('project_id')!=record.get('project_id'):
    # Manual membership belongs to its original project.
    record.update(task_group='',task_group_source='automatic')
  project_id=record.get('project_id','')
  project_tasks=[task for task in self.list('tasks') if task.get('project_id')==project_id]
  linked=None
  link=('documents',record.get('document_id')) if col=='notes' else ('meetings',record.get('meeting_id')) if col=='tasks' else None
  if link and link[1]:
   try:linked=self.get(*link)
   except KeyError:pass
  record.update(organize_record(col,record,project_tasks,linked))
  if col=='deliverables' and record.get('method') and project_id:
   record['material_type']='财务模型'
   if record.get('task_group_source')!='manual' and record.get('task_group') in BUILTIN_GROUPS:
    record.update(task_group='财务与估值',organization_reason='根据保存的结构化估值方法自动归类')
  return record

 def _organize_existing(self,project_id=None):
  changed=0
  # Parents precede their linked notes/tasks, so inheritance sees current groups.
  for col in ('documents','meetings','deliverables','notes','tasks'):
   for record in self.list(col):
    if project_id is not None and record.get('project_id')!=project_id:continue
    updated=self._organization(col,dict(record),internal=True)
    if updated!=record:
     self.db.execute('UPDATE records SET payload=? WHERE collection=? AND id=?',(ensure_json(updated),col,record['id']))
     changed+=1
  return changed

 def organize_project(self,project_id):
  """Reclassify existing material while retaining explicit subtask overrides."""
  if not isinstance(project_id,str) or not project_id:raise ValueError('请先选择项目')
  with self.lock,self.db:
   self.get('projects',project_id)
   changed=self._organize_existing(project_id)
  return {'organized':changed,'project_id':project_id}

 def _refresh_linked_organization(self,col,id):
  target,field=('notes','document_id') if col=='documents' else ('tasks','meeting_id')
  for linked in self.list(target):
   if linked.get(field)==id:
    updated=self._organization(target,dict(linked),internal=True)
    if updated!=linked:self.db.execute('UPDATE records SET payload=? WHERE collection=? AND id=?',(ensure_json(updated),target,linked['id']))

 def create(self,col,data,log=True,internal=False):
  self._collection(col)
  if not isinstance(data,dict): raise ValueError('记录必须是对象')
  if not internal and set(data)&{'id','created_at','updated_at'}: raise ValueError('不能指定系统字段')
  record={**DEFAULTS[col],**data}
  record['id']=data.get('id',str(uuid.uuid4())) if internal else str(uuid.uuid4())
  record['created_at']=data.get('created_at',now()) if internal else now()
  record['updated_at']=data.get('updated_at',now()) if internal else now()
  with self.lock,self.db:
   self._validate(col,record,internal)
   self._organization(col,record,data,internal=internal)
   self._validate(col,record,internal)
   self.db.execute('INSERT INTO records VALUES (?,?,?)',(col,record['id'],ensure_json(record)))
   if col=='tasks' and record.get('project_id') and record.get('task_group_source')=='manual':self._organize_existing(record['project_id'])
   if log and col!='activity': self._log('创建 '+record.get('name',record.get('title','')),record.get('project_id',''))
  return record

 def update(self,col,id,data):
  if not isinstance(data,dict): raise ValueError('更新必须是对象')
  if set(data)&{'id','created_at','updated_at'}: raise ValueError('不能修改系统字段')
  with self.lock,self.db:
   current=self.get(col,id)
   updated={**current,**data,'updated_at':now()}
   if col=='deliverables' and current.get('quality_report') and any(key in data and data[key]!=current.get(key) for key in ('body','source_ids','coverage','workflow_key')):
    updated['quality_report']={**current['quality_report'],'status':'needs_review','label':'编辑后未重新检查',
      'stale':True,'facts_verified':False,'checks':[],
      'review':{'required':True,'status':'stale','issues':[],'factual_truth_verified':False},
      'limitations':['原检查针对生成时的正文；编辑后需重新核实。']}
   if col=='meetings' and 'summary' in data and data['summary']!=current.get('summary') and not {'experts','matrix','contents'}&set(data):
    updated.update(experts=[],matrix={},contents=[])
   self._validate(col,updated)
   self._organization(col,updated,data,current)
   self._validate(col,updated)
   self._validate_project_reassociation(col,id,updated)
   self.db.execute('UPDATE records SET payload=? WHERE collection=? AND id=?',(ensure_json(updated),col,id))
   if col in ('documents','meetings'):self._refresh_linked_organization(col,id)
   if col=='tasks' and (updated.get('task_group_source')=='manual' or current.get('task_group_source')=='manual'):
    for project_id in {current.get('project_id'),updated.get('project_id')}:
     if project_id:self._organize_existing(project_id)
   if col!='activity': self._log('更新 '+updated.get('name',updated.get('title','')),updated.get('project_id',''))
  return updated

 def _validate_project_reassociation(self,col,id,updated):
  if col not in ('documents','meetings'):return
  child_col,field=('notes','document_id') if col=='documents' else ('tasks','meeting_id')
  for child in self.list(child_col):
   if child.get(field)==id and child.get('project_id') and updated.get('project_id') and child['project_id']!=updated['project_id']:
    raise ValueError('关联资料或会议仍被原项目引用，请先调整关联')
  if col=='documents':
   for child in self.list('deliverables'):
    if id in child.get('source_ids',[]) and child.get('project_id') and updated.get('project_id') and child['project_id']!=updated['project_id']:
     raise ValueError('来源资料仍被原项目交付物引用，请先调整关联')

 def delete(self,col,id):
  with self.lock,self.db:
   record=self.get(col,id)
   if col in ('projects','documents','meetings'):
    key={'projects':'project_id','documents':'document_id','meetings':'meeting_id'}[col]
    for table in COLLECTIONS:
     if table=='activity': continue
     if any(obj.get(key)==id for obj in self.list(table)):
      raise ValueError('该记录仍有关联内容，请先取消关联后删除')
   if col=='documents' and any(id in obj.get('source_ids',[]) for obj in self.list('deliverables')):
    raise ValueError('该资料仍被交付物引用，请先取消关联后删除')
   if col=='deliverables' and any(id==obj.get('revision_of') for obj in self.list('deliverables')):
    raise ValueError('该草稿仍有修订版本，不能删除原稿')
   self.db.execute('DELETE FROM records WHERE collection=? AND id=?',(col,id))
   if col=='tasks' and record.get('project_id') and record.get('task_group_source')=='manual':self._organize_existing(record['project_id'])
   if col!='activity': self._log('删除 '+record.get('name',record.get('title','')),'')
  return {'deleted':True}

 def _log(self,title,project_id=''):
  record={'id':str(uuid.uuid4()),'created_at':now(),'updated_at':now(),'title':title,'kind':'change','project_id':project_id}
  self.db.execute('INSERT INTO records VALUES (?,?,?)',('activity',record['id'],ensure_json(record)))
  self.db.execute("DELETE FROM records WHERE collection='activity' AND rowid NOT IN (SELECT rowid FROM records WHERE collection='activity' ORDER BY rowid DESC LIMIT 200)")

 def state(self):
  data={col:self.list(col) for col in COLLECTIONS}
  data['documents']=[{k:v for k,v in doc.items() if k not in ('content','chunks')} for doc in data['documents']]
  return data

 def backup(self,workspace):
  with self.lock:
   return {'format':'local-workos','version':1,'workspace':workspace,'exported_at':now(),'data':{col:self.list(col) for col in COLLECTIONS}}

 def restore(self,backup,workspace):
  if not isinstance(backup,dict) or backup.get('format')!='local-workos' or backup.get('version')!=1: raise ValueError('不是有效的 Local WorkOS 备份')
  if backup.get('workspace')!=workspace: raise ValueError('备份工作区不匹配，禁止跨工作区恢复')
  data=backup.get('data')
  if not isinstance(data,dict) or set(data)!=set(COLLECTIONS): raise ValueError('备份结构不完整')
  ensure_json(data)
  if sum(len(items) for items in data.values() if isinstance(items,list))>20000: raise ValueError('记录数量超过限制')
  ids={}
  for col,items in data.items():
   if not isinstance(items,list): raise ValueError('备份记录格式错误')
   ids[col]=set()
   for obj in items:
    self._validate(col,obj,internal=True)
    if not obj.get('id') or obj['id'] in ids[col]: raise ValueError('备份存在重复或空编号')
    ids[col].add(obj['id'])
  lookup={col:{obj['id']:obj for obj in items} for col,items in data.items()}
  for col,items in data.items():
   if col=='activity':continue
   for obj in items:
    if col=='deliverables':
     if obj.get('revision_of'):
      parent=lookup['deliverables'].get(obj['revision_of'])
      if not parent or parent['id']==obj['id'] or parent.get('project_id','')!=obj.get('project_id',''):raise ValueError('备份含失效或跨项目修订关联')
     for source_id in obj.get('source_ids',[]):
      source=lookup['documents'].get(source_id)
      if not source:raise ValueError('备份含失效资料来源')
      if source.get('kind')=='memory':raise ValueError('备份含个人记忆交付物来源')
      if obj.get('project_id') and source.get('project_id') and obj['project_id']!=source['project_id']:raise ValueError('备份含跨项目资料来源')
    for key,table in [('project_id','projects'),('document_id','documents'),('meeting_id','meetings')]:
     if obj.get(key) and obj[key] not in ids[table]: raise ValueError('备份含失效关联')
     if key in ('document_id','meeting_id') and obj.get(key) and obj.get('project_id'):
      linked=lookup[table][obj[key]]
      if linked.get('project_id') and linked['project_id']!=obj['project_id']:raise ValueError('备份含跨项目关联')
  with self.lock:
   backup_path=self.path.with_name(self.path.stem+'-before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:5]+'.sqlite3')
   target=sqlite3.connect(backup_path)
   self.db.backup(target);target.close()
   with self.db:
    self.db.execute('DELETE FROM records')
    for col,items in data.items():
     for obj in items: self.db.execute('INSERT INTO records VALUES (?,?,?)',(col,obj['id'],ensure_json(obj)))
    self._organize_existing()
  return {'restored':True,'previous_backup':str(backup_path)}

 def close(self):
  with self.lock:self.db.close()
