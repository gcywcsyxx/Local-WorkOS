"""Completion-checked DSH adapter with selected-evidence tools and disposable state."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from .cancellation import check_cancelled

READ_BUDGET = 200_000
TOOL_BUDGET = 128
MAX_OUTPUT = 8_000_000
PLUGIN = Path(__file__).with_name('harness_plugin.mjs')
LAUNCHER = """import {pathToFileURL} from 'node:url';
import {StringDecoder} from 'node:string_decoder';
const entry=process.argv[2],args=process.argv.slice(3);
process.argv=[process.argv[0],entry,...args];
const originalWrite=process.stdout.write.bind(process.stdout),decoder=new StringDecoder('utf8');
let pending='',final=false,ended=false,completed=false,timer;
process.stdout.write=function(chunk,...rest){
  const result=originalWrite(chunk,...rest);
  pending+=typeof chunk==='string'?chunk:decoder.write(chunk);
  const lines=pending.split('\\n');pending=lines.pop();
  for(const line of lines){try{const event=JSON.parse(line);
    if(event.type==='status'&&event.phase==='turn_end'){ended=true;completed=event.reason?.kind==='completed';}
    if(event.type==='final')final=true;
  }catch{}}
  if(final&&ended&&!timer)timer=setInterval(()=>{
    // DSH sets this only after its owned runtime disposal finishes. Close residual handles.
    if(typeof process.exitCode==='number'){
      clearInterval(timer);const code=completed&&process.exitCode===0?0:1;
      originalWrite('',()=>process.exit(code));
    }
  },50);
  return result;
};
const cli=await import(pathToFileURL(entry).href);
if(typeof cli.runCli==='function')await cli.runCli();
"""
BLOCKED_ROWS = ('tool-plugin-manager','tool-bash','tool-pwsh','tool-jobs','tool-fs','tool-fs-search',
    'tool-skill','tool-subagent-control','tool-subagent-list-agents','tool-subagent','tool-subagent-fork',
    'tool-subagent-codex','tool-subagent-claude-code','tool-workflow','tool-result-pruner','tool-todo',
    'tool-goal','tool-ralph','tool-web','tool-ask-user','tool-presentation','persistent-bash',
    'persistent-pwsh','agent-instructions','skill-filesystem','skill-office','workspace-dependencies',
    'plugin-manager','config-editor','settings','hmr','session-log-deepseek','session-title-llm','session-telemetry-otel')


def evidence_packet(docs, coverage):
    if not isinstance(docs, list) or len(docs) > 80:
        raise ValueError('DSH资料范围不正确；最多80份')
    mapped = {item.get('document_id'):item.get('source_id') for item in coverage if isinstance(item, dict)}
    sources, tags, total = [], set(), 0
    for index, doc in enumerate(docs, 1):
        if not isinstance(doc, dict) or doc.get('kind') == 'memory':
            raise ValueError('个人记忆不能提供给DSH研究工具')
        content = doc.get('content')
        source_id = mapped.get(doc.get('id')) or 'S' + str(index)
        if not isinstance(content, str) or not content.strip() or not isinstance(source_id, str) or not re.fullmatch(r'S[1-9][0-9]*', source_id) or source_id in tags:
            raise ValueError('DSH资料文字或来源编号不正确')
        tags.add(source_id)
        total += len(content)
        if total > 4_000_000:
            raise ValueError('选定资料超过本轮DSH工具范围，请分批研究；未自动省略材料')
        sources.append({'source_id':source_id, 'document_id':str(doc.get('id') or ''),
            'title':str(doc.get('title') or '')[:200], 'version':str(doc.get('version_label') or '')[:100],
            'text':content, 'total_chars':len(content)})
    return {'sources':sources, 'read_budget':READ_BUDGET, 'tool_budget':TOOL_BUDGET}


def overlay(model, session_root, models, native=False, packet_path=None, trace_path=None, dsh_entry=None):
    root = Path(session_root).parent
    lines = ['- id: llm-pi-ai','  name: "@deepseek-ai/dsh-llm-pi-ai"','  config:',
        '    providers:','      openai-codex:','        displayName: "ChatGPT Codex"','        models:']
    for model_id, (title, window, limit) in models.items():
        lines.extend([f'          - id: {model_id}','            name: '+json.dumps(title),
            f'            contextWindow: {window}',f'            maxTokens: {limit}'])
    lines.extend(['- id: agent-default-model','  name: "@deepseek-ai/dsh-agent-default-model"',
        '  config:','    provider: openai-codex','    model: '+model])
    for row in BLOCKED_ROWS:
        lines.extend(['- id: '+row,'  disabled: true'])
    lines.extend(['- id: tools','  config:','    mode: native',
        '- id: sandbox-policy','  config:','    mode: read-only','    workspaceRoot: '+json.dumps(str(root)),
        '- id: session-persistence-jsonl','  name: "@deepseek-ai/dsh-session-persistence-jsonl"',
        '  config:','    root: '+json.dumps(str(session_root)),
        '- id: storage-json','  config:','    root: '+json.dumps(str(root/'storage')),
        '- insert:','    - id: workos-evidence-harness','      name: '+json.dumps(PLUGIN.as_uri()),
        '      config:','        native: '+('true' if native else 'false'),
        '        dshEntry: '+json.dumps(str(dsh_entry or '')),
        '        packetPath: '+json.dumps(str(packet_path or '')),
        '        tracePath: '+json.dumps(str(trace_path or ''))])
    return '\n'.join(lines)+'\n'


def parse_completion(events, exit_code):
    final = None
    completed = False
    failed = False
    for event in events:
        if not isinstance(event, dict):
            raise ValueError('DSH返回了无效运行事件')
        if event.get('type') == 'error':
            failed = True
        if event.get('type') == 'status' and event.get('phase') == 'turn_end':
            completed = isinstance(event.get('reason'), dict) and event['reason'].get('kind') == 'completed'
        if event.get('type') == 'final':
            if final is not None:
                raise ValueError('DSH返回了重复完成事件')
            final = event.get('text')
    if exit_code != 0 or failed or not completed or not isinstance(final, str) or not final.strip():
        raise ValueError('DSH运行没有成功完成；没有保存草稿，请检查模型授权或重试')
    if len(final) > 1_000_000:
        raise ValueError('DSH正文超过允许大小')
    return final.strip()


def validate_trace(trace, packet, answer):
    if not isinstance(trace, dict) or not isinstance(trace.get('tool_counts'), dict) or not isinstance(trace.get('read_ranges'), list):
        raise ValueError('DSH研究工具未提供可核验运行记录')
    allowed = {'workos_sources','workos_read_source','workos_find_evidence','workos_check_draft'}
    counts = trace['tool_counts']
    if any(name not in allowed or type(count) is not int or count < 0 for name,count in counts.items()) or sum(counts.values()) > TOOL_BUDGET:
        raise ValueError('DSH工具运行范围或预算不正确')
    by_tag = {source['source_id']:source for source in packet['sources']}
    intervals = {tag:[] for tag in by_tag}
    delivered = 0
    for row in trace['read_ranges']:
        if not isinstance(row, dict) or row.get('source_id') not in by_tag:
            raise ValueError('DSH读取了未选定来源')
        start,end = row.get('start'),row.get('end')
        source = by_tag[row['source_id']]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= source['total_chars']:
            raise ValueError('DSH资料范围记录不正确')
        delivered += end-start
        intervals[row['source_id']].append((start,end))
    if delivered > READ_BUDGET:
        raise ValueError('DSH资料读取超过本轮预算')
    if not counts.get('workos_check_draft') or str(trace.get('qa', {}).get('draft') or '').strip() != answer:
        raise ValueError('DSH尚未对最终正文完成确定性检查')
    tags = set(re.findall(r'\[S(\d+)\]', answer))
    if any('S'+tag not in by_tag for tag in tags) or (by_tag and not tags):
        raise ValueError('DSH正文未包含有效选定资料引用')
    if any(not intervals['S'+tag] for tag in tags):
        raise ValueError('DSH引用了尚未通过研究工具读取的来源')
    coverage = []
    for tag,source in by_tag.items():
        merged = []
        for start,end in sorted(intervals[tag]):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0],max(end,merged[-1][1]))
            else:
                merged.append((start,end))
        read = sum(end-start for start,end in merged)
        coverage.append({'document_id':source['document_id'],'source_id':tag,'title':source['title'],
            'excerpt_chars':read,'total_chars':source['total_chars'],'truncated':read < source['total_chars']})
    qa = dict(trace.get('qa') or {})
    qa.pop('draft', None)
    if qa.get('valid') is not True:
        raise ValueError('DSH最终正文未通过确定性来源检查')
    return {'name':'DSH scoped evidence tools','coverage_basis':'tool_read_ranges',
        'completion_verified':True,'tool_counts':counts,'read_ranges':trace['read_ranges'],
        'coverage':coverage,'blocked_tools':trace.get('blocked_tools',[])[:128], 'qa':qa,
        'read_budget':READ_BUDGET,'tool_budget':TOOL_BUDGET,'full_material_read':bool(coverage) and all(not row['truncated'] for row in coverage)}


def run(app, prompt, model, models, *, docs=None, coverage=(), progress_callback=None, timeout=90):
    if model not in models:
        raise ValueError('所选DSH模型不在允许列表中')
    if not app.dsh_available:
        raise ValueError('没有找到可用的DSH本机运行环境')
    native = docs is not None
    packet = evidence_packet(docs, coverage) if native else {'sources':[],'read_budget':READ_BUDGET,'tool_budget':TOOL_BUDGET}
    from .workflow_runs import exclusive_model_run
    with exclusive_model_run(app.dsh_lock), tempfile.TemporaryDirectory(prefix='workos-dsh-') as temporary:
        check_cancelled()
        root = Path(temporary)
        sessions = root/'sessions'
        sessions.mkdir()
        packet_path,trace_path = root/'evidence.json',root/'trace.json'
        packet_path.write_text(json.dumps(packet,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        patch_path = root/'workos.yml'
        patch_path.write_text(overlay(model,sessions,models,native,packet_path,trace_path,app.dsh_entry),encoding='utf-8')
        launcher = root/'launcher.mjs'
        launcher.write_text(LAUNCHER,encoding='utf-8')
        output,error_output = root/'events.jsonl',root/'stderr.txt'
        env = dict(os.environ)
        env['DSH_TELEMETRY_DISABLED'] = '1'
        env.pop('DSH_TOOLS_MODE',None)
        flags = getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name == 'nt' else 0
        process = None
        events,offset,pending = [],0,b''
        deadline = time.monotonic()+timeout
        last_heartbeat = time.monotonic()-1
        def drain():
            nonlocal offset,pending
            size = output.stat().st_size
            if size > MAX_OUTPUT:
                raise ValueError('DSH运行事件超过允许大小')
            with output.open('rb') as reader:
                reader.seek(offset)
                chunk = reader.read()
                offset = reader.tell()
            pending += chunk
            lines = pending.split(b'\n')
            pending = lines.pop()
            for line in lines:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError,UnicodeError) as exc:
                    raise ValueError('DSH运行事件无法解析') from exc
                events.append(event)
                if progress_callback and isinstance(event,dict) and event.get('type') in ('status','tool_call','tool_result'):
                    public = {'stage':'dsh','event':event['type']}
                    if event.get('phase'):public['phase']=str(event['phase'])[:50]
                    if event.get('tool'):public['tool']=str(event['tool'])[:100]
                    if progress_callback(public) is False:
                        raise ValueError('工作已取消；未保存DSH草稿')
        prompt_path = root/'prompt.txt'
        prompt_path.write_text(prompt,encoding='utf-8')
        try:
            with output.open('wb') as sink,error_output.open('wb') as diagnostics,prompt_path.open('rb') as task_input:
                check_cancelled()
                process = subprocess.Popen([app.dsh_node,str(launcher),str(app.dsh_entry),'--profile','headless','--patch',str(patch_path),'--json','-'],
                    stdin=task_input,stdout=sink,stderr=diagnostics,cwd=str(root),env=env,creationflags=flags)
                while process.poll() is None:
                    drain()
                    if error_output.stat().st_size > MAX_OUTPUT:
                        raise ValueError('DSH诊断输出超过允许大小')
                    if time.monotonic() >= deadline:
                        raise ValueError('DSH模型响应超时；未保存草稿，请重试')
                    if progress_callback and time.monotonic()-last_heartbeat >= 1:
                        last_heartbeat = time.monotonic()
                        if progress_callback({'stage':'dsh','event':'heartbeat'}) is False:
                            raise ValueError('工作已取消；未保存DSH草稿')
                    time.sleep(0.1)
            drain()
            if pending.strip():
                raise ValueError('DSH运行事件被截断；未保存草稿')
            answer = parse_completion(events,process.returncode)
            trace = validate_trace(json.loads(trace_path.read_text(encoding='utf-8')),packet,answer) if native else {'completion_verified':True,'tool_counts':{},'read_ranges':[]}
            return answer,trace
        except OSError as exc:
            raise ValueError('无法启动或读取DSH；请检查本机安装') from exc
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait(timeout=2)
