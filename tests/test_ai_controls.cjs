/* Actual application helpers with synthetic transport/DOM; no service or model calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
function slice(startText, endText) {
  const start = source.indexOf(startText), end = source.indexOf(endText, start);
  assert.ok(start >= 0 && end > start, `Application block ${startText} exists`);
  return source.slice(start, end);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function state() {
  return { aiRuns: new Map(), aiKinds: new Map(), aiReports: new Map(), workflowJobs: [], workflowStopBusy: new Set(),
    question: 'Original draft', workflowMessage: 'Original workflow draft', agentMessage: 'Original agent draft',
    agentAnswer: '', agentSteps: [] };
}
function harness(implementation = async () => ({})) {
  let current = state(), counter = 0, timerCounter = 0;
  const app = { epoch: 1, workspace: 'personal' }, calls = [], effects = [], region = {};
  const timers = new Map();
  const schedule = (kind, callback, delay) => { const id = ++timerCounter; timers.set(id, { kind, callback, delay }); return id; };
  const sandbox = {
    app, AbortController, crypto: { randomUUID: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}` },
    setTimeout: (callback, delay) => schedule('timeout', callback, delay),
    setInterval: (callback, delay) => schedule('interval', callback, delay),
    clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id),
    StaleRequestError: class extends Error { constructor() { super('Workspace changed'); this.name = 'StaleRequestError'; } },
    view: () => current,
    api: async (url, options) => { calls.push({ url, options }); return implementation(url, options, calls); },
    $: selector => selector === '#ai-run-controls' ? region : null,
    $$: () => [],
    esc: value => String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character])),
    actionButton: (label, _action, _symbol, _style, attrs) => `<button ${attrs}>${label}</button>`,
    workflowInfo: () => ({ title: 'Synthetic draft' }), activeWorkflowJob: job => ['queued', 'running'].includes(job.status),
    render: () => effects.push('render'), updateWorkflowRegions: () => effects.push('workflow-regions'), notify: message => effects.push(['notify', message]),
    showError: error => effects.push(['error', error.name]), refreshData: async () => effects.push('refresh'),
    acceptWorkflowJobs: async jobs => effects.push(['jobs', jobs])
  };
  const helpers = vm.runInNewContext(slice('  const AI_BUSY =', '  function notify(') +
    '\n({beginAiRun,assertAiRun,aiRequest,finishAiRun,stopAiRun,updateAiControls});', sandbox);
  return { ...helpers, app, calls, effects, region, timers, get state() { return current; }, changeView: next => { current = next; } };
}
const tests = [];
function test(name, run) { tests.push({ name, run }); }

test('requests carry the exact generated UUID, body and per-run abort signal', async () => {
  const progress = { status: 'completed', stage: 'completed', stage_label: '已完成', elapsed_ms: 1200,
    events: [{ sequence: 1, label: '读取已选资料', status: 'completed', elapsed_ms: 200 }] };
  const h = harness(async url => url === '/ask' ? { answer: 'Synthetic answer' } : { operation: progress }), run = h.beginAiRun('ask');
  const body = { question: 'Synthetic question', document_ids: ['synthetic-source'] };
  assert.match(run.id, /^[0-9a-f-]{36}$/);
  assert.equal(h.state.asking, true);
  assert.equal(h.state.aiRuns.get(run.id), run);
  assert.equal(h.timers.size, 2);
  await h.aiRequest(run, '/ask', body);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].url, '/ask');
  assert.equal(h.calls[0].options.headers['X-WorkOS-Request-ID'], run.id);
  assert.equal(h.calls[0].options.body, body);
  assert.equal(h.calls[0].options.signal, run.controller.signal);
  assert.equal(h.calls[1].url, `/operations/${run.id}`);
  assert.equal(h.calls[1].options?.body, undefined);
  assert.equal(run.progress, progress);
  assert.equal(h.finishAiRun(run), true);
  assert.equal(h.state.asking, false);
  assert.equal(h.state.aiRuns.size, 0);
  assert.equal(h.timers.size, 0);
  assert.equal(h.state.aiReports.get('ask'), run);
  assert.equal(h.state.aiReports.get('ask').progress.events, progress.events);
});

test('late success or error and old finally cannot overwrite a replacement run', async () => {
  for (const reply of ['success', 'error']) {
    const late = deferred();
    const h = harness(url => url.includes('/cancel') ? { status: 'cancelled' } : late.promise);
    const old = h.beginAiRun('ask');
    const result = h.aiRequest(old, '/ask', { question: 'Old question' })
      .then(value => { h.state.question = value.answer; }, error => {
        assert.equal(error.name, 'AbortError');
        if (h.state.aiKinds.get('ask') === old) h.state.question = 'Old error';
      }).finally(() => assert.equal(h.finishAiRun(old), false));
    await h.stopAiRun(old.id);
    const newer = h.beginAiRun('ask'); h.state.question = 'New draft';
    if (reply === 'success') late.resolve({ answer: 'Late old answer' }); else late.reject(new Error('Late provider error'));
    await result;
    assert.equal(h.state.question, 'New draft');
    assert.equal(h.state.asking, true);
    assert.equal(h.state.aiKinds.get('ask'), newer);
    assert.equal(h.state.aiRuns.get(newer.id), newer);
    assert.equal(newer.controller.signal.aborted, false);
  }
});

test('replaced ownership rejects an old response even when its transport ignores abort', async () => {
  const pending = deferred(), h = harness(() => pending.promise), old = h.beginAiRun('valuation');
  const result = assert.rejects(h.aiRequest(old, '/model/parse-assumptions', {}), error => error.name === 'AbortError');
  const newer = h.beginAiRun('valuation');
  pending.resolve({ assumptions: { unsupported: 999 } }); await result;
  assert.equal(h.finishAiRun(old), false);
  assert.equal(h.state.valuationPending, true);
  assert.equal(h.state.aiKinds.get('valuation'), newer);
});

test('a failed stop remains retryable and stops only the requested operation', async () => {
  let stops = 0;
  const h = harness(url => {
    assert.ok(url.includes('/cancel'));
    if (++stops === 1) throw new TypeError('Synthetic network error');
    return { status: 'cancelled' };
  });
  const ask = h.beginAiRun('ask'), meeting = h.beginAiRun('meeting');
  assert.equal(h.timers.size, 4);
  await h.stopAiRun(ask.id);
  assert.equal(h.timers.size, 2);
  assert.equal(ask.controller.signal.aborted, true);
  assert.equal(ask.cancelPending, false);
  assert.ok(ask.cancelError);
  assert.equal(h.state.aiRuns.get(ask.id), ask);
  assert.equal(h.state.asking, false);
  assert.equal(h.state.meetingAiBusy, true);
  assert.equal(meeting.controller.signal.aborted, false);
  h.updateAiControls(); assert.match(h.region.innerHTML, /重试停止/);
  await h.stopAiRun(ask.id);
  assert.equal(h.state.aiRuns.has(ask.id), false);
  assert.equal(h.state.aiKinds.get('meeting'), meeting);
  assert.equal(h.calls.length, 2);
  assert.ok(h.calls.every(call => call.url === `/operations/${ask.id}/cancel`));
});

test('an old agent cancellation acknowledgement preserves a newer draft and result', async () => {
  const pending = deferred(), h = harness(() => pending.promise), old = h.beginAiRun('agent');
  old.projectId = 'synthetic-old-project'; h.state.lastAgentRun = old.id;
  const stopping = h.stopAiRun(old.id);
  const newer = h.beginAiRun('agent'); h.state.lastAgentRun = newer.id;
  h.state.agentMessage = 'New agent draft'; h.state.agentAnswer = 'New result';
  pending.resolve({ status: 'cancelled', steps: [{ action: 'create_task', result: { id: 'old-task' } }] });
  await stopping;
  assert.equal(h.state.agentMessage, 'New agent draft');
  assert.equal(h.state.agentAnswer, 'New result');
  assert.equal(h.state.agentSteps.length, 0);
  assert.equal(h.state.agentBusy, true);
  assert.equal(h.state.aiKinds.get('agent'), newer);
  assert.ok(!h.effects.includes('refresh'));
});

test('workflow stop cancels the original request ID and acknowledgement preserves a new request', async () => {
  const pending = deferred(), h = harness(() => pending.promise), old = h.beginAiRun('workflow-submit');
  h.state.workflowRequest = { id: old.id, signature: 'old' };
  const stopping = h.stopAiRun(old.id);
  assert.equal(h.state.workflowRequest, null);
  const newer = h.beginAiRun('workflow-submit');
  h.state.workflowRequest = { id: newer.id, signature: 'new' }; h.state.workflowMessage = 'New work';
  pending.resolve({ job: { id: 'synthetic-job', status: 'cancelled' } }); await stopping;
  assert.equal(h.calls[0].url, '/workflows/jobs/cancel');
  assert.equal(h.calls[0].options.body.request_id, old.id);
  assert.equal(h.state.workflowRequest.id, newer.id);
  assert.equal(h.state.workflowMessage, 'New work');
  assert.equal(h.state.workflowBusy, true);
  assert.equal(h.effects.filter(effect => Array.isArray(effect) && effect[0] === 'jobs').length, 1);
});

test('workspace or epoch changes reject a late result and prevent fresh dispatch from old context', async () => {
  for (const change of [{ workspace: 'demo' }, { epoch: 2 }]) {
    const pending = deferred(), h = harness(() => pending.promise), run = h.beginAiRun('ask');
    const rejected = assert.rejects(h.aiRequest(run, '/ask', {}), error => error.name === 'StaleRequestError');
    Object.assign(h.app, change); pending.resolve({ answer: 'Old workspace answer' }); await rejected;
    await assert.rejects(h.aiRequest(run, '/ask', {}), error => error.name === 'StaleRequestError');
    assert.equal(h.calls.length, 1);
  }
  const pending = deferred(), h = harness(() => pending.promise), oldState = h.state, run = h.beginAiRun('agent');
  oldState.lastAgentRun = run.id;
  const stopping = h.stopAiRun(run.id), next = state(); h.changeView(next); h.app.workspace = 'demo'; h.app.epoch++;
  pending.resolve({ status: 'cancelled', steps: [{ action: 'create_task' }] }); await stopping;
  assert.equal(next.agentAnswer, '');
  assert.equal(next.aiRuns.size, 0);
  assert.equal(h.effects.filter(effect => Array.isArray(effect) && effect[0] === 'notify').length, 0);
  assert.ok(!h.effects.includes('refresh'));
});

test('plain Enter sends once while newlines, IME, repeats and disabled controls do not send', async () => {
  const listeners = new Map(), send = { disabled: false }, input = { disabled: false,
    addEventListener: (name, handler) => listeners.set(name, handler) };
  let submits = 0;
  const form = { querySelector: () => send, requestSubmit: button => { assert.equal(button, send); submits++; } };
  const bind = vm.runInNewContext(slice('  function bindAiComposer(', '  function bindPage(') + '\nbindAiComposer;',
    { $: selector => selector === '#synthetic-input' ? input : selector === '#synthetic-form' ? form : null });
  bind('synthetic-input', 'synthetic-form');
  const key = overrides => { let prevented = false; listeners.get('keydown')({ key: 'Enter', preventDefault: () => { prevented = true; }, ...overrides }); return prevented; };
  assert.equal(key({}), true); assert.equal(submits, 1);
  for (const modifier of ['shiftKey', 'ctrlKey', 'altKey', 'metaKey']) assert.equal(key({ [modifier]: true }), false);
  assert.equal(key({ key: 'a' }), false);
  assert.equal(key({ isComposing: true }), false);
  assert.equal(key({ keyCode: 229 }), false);
  listeners.get('compositionstart')(); assert.equal(key({}), false); listeners.get('compositionend')();
  assert.equal(key({ repeat: true }), true);
  input.disabled = true; key({}); input.disabled = false;
  send.disabled = true; key({}); send.disabled = false;
  assert.equal(submits, 1);
  key({}); assert.equal(submits, 2);
});

(async () => {
  for (const { name, run } of tests) { await run(); console.log('PASS:', name); }
  console.log(`PASS: ${tests.length} AI controls scenarios`);
})().catch(error => { console.error(error); process.exitCode = 1; });
