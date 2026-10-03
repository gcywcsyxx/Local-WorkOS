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
const root = path.resolve(__dirname, '..');
const chromeExecutable = process.env.WORKOS_TEST_CHROME || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const failures = [], requests = [], originalRequests = [], runtimeErrors = [], interceptionErrors = [];
const workflowCache = new Map(), workflowAttempts = new Map();
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
async function route(name) {
  await cdp.evaluate('location.hash=' + q(name));
  const allowedHashes = name === 'projects' ? ['#projects', '#overview'] : ['#' + name];
  const active=name==='projects'?'overview':name;
  await until(() => cdp.evaluate(q(allowedHashes) + `.includes(location.hash) && !!document.querySelector('#primary-nav [data-page='+`+q(active)+`+'].active') && !!document.querySelector('main h1') && document.querySelector('main').getAttribute('aria-busy')!=='true'`), 'route ' + name);
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
  chrome = start(chromeExecutable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=' + debugPort, '--user-data-dir=' + path.join(temp, 'chrome-profile'), 'about:blank']);
  const targets = await until(() => json('http://127.0.0.1:' + debugPort + '/json/list'), 'new Chrome CDP');
  cdp = await CDP.connect(targets.find(t => t.type === 'page').webSocketDebuggerUrl);
  cdp.on('Runtime.exceptionThrown', event => runtimeErrors.push(event.exceptionDetails.exception?.description || event.exceptionDetails.text));
  // Pause all renderer traffic: only this loopback app is allowed; AI endpoints never reach Python.
  cdp.on('Fetch.requestPaused', async event => {
    const url = new URL(event.request.url);
    if (url.origin !== origin) return cdp.send('Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' });
    if (/^\/api\/documents\/[^/]+\/original$/.test(url.pathname)) originalRequests.push(url.pathname);
    if(url.pathname==='/api/workflows/plan') requests.push({path:url.pathname,method:event.request.method,body:JSON.parse(event.request.postData||'{}')});
    if(url.pathname==='/api/workflows/run'){
      const body=JSON.parse(event.request.postData||'{}');requests.push({path:url.pathname,method:event.request.method,body});
      workflowAttempts.set(body.request_id,(workflowAttempts.get(body.request_id)||0)+1);
      if(body.message==='Synthetic unavailable provider'||(body.message==='Synthetic retryable provider'&&workflowAttempts.get(body.request_id)===1))return cdp.send('Fetch.fulfillRequest',{requestId:event.requestId,responseCode:503,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify({error:'Synthetic provider unavailable. Configure a supported model and retry.'})).toString('base64')});
      if(workflowCache.has(body.request_id))return cdp.send('Fetch.fulfillRequest',{requestId:event.requestId,responseCode:201,responseHeaders:[{name:'Content-Type',value:'application/json'}],body:Buffer.from(JSON.stringify(workflowCache.get(body.request_id))).toString('base64')});
      const docs=await Promise.all(body.document_ids.map(id=>api('documents/'+id)));
      const coverage=docs.map((item,index)=>({document_id:item.id,source_id:'S'+(index+1),title:item.title,excerpt_chars:item.content.length,total_chars:item.content.length,truncated:false}));
      const text='# Synthetic saved workflow\n\n**Editable draft**\n\n- Synthetic finding'+(docs.length?' [S1]':'')+'\n\n| Item | Status |\n| --- | --- |\n| Synthetic result | Draft |';
      const deliverable=await api('deliverables',{title:'Synthetic '+body.workflow_key+' draft',kind:'自定义',project_id:body.project_id,body:text,workflow_key:body.workflow_key,source_ids:body.document_ids,coverage});
      const result={answer:text,citations:docs.map((item,index)=>({document_id:item.id,title:item.title,quote:item.content.slice(0,100),ordinal:1})),coverage,deliverable,workflow_key:body.workflow_key,mode:'model',limitations:['Synthetic mocked model response; no real model called.']};
      workflowCache.set(body.request_id,result);
      return cdp.send('Fetch.fulfillRequest',{requestId:event.requestId,responseCode:201,responseHeaders:[{name:'Content-Type',value:'application/json; charset=utf-8'}],body:Buffer.from(JSON.stringify(result)).toString('base64')});
    }
    if (['/api/ask', '/api/agent'].includes(url.pathname)) {
      const body = JSON.parse(event.request.postData || '{}'); requests.push({ path: url.pathname, method: event.request.method, body });
      const result = url.pathname === '/api/ask' ? { answer, mode: 'model', elapsed_ms: 1, citations: [{ document_id: doc.id, id: source.chunks[0].id, ordinal: source.chunks[0].ordinal, title: doc.title, quote }] } : { answer, steps: [] };
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
    assert(requests.filter(r=>r.path==='/api/agent')[1].body.history.length===0,'Alpha history sent in Beta request');
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
    assert(result.key==='legal'&&result.project===alpha.id&&result.selected===0&&result.composers===1,'Bad staged workflow: '+JSON.stringify(result));
    assert(!requests.some(r=>r.path==='/api/workflows/run'),'Planning silently generated/sent sources');
    const plan=requests.find(r=>r.path==='/api/workflows/plan');assert(plan&&Object.keys(plan.body).length===1&&!JSON.stringify(plan.body).includes(quote),'Intent plan sent project materials');
    await click('#ask-form button[type=submit]');await cdp.evaluate('new Promise(resolve=>setTimeout(resolve,150))');assert(!requests.some(r=>r.path==='/api/workflows/run'),'Required-source recipe ran without selected material');
    await click('[data-source-id="'+doc.id+'"]');await click('#ask-form button[type=submit]');
    await until(()=>requests.some(r=>r.path==='/api/workflows/run'),'workflow explicit generation');await until(()=>cdp.evaluate("!!document.querySelector('.workflow-result')&&!document.querySelector('#question-input').disabled"),'saved workflow UI');
    const request=requests.find(r=>r.path==='/api/workflows/run');assert(request.body.workflow_key==='legal'&&JSON.stringify(request.body.document_ids)===JSON.stringify([doc.id])&&request.body.project_id===alpha.id,'Workflow source scope wrong');
    const saved=(await api('state')).deliverables.find(i=>i.title==='Synthetic legal draft');assert(saved?.workflow_key==='legal'&&saved.source_ids.includes(doc.id)&&saved.body.includes('Editable draft'),'Workflow draft was not persisted');
    assert(await cdp.evaluate("!!document.querySelector('.workflow-result .markdown-body h1') && !!document.querySelector('.workflow-result [data-action=workflow-citation]') && document.querySelector('.workflow-result').textContent.includes('已保存')"),'Workflow Markdown/citation/saved status missing');
    await cdp.evaluate("document.querySelector('.question-panel').scrollIntoView({block:'start',behavior:'instant'})");await screenshot('workflow-result-1280');
    await click('.workflow-result [data-action=workflow-citation]');await until(()=>cdp.evaluate("document.querySelector('#document-dialog').open && document.querySelector('#document-title').textContent==='Synthetic Alpha Evidence'"),'workflow citation original');await click('[data-close-dialog=document-dialog]');
  });
  await check('email draft can use direct instructions with no selected sources and be edited', async () => {
    await route('overview');await fill('#start-input','写一封英文邮件，请对方下周提供财务数据');await select('#start-purpose','');await click('#start-form button[type=submit]');
    await until(()=>cdp.evaluate("location.hash==='#research'&&document.querySelector('#workflow-purpose')?.value==='email'"),'email workflow staged');
    assert(await cdp.evaluate("[...document.querySelectorAll('[data-source-id]')].every(e=>!e.checked) && ![...document.querySelector('#ask-mode').options].some(o=>o.value==='local')"),'Email inherited old sources or misleading no-outbound workflow option');
    await click('#ask-form button[type=submit]');await until(()=>requests.filter(r=>r.path==='/api/workflows/run').length===2,'email generation');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&document.querySelectorAll('.workflow-result').length===2"),'email saved');
    const request=requests.filter(r=>r.path==='/api/workflows/run')[1];assert(request.body.workflow_key==='email'&&request.body.document_ids.length===0,'Email sent old selected documents');
    const saved=(await api('state')).deliverables.find(i=>i.title==='Synthetic email draft');assert(saved?.source_ids.length===0,'No-source email draft metadata wrong');
    await click('.workflow-result [data-action=open-record]');await until(()=>cdp.evaluate("location.hash==='#deliverables'&&!!document.querySelector('#deliverable-body')"),'saved draft opened');
    await fill('#deliverable-body','Synthetic edited email ready for human review.');await click('#deliverable-form button[type=submit]');await until(async()=>((await api('state')).deliverables.find(i=>i.id===saved.id)?.body==='Synthetic edited email ready for human review.'),'edited draft persisted');await until(()=>cdp.evaluate("!document.querySelector('#deliverable-form button[type=submit]').disabled"),'draft save UI complete');
  });
  await check('provider failures are visible and do not claim a saved draft', async () => {
    await route('research');const before=(await api('state')).deliverables.length;await fill('#question-input','Synthetic unavailable provider');await click('#ask-form button[type=submit]');
    await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&document.querySelector('#toast-region').textContent.includes('Synthetic provider unavailable')"),'provider failure visible');
    assert((await api('state')).deliverables.length===before,'Failure created an empty saved draft');
    assert(await cdp.evaluate("[...document.querySelectorAll('#ask-form .banner')].some(e=>e.textContent.includes('DeepSeek'))&&!document.querySelector('#ask-form').textContent.includes('尚未配置模型连接')"),'DeepSeek preset shows incorrect unconfigured generic provider status');
  });
  await check('workflow retries retain request IDs and completed repeats reuse saved drafts', async () => {
    const count=()=>requests.filter(r=>r.path==='/api/workflows/run').length;
    await fill('#question-input','Synthetic retryable provider');let before=count();await click('#ask-form button[type=submit]');
    await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&document.querySelector('.question-panel').textContent.includes('草稿未生成')"),'retryable provider failed');
    const first=requests.filter(r=>r.path==='/api/workflows/run')[before];assert(/^[A-Za-z0-9_-]{8,100}$/.test(first.body.request_id),'Valid workflow request ID missing');
    const savedBefore=(await api('state')).deliverables.length;await click('#ask-form button[type=submit]');await until(()=>count()===before+2,'retry sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled&&!document.querySelector('.question-panel').textContent.includes('草稿未生成')"),'retry completed');
    const second=requests.filter(r=>r.path==='/api/workflows/run')[before+1];assert(second.body.request_id===first.body.request_id,'Provider retry created a new request ID');
    const results=await cdp.evaluate("document.querySelectorAll('.workflow-result').length");await click('#ask-form button[type=submit]');await until(()=>count()===before+3,'completed repeat sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'completed repeat returned');
    assert((await api('state')).deliverables.length===savedBefore+1&&await cdp.evaluate("document.querySelectorAll('.workflow-result').length")===results,'Completed repeat duplicated a draft or result card');
    await fill('#question-input','Synthetic changed retry instruction');await click('#ask-form button[type=submit]');await until(()=>count()===before+4,'changed request sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'changed request completed');
    const changed=requests.filter(r=>r.path==='/api/workflows/run')[before+3];assert(changed.body.request_id!==first.body.request_id,'Changed message reused old request ID');
    await click('[data-source-id="'+doc.id+'"]');await click('#ask-form button[type=submit]');await until(()=>count()===before+5,'changed source request sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'changed source completed');
    const sourced=requests.filter(r=>r.path==='/api/workflows/run')[before+4];assert(sourced.body.request_id!==changed.body.request_id&&sourced.body.document_ids.includes(doc.id),'Changed sources reused old request ID');
    await route('overview');await click('[data-action=project-detail][data-id="'+alpha.id+'"]');await select('#library-group','');await cdp.evaluate("document.querySelectorAll('.material-family').forEach(e=>e.open=true)");
    await click('[data-action=edit][data-collection=documents][data-id="'+doc.id+'"]');await until(()=>cdp.evaluate("!!document.querySelector('#field-content')"),'source edit dialog');await fill('#field-content',quote+'\nSynthetic updated source text.');await click('#modal form button[type=submit]');await until(()=>cdp.evaluate("!document.querySelector('#modal').open"),'source edit completed');await route('research');
    await click('#ask-form button[type=submit]');await until(()=>count()===before+6,'updated source sent');await until(()=>cdp.evaluate("!document.querySelector('#question-input').disabled"),'updated source complete');
    assert(requests.filter(r=>r.path==='/api/workflows/run')[before+5].body.request_id!==sourced.body.request_id,'Edited source reused stale cached draft');
    assert(await cdp.evaluate("document.querySelectorAll('#toast-region .toast').length<=2"),'More than two toast messages cover the work surface');
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
