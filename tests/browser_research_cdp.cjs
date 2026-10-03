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
const failures = [], requests = [], runtimeErrors = [], interceptionErrors = [];
let temp, server, chrome, cdp, origin, csrf;

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
async function check(name, fn) {
  try { await fn(); console.log('PASS ' + name); }
  catch (error) { const dom = await details().catch(() => null); failures.push({ name, error: error.message, dom }); console.error('FAIL ' + name + ': ' + error.message + '\nDOM ' + JSON.stringify(dom)); }
}
function assert(value, message) { if (!value) throw new Error(message); }
async function click(selector) {
  const point = await cdp.evaluate(`(() => { const e=document.querySelector(` + q(selector) + `); if(!e)throw Error('Missing '+` + q(selector) + `); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
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
  await until(() => cdp.evaluate(q(allowedHashes) + `.includes(location.hash) && !!document.querySelector('main h1') && document.querySelector('main').getAttribute('aria-busy')!=='true'`), 'route ' + name);
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
    if (['/api/ask', '/api/agent'].includes(url.pathname)) {
      const body = JSON.parse(event.request.postData || '{}'); requests.push({ path: url.pathname, method: event.request.method, body });
      const result = url.pathname === '/api/ask' ? { answer, mode: 'model', elapsed_ms: 1, citations: [{ document_id: doc.id, id: source.chunks[0].id, ordinal: source.chunks[0].ordinal, title: doc.title, quote }] } : { answer, steps: [] };
      return cdp.send('Fetch.fulfillRequest', { requestId: event.requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'application/json; charset=utf-8' }], body: Buffer.from(JSON.stringify(result)).toString('base64') });
    }
    if (/^\/api\/(meeting-draft|valuation-parse|ai|dsh)/.test(url.pathname) && event.request.method !== 'GET') {
      interceptionErrors.push('Blocked unexpected model endpoint: ' + url.pathname);
      return cdp.send('Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' });
    }
    return cdp.send('Fetch.continueRequest', { requestId: event.requestId });
  });
  await cdp.send('Page.enable'); await cdp.send('Runtime.enable');
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: origin });
  await until(() => cdp.evaluate("!!document.querySelector('.project-card') && document.querySelector('#main').getAttribute('aria-busy')!=='true'"), 'homepage synthetic cards');
  console.log('Isolated app PID ' + server.pid + '; Chrome PID ' + chrome.pid + '; loopback port ' + port);
  await check('no separate projects navigation', async () => assert(await cdp.evaluate("!document.querySelector('#primary-nav [data-page=projects]')"), 'Separate projects sidebar entry remains'));
  await check('homepage company folders and two primary research/meeting starts', async () => {
    const result = await cdp.evaluate("({cards:[...document.querySelectorAll('.project-title')].map(e=>e.textContent),starts:[...document.querySelectorAll('.research-start-grid .button.primary')].map(e=>({action:e.dataset.action,text:e.textContent}))})");
    assert(result.cards.includes(alpha.name) && result.cards.includes(beta.name) && result.starts.length === 2 && result.starts.some(e=>e.action==='research-ask') && result.starts.some(e=>e.action==='new-meeting'), JSON.stringify(result));
  });
  await check('legacy #projects opens company home', async () => { await route('projects'); assert(await cdp.evaluate("!!document.querySelector('.project-card') && !/不存在|错误/.test(document.querySelector('main h1').textContent)"), 'Legacy project route broken'); });
  await route('research');
  await check('one research prompt textarea', async () => assert(await cdp.evaluate("document.querySelectorAll('main textarea').length===1 && !!document.querySelector('#question-input')"), 'Research has duplicate prompt textareas'));
  await check('ask/actions modes retain independent drafts', async () => {
    await fill('#question-input', 'Synthetic ask draft'); await select('#research-intent', 'actions'); await fill('#question-input', 'Synthetic action draft');
    await select('#research-intent', 'ask'); assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic ask draft'"), 'Ask draft lost switching modes');
    await select('#research-intent', 'actions'); assert(await cdp.evaluate("document.querySelector('#question-input').value==='Synthetic action draft'"), 'Action draft lost switching modes'); await select('#research-intent', 'ask');
  });
  await check('company filtering and navigation preserve research scope', async () => {
    await select('#research-project', alpha.id);
    const visible = await cdp.evaluate("[...document.querySelectorAll('[data-source-id]')].map(e=>e.dataset.sourceId)");
    assert(visible.length===1 && visible[0]===doc.id, 'Company filter leaked evidence: '+JSON.stringify(visible));
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
  await check('mobile 375px viewport has no document horizontal overflow', async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 375, height: 812, deviceScaleFactor: 1, mobile: true });
    for (const page of ['research','overview','projects','meetings']) {
      await route(page);
      const result=await cdp.evaluate(`(() => ({viewport:document.documentElement.clientWidth,width:document.documentElement.scrollWidth,body:document.body.scrollWidth,offenders:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width && (r.right>innerWidth+1 || r.left < -1) && getComputedStyle(e).position!=='fixed';}).slice(0,15).map(e=>({tag:e.tagName,id:e.id,class:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right,width:e.scrollWidth}))}))()`);
      assert(result.width<=result.viewport+1 && result.body<=result.viewport+1, page+' overflow: '+JSON.stringify(result));
    }
  });
  await check('no browser exceptions or interception failures', async () => assert(!runtimeErrors.length && !interceptionErrors.length, JSON.stringify({runtimeErrors,interceptionErrors})));
  console.log('RESULT ' + JSON.stringify({ failures: failures.length, intercepted: requests.map(r=>r.path), assertions: 14 }));
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
