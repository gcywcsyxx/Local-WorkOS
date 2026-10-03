#!/usr/bin/env node
'use strict';
// Node >=24, installed Chrome, Python in PATH (or WORKOS_TEST_PYTHON).
// Run: node tests/browser_research_cdp.cjs
// Only synthetic temporary data; no launcher, production profiles, or model calls.
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { randomUUID } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const chromeExecutable = process.env.WORKOS_TEST_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const failures = [], requests = [], originalRequests = [], runtimeErrors = [], interceptionErrors = [];
const workflowJobs = new Map(), workflowRequestKeys = new Map(), workflowCancelTombstones = new Set();
const auxiliaryModelMocks = new Map();
const operationCancelFailures = new Map();
const mockConversations=new Map(),mockOperations=new Map(),mockArchives=new Map(),mockBindings=new Map();
const restoreOperationIds=new Set();
const requestWorkspace=event=>Object.entries(event.request.headers).find(([name])=>name.toLowerCase()==='x-workspace')?.[1]||'personal';
const requestOperation=event=>Object.entries(event.request.headers).find(([name])=>name.toLowerCase()==='x-workos-request-id')?.[1];
const csrfScenario={enabled:false,seedStale:false,mode:'recover',bootstrapCalls:0,parseRequests:[],successfulModelCalls:0,expected:null,retryDom:null};
function syntheticModelCatalog(){const entries=[['gpt','GPT','dsh',[['gpt-6-luna','GPT-6 Luna'],['gpt-6-sol','GPT-6 Sol'],['gpt-6-astra','GPT-6 Astra']]],['deepseek','DeepSeek','deepseek',[['deepseek-v4.1-flash','DeepSeek V4.1 Flash'],['deepseek-v4-pro','DeepSeek V4 Pro']]],['glm','GLM','local-models',[['glm-5.2','GLM-5.2']]],['kimi','Kimi','local-models',[['kimi-k2.7','Kimi K2.7']]],['hunyuan','Hunyuan','local-models',[['hy3','Hunyuan 3']]],['custom','已配置模型','model',[['synthetic-custom','Synthetic configured model']]]];return {groups:entries.map(([id,label,mode,items])=>({id,label,models:items.map(([id,name])=>({id,name,mode,provider:mode,selection_id:mode+':'+id,available:true,status:'not_checked'}))})).concat([{id:'unavailable',label:'Synthetic unavailable',models:[{id:'synthetic-unavailable',name:'Synthetic unavailable model',mode:'dsh',provider:'dsh',selection_id:'dsh:synthetic-unavailable',available:false,status:'unavailable',reason:'Synthetic model missing from bridge'}]}])};}
let syntheticModels=syntheticModelCatalog();
const syntheticModelCheckFailures=new Set();
const syntheticBoot=fresh=>({...fresh,models:structuredClone(syntheticModels),dsh:{...fresh.dsh,available:true,models:fresh.dsh?.models?.length?fresh.dsh.models:[{id:'gpt-6-luna',name:'Synthetic GPT-6 Luna'}]}});
let temp, server, chrome, cdp, origin, csrf, checks = 0;

async function freePort() {
  const listener = net.createServer();
  listener.listen(0, '127.0.0.1'); await once(listener, 'listening');
  const port = listener.address().port; await new Promise(resolve => listener.close(resolve)); return port;
}
function start(executable, args, options = {}) {
  const child = spawn(executable, args, { cwd: root, stdio: 'ignore', windowsHide: true, ...options });
  child.startError = null;
  child.on('error', error => { child.startError = error; });
  return child;
}
async function until(fn, label, timeout = 12000) {
  const deadline = Date.now() + timeout; let last;
  while (Date.now() < deadline) {
    try { const value = await fn(); if (value) return value; } catch (error) { last = error; }
    await delay(80);
  }
  throw new Error('Timeout: ' + label + (last ? ' (' + last.message + ')' : ''));
}
async function json(url, options) {
  const response = await fetch(url, { ...options, signal: AbortSignal.timeout(4000) });
  const text = await response.text();
  if (!response.ok) throw new Error(response.status + ' ' + url + ': ' + text.slice(0, 350));
  return JSON.parse(text);
}
async function api(route, body) {
  return json(origin + '/api/' + route, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, Origin: origin }, body: JSON.stringify(body)
  });
}
class CDP {
  constructor(socket) {
    this.socket = socket; this.id = 0; this.pending = new Map(); this.listeners = new Map();
    socket.addEventListener('message', event => {
      const message = JSON.parse(event.data);
      if (message.id) {
        const entry = this.pending.get(message.id); if (!entry) return;
        this.pending.delete(message.id); clearTimeout(entry.timer);
        if (message.error) entry.reject(new Error(JSON.stringify(message.error))); else entry.resolve(message.result);
      } else {
        for (const fn of this.listeners.get(message.method) || []) Promise.resolve(fn(message.params)).catch(error => interceptionErrors.push(error.message));
      }
    });
    socket.addEventListener('close', () => {
      for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('CDP socket closed')); }
      this.pending.clear();
    });
  }
  static async connect(url) { const socket = new WebSocket(url); await once(socket, 'open'); return new CDP(socket); }
  on(name, fn) { if (!this.listeners.has(name)) this.listeners.set(name, []); this.listeners.get(name).push(fn); }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CDP timeout ' + method)); }, 12000);
      this.pending.set(id, { resolve, reject, timer }); this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text + ': ' + (result.exceptionDetails.exception?.description || expression));
    return result.result.value;
  }
}
const q = value => JSON.stringify(value);
async function details() {
  return cdp.evaluate(`(() => ({ hash: location.hash, title: document.querySelector('main h1')?.textContent,
    text: document.querySelector('main')?.innerText.slice(0, 4500), dialogs: [...document.querySelectorAll('dialog[open]')].map(e => e.innerText.slice(0, 1000)),
    fields: [...document.querySelectorAll('main input,main select,main textarea')].map(e => ({ id: e.id, type: e.type, value: e.value, disabled: e.disabled })),
    toasts: document.querySelector('#toast-region')?.innerText }))()`);
}
async function screenshot(name){
  if(!process.env.WORKOS_TEST_SCREENSHOTS)return;
  await cdp.evaluate("document.querySelectorAll('#toast-region .toast button').forEach(button=>button.click())");
  const directory=path.resolve(process.env.WORKOS_TEST_SCREENSHOTS);await fs.mkdir(directory,{recursive:true});
  const result=await cdp.send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  const filename=path.join(directory,name+'.png');await fs.writeFile(filename,Buffer.from(result.data,'base64'));console.log('SCREENSHOT '+filename);
}
async function check(name, fn) {
  checks++;
  try { await fn(); console.log('PASS ' + name); }
  catch (error) { const dom = await details().catch(() => null); failures.push({ name, error: error.message, dom }); console.error('FAIL ' + name + ': ' + error.message + '\nDOM ' + JSON.stringify(dom)); }
}
function assert(value, message) { if (!value) throw new Error(message); }
async function click(selector) {
  await cdp.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  const point = await cdp.evaluate(`(() => { const e=document.querySelector(` + q(selector) + `); if(!e)throw Error('Missing '+` + q(selector) + `); e.scrollIntoView({block:'center',behavior:'instant'}); const r=e.getBoundingClientRect(); const x=r.x+r.width/2,y=r.y+r.height/2;const hit=document.elementFromPoint(x,y);if(!hit||!(hit===e||e.contains(hit)))throw Error('Click target obscured '+`+q(selector)+`+' by '+hit?.outerHTML.slice(0,350));return {x,y}; })()`);
  await cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
  await cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
}
async function fill(selector, text) {
  await click(selector); await cdp.evaluate(`document.querySelector(` + q(selector) + `).select()`);
  await cdp.send('Input.insertText', { text });
}
async function select(selector, value) {
  await cdp.evaluate(`(() => {const e=document.querySelector(` + q(selector) + `);if(!e)throw Error('Missing select');e.value=` + q(value) + `;e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
}
async function enter(selector,{shift=false,repeat=false}={}) {
  await cdp.evaluate('document.querySelector('+q(selector)+').focus()');
  const event={key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13,modifiers:shift?8:0};
  await cdp.send('Input.dispatchKeyEvent',{type:'keyDown',...event,text:'\r',unmodifiedText:'\r',autoRepeat:repeat});
  await cdp.send('Input.dispatchKeyEvent',{type:'keyUp',...event});
}
async function holdBrowserResponse(pathname) {
  await cdp.evaluate(`(() => {if(window.__stopNativeFetch)throw Error('Prior response wrapper still active');window.__stopNativeFetch=window.fetch;window.__stopReplies=[];window.__stopSignals=[];window.fetch=async (...args)=>{const matches=new URL(args[0],location.href).pathname===${q(pathname)};if(matches)window.__stopSignals.push(args[1]?.signal);const response=await window.__stopNativeFetch(...args);if(matches)await new Promise(resolve=>window.__stopReplies.push(resolve));return response;};})()`);
}
async function releaseBrowserResponses() {
  await cdp.evaluate("(() => {const original=window.__stopNativeFetch;if(original)window.fetch=original;window.__stopNativeFetch=null;const replies=window.__stopReplies||[];window.__stopReplies=[];replies.forEach(resolve=>resolve());})()");
}
async function route(name) {
  await cdp.evaluate('location.hash=' + q(name));
  const allowedHashes = name === 'projects' ? ['#projects', '#overview'] : ['#' + name];
  const active=name==='projects'?'overview':name;
  const navSelector=name==='settings'?'#settings-nav.active':'#primary-nav [data-page='+active+'].active';
  await until(() => cdp.evaluate(q(allowedHashes) + `.includes(location.hash) && !!document.querySelector(`+q(navSelector)+`) && !!document.querySelector('main h1') && document.querySelector('main').getAttribute('aria-busy')!=='true'`), 'route ' + name);
  // hashchange rendering is synchronous, but wait for its dispatch after Runtime.evaluate.
  await cdp.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
}
async function markdown(selector) {
  const observed = await cdp.evaluate(`(() => {const e=document.querySelector(` + q(selector) + `);return e && {heading:!!e.querySelector('h1,h2,h3'),bold:!!e.querySelector('strong'),list:!!e.querySelector('ul li,ol li'),table:!!e.querySelector('table tbody tr'),unsafe:!!e.querySelector('script,img,iframe,svg'),text:e.textContent,html:e.innerHTML,pwned:window.__cdpUnsafe};})()`);
  assert(observed, 'Missing Markdown result');
  assert(observed.heading && observed.bold && observed.list && observed.table, 'Missing Markdown structure: ' + JSON.stringify(observed));
  assert(!observed.unsafe && !observed.pwned && observed.text.includes('[S1]') && observed.text.includes('<img') && observed.text.includes('<script>'), 'HTML was not inert literal text: ' + JSON.stringify(observed));
}
async function stop(child, label) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  const exited = once(child, 'exit').catch(() => {});
  if (process.platform === 'win32') {
    const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true });
    await once(killer, 'exit');
  } else child.kill('SIGTERM');
  await Promise.race([exited, delay(6000)]);
  if (child.exitCode === null && child.signalCode === null) throw new Error('Created ' + label + ' process did not stop: ' + child.pid);
}
function workflowPosts(){return requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST');}
async function fulfillJson(event,result,status=200){
  return cdp.send('Fetch.fulfillRequest',{requestId:event.requestId,responseCode:status,responseHeaders:[{name:'Content-Type',value:'application/json; charset=utf-8'}],body:Buffer.from(JSON.stringify(result)).toString('base64')});
}
const mockStages=()=>['prepare','generate','check','review','repair','save'].map((key,index)=>({key,label:['整理范围','生成正文','检查结构','复核证据','修订内容','保存草稿'][index],status:'pending',detail:''}));
async function finishMockWorkflow(meta){
  const job=meta.job;
  const docs=meta.documents;
  const coverage=docs.map((item,index)=>({document_id:item.id,source_id:'S'+(index+1),title:item.title,excerpt_chars:item.content.length,total_chars:item.content.length,truncated:false}));
  const text='# Synthetic saved workflow\n\n**Editable draft**\n\n- Synthetic finding'+(docs.length?' [S1]':'')+'\n\n| Item | Status |\n| --- | --- |\n| Synthetic result | Draft |';
  const quality_report={status:'needs_review',label:'流程检查完成',can_save:true,facts_verified:false,harness:'synthetic',checks:[{id:'coverage',label:'资料覆盖',status:docs.length?'pass':'warn',detail:docs.length?'Selected synthetic evidence only.':'No selected evidence.'},{id:'table_structure',label:'table structure',status:'pass',detail:'Synthetic Markdown structure checked.'},{id:'verification',label:'外部事实核实',status:'not_checked',detail:'Synthetic fixture; no fact verification.'}],metrics:{sources:docs.length},constraints:{table_required:true,table_count:1,table_columns:2},limitations:['Synthetic mocked pipeline; no real model called.'],review:{status:'advisory_complete',verdict:'issues_found',scope:'Synthetic source excerpts only; no outside verification.',issues:[{criterion:'Evidence support',severity:'warning',quote:'Synthetic finding',explanation:'Synthetic unresolved evidence question.',proposed_fix:'Request specific supporting source evidence.',source_ids:docs.length?['S1']:[]}]}};
  const deliverable=await api('deliverables',{title:'Synthetic '+job.workflow_key+' draft',kind:'自定义',project_id:job.project_id,body:text,workflow_key:job.workflow_key,source_ids:job.document_ids,coverage,generation_id:job.id,quality_report,...(job.revision_of?{revision_of:job.revision_of,revision_number:Number(meta.parent?.revision_number||1)+1}:{})});
  job.result={answer:text,citations:docs.map(item=>({document_id:item.id,title:item.title,quote:item.content.slice(0,100),ordinal:1})),coverage,deliverable,quality_report,workflow_key:job.workflow_key,mode:'model',limitations:['Synthetic mocked model response; no real model called.']};
  appendMockTurn({...job,message:job.message},job.result,job.id,meta.parent);
  job.result.archive=mockArchiveReceipt('deliverables',deliverable,job.project_id);
  job.status='completed';job.stage='save';job.stages.forEach(stage=>stage.status='completed');job.updated_at=new Date().toISOString();job.revision++;
}
function cancelMockWorkflow(meta) {
  if(['completed','failed','interrupted','cancelled'].includes(meta.job.status))return;
  meta.hold=false;meta.job.status='cancelled';meta.job.error='';meta.job.retryable=false;meta.job.revision++;meta.job.updated_at=new Date().toISOString();
  meta.job.stages.forEach(stage=>{if(stage.status==='running')stage.status='cancelled';else if(stage.status==='pending')stage.status='skipped';});
}
async function mockWorkflowRequest(event,url){
  if(!url.pathname.startsWith('/api/workflows/jobs'))return false;
  const workspace=Object.entries(event.request.headers).find(([name])=>name.toLowerCase()==='x-workspace')?.[1]||'personal';
  if(url.pathname==='/api/workflows/jobs'&&event.request.method==='GET'){
    await fulfillJson(event,{jobs:[...workflowJobs.values()].filter(meta=>meta.workspace===workspace).map(meta=>meta.job).reverse()});return true;
  }
  if(url.pathname==='/api/workflows/jobs/cancel'&&event.request.method==='POST'){
    const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:event.request.method,body});
    const key=workspace+':'+body.request_id;workflowCancelTombstones.add(key);const id=workflowRequestKeys.get(key),meta=id&&workflowJobs.get(id);
    if(meta){cancelMockWorkflow(meta);await fulfillJson(event,{job:meta.job});}else await fulfillJson(event,{status:'cancelled',request_id:body.request_id});return true;
  }
  if(url.pathname==='/api/workflows/jobs'&&event.request.method==='POST'){
    const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:event.request.method,body});
    const cacheKey=workspace+':'+body.request_id;
    if(workflowRequestKeys.has(cacheKey)){await fulfillJson(event,{job:workflowJobs.get(workflowRequestKeys.get(cacheKey)).job},202);return true;}
    const id=randomUUID(),stamp=new Date(body.message==='Synthetic durable running job'?Date.now()-120000:Date.now()).toISOString();
    const job={id,workflow_key:body.workflow_key,message:body.message,project_id:body.project_id,document_ids:body.document_ids,mode:body.mode,model_id:body.model_id,quality_mode:body.quality_mode,conversation_id:body.conversation_id,revision_of:body.revision_of,status:'queued',stage:'prepare',stage_label:'整理范围',eta:{min_seconds:30,max_seconds:60,estimated:true,basis:'Synthetic phase estimate, not token progress.'},elapsed_ms:0,events:[{sequence:1,elapsed_ms:0,stage:'prepare',label:'整理范围',status:'completed',detail:'仅使用提交时所选材料。'}],stages:mockStages(),revision:1,created_at:stamp,updated_at:stamp,poll_after_ms:1500,retryable:false};
    const documents=await Promise.all(body.document_ids.map(documentId=>api('documents/'+documentId)));
    const parent=body.revision_of?(await api('state')).deliverables.find(item=>item.id===body.revision_of):null;
    const meta={workspace,job,documents,parent,reads:0,attempts:1,hold:body.message==='Synthetic durable running job'||body.message.startsWith('Synthetic stoppable workflow'),disconnectOnce:false};
    workflowJobs.set(id,meta);workflowRequestKeys.set(cacheKey,id);if(workflowCancelTombstones.has(cacheKey))cancelMockWorkflow(meta);
    await fulfillJson(event,{job},202);return true;
  }
  const parts=url.pathname.split('/'),meta=workflowJobs.get(parts[4]);
  if(!meta||meta.workspace!==workspace){await fulfillJson(event,{error:'Synthetic job not found'},404);return true;}
  if(parts[5]==='cancel'&&event.request.method==='POST'){
    requests.push({path:url.pathname,method:event.request.method,body:JSON.parse(event.request.postData||'{}')});cancelMockWorkflow(meta);await fulfillJson(event,{job:meta.job});return true;
  }
  if(parts[5]==='retry'&&event.request.method==='POST'){
    requests.push({path:url.pathname,method:event.request.method,body:JSON.parse(event.request.postData||'{}')});
    if(meta.job.status==='cancelled'){await fulfillJson(event,{error:'Synthetic cancelled jobs require a new submission'},409);return true;}
    meta.attempts++;meta.reads=0;meta.hold=false;meta.job.status='queued';meta.job.error='';meta.job.retryable=false;meta.job.stage='prepare';meta.job.stages=mockStages();meta.job.revision++;
    await fulfillJson(event,{job:meta.job},202);return true;
  }
  if(event.request.method==='GET'){
    if(meta.disconnectOnce){meta.disconnectOnce=false;await fulfillJson(event,{error:'Synthetic temporary connection failure'},503);return true;}
    if(['queued','running'].includes(meta.job.status)){
      meta.reads++;meta.job.status='running';meta.job.stage=meta.reads===1?'generate':'review';meta.job.revision++;meta.job.updated_at=new Date().toISOString();
      meta.job.elapsed_ms=Date.now()-Date.parse(meta.job.created_at);meta.job.stage_label=meta.reads===1?'生成正文':'复核证据';meta.job.progress_percent=meta.reads===1?17:50;meta.job.events.push({sequence:meta.job.events.length+1,elapsed_ms:meta.job.elapsed_ms,stage:meta.job.stage,label:meta.job.stage_label,status:'running',detail:'Synthetic public execution event.'});
      meta.job.stages.forEach(stage=>stage.status=stage.key==='prepare'?'completed':stage.key===meta.job.stage?'running':'pending');
      if(meta.reads>=2&&!meta.hold){
        if(meta.job.message==='Synthetic unavailable provider'||(meta.job.message==='Synthetic retryable provider'&&meta.attempts===1)){
          meta.job.status='failed';meta.job.error='Synthetic provider unavailable. Configure a supported model and retry.';meta.job.retryable=true;meta.job.stages.find(stage=>stage.key===meta.job.stage).status='failed';
        }else await finishMockWorkflow(meta);
      }
    }
    await fulfillJson(event,{job:meta.job});return true;
  }
  throw Error('Unexpected synthetic job request '+url.pathname);
}
function appendMockTurn(body,result,operationId,parent=null) {
  const conversation=mockConversations.get(body.conversation_id);if(!conversation)return result;
  const artifact=result.deliverable?{collection:'deliverables',id:result.deliverable.id,version:result.deliverable.revision_number||1}:result.meeting_id?{collection:'meetings',id:result.meeting_id}:null;
  const turn={id:randomUUID(),sequence:conversation.turns.length+1,request_id:operationId,status:'completed',user_message:body.question||body.message||body.text||body.revision_instructions||body.transcript,assistant_message:result.answer||result.summary||JSON.stringify(result.assumptions||{}),source_ids:body.document_ids||[],current_artifact:artifact,base_snapshot:parent,created_at:new Date().toISOString()};
  conversation.turns.push(turn);conversation.turns_total=conversation.turns.length;conversation.updated_at=turn.created_at;if(artifact)conversation.metadata.current_artifact=artifact;
  result.conversation_id=conversation.id;result.context={conversation_id:conversation.id,turns_total:conversation.turns_total,truncated:false,source_ids:conversation.source_ids};return result;
}
function mockArchiveReceipt(collection,record,projectId,{failed=false}={}) {
  const archive_id=randomUUID(),folder=mockBindings.get(String(projectId))||path.join(temp,'synthetic-archives',String(projectId));
  const receipt={archive_id,collection,record_id:record.id,project_id:projectId,version:'v1',version_number:1,folder,artifact_folder:path.join(folder,'Synthetic draft v1'),status:failed?'failed':'saved_local',binding_status:mockBindings.has(String(projectId))?'bound':'managed',files:failed?[]:[{name:'Synthetic draft.html',path:path.join(folder,'Synthetic draft v1','Synthetic draft.html'),format:'html',index:0}],error:failed?'Synthetic exporter failed; record remains saved.':'',retryable:failed};
  const key=String(projectId),list=mockArchives.get(key)||[];list.unshift(receipt);mockArchives.set(key,list);return receipt;
}
async function mockContextRequest(event,url) {
  const workspace=requestWorkspace(event);
  if(url.pathname==='/api/operations'){await fulfillJson(event,{operations:[...restoreOperationIds].map(request_id=>({request_id,kind:'ask',status:mockOperations.get(request_id)?.status||'running',conversation_id:mockOperations.get(request_id)?.body?.conversation_id,elapsed_ms:12000,stage:'generate',stage_label:'调用所选模型',events:[]}))});return true;}
  if(url.pathname==='/api/artifacts/config'){if(event.request.method==='POST'){const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:'POST',body});mockBindings.set('__roots',body.roots);}await fulfillJson(event,{roots:mockBindings.get('__roots')||[]});return true;}
  if(url.pathname==='/api/conversations'){
    if(event.request.method==='POST'){const body=JSON.parse(event.request.postData||'{}'),stamp=new Date().toISOString();const conversation={...body,id:randomUUID(),workspace,turns:[],turns_total:0,created_at:stamp,updated_at:stamp};mockConversations.set(conversation.id,conversation);await fulfillJson(event,{conversation},201);}
    else await fulfillJson(event,{conversations:[...mockConversations.values()].filter(item=>item.workspace===workspace&&item.project_id===url.searchParams.get('project_id')&&item.purpose===url.searchParams.get('purpose')).reverse()});
    return true;
  }
  if(/^\/api\/conversations\/[^/]+$/.test(url.pathname)){const conversation=mockConversations.get(url.pathname.split('/')[3]);await fulfillJson(event,conversation?.workspace===workspace?{conversation}:{error:'Synthetic conversation unavailable'},conversation?.workspace===workspace?200:404);return true;}
  if(/^\/api\/operations\/[^/]+$/.test(url.pathname)){
    const id=url.pathname.split('/')[3],meta=mockOperations.get(id);if(!meta){await fulfillJson(event,{error:'Synthetic operation not registered'},404);return true;}
    await fulfillJson(event,{operation:{id,request_id:id,conversation_id:meta.body?.conversation_id,status:meta.status||'running',elapsed_ms:Date.now()-meta.start,stage:'generate',stage_label:'调用所选模型',progress_percent:null,eta:{min_seconds:20,max_seconds:55,estimated:true,basis:'按当前阶段估计，模型耗时可能变化。'},events:[{sequence:1,elapsed_ms:0,stage:'prepare',label:'核对项目与资料范围',status:'completed',detail:'仅带入本次明确选定的材料。'},{sequence:2,elapsed_ms:10,stage:'generate',label:'调用所选模型',status:'running',detail:'等待模型回复；不显示内部推理内容。'}]}});return true;
  }
  const projectMatch=url.pathname.match(/^\/api\/projects\/([^/]+)\/artifacts(?:\/bind)?$/);
  if(projectMatch){const projectId=projectMatch[1];if(event.request.method==='POST'){const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:'POST',body});mockBindings.set(projectId,body.path);}
    await fulfillJson(event,{binding:{status:mockBindings.has(projectId)?'bound':'managed',folder:mockBindings.get(projectId)||path.join(temp,'synthetic-archives',projectId),managed:!mockBindings.has(projectId),candidates:[]},archives:mockArchives.get(projectId)||[]});return true;}
  if(url.pathname==='/api/artifacts/archive'){const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:'POST',body});const record=(await api('state'))[body.collection].find(item=>item.id===body.id),receipt=mockArchiveReceipt(body.collection,record,record.project_id);await fulfillJson(event,{archive:receipt});return true;}
  if(/^\/api\/artifacts\/[^/]+\/files\/\d+$/.test(url.pathname)){requests.push({path:url.pathname,method:'GET'});await cdp.send('Fetch.fulfillRequest',{requestId:event.requestId,responseCode:200,responseHeaders:[{name:'Content-Type',value:'application/octet-stream'}],body:Buffer.from('Synthetic archived file.').toString('base64')});return true;}
  return false;
}
async function main() {
  temp = await fs.mkdtemp(path.join(os.tmpdir(), 'workos-research-cdp-'));
  const port = await freePort(), debugPort = await freePort(); origin = 'http://127.0.0.1:' + port;
  // Strip inherited model/account configuration; retain OS/PATH variables needed to start executables.
  const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(WORKOS_|OPENAI_|ANTHROPIC_|DEEPSEEK_|DSH_|CF_)/i.test(key)));
  Object.assign(env, { WORKOS_SYNC_ROOT: '', WORKOS_MEMORY_ROOT: '', WORKOS_PUBLIC_ORIGIN: '', WORKOS_PUBLIC_AUTH_MODE: 'access', SYNC_ROOT: '', MEMORY_ROOT: '', PUBLIC_ORIGIN: '', AUTH_MODE: 'access', PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' });
  server = start(process.env.WORKOS_TEST_PYTHON || 'python', ['-m', 'workos.server', '--port', String(port), '--data-dir', path.join(temp, 'data')], { env });
  const boot = await until(async () => { if(server.startError)throw server.startError; if(server.exitCode !== null)throw Error('Python exited '+server.exitCode);return api('bootstrap'); }, 'isolated app bootstrap');
  csrf = boot.csrf;
  assert(!boot.memory_root_available && !boot.sync?.enabled, 'Isolation roots unexpectedly enabled');
  const alpha = await api('projects', { name: 'Synthetic Alpha Company', sector: 'Synthetic testing', stage: '尽调', priority: '中' });
  const beta = await api('projects', { name: 'Synthetic Beta Company', sector: 'Synthetic testing', stage: '初筛', priority: '中' });
  const quote = 'Synthetic quoted source: Alpha revenue grew 17 percent. No real business data.';
  const doc = await api('documents', { title: 'Synthetic Alpha Evidence', project_id: alpha.id, kind: 'research', category: 'Test', private: true, content: quote + '\n\nA second synthetic paragraph.' });
  await api('documents', { title: 'Synthetic Beta Evidence', project_id: beta.id, kind: 'research', category: 'Test', private: true, content: 'Synthetic Beta unrelated evidence.' });
  const memo1 = await api('upload', { name: 'Synthetic Alpha Memo v1.txt', base64: Buffer.from('Synthetic investment memo draft one. No real business data.').toString('base64'), project_id: alpha.id, kind: 'research', source_ref: 'SyntheticFolder/IC/Synthetic Alpha Memo v1.txt' });
  const memo2 = await api('upload', { name: 'Synthetic Alpha Memo v2.txt', base64: Buffer.from('Synthetic investment memo draft two. No real business data.').toString('base64'), project_id: alpha.id, kind: 'research', source_ref: 'SyntheticFolder/IC/Synthetic Alpha Memo v2.txt' });
  for (let index=1; index<=5; index++) await api('notes', { title: 'Synthetic Alpha research note '+index, project_id: alpha.id, body: 'Synthetic research note.', status: '待核实' });
  await api('meetings', { title: 'Synthetic Alpha meeting minutes', project_id: alpha.id, transcript: 'Synthetic transcript.', date: '2026-10-03' });
  await api('deliverables', { title: 'Synthetic Alpha research deliverable', project_id: alpha.id, kind: '研究简报', body: 'Synthetic editable research deliverable.' });
  const assumptions={currency:'RMB',unit:'百万元',period:'FY2025A',net_income:100,pe_multiple:12,diluted_shares:50};
  const modelResult=await api('model/valuation',{method:'net_income',assumptions});
  const savedModel=await api('deliverables',{title:'Synthetic saved valuation model',project_id:alpha.id,kind:'自定义',method:'net_income',assumptions,result:modelResult});
  const source = await api('documents/' + doc.id);
  const answer = '# Synthetic heading\n\n**Bold evidence** [S1]\n\n- First item\n- Second item\n\n| Metric | Value |\n| --- | --- |\n| Synthetic growth | 17% |\n\n<img src=x onerror="window.__cdpUnsafe=1">\n<script>window.__cdpUnsafe=1</script>\n<iframe src="https://invalid.example/"></iframe>';
  const nohitQuestion='请通读这份材料，概括主要结论，并列出需要核实的问题。';
  const nohitWarning='关键词未命中；已按你选定的范围使用原文节选进行模型分析，未读部分仍需核实。';
  chrome = start(chromeExecutable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + debugPort, '--user-data-dir=' + path.join(temp, 'chrome-profile'), 'about:blank']);
  const targets = await until(() => json('http://127.0.0.1:' + debugPort + '/json/list'), 'new Chrome CDP');
  cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  cdp.on('Runtime.exceptionThrown', event => runtimeErrors.push(event.exceptionDetails.exception?.description || event.exceptionDetails.text));
  // Pause all renderer traffic: only this loopback app is allowed; AI endpoints never reach Python.
  cdp.on('Fetch.requestPaused', async event => {
    const url = new URL(event.request.url);
    if (url.origin !== origin) return cdp.send('Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' });
    const opId=requestOperation(event);if(opId&&event.request.method==='POST'&&/^\/api\/(ask|agent|meeting-draft|model\/parse-assumptions|workflows\/plan|models\/check)$/.test(url.pathname)&&!mockOperations.has(opId))mockOperations.set(opId,{start:Date.now(),body:JSON.parse(event.request.postData||'{}'),status:'running'});
    if(await mockContextRequest(event,url))return;
    if(csrfScenario.enabled&&url.pathname==='/api/bootstrap'&&event.request.method==='GET'){
      csrfScenario.bootstrapCalls++;
      // Only the browser receives a synthetic stale token. No server token or endpoint is modified.
      const fresh=await api('bootstrap');
      const result={...syntheticBoot(fresh),csrf:csrfScenario.seedStale?'synthetic-expired-token':fresh.csrf};
      return fulfillJson(event,result);
    }
    if(url.pathname==='/api/bootstrap'&&event.request.method==='GET')return fulfillJson(event,syntheticBoot(await api('bootstrap')));
    if(url.pathname==='/api/models'&&event.request.method==='GET'){requests.push({path:url.pathname,method:'GET'});return fulfillJson(event,{models:structuredClone(syntheticModels)});}
    if(url.pathname==='/api/models/check'&&event.request.method==='POST'){const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:'POST',body,operationId:opId});const selected=syntheticModels.groups.flatMap(group=>group.models).find(item=>item.mode===body.mode&&item.id===body.model_id);if(selected){const fail=syntheticModelCheckFailures.delete(selected.selection_id);Object.assign(selected,{status:fail?'unavailable':'verified',available:!fail,checked_at:new Date().toISOString(),reason:fail?'Synthetic transient connection unavailable':''});}return fulfillJson(event,{model:structuredClone(selected),models:structuredClone(syntheticModels)});}
    if(csrfScenario.enabled&&url.pathname==='/api/model/parse-assumptions'){
      const body=JSON.parse(event.request.postData||'{}');
      const token=Object.entries(event.request.headers).find(([name])=>name.toLowerCase()==='x-csrf-token')?.[1];
      csrfScenario.parseRequests.push({body,token,serialized:event.request.postData||'',mode:csrfScenario.mode});requests.push({path:url.pathname,method:event.request.method,body});
      if(csrfScenario.mode==='forbidden')return fulfillJson(event,{code:'permission_denied',error:'Synthetic permissions denied'},403);
      if(csrfScenario.parseRequests.filter(item=>item.mode==='recover').length===1){
        await cdp.evaluate("window.__csrfPendingReview=document.querySelector('.valuation-review');window.__csrfPendingMain=document.querySelector('#main')");
        // The real temporary server rejects the stale token before any model call.
        if(token!=='synthetic-expired-token'){
          interceptionErrors.push('Refused to forward a parser request without the deliberately invalid token');
          return cdp.send('Fetch.failRequest',{requestId:event.requestId,errorReason:'BlockedByClient'});
        }
        return cdp.send('Fetch.continueRequest',{requestId:event.requestId});
      }
      csrfScenario.retryDom=await cdp.evaluate("({sameReview:document.querySelector('.valuation-review')===window.__csrfPendingReview,sameMain:document.querySelector('#main')===window.__csrfPendingMain,ready:document.querySelector('#main').getAttribute('aria-busy')!=='true',text:document.querySelector('#valuation-text').value,json:document.querySelector('#valuation-json').value})");
      csrfScenario.successfulModelCalls++;
      return fulfillJson(event,appendMockTurn(body,{assumptions:csrfScenario.expected,missing:[],unmapped_fields:[]},opId));
    }
    if (/^\/api\/documents\/[^/]+\/original$/.test(url.pathname)) originalRequests.push(url.pathname);
    if(url.pathname==='/api/workflows/plan') requests.push({path:url.pathname,method:event.request.method,body:JSON.parse(event.request.postData||'{}')});
    if(/^\/api\/operations\/[^/]+\/cancel$/.test(url.pathname)){
      requests.push({path:url.pathname,method:event.request.method,body:JSON.parse(event.request.postData||'{}')});
      const id=url.pathname.split('/')[3],remaining=operationCancelFailures.get(id)||0;if(remaining){operationCancelFailures.set(id,remaining-1);return fulfillJson(event,{error:'Synthetic cancellation temporarily unavailable'},503);}
      if(mockOperations.has(id))mockOperations.get(id).status='cancelled';
      for(const conversation of mockConversations.values())for(const turn of conversation.turns)if(turn.request_id===id)turn.status='cancelled';
      return fulfillJson(event,{status:'cancelled',steps:[]});
    }
    if(await mockWorkflowRequest(event,url))return;
    if(auxiliaryModelMocks.has(url.pathname)){
      const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:event.request.method,body,operationId:opId});const mock=auxiliaryModelMocks.get(url.pathname),result=typeof mock==='function'?await mock(body):structuredClone(mock);return fulfillJson(event,appendMockTurn(body,result,opId));
    }
    if (['/api/ask', '/api/agent'].includes(url.pathname)) {
      const body = JSON.parse(event.request.postData || '{}'),operationId=Object.entries(event.request.headers).find(([name])=>name.toLowerCase()==='x-workos-request-id')?.[1]; requests.push({ path: url.pathname, method: event.request.method, body, operationId });
      const result = url.pathname === '/api/ask' ? { answer, mode: 'model', elapsed_ms: 1, citations: [{ document_id: doc.id, id: source.chunks[0].id, ordinal: source.chunks[0].ordinal, title: doc.title, quote }] } : { answer, steps: [] };
      // This is a synthetic presentation fixture; backend tests verify actual no-hit provider dispatch.
      if(url.pathname==='/api/ask'&&body.question===nohitQuestion)Object.assign(result,{answer:'已阅读选定材料的原文节选。合成结论：收入增长17%；仍需核实定义和统计期间。[S1]',model:'DeepSeek V4.1 Flash',model_called:true,retrieval_basis:'selected_excerpt',warning:nohitWarning});
      appendMockTurn(body,result,opId);
      return cdp.send('Fetch.fulfillRequest', { requestId: event.requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'application/json; charset=utf-8' }], body: Buffer.from(JSON.stringify(result)).toString('base64') });
    }
    if (/^\/api\/(meeting-draft|meeting-ai|meeting-expert|valuation-parse|ai|dsh|model\/parse-assumptions)/.test(url.pathname) && event.request.method !== 'GET') {
      interceptionErrors.push('Blocked unexpected model endpoint: ' + url.pathname);
      return cdp.send('Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' });
    }
    return cdp.send('Fetch.continueRequest', { requestId: event.requestId });
  });
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: path.join(temp, 'downloads') });
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: origin });
  await until(() => cdp.evaluate("!!document.querySelector('.project-card') && document.querySelector('#main').getAttribute('aria-busy')!=='true'"), 'homepage synthetic cards');
  console.log('Isolated app PID ' + server.pid + '; Chrome PID ' + chrome.pid + '; loopback port ' + port);
  await check('no separate projects navigation', async () => assert(await cdp.evaluate("!document.querySelector('#primary-nav [data-page=projects]')"), 'Separate projects sidebar entry remains'));
  await check('homepage has company folders and one natural-language work start', async () => {
    const result = await cdp.evaluate("({cards:[...document.querySelectorAll('.project-title')].map(e=>e.textContent),composer:document.querySelectorAll('#start-input').length,purposes:[...document.querySelector('#start-purpose').options].map(e=>e.textContent),routes:document.querySelectorAll('[data-action=start-route]').length})");
    assert(result.cards.includes(alpha.name) && result.cards.includes(beta.name) && result.composer===1 && result.purposes.length>=12 && result.routes===3, JSON.stringify(result));
    await screenshot('home-1280');
  });
  await check('homepage project creation validates name auto-selects and preserves existing work', async () => {
    const before=await api('state'),message='Synthetic preserve home work while creating a company';
    await route('research');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');
    await route('overview');await select('#start-project',beta.id);await select('#start-purpose','brief');await fill('#start-input',message);
    assert(await cdp.evaluate("!!document.querySelector('.start-work [data-action=start-create-project]')&&[...document.querySelector('#start-project').options].some(item=>item.value==='__create_project__')"),'Homepage project creation entries missing');
    await click('[data-action=start-create-project]');await until(()=>cdp.evaluate("document.querySelector('#modal').open&&!!document.querySelector('#field-name')"),'home new-project dialog');
    await fill('#field-name','Synthetic cancelled project');await click('[data-close-dialog=modal]');
    const cancelled=await cdp.evaluate("({project:document.querySelector('#start-project').value,message:document.querySelector('#start-input').value,purpose:document.querySelector('#start-purpose').value,open:document.querySelector('#modal').open})");
    assert(!cancelled.open&&cancelled.project===beta.id&&cancelled.message===message&&cancelled.purpose==='brief','Cancellation changed current home work: '+JSON.stringify(cancelled));
    assert(JSON.stringify((await api('state')).projects)===JSON.stringify(before.projects),'Cancelled project was persisted');
    await select('#start-project','__create_project__');await until(()=>cdp.evaluate("document.querySelector('#modal').open&&!!document.querySelector('#field-name')"),'dropdown new-project dialog');
    assert(await cdp.evaluate("document.querySelector('#field-name').required"),'New project name is not required');await fill('#field-name','');await click('#modal-submit');
    assert(await cdp.evaluate("document.querySelector('#modal').open&&!document.querySelector('#field-name').checkValidity()"),'Blank project name did not retain validation dialog');
    assert(JSON.stringify((await api('state')).projects)===JSON.stringify(before.projects),'Blank name created a project');
    await fill('#field-name','Synthetic created from home');await click('#modal-submit');await until(()=>cdp.evaluate("!document.querySelector('#modal').open&&location.hash==='#overview'&&!!document.querySelector('#start-input')"),'new home project saved');
    const after=await api('state'),created=after.projects.find(item=>item.name==='Synthetic created from home');
    assert(created&&after.projects.length===before.projects.length+1&&await cdp.evaluate('document.querySelector("#start-project").value==='+q(created.id)),'Created project not automatically selected');
    assert(await cdp.evaluate('document.querySelector("#start-input").value==='+q(message)+'&&document.querySelector("#start-purpose").value===\'brief\''),'Project creation lost home request or purpose');
    assert(JSON.stringify(after.projects.filter(item=>item.id!==created.id))===JSON.stringify(before.projects)&&JSON.stringify(after.documents)===JSON.stringify(before.documents),'Creating a project changed prior projects or moved/copied materials');
    await route('research');assert(await cdp.evaluate('document.querySelector("#research-project").value==='+q(alpha.id)+'&&document.querySelector('+q('[data-source-id="'+doc.id+'"]')+').checked'),'Project creation changed prior research source scope/selection');
    await select('#research-project','');await route('overview');await select('#start-project','');await select('#start-purpose','');await fill('#start-input','');
  });
  await check('legacy #projects opens company home', async () => { await route('projects'); assert(await cdp.evaluate("!!document.querySelector('.project-card') && !/不存在|错误/.test(document.querySelector('main h1').textContent)"), 'Legacy project route broken'); });
  await route('research');
  await check('one research prompt textarea', async () => assert(await cdp.evaluate("document.querySelectorAll('main textarea').length===1 && !!document.querySelector('#question-input')"), 'Research has duplicate prompt textareas'));
  await check('ask/actions modes retain independent drafts', async () => {
    await fill('#question-input', 'Synthetic ask draft'); await select('#research-intent', 'actions'); await fill('#question-input', 'Synthetic action draft');
    await select('#research-intent', 'ask'); assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic ask draft'"), 'Ask draft lost switching modes');
    await select('#research-intent', 'actions'); assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic action draft'"), 'Action draft lost switching modes'); await select('#research-intent', 'ask');
    await select('#research-intent','workflow');await fill('#question-input','Synthetic workflow draft');await select('#research-intent','ask');
    assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic ask draft'"),'Workflow draft replaced ask draft');await select('#research-intent','workflow');
    assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic workflow draft'"),'Workflow draft lost on mode change');await select('#research-intent','ask');
  });
  await check('company filtering and navigation preserve research scope', async () => {
    await select('#research-project', alpha.id);
    const visible = await cdp.evaluate("[...document.querySelectorAll('[data-source-id]')].map(e=>e.dataset.sourceId)");
    assert(visible.length===3 && visible.includes(doc.id) && visible.includes(memo1.id) && visible.includes(memo2.id), 'Company filter leaked evidence: '+JSON.stringify(visible));
    await click('#primary-nav [data-page=overview]'); await click('#primary-nav [data-page=research]');
    assert(await cdp.evaluate('document.querySelector("#research-project").value===' + q(alpha.id)), 'Company scope reset across sidebar navigation');
  });
  await check('ask uses explicit selected IDs and /api/ask', async () => {
    await select('#research-project', alpha.id); await select('#research-intent', 'ask');
    await fill('#question-input', 'Synthetic no-selection question'); await click('#ask-form button[type=submit]');
    await cdp.evaluate("new Promise(resolve=>setTimeout(resolve,200))");
    assert(!requests.some(r=>r.path==='/api/ask'), 'Ask sent documents without explicit selection');
    await click('[data-source-id="' + doc.id + '"]'); await fill('#question-input', 'Synthetic evidence question'); await click('#ask-form button[type=submit]');
    await until(() => requests.find(r=>r.path==='/api/ask'), 'intercepted ask');
    const req = requests.find(r=>r.path==='/api/ask');
    assert(req.method==='POST' && req.body.question==='Synthetic evidence question' && req.body.project_id===alpha.id && JSON.stringify(req.body.document_ids)===JSON.stringify([doc.id]), 'Wrong ask payload: '+JSON.stringify(req));
    await until(() => cdp.evaluate("!!document.querySelector('.answer-text') && !document.querySelector('#question-input').disabled"), 'ask answer rendering');
  });
  await check('ask output Markdown structures and HTML safety', () => markdown('.answer-text'));
  await check('citation click opens highlighted quoted source', async () => {
    await click('[data-action=citation]'); await until(() => cdp.evaluate("document.querySelector('#document-dialog').open && !!document.querySelector('.document-chunk.highlight')"), 'citation source dialog');
    const result = await cdp.evaluate("({title:document.querySelector('#document-title').textContent,quote:document.querySelector('.document-chunk.highlight').textContent})");
    assert(result.title===doc.title && result.quote.includes(quote), 'Wrong citation target: '+JSON.stringify(result));
    await click('[data-close-dialog=document-dialog]');
  });
  // Close any source dialog even when its assertion fails, so subsequent checks are independent.
  await cdp.evaluate("document.querySelector('#document-dialog').close()");
  await check('editable paste is not globally imported (textarea/input/contenteditable)', async () => {
    const count = (await api('state')).documents.length;
    const result = await cdp.evaluate(`(() => { const nodes=[document.querySelector('#question-input'),document.querySelector('#source-search')]; const editable=document.createElement('div');editable.contentEditable='true';document.querySelector('main').append(editable);nodes.push(editable);const prevented=nodes.map(e=>{e.focus();const data=new DataTransfer();data.setData('text/plain','Synthetic paste that must not become a document');const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});e.dispatchEvent(event);return {tag:e.tagName,prevented:event.defaultPrevented};});editable.remove();return prevented;})()`);
    await cdp.evaluate("new Promise(resolve=>setTimeout(resolve,250))");
    assert(result.every(e=>!e.prevented), 'Global paste consumed editable input: '+JSON.stringify(result));
    assert((await api('state')).documents.length===count, 'Pasting in editable field imported an unsolicited document');
  });
  await check('actions use /api/agent without selected documents', async () => {
    await select('#research-intent', 'actions'); await fill('#question-input', 'Synthetic create task request'); await click('#ask-form button[type=submit]');
    await until(() => requests.find(r=>r.path==='/api/agent'), 'intercepted action'); const req=requests.find(r=>r.path==='/api/agent');
    assert(req.method==='POST' && req.body.message==='Synthetic create task request' && req.body.project_id===alpha.id && !Object.keys(req.body).some(k=>/document|source|attachment/i.test(k)) && !JSON.stringify(req.body).includes(quote), 'Unexpected action scope/body: '+JSON.stringify(req));
    await until(() => cdp.evaluate("!!document.querySelector('.agent-answer') && !document.querySelector('#question-input').disabled"), 'action result');
  });
  await check('action output Markdown and HTML safety', () => markdown('.agent-answer'));
  await check('action scope and model survive composer rerenders', async () => {
    await cdp.evaluate("document.querySelector('#agent-project-scope').checked=false;document.querySelector('#agent-project-scope').dispatchEvent(new Event('change',{bubbles:true}))");
    await click('[data-source-id="'+doc.id+'"]');
    assert(await cdp.evaluate("!document.querySelector('#agent-project-scope').checked && document.querySelector('.source-scope').textContent.includes('工作区')"), 'Action scope reverted during selection');
    const model=await cdp.evaluate("[...document.querySelector('#agent-model').options].find(o=>o.value!==document.querySelector('#agent-model').value&&!o.disabled)?.value");
    assert(model, 'Missing second action model'); await select('#agent-model',model); await select('#research-intent','ask'); await select('#research-intent','actions');
    assert(await cdp.evaluate('document.querySelector("#agent-model").value==='+q(model)), 'Action model reverted during mode switching');
    await cdp.evaluate("document.querySelector('#agent-project-scope').checked=true;document.querySelector('#agent-project-scope').dispatchEvent(new Event('change',{bubbles:true}))");
    await select('#research-project',beta.id); assert(await cdp.evaluate("!document.querySelector('.agent-answer')"),'Alpha action result shown under Beta');
    await fill('#question-input','Synthetic Beta scoped action'); await click('#ask-form button[type=submit]');
    await until(()=>requests.filter(r=>r.path==='/api/agent').length===2,'Beta action request');
    const sent=requests.filter(r=>r.path==='/api/agent');assert(sent[1].body.conversation_id!==sent[0].body.conversation_id&&mockConversations.get(sent[1].body.conversation_id)?.project_id===beta.id&&!('history' in sent[1].body),'Alpha client history or conversation sent in Beta request');
    await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'Beta action complete');
  });
  await check('project material library automatically groups versions and includes every record', async () => {
    assert(memo1.task_group && memo1.task_group_source==='automatic' && memo1.version_family===memo2.version_family,'Automatic Memo family missing: '+JSON.stringify({memo1,memo2}));
    await route('overview'); await click('[data-action=project-detail][data-id="'+alpha.id+'"]');
    const records=(await api('state'));const expected=['documents','notes','meetings','deliverables','tasks'].flatMap(c=>records[c].filter(i=>i.project_id===alpha.id));
    const observed=await cdp.evaluate("({rows:[...document.querySelectorAll('[data-material-id]')].map(e=>e.dataset.materialId),families:document.querySelectorAll('.material-family').length,text:document.querySelector('.material-library').textContent})");
    assert(expected.every(i=>observed.rows.includes(i.id)) && observed.rows.length===expected.length && observed.families>=1,'Library omitted or duplicated records: '+JSON.stringify(observed));
    assert(!observed.text.includes(memo1.version_family) && !/最新定稿|最终确认/.test(observed.text),'Opaque family ID or unverified final claim displayed');
    await click('.material-family summary');assert(await cdp.evaluate("document.querySelector('.material-family').open && document.querySelector('.material-family').textContent.includes('最近导入')"),'Versions did not expand');
    await select('#library-group',memo1.task_group);await cdp.evaluate("document.querySelectorAll('.material-family').forEach(e=>e.open=true);document.querySelector('.material-library').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('project-library-1280');await select('#library-group','');
  });
  await check('original file download uses authenticated document original route', async () => {
    await cdp.evaluate("document.querySelectorAll('.material-family').forEach(e=>e.open=true)");
    await click('[data-action=original-download][data-id="'+memo1.id+'"]');
    await until(()=>originalRequests.includes('/api/documents/'+memo1.id+'/original'),'original download request');
  });
  await check('custom project subtask creates and organizes a new document', async () => {
    const group='Synthetic ESG diligence';
    await click('[data-action=project-subtask]'); await fill('#field-title',group); await click('#modal-submit');
    await until(()=>cdp.evaluate("!document.querySelector('#modal').open && !!document.querySelector('[data-task-group]')"),'custom subtask saved');
    assert(await cdp.evaluate('document.querySelector("#library-group").value==='+q(group)), 'Custom subtask not selected');
    await click('.material-group [data-action=project-create][data-collection=documents]');
    assert(await cdp.evaluate('document.querySelector("#field-task_group").value==='+q(group)), 'New document did not inherit group');
    await fill('#field-title','Synthetic custom task evidence'); await fill('#field-content','Synthetic ESG diligence evidence without real data.');await click('#modal-submit');
    await until(()=>cdp.evaluate("!document.querySelector('#modal').open && [...document.querySelectorAll('.material-title')].some(e=>e.textContent==='Synthetic custom task evidence')"),'custom document saved');
    const state=await api('state'), saved=state.documents.find(i=>i.title==='Synthetic custom task evidence');
    assert(saved?.task_group===group && saved.task_group_source==='manual' && state.tasks.some(i=>i.project_id===alpha.id&&i.title===group&&i.task_group===group),'Custom subtask/document metadata incorrect');
    assert(state.documents.find(i=>i.id===memo1.id)?.task_group===memo1.task_group && state.documents.find(i=>i.id===doc.id)?.task_group===doc.task_group,'Common words in a custom subtask absorbed unrelated existing documents');
  });
  await check('research task filter scopes selections and resets on project switch', async () => {
    await select('#library-group',memo1.task_group);await click('.material-group [data-action=group-research]');
    const result=await cdp.evaluate("({group:document.querySelector('#source-group').value,ids:[...document.querySelectorAll('[data-source-id]')].map(e=>e.dataset.sourceId)})");
    assert(result.group===memo1.task_group&&result.ids.length===2&&result.ids.includes(memo1.id)&&result.ids.includes(memo2.id),'Task source filter wrong: '+JSON.stringify(result));
    await click('#source-select-all');await select('#source-group','');assert(await cdp.evaluate("[...document.querySelectorAll('[data-source-id]')].every(e=>!e.checked)"),'Hidden prior task selection retained');
    await select('#source-group',memo1.task_group);await select('#research-project',beta.id);assert(await cdp.evaluate("document.querySelector('#source-group').value===''"),'Task filter not reset with company');
  });
  await check('new records default to automatic organization without manual setup', async () => {
    await select('#research-project',alpha.id);await click('[data-action=create][data-collection=notes]');
    assert(await cdp.evaluate("document.querySelector('#field-task_group').value===''"),'New record requires explicit task group');
    await fill('#field-title','Synthetic automatic research note');await fill('#field-body','Synthetic fundamental research finding.');await click('#modal-submit');
    await until(()=>cdp.evaluate("!document.querySelector('#modal').open"),'automatic note save');
    const saved=(await api('state')).notes.find(i=>i.title==='Synthetic automatic research note');
    assert(saved?.task_group&&saved.task_group_source==='automatic'&&saved.project_id===alpha.id,'Automatic new-record classification failed');
  });
  await check('folder intake preserves relative source path and creates automatic metadata', async () => {
    await select('#research-project',alpha.id);
    assert(await cdp.evaluate("document.querySelector('#research-folder-input').hasAttribute('webkitdirectory') && !!document.querySelector('[data-action=upload-folder]')"),'Folder import entry missing');
    await cdp.evaluate("(() => { const input=document.querySelector('#research-folder-input'); const file=new File(['Synthetic industry research folder fixture.'],'Synthetic Folder Research.txt',{type:'text/plain'});Object.defineProperty(file,'webkitRelativePath',{value:'SyntheticFolder/Research/Synthetic Folder Research.txt'});const transfer=new DataTransfer();transfer.items.add(file);input.files=transfer.files;input.dispatchEvent(new Event('change',{bubbles:true}));})()");
    const saved=await until(async()=>{const state=await api('state');return state.documents.find(i=>i.filename==='Synthetic Folder Research.txt');},'folder fixture import');
    assert(saved.source_ref==='SyntheticFolder/Research/Synthetic Folder Research.txt'&&saved.task_group_source==='automatic'&&saved.attachment_name==='Synthetic Folder Research.txt','Folder metadata/source missing: '+JSON.stringify(saved));
    await until(()=>cdp.evaluate("!document.querySelector('.file-progress')"),'folder import completed');
  });
  await check('home intent staging chooses a recipe and never sends sources before submit', async () => {
    await route('overview');await select('#start-project',alpha.id);await fill('#start-input','审阅协议并指出交易条款需要核实的问题');await click('#start-form button[type=submit]');
    await until(()=>cdp.evaluate("location.hash==='#research' && document.querySelector('#research-intent').value==='workflow'"),'legal workflow stage');
    const result=await cdp.evaluate("({key:document.querySelector('#workflow-purpose').value,project:document.querySelector('#research-project').value,selected:[...document.querySelectorAll('[data-source-id]')].filter(e=>e.checked).length,composers:document.querySelectorAll('main textarea').length})");
    assert(result.key==='legal'&&result.project===alpha.id&&result.selected===0&&result.composers===1&&await cdp.evaluate("document.querySelector('#workflow-quality').value==='thorough'"),'Bad staged workflow: '+JSON.stringify(result));
    assert(!requests.some(r=>r.path==='/api/workflows/jobs'),'Planning silently generated/sent sources');
    const plan=requests.find(r=>r.path==='/api/workflows/plan');assert(plan&&Object.keys(plan.body).length===1&&!JSON.stringify(plan.body).includes(quote),'Intent plan sent project materials');
    await click('#ask-form button[type=submit]');await cdp.evaluate('new Promise(resolve=>setTimeout(resolve,150))');assert(!requests.some(r=>r.path==='/api/workflows/jobs'),'Required-source recipe ran without selected material');
    await click('[data-source-id="'+doc.id+'"]');await click('#ask-form button[type=submit]');
    await until(()=>requests.some(r=>r.path==='/api/workflows/jobs'),'workflow explicit generation');await until(()=>cdp.evaluate("!!document.querySelector('.workflow-result')&&!document.querySelector('#question-input').disabled"),'saved workflow UI');
    const request=requests.find(r=>r.path==='/api/workflows/jobs');assert(request.body.workflow_key==='legal'&&JSON.stringify(request.body.document_ids)===JSON.stringify([doc.id])&&request.body.project_id===alpha.id,'Workflow source scope wrong');
    const saved=(await api('state')).deliverables.find(i=>i.title==='Synthetic legal draft');assert(saved?.workflow_key==='legal'&&saved.source_ids.includes(doc.id)&&saved.body.includes('Editable draft')&&saved.quality_report?.facts_verified===false&&saved.generation_id,'Workflow draft was not persisted');
    assert(await cdp.evaluate("!!document.querySelector('.workflow-result .markdown-body h1') && !!document.querySelector('.workflow-result [data-action=workflow-citation]') && document.querySelector('.workflow-result').textContent.includes('已保存')"),'Workflow Markdown/citation/saved status missing');
    await cdp.evaluate("document.querySelector('.question-panel').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('workflow-result-1280');
    await click('.workflow-result [data-action=workflow-citation]');await until(()=>cdp.evaluate("document.querySelector('#document-dialog').open && document.querySelector('#document-title').textContent==='Synthetic Alpha Evidence'"),'workflow citation original');await click('[data-close-dialog=document-dialog]');
  });
  await check('email draft can use direct instructions with no selected sources and be edited', async () => {
    await route('overview');await fill('#start-input','写一封英文邮件，请对方下周提供财务数据');await select('#start-purpose','');await click('#start-form button[type=submit]');
    await until(()=>cdp.evaluate("location.hash==='#research'&&document.querySelector('#workflow-purpose')?.value==='email'"),'email workflow staged');
    assert(await cdp.evaluate("[...document.querySelectorAll('[data-source-id]')].every(e=>!e.checked) && ![...document.querySelector('#ask-mode').options].some(o=>o.value==='local:')"),'Email inherited old sources or misleading no-outbound workflow option');
    await click('#ask-form button[type=submit]');await until(()=>requests.filter(r=>r.path==='/api/workflows/jobs').length===2,'email generation');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&document.querySelectorAll('.workflow-result').length===2"),'email saved');
    const request=requests.filter(r=>r.path==='/api/workflows/jobs')[1];assert(request.body.workflow_key==='email'&&request.body.document_ids.length===0,'Email sent old selected documents');
    const saved=(await api('state')).deliverables.find(i=>i.title==='Synthetic email draft');assert(saved?.source_ids.length===0&&request.body.quality_mode==='fast','No-source email draft metadata or default mode wrong');
    await click('.workflow-result [data-action=open-record]');await until(()=>cdp.evaluate("location.hash==='#deliverables'&&!!document.querySelector('#deliverable-body')"),'saved draft opened');
    assert(await cdp.evaluate("!!document.querySelector('#deliverable-form .quality-report')&&document.querySelector('#deliverable-form .quality-report').textContent.includes('事实仍需核实')"),'Saved draft lost persisted quality report');
    await fill('#deliverable-body','Synthetic edited email ready for human review.');assert(await cdp.evaluate("document.querySelector('#deliverable-form .quality-report').textContent.includes('编辑后未重新检查')"),'Unsaved body edits retained current-check claim');await click('#deliverable-form button[type=submit]');await until(async()=>((await api('state')).deliverables.find(i=>i.id===saved.id)?.body==='Synthetic edited email ready for human review.'),'edited draft persisted');await until(()=>cdp.evaluate("!document.querySelector('#deliverable-form button[type=submit]').disabled"),'draft save UI complete');const edited=(await api('state')).deliverables.find(item=>item.id===saved.id);assert(edited.quality_report?.stale&&edited.quality_report.checks.length===0&&await cdp.evaluate("document.querySelector('#deliverable-form .quality-report').textContent.includes('编辑后未重新检查')"),'Saved body edits did not invalidate old checks');
  });
  await check('provider failures are visible and do not claim a saved draft', async () => {
    await route('research');const before=(await api('state')).deliverables.length;await fill('#question-input','Synthetic unavailable provider');await click('#ask-form button[type=submit]');
    await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&[...document.querySelectorAll('.workflow-job')].some(e=>e.dataset.jobStatus==='failed'&&e.textContent.includes('Synthetic unavailable provider'))"),'provider failure visible');
    assert((await api('state')).deliverables.length===before,'Failure created an empty saved draft');
    assert(await cdp.evaluate("[...document.querySelectorAll('#ask-form .banner')].some(e=>e.textContent.includes('DeepSeek'))&&!document.querySelector('#ask-form').textContent.includes('尚未配置模型连接')"),'DeepSeek preset shows incorrect unconfigured generic provider status');
  });
  await check('workflow retries retain request IDs and completed repeats reuse saved drafts', async () => {
    const count=()=>workflowPosts().length;
    await fill('#question-input','Synthetic retryable provider');const before=count();await click('#ask-form button[type=submit]');await until(()=>count()===before+1,'retryable job accepted');
    const first=workflowPosts()[before],meta=[...workflowJobs.values()].find(item=>item.job.message===first.body.message);assert(/^[A-Za-z0-9_-]{8,100}$/.test(first.body.request_id),'Valid workflow request ID missing');
    await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+meta.job.id+'"]')})?.dataset.jobStatus==='failed'`),'retryable provider job failed');
    const savedBefore=(await api('state')).deliverables.length;await click('#ask-form button[type=submit]');await until(()=>count()===before+2,'failed repeat sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'failed repeat returned');
    assert(workflowPosts()[before+1].body.request_id===first.body.request_id,'Failed repeat created a new request ID');
    await click('[data-action=workflow-job-retry][data-id="'+meta.job.id+'"]');await until(()=>meta.job.status==='completed','retry job completed');await until(()=>cdp.evaluate(`!!document.querySelector(${q('.workflow-result [data-action=open-record][data-id="'+meta.job.result.deliverable.id+'"]')})`),'retried saved draft visible');
    const retry=requests.find(item=>item.path==='/api/workflows/jobs/'+meta.job.id+'/retry');assert(retry&&Object.keys(retry.body).length===0&&meta.job.message===first.body.message,'Retry changed original captured scope');
    const results=await cdp.evaluate("document.querySelectorAll('.workflow-result').length");await click('#ask-form button[type=submit]');await until(()=>count()===before+3,'completed repeat sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'completed repeat returned');
    assert((await api('state')).deliverables.length===savedBefore+1&&await cdp.evaluate("document.querySelectorAll('.workflow-result').length")===results,'Completed repeat duplicated a draft or result card');
    await fill('#question-input','Synthetic changed retry instruction');await click('#ask-form button[type=submit]');await until(()=>count()===before+4,'changed request sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'changed request accepted');
    const changed=workflowPosts()[before+3];assert(changed.body.request_id!==first.body.request_id,'Changed message reused old request ID');
    await click('[data-source-id="'+doc.id+'"]');await click('#ask-form button[type=submit]');await until(()=>count()===before+5,'changed source request sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'changed source accepted');
    const sourced=workflowPosts()[before+4];assert(sourced.body.request_id!==changed.body.request_id&&sourced.body.document_ids.includes(doc.id),'Changed sources reused old request ID');
    await route('overview');await click('[data-action=project-detail][data-id="'+alpha.id+'"]');await select('#library-group','');await cdp.evaluate("document.querySelectorAll('.material-family').forEach(e=>e.open=true)");
    await click('[data-action=edit][data-collection=documents][data-id="'+doc.id+'"]');await until(()=>cdp.evaluate("!!document.querySelector('#field-content')"),'source edit dialog');await fill('#field-content',quote+'\nSynthetic updated source text.');await click('#modal form button[type=submit]');await until(()=>cdp.evaluate("!document.querySelector('#modal').open"),'source edit completed');await route('research');
    await click('#ask-form button[type=submit]');await until(()=>count()===before+6,'updated source sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'updated source accepted');
    const updated=workflowPosts()[before+5];assert(updated.body.request_id!==sourced.body.request_id,'Edited source reused stale cached draft');
    const model=updated.body.model_id;await select('#workflow-quality','thorough');await click('#ask-form button[type=submit]');await until(()=>count()===before+7,'changed quality sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'changed quality accepted');
    const quality=workflowPosts()[before+6];assert(quality.body.request_id!==updated.body.request_id&&quality.body.quality_mode==='thorough'&&quality.body.model_id===model,'Quality change reused cache or silently changed provider');
    assert(await cdp.evaluate("document.querySelectorAll('#toast-region .toast').length<=2"),'More than two toast messages cover the work surface');
    await until(()=>[...workflowJobs.values()].filter(item=>item.job.status==='running'||item.job.status==='queued').length===0,'short jobs finished');
  });
  await check('durable jobs preserve composer focus reconnect restore workspace and retry interrupted work', async () => {
    await select('#workflow-purpose','dd');assert(await cdp.evaluate("document.querySelector('#workflow-quality').value==='thorough'"),'Complex task does not default to thorough');
    await fill('#question-input','Synthetic durable running job');await click('#ask-form button[type=submit]');const meta=await until(()=>[...workflowJobs.values()].find(item=>item.job.message==='Synthetic durable running job'),'durable acceptance');const id=meta.job.id;
    await until(()=>cdp.evaluate(`!!document.querySelector(${q('[data-job-id="'+id+'"]')})&&!document.querySelector('#question-input').disabled`),'accepted job releases composer');
    await fill('#question-input','Synthetic next work draft');await click('#workflow-results .quality-report summary');await cdp.evaluate("window.__qualityElement=document.querySelector('#workflow-results .quality-report');window.__composerElement=document.querySelector('#question-input');window.__composerElement.focus()");
    await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+id+'"]')})?.dataset.jobStatus==='running'`),'durable stage progress');
    assert(await cdp.evaluate("document.querySelector('#question-input')===window.__composerElement&&document.activeElement===window.__composerElement&&window.__composerElement.value==='Synthetic next work draft'"),'Polling replaced composer or stole typing focus');
    assert(await cdp.evaluate("document.querySelector('#workflow-results .quality-report')===window.__qualityElement&&window.__qualityElement.open"),'Polling replaced a completed result or collapsed its open quality report');
    await cdp.evaluate(`document.querySelector(${q('[data-job-id="'+id+'"]')}).scrollIntoView({block:'start',behavior:'instant'})`);await screenshot('workflow-progress-1280');
    await cdp.send('Emulation.setDeviceMetricsOverride',{width:375,height:812,deviceScaleFactor:1,mobile:true});await screenshot('workflow-progress-375');assert(await cdp.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+1"),'Mobile progress/quality report causes horizontal overflow');await cdp.send('Emulation.setDeviceMetricsOverride',{width:1280,height:1000,deviceScaleFactor:1,mobile:false});
    assert(await cdp.evaluate(`document.querySelector(${q('[data-job-id="'+id+'"]')}).textContent.includes('2分')`),'Long-running job age absent');
    meta.disconnectOnce=true;await until(()=>cdp.evaluate("!!document.querySelector('.workflow-reconnect')"),'transient reconnect visible');assert(meta.job.status==='running','Transient connection marked server job failed');await click('[data-action=workflow-reconnect]');await until(()=>cdp.evaluate("!document.querySelector('.workflow-reconnect')"),'connection restored');
    await route('overview');assert(await cdp.evaluate("!!document.querySelector('#workflow-activity [data-action=workflow-progress]')"),'Home lost active work indicator');
    await click('#workspace-switch');await select('#workspace-choice','demo');await click('#modal form button[type=submit]');await until(()=>cdp.evaluate("document.querySelector('#footer-workspace').textContent.includes('演示')&&!document.querySelector('#modal').open"),'demo workspace opened');assert(await cdp.evaluate("!document.querySelector('main').textContent.includes('Synthetic durable running job')&&!document.querySelector('.workflow-job')"),'Personal job leaked to demo workspace');
    await click('#workspace-switch');await select('#workspace-choice','personal');await click('#modal form button[type=submit]');await until(()=>cdp.evaluate("document.querySelector('#footer-workspace').textContent.includes('个人')&&!document.querySelector('#modal').open"),'personal workspace restored');await route('research');assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic next work draft'"),'Workspace return lost independent composer draft');
    await cdp.evaluate('window.__previousDocumentBeforeReload=true');
    await cdp.send('Page.reload');await until(()=>cdp.evaluate(`window.__previousDocumentBeforeReload!==true&&document.readyState==='complete'&&!!document.querySelector(${q('[data-job-id="'+id+'"]')})&&!!document.querySelector('#question-input')&&!document.querySelector('#question-input').disabled&&document.querySelector('main').getAttribute('aria-busy')!=='true'`),'durable job restored after reload');
    assert(await cdp.evaluate("document.querySelectorAll('main textarea').length===1&&[...document.querySelectorAll('[data-source-id]')].every(item=>!item.checked)"),'Restoration added composer or silently selected captured sources');
    meta.job.status='interrupted';meta.job.error='Synthetic server restart interrupted generation.';meta.job.retryable=true;meta.job.revision++;await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+id+'"]')})?.dataset.jobStatus==='interrupted'`),'interrupted job visible');
    await click('[data-action=workflow-job-retry][data-id="'+id+'"]');await until(()=>meta.job.status==='completed','interrupted job retry complete');const saved=meta.job.result.deliverable;
    await until(()=>cdp.evaluate(`!!document.querySelector(${q('.workflow-result [data-action=open-record][data-id="'+saved.id+'"]')})`),'completed restored result visible');assert(saved.generation_id===id&&saved.quality_report?.facts_verified===false&&meta.job.document_ids.includes(doc.id),'Retry failed to preserve job scope and quality report');
    await click('.workflow-result [data-action=open-record][data-id="'+saved.id+'"]');await until(()=>cdp.evaluate("location.hash==='#deliverables'&&!!document.querySelector('#deliverable-form .quality-report')"),'quality report reopened with saved draft');await click('#deliverable-form .quality-report summary');assert(await cdp.evaluate("document.querySelector('#deliverable-form .quality-report').textContent.includes('Synthetic unresolved evidence question.')&&document.querySelector('#deliverable-form .quality-report').textContent.includes('事实仍需核实')&&document.querySelector('#deliverable-form .quality-report').textContent.includes('Request specific supporting source evidence.')&&document.querySelector('#deliverable-form .quality-report').textContent.includes('表格结构')"),'Saved report lost canonical review fields or falsely claimed verified facts');
    await cdp.evaluate("document.querySelector('#deliverable-form .quality-report').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('quality-report-1280');
  });
  await check('meeting model and organization intents route to working staged screens', async () => {
    const before=(await api('state')).meetings;
    await route('overview');await select('#start-project',alpha.id);await click('[data-action=start-route][data-request="整理会议纪要"]');
    await until(()=>cdp.evaluate("location.hash==='#meetings'&&document.querySelector('#modal').open"),'fresh meeting intent dialog');
    assert(await cdp.evaluate('document.querySelector("#field-transcript").value===\'\' && document.querySelector("#field-project_id").value==='+q(alpha.id)),'Meeting intent overwrote existing transcript');
    await click('[data-close-dialog=modal]');assert(JSON.stringify((await api('state')).meetings)===JSON.stringify(before),'Meeting routing mutated existing records');
    await route('overview');await fill('#start-input','建立 DCF 估值模型');await click('#start-form button[type=submit]');await until(()=>cdp.evaluate("location.hash==='#finance'&&!!document.querySelector('#valuation-json')"),'model route');
    assert(await cdp.evaluate("document.querySelector('#valuation-method').value==='dcf'&&document.querySelector('#valuation-text').value.includes('DCF')"),'Model intent missing staged method/request');
    await route('overview');await fill('#start-input','整理项目材料和版本');await click('#start-form button[type=submit]');await until(()=>cdp.evaluate("location.hash==='#overview'&&!!document.querySelector('#project-detail')&&!document.querySelector('#start-input').disabled"),'organization route');
    assert(await cdp.evaluate('document.querySelector("#project-detail h2").textContent==='+q(alpha.name)),'Organization opened wrong project');
  });
  await check('saved model restores typed assumptions compares scenarios and saves recomputation', async () => {
    await route('deliverables');await click('[data-action=model-load][data-id="'+savedModel.id+'"]');await until(()=>cdp.evaluate("location.hash==='#finance'&&!!document.querySelector('.valuation-result')"),'typed model load');
    const loaded=await cdp.evaluate("JSON.parse(document.querySelector('#valuation-json').value)");assert(loaded.net_income===100&&loaded.pe_multiple===12,'Saved assumptions not restored');
    assert(await cdp.evaluate("!document.querySelector('.valuation-scenarios details').open&&!document.querySelector('.valuation-review details').open"),'Advanced finance editors are open by default');
    await click('[data-action=valuation-scenarios-quick]');await until(()=>cdp.evaluate("!!document.querySelector('.valuation-scenarios table tbody tr')"),'one-click scenario compare');
    assert(await cdp.evaluate("JSON.parse(document.querySelector('#valuation-scenarios-json').value)[0].overrides.pe_multiple===9.6&&!document.querySelector('.valuation-scenarios details').open"),'Quick scenario has floating-point noise or forces JSON editor open');
    const text=await cdp.evaluate("document.querySelector('#valuation-scenarios-json').closest('section').textContent");assert(text.includes('960')&&text.includes('1,440'),'Scenario formulas wrong: '+text);
    await cdp.evaluate("document.querySelector('.valuation-result').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('finance-1280');
    await click('.valuation-review details summary');await fill('#valuation-json',JSON.stringify({...assumptions,net_income:200},null,2));assert(await cdp.evaluate("!document.querySelector('.valuation-result')&&!document.querySelector('#valuation-scenarios-json')"),'Edited assumptions left stale model/scenario results');
    await click('[data-action=valuation-calculate]');await until(()=>cdp.evaluate("!!document.querySelector('.valuation-result')&&document.querySelector('.valuation-result').textContent.includes('2,400')"),'recomputed saved model');
    await click('[data-action=valuation-save]');await until(async()=>((await api('state')).deliverables.some(i=>i.method==='net_income'&&i.assumptions?.net_income===200&&i.result?.equity_value===2400)),'typed recomputed model save');
  });
  await check('expired CSRF refreshes once and retries valuation parsing without losing edited inputs', async () => {
    csrfScenario.enabled=true;csrfScenario.seedStale=true;csrfScenario.mode='recover';
    await route('settings');await click('[data-action=refresh-status]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=refresh-status]').disabled"),'synthetic stale session seeded');csrfScenario.seedStale=false;
    await route('finance');await select('#valuation-method','net_income');
    const text='Synthetic FY2026E RMB 百万元 net income 321 and P/E 11.';
    const edited={currency:'RMB',unit:'百万元',period:'FY2026E',net_income:321,pe_multiple:11,diluted_shares:50};csrfScenario.expected=edited;
    await fill('#valuation-text',text);await click('.valuation-review details summary');await fill('#valuation-json',JSON.stringify(edited,null,2));
    const bootstrapBefore=csrfScenario.bootstrapCalls;await click('[data-action=valuation-parse]');
    await until(()=>csrfScenario.parseRequests.length===2&&csrfScenario.successfulModelCalls===1,'csrf refresh and single successful retry');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled"),'valuation parse retry completed');
    const [first,second]=csrfScenario.parseRequests;
    assert(first.token==='synthetic-expired-token'&&second.token===csrf&&first.serialized===second.serialized,'Retry did not replace the stale token or preserve the exact serialized parse request');
    assert(csrfScenario.bootstrapCalls===bootstrapBefore+1&&csrfScenario.successfulModelCalls===1,'Expired-session recovery repeated bootstrap or charged more than one model call');
    const pending=csrfScenario.retryDom;assert(pending?.sameReview&&pending.sameMain&&pending.ready&&pending.text===text&&JSON.stringify(JSON.parse(pending.json))===JSON.stringify(edited),'Token refresh rebooted the page or discarded pending valuation inputs');
    assert(await cdp.evaluate('document.querySelector("#valuation-text").value==='+q(text)+'&&JSON.stringify(JSON.parse(document.querySelector("#valuation-json").value))==='+q(JSON.stringify(edited))),'Successful retry lost natural-language or edited JSON inputs');
    await screenshot('csrf-recovery-1280');
  });
  await check('ordinary forbidden responses do not refresh or retry model calls', async () => {
    csrfScenario.mode='forbidden';const before=csrfScenario.parseRequests.length,bootstrapBefore=csrfScenario.bootstrapCalls,chargesBefore=csrfScenario.successfulModelCalls;
    const previous=await cdp.evaluate("({text:document.querySelector('#valuation-text').value,json:document.querySelector('#valuation-json').value})");
    await click('[data-action=valuation-parse]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled&&document.querySelector('main').textContent.includes('Synthetic permissions denied')"),'ordinary 403 visible');
    assert(csrfScenario.parseRequests.length===before+1&&csrfScenario.bootstrapCalls===bootstrapBefore&&csrfScenario.successfulModelCalls===chargesBefore,'Non-CSRF 403 was retried or invoked a model');
    assert(await cdp.evaluate('document.querySelector("#valuation-text").value==='+q(previous.text)+'&&document.querySelector("#valuation-json").value==='+q(previous.json)),'Permission failure discarded valuation draft inputs');
    await screenshot('csrf-permission-error-1280');
    csrfScenario.enabled=false;
  });
  await check('research Enter sends once while Shift+Enter and IME preserve the draft', async () => {
    await route('research');await select('#research-intent','ask');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');
    const count=()=>requests.filter(item=>item.path==='/api/ask').length,before=count();
    await fill('#question-input','Synthetic keyboard first line');await enter('#question-input',{shift:true});await cdp.send('Input.insertText',{text:'Synthetic keyboard second line'});
    assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic keyboard first line\\nSynthetic keyboard second line'"),'Shift+Enter failed to insert a newline');assert(count()===before,'Shift+Enter sent a request');
    await cdp.evaluate("(() => {const e=document.querySelector('#question-input');e.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true,data:'研究'}));e.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',isComposing:true,keyCode:229}));e.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'研究'}));e.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',keyCode:229}));e.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter',code:'Enter',repeat:true}));})()");
    await delay(120);assert(count()===before,'IME confirmation, key 229, or a held Enter sent a request');
    await fill('#question-input','Synthetic keyboard single ask');await enter('#question-input');await until(()=>count()===before+1,'keyboard ask accepted');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'keyboard ask complete');await delay(120);
    const sent=requests.filter(item=>item.path==='/api/ask').at(-1);assert(count()===before+1&&sent.body.question==='Synthetic keyboard single ask'&&sent.body.document_ids.includes(doc.id),'Enter duplicated the request or changed source scope');
  });
  await check('Enter uses the selected action or saved-draft purpose and home stages only once', async () => {
    const actionBefore=requests.filter(item=>item.path==='/api/agent').length;
    await select('#research-intent','actions');await fill('#question-input','Synthetic keyboard single action');await enter('#question-input');await until(()=>requests.filter(item=>item.path==='/api/agent').length===actionBefore+1,'keyboard action accepted');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'keyboard action complete');
    assert(requests.filter(item=>item.path==='/api/agent').at(-1).body.message==='Synthetic keyboard single action','Enter used the wrong action draft');
    await select('#research-intent','workflow');await select('#workflow-purpose','email');const jobsBefore=requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length;
    await fill('#question-input','Synthetic keyboard single saved draft');await enter('#question-input');await until(()=>requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length===jobsBefore+1,'keyboard generation accepted');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'keyboard generation registration complete');await delay(120);
    assert(requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').at(-1).body.workflow_key==='email','Enter used the wrong workflow purpose');
    await route('overview');await select('#start-project',alpha.id);await select('#start-purpose','');await fill('#start-input','帮我起草一封邮件，Synthetic keyboard home staging');const plansBefore=requests.filter(item=>item.path==='/api/workflows/plan').length;
    await enter('#start-input');await until(()=>cdp.evaluate("location.hash==='#research'&&document.querySelector('#research-intent').value==='workflow'"),'home keyboard staging');await delay(120);
    assert(requests.filter(item=>item.path==='/api/workflows/plan').length===plansBefore+1&&requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length===jobsBefore+1,'Home Enter duplicated planning or generated before scope confirmation');
  });
  await check('stopping ask and actions aborts promptly preserves drafts and ignores late responses', async () => {
    await route('research');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');
    for(const {intent,path,kind} of [{intent:'ask',path:'/api/ask',kind:'ask'},{intent:'actions',path:'/api/agent',kind:'agent'}]){
      await select('#research-intent',intent);const message='Synthetic stoppable '+kind+' late reply';await fill('#question-input',message);
      const before=requests.filter(item=>item.path===path).length,answersBefore=await cdp.evaluate("document.querySelectorAll('.answer-card').length");
      await holdBrowserResponse(path);
      try {
        await enter('#question-input');await until(()=>cdp.evaluate("window.__stopReplies.length===1"),'held '+kind+' response');
        const sent=requests.filter(item=>item.path===path).at(-1),selector='main [data-action=ai-stop][data-kind="'+kind+'"]';
        assert(sent.operationId&&await cdp.evaluate('!!document.querySelector('+q(selector)+')&&!document.querySelector('+q(selector)+').disabled'),'Stop control or operation ID missing immediately for '+kind);
        await click(selector);await until(()=>cdp.evaluate('!document.querySelector("#question-input").disabled&&document.querySelector("#question-input").value==='+q(message)),'stopped '+kind+' unlocks draft');
        await until(()=>requests.some(item=>item.path==='/api/operations/'+sent.operationId+'/cancel'),'server cancellation for '+kind);
        assert(await cdp.evaluate("window.__stopSignals.length===1&&window.__stopSignals[0]?.aborted"),'Stop did not abort '+kind+' transport');
        await until(()=>cdp.evaluate('!document.querySelector('+q('[data-action=ai-stop][data-id="'+sent.operationId+'"]')+')'),'confirmed '+kind+' stop');
        const stoppedAction=await cdp.evaluate("document.querySelector('.agent-answer')?.textContent||''");
        await releaseBrowserResponses();await delay(150);
        assert(await cdp.evaluate('document.querySelector("#question-input").value==='+q(message)+'&&!document.querySelector("#question-input").disabled'),'Late '+kind+' response cleared or relocked draft');
        if(intent==='ask')assert(await cdp.evaluate("document.querySelectorAll('.answer-card').length")===answersBefore,'Cancelled late ask was added to answer history');
        else assert(await cdp.evaluate("document.querySelector('.agent-answer')?.textContent||''")===stoppedAction&&!stoppedAction.includes('Bold evidence'),'Cancelled late action answer was applied');
        assert(!await cdp.evaluate('!!document.querySelector('+q(selector)+')'),'Completed stop left active '+kind+' controls');
        if(intent==='ask')await screenshot('ask-stopped-1280');
        await enter('#question-input');await until(()=>requests.filter(item=>item.path===path).length===before+2,'explicit '+kind+' retry');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'retried '+kind+' response');
        const retried=requests.filter(item=>item.path===path).at(-1);assert(retried.operationId!==sent.operationId,'Retry reused the cancelled '+kind+' operation');
        if(intent==='actions')assert(!('history' in retried.body)&&mockConversations.get(retried.body.conversation_id)?.turns.filter(turn=>turn.status==='completed'&&turn.request_id===sent.operationId).length===0,'Cancelled action entered future assistant history');
      } finally { await releaseBrowserResponses(); }
    }
  });
  await check('home Shift+Enter and stop keep the staged request without late navigation', async () => {
    await route('overview');await select('#start-project',alpha.id);await select('#start-purpose','');await fill('#start-input','帮我起草一封邮件');const before=requests.filter(item=>item.path==='/api/workflows/plan').length;
    await enter('#start-input',{shift:true});await cdp.send('Input.insertText',{text:'Synthetic stoppable preparation'});const message='帮我起草一封邮件\nSynthetic stoppable preparation';
    assert(await cdp.evaluate('document.querySelector("#start-input").value==='+q(message)),'Home Shift+Enter failed to retain multiline work requirement');assert(requests.filter(item=>item.path==='/api/workflows/plan').length===before,'Home Shift+Enter submitted planning');
    await holdBrowserResponse('/api/workflows/plan');
    try {
      await enter('#start-input');await until(()=>cdp.evaluate("window.__stopReplies.length===1&&!!document.querySelector('main [data-action=ai-stop][data-kind=start]')"),'home planning stop visible');await click('main [data-action=ai-stop][data-kind=start]');
      await until(()=>cdp.evaluate("!document.querySelector('#start-input').disabled"),'home planning stopped');await releaseBrowserResponses();await delay(150);
      assert(await cdp.evaluate('location.hash==="#overview"&&document.querySelector("#start-input").value==='+q(message)+'&&document.querySelector("#start-project").value==='+q(alpha.id)+'&&document.querySelector("#start-purpose").value===""'),'Stopped planning lost scope/request or navigated on its late response');
      await enter('#start-input');await until(()=>cdp.evaluate("location.hash==='#research'&&!!document.querySelector('#question-input')"),'home planning explicit retry');assert(requests.filter(item=>item.path==='/api/workflows/plan').length===before+2,'Home stop triggered an implicit or duplicate retry');
    } finally { await releaseBrowserResponses(); }
  });
  await check('unconfirmed stop remains visible and retry targets the original operation', async () => {
    await route('research');await select('#research-intent','ask');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');const message='Synthetic stoppable cancellation connection failure';await fill('#question-input',message);const answersBefore=await cdp.evaluate("document.querySelectorAll('.answer-card').length");await holdBrowserResponse('/api/ask');
    try {
      await enter('#question-input');await until(()=>cdp.evaluate("window.__stopReplies.length===1"),'retry-stop held response');const sent=requests.filter(item=>item.path==='/api/ask').at(-1),selector='#ai-run-controls [data-action=ai-stop][data-id="'+sent.operationId+'"]';operationCancelFailures.set(sent.operationId,1);
      await click('main [data-action=ai-stop][data-kind=ask]');await until(()=>cdp.evaluate('document.querySelector('+q(selector)+')?.textContent.includes("重试停止")&&!document.querySelector('+q(selector)+').disabled'),'failed cancellation retry control');
      assert(await cdp.evaluate('document.querySelector("#question-input").value==='+q(message)+'&&!document.querySelector("#question-input").disabled&&document.querySelector("#ai-run-controls").textContent.includes("停止未确认")'),'Unconfirmed cancellation hid the control or lost the draft');
      await click(selector);await until(()=>cdp.evaluate('!document.querySelector('+q(selector)+')'),'retried stop confirmed');const cancellations=requests.filter(item=>item.path==='/api/operations/'+sent.operationId+'/cancel');assert(cancellations.length===2&&cancellations.every(item=>Object.keys(item.body).length===0),'Retry changed the stopped operation or duplicated cancellation');
      await releaseBrowserResponses();await delay(150);assert(await cdp.evaluate("document.querySelectorAll('.answer-card').length")===answersBefore&&await cdp.evaluate('document.querySelector("#question-input").value==='+q(message)),'Late response after cancellation retry was applied');
    } finally { await releaseBrowserResponses(); }
  });
  await check('valuation and meeting stop preserve inputs and prevent late automatic saves', async () => {
    auxiliaryModelMocks.set('/api/model/parse-assumptions',{assumptions:{currency:'RMB',unit:'百万元',period:'FY2026E',net_income:777,pe_multiple:11},missing:[],unmapped_fields:[]});
    try {
      await route('finance');await select('#valuation-method','net_income');await fill('#valuation-text','Synthetic stoppable model assumption description');const before=await cdp.evaluate("({text:document.querySelector('#valuation-text').value,json:document.querySelector('#valuation-json').value})");await holdBrowserResponse('/api/model/parse-assumptions');
      await click('[data-action=valuation-parse]');await until(()=>cdp.evaluate("window.__stopReplies.length===1&&!!document.querySelector('main [data-action=ai-stop][data-kind=valuation]')"),'valuation stop visible');await click('main [data-action=ai-stop][data-kind=valuation]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled"),'valuation stopped');await releaseBrowserResponses();await delay(150);
      assert(await cdp.evaluate('document.querySelector("#valuation-text").value==='+q(before.text)+'&&document.querySelector("#valuation-json").value==='+q(before.json)),'Late valuation response replaced the saved input or JSON');
      await click('[data-action=valuation-parse]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled&&JSON.parse(document.querySelector('#valuation-json').value).net_income===777"),'valuation explicit retry');
    } finally { await releaseBrowserResponses();auxiliaryModelMocks.delete('/api/model/parse-assumptions'); }
    const meeting=(await api('state')).meetings.find(item=>item.title==='Synthetic Alpha meeting minutes');let meetingCalls=0;
    auxiliaryModelMocks.set('/api/meeting-draft',async body=>{
      assert(body.save_meeting_id===meeting.id,'Meeting generation did not request atomic save for its own meeting');
      const result={summary:'Synthetic retried meeting summary',experts:[],matrix:{},contents:[],actions:[],meeting_id:meeting.id,saved:false};
      if(++meetingCalls===1)return result;
      await json(origin+'/api/meetings/'+meeting.id,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,Origin:origin},body:JSON.stringify({summary:result.summary,transcript:body.transcript})});return {...result,saved:true};
    });
    try {
      await route('meetings');await select('#meeting-project',alpha.id);await click('[data-action=select-meeting][data-id="'+meeting.id+'"]');const transcript=await cdp.evaluate("document.querySelector('#meeting-transcript-input').value");await holdBrowserResponse('/api/meeting-draft');
      await click('[data-action=meeting-ai-draft]');await until(()=>cdp.evaluate("window.__stopReplies.length===1&&!!document.querySelector('main [data-action=ai-stop][data-kind=meeting]')"),'meeting stop visible');await click('main [data-action=ai-stop][data-kind=meeting]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'meeting stopped');await releaseBrowserResponses();await delay(150);
      assert((await api('meetings/'+meeting.id)).summary===meeting.summary&&await cdp.evaluate('document.querySelector("#meeting-transcript-input").value==='+q(transcript)),'Cancelled meeting response saved a late summary or lost transcript');
      await click('[data-action=meeting-ai-draft]');await until(async()=>(await api('meetings/'+meeting.id)).summary==='Synthetic retried meeting summary','meeting explicit retry saves new summary');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'meeting retry finished');
    } finally { await releaseBrowserResponses();auxiliaryModelMocks.delete('/api/meeting-draft'); }
  });
  await check('queued and running workflow cancellation is terminal and explicit resubmit is fresh', async () => {
    await route('research');await select('#research-intent','workflow');await select('#workflow-purpose','email');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');
    await until(()=>[...workflowJobs.values()].every(meta=>!['queued','running'].includes(meta.job.status)),'prior keyboard generation finished');
    const posts=()=>requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST'),before=posts().length,savedBefore=(await api('state')).deliverables.length;
    const message='Synthetic stoppable workflow queued cancellation';await fill('#question-input',message);await enter('#question-input');const queued=await until(()=>[...workflowJobs.values()].find(item=>item.job.message===message),'queued stoppable workflow accepted');
    await until(()=>cdp.evaluate(`!!document.querySelector(${q('[data-action=workflow-job-stop][data-id="'+queued.job.id+'"]')})&&!document.querySelector('#question-input').disabled`),'queued workflow stop visible');assert(queued.job.status==='queued','Workflow skipped the queued cancellation stage');
    await click('[data-action=workflow-job-stop][data-id="'+queued.job.id+'"]');await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+queued.job.id+'"]')})?.dataset.jobStatus==='cancelled'`),'queued workflow cancelled');
    const first=posts()[before];assert(queued.job.retryable===false&&await cdp.evaluate('document.querySelector("#question-input").value==='+q(message)+'&&document.querySelector('+q('[data-source-id="'+doc.id+'"]')+').checked'),'Queued cancellation lost draft or selected scope');
    assert(!await cdp.evaluate(`!!document.querySelector(${q('[data-action=workflow-job-retry][data-id="'+queued.job.id+'"]')})`),'Cancelled workflow still offers the failed-job retry');
    await enter('#question-input');await until(()=>posts().length===before+2,'cancelled workflow explicit resubmit');const second=posts()[before+1];assert(second.body.request_id!==first.body.request_id,'Explicit resubmit reused cancelled request ID');
    const running=await until(()=>[...workflowJobs.values()].find(item=>item.job.message===message&&item.job.id!==queued.job.id),'resubmitted workflow snapshot');await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+running.job.id+'"]')})?.dataset.jobStatus==='running'`),'resubmitted workflow running');
    await fill('#question-input','Synthetic next draft kept during stop');await click('[data-action=workflow-job-stop][data-id="'+running.job.id+'"]');await until(()=>cdp.evaluate(`document.querySelector(${q('[data-job-id="'+running.job.id+'"]')})?.dataset.jobStatus==='cancelled'`),'running workflow cancelled');
    await delay(1800);assert(posts().length===before+2&&(await api('state')).deliverables.length===savedBefore&&queued.job.status==='cancelled'&&running.job.status==='cancelled','Cancelled job auto-retried or saved a late generated draft');
    assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic next draft kept during stop'&&!document.querySelector('#question-input').disabled"),'Stopping running job replaced the next composer draft');await screenshot('workflow-cancelled-1280');
  });
  await check('stopping pending workflow registration cancels by request ID and ignores late acknowledgement', async () => {
    const message='Synthetic stoppable workflow pending acknowledgement';await fill('#question-input',message);const before=requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length;
    await holdBrowserResponse('/api/workflows/jobs');
    try {
      await enter('#question-input');await until(()=>cdp.evaluate("window.__stopReplies.length===1&&!!document.querySelector('main [data-action=ai-stop][data-kind=workflow-submit]')"),'pending workflow registration stop');
      const sent=requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').at(-1),meta=[...workflowJobs.values()].find(item=>item.job.message===message);
      await click('main [data-action=ai-stop][data-kind=workflow-submit]');await until(()=>requests.some(item=>item.path==='/api/workflows/jobs/cancel'&&item.body.request_id===sent.body.request_id),'pending workflow cancellation by request ID');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'pending workflow stopped');
      await releaseBrowserResponses();await delay(1800);assert(meta.job.status==='cancelled'&&!meta.job.result&&requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length===before+1,'Late registration restarted or completed a cancelled workflow');
      assert(await cdp.evaluate('document.querySelector("#question-input").value==='+q(message)+'&&!document.querySelector("#question-input").disabled'),'Pending registration stop lost its request');
      await enter('#question-input');await until(()=>requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').length===before+2,'pending workflow explicit retry');const retry=requests.filter(item=>item.path==='/api/workflows/jobs'&&item.method==='POST').at(-1);assert(retry.body.request_id!==sent.body.request_id,'Pending cancellation poisoned subsequent request ID');
      const retried=await until(()=>[...workflowJobs.values()].find(item=>item.job.message===message&&item.job.id!==meta.job.id),'pending workflow retry snapshot');await until(()=>cdp.evaluate(`!!document.querySelector(${q('[data-action=workflow-job-stop][data-id="'+retried.job.id+'"]')})`),'retried pending workflow stop');await click('[data-action=workflow-job-stop][data-id="'+retried.job.id+'"]');await until(()=>retried.job.status==='cancelled','retry cleanup cancellation');
    } finally { await releaseBrowserResponses(); }
  });
  await check('Enter in an editable deliverable remains a newline instead of sending AI work', async () => {
    await route('deliverables');const previous=await cdp.evaluate("document.querySelector('#deliverable-body').value"),before=requests.length;
    await fill('#deliverable-body','Synthetic editable paragraph');await enter('#deliverable-body');await cdp.send('Input.insertText',{text:'Synthetic next paragraph'});assert(await cdp.evaluate("document.querySelector('#deliverable-body').value==='Synthetic editable paragraph\\nSynthetic next paragraph'"),'Document editor Enter did not insert newline');assert(requests.length===before,'Document editor Enter sent a model request');
    await fill('#deliverable-body',previous);await click('#deliverable-form button[type=submit]');await until(()=>cdp.evaluate("document.querySelector('#deliverable-save-state').textContent.includes('已保存')"),'restored synthetic editor body');
  });
  await check('no-hit model analysis shows actual identity selected excerpts and scoped citation without saving records', async () => {
    await route('research');await select('#research-intent','ask');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');await select('#ask-mode','deepseek:deepseek-v4.1-flash');
    const before=await api('state'),requestsBefore=requests.filter(item=>item.path==='/api/ask').length;await fill('#question-input',nohitQuestion);await enter('#question-input');
    await until(()=>requests.filter(item=>item.path==='/api/ask').length===requestsBefore+1,'synthetic no-hit model request');await until(()=>cdp.evaluate('!document.querySelector("#question-input").disabled&&document.querySelector(".answer-card .question-history")?.textContent==='+q(nohitQuestion)),'synthetic selected-excerpt answer');
    const sent=requests.filter(item=>item.path==='/api/ask').at(-1);assert(sent.body.mode==='deepseek'&&sent.body.model_id==='deepseek-v4.1-flash'&&sent.body.project_id===alpha.id&&JSON.stringify(sent.body.document_ids)===JSON.stringify([doc.id]),'No-hit analysis changed the chosen engine/model or selected source scope');
    const shown=await cdp.evaluate("({heading:document.querySelector('.answer-card .answer-heading').textContent,warning:document.querySelector('.answer-card .banner')?.textContent||'',text:document.querySelector('.answer-card').textContent})");
    assert(shown.heading.includes('DeepSeek')&&!/本地证据|非大模型/.test(shown.heading)&&shown.warning.includes(nohitWarning)&&shown.warning.length<180,'Model identity or compact no-hit explanation is misleading: '+JSON.stringify(shown));
    assert(shown.text.includes('原文节选')&&shown.text.includes('[S1]')&&!shown.text.includes('未向外部模型发出请求'),'Synthetic model analysis was replaced by a local no-hit response');
    const after=await api('state');assert(after.notes.length===before.notes.length&&after.deliverables.length===before.deliverables.length,'Ask mode automatically saved a note or deliverable');
    await click('.answer-card .citation');
    try {await until(()=>cdp.evaluate('document.querySelector("#document-dialog").open&&document.querySelector("#document-title").textContent==='+q(doc.title)),'selected-excerpt citation source');assert(await cdp.evaluate('document.querySelector("#document-dialog").textContent.includes('+q(quote)+')&&!!document.querySelector(".document-chunk.highlight")'),'No-hit citation did not locate the selected original source');}
    finally {await cdp.evaluate("document.querySelector('#document-dialog').close()");}
    await cdp.evaluate("document.querySelector('.answer-card').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('ask-selected-excerpt-1280');
  });
  await check('public AI progress shows stage elapsed estimated ETA and execution events without replacing drafts',async()=>{
    await route('research');await select('#research-project',alpha.id);await select('#research-intent','ask');await select('#ask-mode','deepseek:deepseek-v4.1-flash');await click('[data-source-id="'+doc.id+'"]');
    const message='Synthetic progress and ETA question';await fill('#question-input',message);await holdBrowserResponse('/api/ask');
    try{await enter('#question-input');await until(()=>cdp.evaluate("window.__stopReplies.length===1"),'held progress response');await cdp.evaluate("window.__progressComposer=document.querySelector('#question-input')");
      await until(()=>cdp.evaluate("document.querySelector('[data-ai-progress=ask]').textContent.includes('预计还需')&&document.querySelector('[data-ai-progress=ask]').textContent.includes('调用所选模型')"),'server stage and ETA');
      await click('[data-ai-progress=ask] .execution-record summary');const observed=await cdp.evaluate("({text:document.querySelector('[data-ai-progress=ask]').textContent,unknown:document.querySelector('[data-ai-progress=ask] [role=progressbar]').getAttribute('aria-valuenow'),same:document.querySelector('#question-input')===window.__progressComposer,value:document.querySelector('#question-input').value})");assert(observed.text.includes('已用')&&observed.text.includes('时间为估计')&&observed.text.includes('核对项目与资料范围')&&observed.unknown===null&&observed.same&&observed.value===message,'Progress omitted public records, fabricated percentage, or replaced composer: '+JSON.stringify(observed));
      await cdp.evaluate("document.querySelector('[data-ai-progress=ask]').scrollIntoView({block:'center',behavior:'instant'})");await screenshot('ai-progress-1280');
      await route('overview');await fill('#start-input','Synthetic unsent home draft during background progress');await delay(1700);assert(await cdp.evaluate("document.querySelector('#start-input').value==='Synthetic unsent home draft during background progress'&&document.querySelector('#ai-run-controls').textContent.includes('预计还需')"),'Progress navigation lost unsent home draft');
      await click('#ai-run-controls [data-action=ai-stop][data-kind=ask]');await until(()=>cdp.evaluate("!document.querySelector('#ai-run-controls [data-action=ai-stop][data-kind=ask]')"),'progress stop confirmed');
    }finally{await releaseBrowserResponses();}
  });
  let contextualConversationId;
  await check('ask followups use a stable scoped conversation reset preserves draft and source edits isolate context',async()=>{
    await route('research');await select('#research-project',alpha.id);await select('#research-intent','ask');await click('[data-source-id="'+doc.id+'"]');
    const send=async message=>{const before=requests.filter(r=>r.path==='/api/ask').length;await fill('#question-input',message);await enter('#question-input');await until(()=>requests.filter(r=>r.path==='/api/ask').length===before+1,'contextual ask sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'contextual ask returned');return requests.filter(r=>r.path==='/api/ask').at(-1);};
    const first=await send('Synthetic contextual opening question'),second=await send('Synthetic followup: expand the previous answer');contextualConversationId=second.body.conversation_id;assert(first.body.conversation_id===second.body.conversation_id&&mockConversations.get(contextualConversationId).turns.length===2,'Followup lost conversation continuity');
    assert(await cdp.evaluate("document.querySelector('[data-conversation-kind=ask]').textContent.includes('已有 2 轮')"),'Current contextual scope or turn count missing');
    await click('[data-action=conversation-history][data-kind=ask]');await until(()=>cdp.evaluate("document.querySelector('#modal').open&&document.querySelector('.conversation-transcript').textContent.includes('Synthetic contextual opening question')&&document.querySelector('.conversation-transcript').textContent.includes('Synthetic followup')"),'visible conversation turns');await screenshot('conversation-history-1280');await click('[data-close-dialog=modal]');
    await fill('#question-input','Synthetic unsent draft retained by new chat');await click('[data-action=conversation-reset][data-kind=ask]');assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic unsent draft retained by new chat'&&document.querySelector("+q('[data-source-id="'+doc.id+'"]')+").checked"),'New conversation discarded draft or selection');
    const fresh=await send('Synthetic fresh conversation');assert(fresh.body.conversation_id!==contextualConversationId,'New chat reused old conversation');
    await click('[data-source-id="'+memo1.id+'"]');const sourcesChanged=await send('Synthetic changed source scope');assert(sourcesChanged.body.conversation_id!==fresh.body.conversation_id&&sourcesChanged.body.document_ids.length===2,'Source change reused prior context');
  });
  await check('historical conversations reopen explicitly after refresh and preserve the unsent question',async()=>{
    await cdp.evaluate('window.__contextReloadMarker=true');await cdp.send('Page.reload');await until(()=>cdp.evaluate("window.__contextReloadMarker===undefined&&!!document.querySelector('#research-project')&&!document.querySelector('#question-input').disabled"),'reloaded research');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');await fill('#question-input','Synthetic unsent restored-context question');
    const selector='[data-conversation-picker=ask]';await until(()=>cdp.evaluate('[...document.querySelector('+q(selector)+').options].some(option=>option.value==='+q(contextualConversationId)+')'),'persisted conversation option');
    assert(await cdp.evaluate("document.querySelector('[data-conversation-kind=ask]').textContent.includes('新对话')"),'Refresh silently attached old conversation');await select(selector,contextualConversationId);await until(()=>cdp.evaluate("document.querySelector('[data-conversation-kind=ask]').textContent.includes('已有 2 轮')"),'explicit resumed conversation');assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic unsent restored-context question'"),'Conversation restore overwrote pending question');
    await enter('#question-input');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&document.querySelector('[data-conversation-kind=ask]').textContent.includes('已有 3 轮')"),'restored contextual answer');assert(requests.filter(r=>r.path==='/api/ask').at(-1).body.conversation_id===contextualConversationId,'Restored request did not continue history');
    await select('#research-project',beta.id);await until(()=>cdp.evaluate("[...document.querySelector('[data-conversation-picker=ask]').options].length===1"),'isolated Beta history');assert(await cdp.evaluate("document.querySelector('[data-conversation-kind=ask]').textContent.includes('新对话')"),'Alpha conversation crossed project boundary');
  });
  await check('refresh restores active execution progress and finishes without resending model work or overwriting drafts',async()=>{
    const id=randomUUID(),beforeModels=requests.filter(r=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(r.path)).length;mockOperations.set(id,{start:Date.now()-12000,status:'running',body:{conversation_id:contextualConversationId}});restoreOperationIds.add(id);
    try{await route('overview');await cdp.send('Page.reload');await until(()=>cdp.evaluate('!!document.querySelector('+q('#ai-run-controls [data-action=ai-stop][data-id="'+id+'"]')+')'),'restored sync operation control');await fill('#start-input','Synthetic unsent home draft during restored execution');await until(()=>cdp.evaluate("document.querySelector('#ai-run-controls').textContent.includes('预计还需')"),'restored live ETA');mockOperations.get(id).status='completed';await until(()=>cdp.evaluate('!document.querySelector('+q('#ai-run-controls [data-action=ai-stop][data-id="'+id+'"]')+')'),'restored operation terminal');assert(await cdp.evaluate("document.querySelector('#start-input').value==='Synthetic unsent home draft during restored execution'"),'Recovered completion overwrote unsent draft');assert(requests.filter(r=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(r.path)).length===beforeModels,'Restore resent model request');}
    finally{restoreOperationIds.delete(id);mockOperations.get(id).status='completed';}
  });
  await check('workflow revision saves manual edits first and creates a separate version from the current artifact',async()=>{
    const original=(await api('state')).deliverables.find(item=>item.workflow_key==='legal');assert(original,'Missing original synthetic draft');await route('deliverables');await click('[data-action=select-deliverable][data-id="'+original.id+'"]');const edited='# Synthetic manually edited current draft\n\nUser edits must remain the revision base.';await fill('#deliverable-body',edited);await click('[data-action=workflow-revise][data-id="'+original.id+'"]');await until(()=>cdp.evaluate("location.hash==='#research'&&document.querySelector('[data-conversation-kind=workflow]').textContent.includes('修订：')"),'revision composer');assert((await api('state')).deliverables.find(item=>item.id===original.id).body===edited,'Continue revision ignored unsaved current edits');
    const count=(await api('state')).deliverables.length,before=workflowPosts().length;await fill('#question-input','Synthetic revise current saved version with a clearer risk table');await enter('#question-input');await until(()=>workflowPosts().length===before+1,'revision registration');const request=workflowPosts().at(-1);assert(request.body.revision_of===original.id&&request.body.project_id===original.project_id&&JSON.stringify(request.body.document_ids)===JSON.stringify(original.source_ids),'Revision lost project or evidence scope');
    const meta=await until(()=>[...workflowJobs.values()].find(item=>item.job.message===request.body.message),'revision synthetic registration ready');await until(()=>meta.job.status==='completed','revision completed');await until(()=>cdp.evaluate('!!document.querySelector('+q('.workflow-result[data-deliverable-id="'+meta.job.result.deliverable.id+'"]')+')'),'revised version visible');const saved=await api('state');assert(saved.deliverables.length===count+1&&saved.deliverables.find(item=>item.id===original.id).body===edited&&meta.parent.body===edited&&meta.job.result.deliverable.id!==original.id,'Revision overwrote original or used stale base');
    await cdp.evaluate('document.querySelector('+q('.workflow-result[data-deliverable-id="'+meta.job.result.deliverable.id+'"]')+').scrollIntoView({block:"start",behavior:"instant"})');await screenshot('workflow-revision-1280');
  });
  await check('valuation continuation sends the edited prior assumptions with the same method-scoped conversation',async()=>{
    csrfScenario.enabled=true;csrfScenario.seedStale=false;await route('settings');await click('[data-action=refresh-status]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=refresh-status]').disabled"),'synthetic DSH available');csrfScenario.enabled=false;
    auxiliaryModelMocks.set('/api/model/parse-assumptions',{assumptions:{...assumptions,net_income:101},missing:[],unmapped_fields:[]});
    try{await route('finance');await select('#valuation-method','net_income');await select('#valuation-project',alpha.id);await fill('#valuation-text','Synthetic starting assumptions');await click('[data-action=valuation-parse]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled&&JSON.parse(document.querySelector('#valuation-json').value).net_income===101"),'initial model assumptions');const first=requests.filter(r=>r.path==='/api/model/parse-assumptions').at(-1);
      await click('.valuation-review details summary');const prior={...assumptions,net_income:202};await fill('#valuation-json',JSON.stringify(prior));await fill('#valuation-text','Synthetic followup: preserve current income and reduce the multiple');await enter('#valuation-text');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled"),'model followup');const second=requests.filter(r=>r.path==='/api/model/parse-assumptions').at(-1);assert(second!==first&&second.body.conversation_id===first.body.conversation_id&&second.body.prior_assumptions.net_income===202&&second.body.project_id===alpha.id,'Model followup omitted manually edited current assumptions or lost scope');
    }finally{auxiliaryModelMocks.delete('/api/model/parse-assumptions');}
  });
  await check('meeting followups carry revision instructions and retain the current meeting transcript',async()=>{
    const meeting=(await api('state')).meetings.find(item=>item.project_id===alpha.id);auxiliaryModelMocks.set('/api/meeting-draft',async body=>{await json(origin+'/api/meetings/'+body.save_meeting_id,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,Origin:origin},body:JSON.stringify({summary:'Synthetic revised meeting summary'})});return {saved:true,meeting_id:body.save_meeting_id,summary:'Synthetic revised meeting summary',actions:[]};});
    try{await route('meetings');await select('#meeting-project',alpha.id);await click('[data-action=select-meeting][data-id="'+meeting.id+'"]');const original=await cdp.evaluate("document.querySelector('#meeting-transcript-input').value");await fill('#meeting-revision-input','Synthetic first meeting requirement');await enter('#meeting-revision-input');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'first meeting contextual summary');const first=requests.filter(r=>r.path==='/api/meeting-draft').at(-1);await fill('#meeting-revision-input','Synthetic followup: add a table of unresolved questions');await enter('#meeting-revision-input');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'meeting followup');const second=requests.filter(r=>r.path==='/api/meeting-draft').at(-1);assert(second!==first&&second.body.conversation_id===first.body.conversation_id&&second.body.revision_instructions.includes('unresolved')&&second.body.transcript===original&&second.body.save_meeting_id===meeting.id,'Meeting followup lost original or current meeting context');
    }finally{auxiliaryModelMocks.delete('/api/meeting-draft');}
  });
  await check('project folder status displays saved paths and retries export without another model call',async()=>{
    const saved=(await api('state')).deliverables.find(item=>item.project_id===alpha.id);const failed=mockArchiveReceipt('deliverables',saved,alpha.id,{failed:true}),beforeModels=requests.filter(r=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(r.path)).length;await route('overview');await click('[data-action=project-detail][data-id="'+alpha.id+'"]');await click('[data-action=archive-refresh][data-id="'+alpha.id+'"]');await until(()=>cdp.evaluate("document.querySelector('.project-archives').textContent.includes('Synthetic exporter failed')"),'failed archive receipt');await click('.archive-failed summary');const oldIds=new Set((mockArchives.get(alpha.id)||[]).map(item=>item.archive_id));await click('[data-action=archive-retry][data-id="'+saved.id+'"]');await until(()=>{const receipt=(mockArchives.get(alpha.id)||[]).find(item=>!oldIds.has(item.archive_id)&&item.record_id===saved.id);return receipt&&cdp.evaluate('!!document.querySelector('+q('[data-action=archive-download][data-id="'+receipt.archive_id+'"]')+')');},'retried file archive');
    const modelCount=requests.filter(r=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(r.path)).length;assert(modelCount===beforeModels&&(await api('state')).deliverables.find(item=>item.id===saved.id).body===saved.body,'Export retry repeated generation or changed record');const receipt=(mockArchives.get(alpha.id)||[]).find(item=>!oldIds.has(item.archive_id)&&item.record_id===saved.id);await cdp.evaluate('document.querySelector('+q('[data-action=archive-download][data-id="'+receipt.archive_id+'"]')+').closest("details").open=true');await click('[data-action=archive-download][data-id="'+receipt.archive_id+'"]');await until(()=>requests.some(item=>item.path==='/api/artifacts/'+receipt.archive_id+'/files/0'),'archive download route');
    const folder=path.join(temp,'synthetic-bound-project');await click('[data-action=archive-bind][data-id="'+alpha.id+'"]');await fill('#field-path',folder);await click('#modal-submit');await until(()=>cdp.evaluate("!document.querySelector('#modal').open&&document.querySelector('.project-archives').textContent.includes('已绑定项目文件夹')"),'folder bound');assert(mockBindings.get(alpha.id)===folder,'Binding path missing');await cdp.evaluate("document.querySelector('.project-archives').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('project-archive-1280');
  });
  const groupedChoices=[['dsh:gpt-6-luna','dsh','gpt-6-luna'],['deepseek:deepseek-v4.1-flash','deepseek','deepseek-v4.1-flash'],['local-models:glm-5.2','local-models','glm-5.2'],['local-models:kimi-k2.7','local-models','kimi-k2.7'],['local-models:hy3','local-models','hy3'],['model:synthetic-custom','model','synthetic-custom']];
  async function assertGroupedPicker(selector,{local=false,rules=false,recheck=false}={}){const result=await cdp.evaluate(`(() => {const select=document.querySelector(${q(selector)});return {count:document.querySelectorAll('[data-model-picker]').length,groups:[...select.querySelectorAll('optgroup')].map(item=>item.label),values:[...select.options].map(item=>({value:item.value,disabled:item.disabled,text:item.textContent})),legacy:!!document.querySelector('#local-model,#dsh-model')};})()`);assert(result.count===1&&!result.legacy&&['GPT','DeepSeek','GLM','Kimi','Hunyuan'].every(group=>result.groups.includes(group)),selector+' missing a shared grouped picker: '+JSON.stringify(result));const unavailable=result.values.find(item=>item.value==='dsh:synthetic-unavailable');assert(unavailable?.disabled===!recheck&&unavailable.text.includes('missing from bridge'),'Unavailable choice was selectable or its reason missing');assert(result.values.some(item=>item.value==='local:')===local&&result.values.some(item=>item.value==='rules:')===rules,'NonAI tools mixed into unsupported work');assert(groupedChoices.every(([value])=>result.values.some(item=>item.value===value&&!item.disabled)),'A supported provider or configured custom model disappeared');}
  await check('every AI work surface has one grouped model picker with disabled unavailable choices',async()=>{
    await route('overview');await assertGroupedPicker('#start-model');await cdp.evaluate('window.scrollTo(0,0)');await screenshot('models-home-1280');
    await route('research');await select('#research-intent','ask');await assertGroupedPicker('#ask-mode',{local:true});await select('#research-intent','actions');await assertGroupedPicker('#agent-model');await select('#research-intent','workflow');await assertGroupedPicker('#ask-mode');
    await route('finance');await assertGroupedPicker('#valuation-model');await screenshot('models-valuation-1280');await route('meetings');await assertGroupedPicker('#meeting-model',{rules:true});await route('settings');await assertGroupedPicker('#model-check-model',{recheck:true});
  });
  await check('grouped research choices dispatch all providers and preserve explicit sources',async()=>{
    await route('research');await select('#research-intent','ask');await select('#research-project',alpha.id);await click('[data-source-id="'+doc.id+'"]');const notesBefore=(await api('state')).notes.length;
    for(const [value,mode,id] of groupedChoices){await select('#ask-mode',value);const before=requests.filter(item=>item.path==='/api/ask').length;await fill('#question-input','Synthetic grouped ask '+value);await enter('#question-input');await until(()=>requests.filter(item=>item.path==='/api/ask').length===before+1,'grouped ask dispatch');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'grouped ask result');const sent=requests.filter(item=>item.path==='/api/ask').at(-1);assert(sent.body.mode===mode&&sent.body.provider===mode&&sent.body.model_id===id&&JSON.stringify(sent.body.document_ids)===JSON.stringify([doc.id]),'Unified research picker sent the wrong provider/model/scope: '+JSON.stringify(sent.body));}
    assert((await api('state')).notes.length===notesBefore,'Changing research models saved an unsolicited note');await cdp.evaluate("document.querySelector('#ask-mode').scrollIntoView({block:'center',behavior:'instant'})");await screenshot('models-research-1280');
  });
  await check('grouped action choices dispatch independently of the research model without source content',async()=>{
    const askChoice=await cdp.evaluate("document.querySelector('#ask-mode').value");await select('#research-intent','actions');
    for(const [value,mode,id] of groupedChoices){await select('#agent-model',value);const before=requests.filter(item=>item.path==='/api/agent').length;await fill('#question-input','Synthetic grouped action '+value);await enter('#question-input');await until(()=>requests.filter(item=>item.path==='/api/agent').length===before+1,'grouped action dispatch');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'grouped action result');const sent=requests.filter(item=>item.path==='/api/agent').at(-1);assert(sent.body.mode===mode&&sent.body.provider===mode&&sent.body.model_id===id&&!('document_ids' in sent.body)&&!JSON.stringify(sent.body).includes(quote),'Action picker used fixed DeepSeek or leaked evidence: '+JSON.stringify(sent.body));}
    await select('#research-intent','ask');assert(await cdp.evaluate('document.querySelector("#ask-mode").value==='+q(askChoice)),'Action provider selection replaced the independent research preference');
  });
  await check('grouped valuation choices include all providers and preserve edited assumptions and followup context',async()=>{
    auxiliaryModelMocks.set('/api/model/parse-assumptions',{assumptions:{...assumptions,net_income:303},missing:[],unmapped_fields:[]});
    try{await route('finance');await select('#valuation-method','net_income');await select('#valuation-project',alpha.id);await click('.valuation-review details summary');const current=JSON.stringify({...assumptions,net_income:303});await fill('#valuation-json',current);let conversation;
      for(const [value,mode,id] of groupedChoices){const text='Synthetic grouped valuation '+value;await fill('#valuation-text',text);await select('#valuation-model',value);assert(await cdp.evaluate('document.querySelector("#valuation-text").value==='+q(text)+'&&JSON.parse(document.querySelector("#valuation-json").value).net_income===303'),'Model change lost edited valuation inputs');const before=requests.filter(item=>item.path==='/api/model/parse-assumptions').length;await click('[data-action=valuation-parse]');await until(()=>requests.filter(item=>item.path==='/api/model/parse-assumptions').length===before+1,'grouped valuation dispatch');await until(()=>cdp.evaluate("!document.querySelector('[data-action=valuation-parse]').disabled"),'grouped valuation result');const sent=requests.filter(item=>item.path==='/api/model/parse-assumptions').at(-1);assert(sent.body.mode===mode&&sent.body.provider===mode&&sent.body.model_id===id&&sent.body.prior_assumptions.net_income===303,'Valuation remained locked to GPT/DSH or ignored current assumptions');if(conversation)assert(sent.body.conversation_id===conversation,'Changing model silently dropped method-scoped followup context');conversation=sent.body.conversation_id;}
    }finally{auxiliaryModelMocks.delete('/api/model/parse-assumptions');}
  });
  await check('grouped meeting choices dispatch all providers while rules stay explicitly nonAI',async()=>{
    const meeting=(await api('state')).meetings.find(item=>item.project_id===alpha.id);auxiliaryModelMocks.set('/api/meeting-draft',async body=>{await json(origin+'/api/meetings/'+body.save_meeting_id,{method:'PATCH',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,Origin:origin},body:JSON.stringify({summary:'Synthetic grouped meeting summary'})});return {saved:true,meeting_id:body.save_meeting_id,summary:'Synthetic grouped meeting summary',actions:[]};});
    try{await route('meetings');await select('#meeting-project',alpha.id);await click('[data-action=select-meeting][data-id="'+meeting.id+'"]');const transcript=await cdp.evaluate("document.querySelector('#meeting-transcript-input').value");for(const [value,mode,id] of groupedChoices){await select('#meeting-model',value);await fill('#meeting-revision-input','Synthetic grouped meeting '+value);const before=requests.filter(item=>item.path==='/api/meeting-draft').length;await click('[data-action=meeting-ai-draft]');await until(()=>requests.filter(item=>item.path==='/api/meeting-draft').length===before+1,'grouped meeting dispatch');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'grouped meeting result');const sent=requests.filter(item=>item.path==='/api/meeting-draft').at(-1);assert(sent.body.mode===mode&&sent.body.provider===mode&&sent.body.model_id===id&&sent.body.transcript===transcript,'Meeting picker ignored provider/model or changed original transcript');}
      await select('#meeting-model','rules:');assert(await cdp.evaluate("document.querySelector('.meeting-body').textContent.includes('不调用 AI')&&!document.querySelector('[data-conversation-kind=meeting]')"),'Rules option implied an AI conversation');const before=requests.filter(item=>item.path==='/api/meeting-draft').length;await click('[data-action=meeting-ai-draft]');await until(()=>requests.filter(item=>item.path==='/api/meeting-draft').length===before+1,'deterministic meeting dispatch');await until(()=>cdp.evaluate("!document.querySelector('[data-action=meeting-ai-draft]').disabled"),'deterministic meeting complete');const sent=requests.filter(item=>item.path==='/api/meeting-draft').at(-1);assert(sent.body.provider==='rules'&&!sent.body.conversation_id&&!sent.operationId,'Rules request registered an AI run or model context');await select('#meeting-model','deepseek:deepseek-v4.1-flash');await cdp.evaluate("document.querySelector('#meeting-model').scrollIntoView({block:'center',behavior:'instant'})");await screenshot('models-meeting-1280');
    }finally{auxiliaryModelMocks.delete('/api/meeting-draft');}
  });
  await check('grouped workflow choices dispatch every provider with one picker and no local option',async()=>{
    await route('research');await select('#research-project',alpha.id);await select('#research-intent','workflow');await select('#workflow-purpose','email');await select('#workflow-quality','fast');
    for(const [value,mode,id] of groupedChoices){await select('#ask-mode',value);const before=workflowPosts().length;await fill('#question-input','Synthetic grouped email '+value);await enter('#question-input');await until(()=>workflowPosts().length===before+1,'grouped workflow dispatch');const sent=workflowPosts().at(-1);assert(sent.body.mode===mode&&sent.body.provider===mode&&sent.body.model_id===id&&sent.body.document_ids.length===0,'Workflow picker dispatched mismatching provider or stale sources');const meta=await until(()=>[...workflowJobs.values()].find(item=>item.job.message===sent.body.message),'grouped job registration');await until(()=>meta.job.status==='completed','grouped draft saved');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'grouped workflow composer ready');}
    await assertGroupedPicker('#ask-mode');
  });
  await check('home model choice carries into prepared work without premature generation',async()=>{
    const value='local-models:kimi-k2.7',modelsBefore=requests.filter(item=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(item.path)).length;await route('overview');await select('#start-model',value);await select('#start-project',alpha.id);await select('#start-purpose','email');await fill('#start-input','Synthetic staged email with Kimi');await enter('#start-input');await until(()=>cdp.evaluate("location.hash==='#research'&&document.querySelector('#workflow-purpose').value==='email'"),'home model research staging');assert(await cdp.evaluate('document.querySelector("#ask-mode").value==='+q(value)),'Home selection was lost when staging research');
    await route('overview');await select('#start-purpose','');await fill('#start-input','建立 DCF 估值模型');await enter('#start-input');await until(()=>cdp.evaluate("location.hash==='#finance'&&!!document.querySelector('#valuation-model')"),'home model finance staging');assert(await cdp.evaluate('document.querySelector("#valuation-model").value==='+q(value)),'Home selection was lost when staging valuation');
    await route('overview');await fill('#start-input','整理会议纪要');await enter('#start-input');await until(()=>cdp.evaluate("location.hash==='#meetings'&&document.querySelector('#modal').open"),'home model meeting staging');await click('[data-close-dialog=modal]');assert(await cdp.evaluate('document.querySelector("#meeting-model").value==='+q(value)),'Home selection was lost when staging meeting work');assert(requests.filter(item=>['/api/ask','/api/agent','/api/workflows/jobs','/api/model/parse-assumptions','/api/meeting-draft'].includes(item.path)).length===modelsBefore,'Home selection or staging silently sent material to a model');
  });
  await check('model catalog refresh is read-only and selected connection check updates shared availability without losing configuration drafts',async()=>{
    await route('settings');await select('#model-check-model','local-models:glm-5.2');await fill('#ai-model','Synthetic unsaved configuration');await fill('#ai-api-key','Synthetic unsaved noncredential');const before=requests.filter(item=>item.path==='/api/models/check').length;await click('[data-action=models-refresh]');await until(()=>cdp.evaluate("!document.querySelector('[data-action=models-refresh]').disabled"),'model catalog refreshed');assert(requests.filter(item=>item.path==='/api/models/check').length===before,'Refreshing catalog silently called a model');await click('[data-action=models-check]');await until(()=>requests.filter(item=>item.path==='/api/models/check').length===before+1,'selected synthetic check');await until(()=>cdp.evaluate("!document.querySelector('[data-action=models-check]').disabled&&document.querySelector('#model-catalog').textContent.includes('已验证')"),'checked model availability');const sent=requests.filter(item=>item.path==='/api/models/check').at(-1);assert(sent.body.mode==='local-models'&&sent.body.model_id==='glm-5.2'&&await cdp.evaluate("document.querySelector('#ai-model').value==='Synthetic unsaved configuration'&&document.querySelector('#ai-api-key').value==='Synthetic unsaved noncredential'"),'Connection check chose wrong provider or cleared unsaved settings');await cdp.evaluate("document.querySelector('#model-catalog').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('models-settings-1280');await route('finance');await select('#valuation-model','local-models:glm-5.2');assert(await cdp.evaluate("document.querySelector('.question-panel').textContent.includes('已验证')"),'Updated availability was not shared with valuation');
    await route('settings');await select('#model-check-model','local-models:kimi-k2.7');syntheticModelCheckFailures.add('local-models:kimi-k2.7');const failedBefore=requests.filter(item=>item.path==='/api/models/check').length;await click('[data-action=models-check]');await until(()=>requests.filter(item=>item.path==='/api/models/check').length===failedBefore+1,'synthetic unavailable result');await until(()=>cdp.evaluate("!document.querySelector('[data-action=models-check]').disabled&&document.querySelector('#model-catalog').textContent.includes('Synthetic transient connection unavailable')"),'unavailable selection retained');assert(await cdp.evaluate("document.querySelector('#model-check-model').value==='local-models:kimi-k2.7'&&document.querySelector('#model-catalog').textContent.includes('Synthetic transient connection unavailable')"),'Failed check hid the selected model or reason');await route('finance');assert(await cdp.evaluate("document.querySelector('#valuation-model option[value=\"local-models:kimi-k2.7\"]').disabled"),'Failed model remained enabled for real work');await route('settings');await select('#model-check-model','deepseek:deepseek-v4.1-flash');await select('#model-check-model','local-models:kimi-k2.7');assert(await cdp.evaluate("document.querySelector('#model-check-model').value==='local-models:kimi-k2.7'&&!document.querySelector('#model-check-model').selectedOptions[0].disabled"),'Settings could not select a different failed model to recheck');await click('[data-action=models-check]');await until(()=>requests.filter(item=>item.path==='/api/models/check').length===failedBefore+2,'unavailable selected model recheck');await until(()=>cdp.evaluate("!document.querySelector('[data-action=models-check]').disabled&&!document.querySelector('#model-check-model').selectedOptions[0].disabled"),'rechecked model restored');assert(requests.filter(item=>item.path==='/api/models/check').at(-1).body.model_id==='kimi-k2.7','Recheck silently fell back to another model');
    await select('#model-check-model','deepseek:deepseek-v4-pro');await fill('#ai-model','Synthetic configuration retained through stop');await holdBrowserResponse('/api/models/check');
    try{const stopBefore=requests.filter(item=>item.path==='/api/models/check').length;await click('[data-action=models-check]');await until(()=>cdp.evaluate("window.__stopReplies.length===1&&!!document.querySelector('#model-catalog [data-action=ai-stop]')"),'model check response held with stop control');const first=requests.filter(item=>item.path==='/api/models/check').at(-1);await click('#model-catalog [data-action=ai-stop]');await until(()=>cdp.evaluate("!document.querySelector('#model-catalog [data-action=ai-stop]')&&!document.querySelector('#ai-run-controls [data-kind=\"model-check\"]')"),'model check stop confirmed');await releaseBrowserResponses();await cdp.evaluate('new Promise(resolve=>setTimeout(resolve,100))');assert(await cdp.evaluate("document.querySelector('#ai-model').value==='Synthetic configuration retained through stop'&&document.querySelector('#model-catalog').textContent.includes('待验证')"),'Stopped check cleared config draft or applied late verification');await click('[data-action=models-check]');await until(()=>requests.filter(item=>item.path==='/api/models/check').length===stopBefore+2,'explicit fresh model check retry');await until(()=>cdp.evaluate("!document.querySelector('[data-action=models-check]').disabled&&document.querySelector('#model-catalog').textContent.includes('已验证')"),'fresh model check verified');assert(requests.filter(item=>item.path==='/api/models/check').at(-1).operationId!==first.operationId,'Explicit model check retry reused cancelled operation ID');}
    finally{await releaseBrowserResponses();}
  });
  await check('mobile 375px viewport has no document horizontal overflow', async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
    for (const page of ['research','overview','projects','meetings','finance','deliverables']) {
      await route(page);
      if(page==='overview'){await cdp.evaluate('window.scrollTo(0,0)');await screenshot('home-375');}
      if(page==='overview'||page==='projects'){await click('[data-action=project-detail][data-id="'+alpha.id+'"]');await select('#library-group','');await cdp.evaluate("document.querySelectorAll('.material-family').forEach(e=>e.open=true)");}
      const result=await cdp.evaluate(`(() => ({viewport:document.documentElement.clientWidth,width:document.documentElement.scrollWidth,body:document.body.scrollWidth,offenders:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width && (r.right>innerWidth+1 || r.left < -1) && getComputedStyle(e).position!=='fixed';}).slice(0,15).map(e=>({tag:e.tagName,id:e.id,class:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:e.scrollWidth}))}))()`);
      assert(result.width<=result.viewport+1 && result.body<=result.viewport+1, page+' overflow: '+JSON.stringify(result));
    }
  });
  await check('no browser exceptions or interception failures', async () => assert(!runtimeErrors.length && !interceptionErrors.length, JSON.stringify({runtimeErrors,interceptionErrors})));
  console.log('RESULT ' + JSON.stringify({ failures: failures.length, intercepted: requests.map(r=>r.path), originalDownloads: originalRequests.length, assertions: checks }));
  if(failures.length) process.exitCode=1;
}
(async () => {
  try { await main(); }
  catch(error) { console.error('HARNESS ERROR ' + error.stack); if(cdp)console.error('DOM ' + JSON.stringify(await details().catch(()=>null))); process.exitCode=1; }
  finally {
    if(cdp)cdp.socket.close();
    const errors=[];
    for(const [child,label] of [[chrome,'Chrome'],[server,'Python']])try{await stop(child,label);}catch(error){errors.push(error.message);}
    if(temp && !errors.length) {
      // Delete only the exact mkdtemp-owned directory, never a supplied app/profile path.
      const resolved=path.resolve(temp), parent=path.resolve(os.tmpdir());
      const stat=await fs.lstat(resolved);
      if(path.dirname(resolved)!==parent || !path.basename(resolved).startsWith('workos-research-cdp-') || stat.isSymbolicLink())throw Error('Refusing unsafe temporary cleanup '+resolved);
      await fs.rm(resolved,{recursive:true,force:true,maxRetries:10,retryDelay:150});
      console.log('CLEANUP stopped created Chrome/Python processes and removed verified temporary directory');
    }
    if(errors.length){console.error('CLEANUP ERROR '+errors.join('; '));process.exitCode=1;}
  }
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
