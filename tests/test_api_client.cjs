/* Synthetic transport tests: no server, account, browser or provider calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { create } = require('../web/api-client.js');

function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function response(status, data, jsonError) {
  return { status, ok: status >= 200 && status < 300,
    json: async () => { if (jsonError) throw jsonError; return data; } };
}
const expired = () => response(403, { code: 'csrf_expired', error: 'Expired session token' });
const stale = () => Object.assign(new Error('Workspace changed'), { name: 'StaleRequestError' });
function harness(implementation, settings = {}) {
  let current = { epoch: 1, workspace: 'personal', csrf: 'old-token' };
  const calls = [], commits = [];
  const fetch = async (url, options) => { calls.push({ url, options }); return implementation(url, options, calls); };
  const client = create({ fetch, context: () => ({ ...current }),
    setToken: (token, snapshot) => { commits.push({ token, snapshot }); current.csrf = token; },
    staleError: stale, ...settings });
  return { request: client.request, calls, commits, change: update => { current = { ...current, ...update }; } };
}
const tests = [];
function test(name, run) { tests.push({ name, run }); }

test('concurrent expired writes share one bootstrap and both use its fresh token', async () => {
  const refresh = deferred(), started = deferred();
  const h = harness((url, options) => {
    if (url === '/api/bootstrap') { started.resolve(); return refresh.promise; }
    return options.headers['X-CSRF-Token'] === 'old-token' ? expired() : response(201, { saved: url });
  });
  const first = h.request('/tasks', { body: { title: 'First draft' } });
  const second = h.request('/notes', { body: { title: 'Second draft' } });
  await started.promise;
  assert.equal(h.calls.filter(call => call.url === '/api/bootstrap').length, 1);
  refresh.resolve(response(200, { workspace: 'personal', csrf: 'fresh-token' }));
  assert.deepEqual(await Promise.all([first, second]), [{ saved: '/api/tasks' }, { saved: '/api/notes' }]);
  assert.equal(h.commits.length, 1);
  assert.equal(h.calls.filter(call => call.url === '/api/bootstrap').length, 1);
  assert.equal(h.calls.filter(call => call.options.headers['X-CSRF-Token'] === 'fresh-token').length, 2);
  const boot = h.calls.find(call => call.url === '/api/bootstrap').options;
  assert.equal(boot.method, 'GET');
  assert.deepEqual(boot.headers, { 'X-Workspace': 'personal' });
  assert.equal(boot.cache, 'no-store');
  assert.equal(boot.credentials, 'same-origin');
});

test('a delayed concurrent403 reuses the token already refreshed by another request', async () => {
  const late = deferred();
  const h = harness((url, options) => {
    if (url === '/api/bootstrap') return response(200, { workspace: 'personal', csrf: 'fresh-token' });
    if (options.headers['X-CSRF-Token'] !== 'old-token') return response(201, { saved: url });
    return url === '/api/notes' ? late.promise : expired();
  });
  const first = h.request('/tasks', { body: { title: 'First' } });
  const second = h.request('/notes', { body: { title: 'Delayed rejection' } });
  assert.deepEqual(await first, { saved: '/api/tasks' });
  late.resolve(expired());
  assert.deepEqual(await second, { saved: '/api/notes' });
  assert.equal(h.calls.filter(call => call.url === '/api/bootstrap').length, 1);
  assert.equal(h.commits.length, 1);
});

test('retry preserves one serialization, verb, custom headers and original workspace', async () => {
  let serializations = 0;
  const body = { title: 'Before', toJSON() { serializations++; return { title: this.title }; } };
  const headers = { 'X-Request-Id': 'synthetic-request', 'x-workspace': 'demo', 'x-csrf-token': 'forged' };
  const h = harness((url, _options, calls) => {
    if (url === '/api/bootstrap') { body.title = 'After'; headers['X-Request-Id'] = 'Changed'; return response(200, { workspace: 'personal', csrf: 'new-token' }); }
    return calls.filter(call => call.url === '/api/tasks/synthetic').length === 1 ? expired() : response(200, { ok: true });
  });
  assert.deepEqual(await h.request('/tasks/synthetic', { method: 'patch', body, headers }), { ok: true });
  assert.equal(serializations, 1);
  const writes = h.calls.filter(call => call.url === '/api/tasks/synthetic');
  assert.equal(writes.length, 2);
  assert.equal(writes[0].options.body, '{"title":"Before"}');
  assert.equal(writes[1].options.body, writes[0].options.body);
  for (const write of writes) {
    assert.equal(write.options.method, 'PATCH');
    assert.equal(write.options.headers['X-Workspace'], 'personal');
    assert.equal(write.options.headers['X-Request-Id'], 'synthetic-request');
    assert.equal(write.options.headers['Content-Type'], 'application/json');
    assert.equal(write.options.cache, 'no-store');
    assert.equal(write.options.credentials, 'same-origin');
    assert.ok(!('x-workspace' in write.options.headers));
    assert.ok(!('x-csrf-token' in write.options.headers));
  }
  assert.equal(writes[0].options.headers['X-CSRF-Token'], 'old-token');
  assert.equal(writes[1].options.headers['X-CSRF-Token'], 'new-token');
});

test('a second csrf rejection stops after one refresh and one retry', async () => {
  const h = harness(url => url === '/api/bootstrap' ? response(200, { workspace: 'personal', csrf: 'fresh-token' }) : expired());
  await assert.rejects(h.request('/tasks', { body: {} }), error => error.status === 403 && error.code === 'csrf_expired');
  assert.deepEqual(h.calls.map(call => call.url), ['/api/tasks', '/api/bootstrap', '/api/tasks']);
  assert.equal(h.commits.length, 1);
});

test('ordinary403,401, nonJSON errors, network loss and lost success JSON never replay writes', async () => {
  const cases = [
    { name: 'generic403', reply: () => response(403, { error: 'Forbidden' }), status: 403 },
    { name: '401 even with csrf code', reply: () => response(401, { code: 'csrf_expired', error: 'Login required' }), status: 401 },
    { name: 'nonJSON403', reply: () => response(403, null, new SyntaxError('HTML response')), status: 403 },
    { name: 'network failure', reply: () => { throw new TypeError('Connection lost'); } },
    { name: 'success response JSON lost', reply: () => response(201, null, new SyntaxError('Response truncated')) }
  ];
  for (const item of cases) {
    const h = harness(item.reply);
    await assert.rejects(h.request('/tasks', { body: { title: item.name } }), error => item.status ? error.status === item.status : /lost|truncated/i.test(error.message));
    assert.equal(h.calls.length, 1, item.name);
    assert.equal(h.commits.length, 0, item.name);
  }
});

test('invalid bootstrap identity/token or failed bootstrap does not retry or commit', async () => {
  const replies = [
    response(200, { workspace: 'demo', csrf: 'fresh-token' }),
    response(200, { workspace: 'personal', csrf: '' }),
    response(200, { workspace: 'personal', csrf: '   ' }),
    response(200, { workspace: 'personal', csrf: 123 }),
    response(200, { workspace: 'personal', csrf: 'x'.repeat(513) }),
    response(200, { csrf: 'fresh-token' }),
    response(401, { error: 'Login required' }),
    response(200, null, new SyntaxError('Invalid bootstrap JSON')),
    () => Promise.reject(new TypeError('Bootstrap network lost'))
  ];
  for (const boot of replies) {
    const h = harness(url => url === '/api/bootstrap' ? (typeof boot === 'function' ? boot() : boot) : expired());
    await assert.rejects(h.request('/notes', { body: { title: 'Kept draft' } }));
    assert.deepEqual(h.calls.map(call => call.url), ['/api/notes', '/api/bootstrap']);
    assert.equal(h.commits.length, 0);
  }
});

test('workspace and epoch changes during either bootstrap await refuse commit and retry', async () => {
  for (const change of [{ workspace: 'demo' }, { epoch: 2 }]) {
    for (const phase of ['fetch', 'json']) {
      const pending = deferred(), entered = deferred(), jsonStarted = deferred();
      const h = harness(url => {
        if (url !== '/api/bootstrap') return expired();
        entered.resolve();
        return phase === 'fetch' ? pending.promise : { status: 200, ok: true, json: () => { jsonStarted.resolve(); return pending.promise; } };
      });
      const result = h.request('/deliverables', { body: { title: 'Kept draft' } });
      const rejection = assert.rejects(result, error => error.name === 'StaleRequestError');
      await entered.promise;
      if (phase === 'json') await jsonStarted.promise;
      h.change(change);
      pending.resolve(phase === 'fetch' ? response(200, { workspace: 'personal', csrf: 'fresh-token' }) : { workspace: 'personal', csrf: 'fresh-token' });
      await rejection;
      assert.equal(h.calls.length, 2, `${phase} ${JSON.stringify(change)}`);
      assert.equal(h.commits.length, 0);
    }
  }
});

test('one caller aborts without canceling another caller shared refresh or causing its own retry', async () => {
  const pending = deferred(), entered = deferred();
  const controller = new AbortController();
  const h = harness((url, options) => {
    if (url === '/api/bootstrap') { entered.resolve(); return pending.promise; }
    return options.headers['X-CSRF-Token'] === 'old-token' ? expired() : response(201, { ok: true });
  });
  const first = h.request('/tasks', { body: { title: 'Canceled' }, signal: controller.signal });
  const second = h.request('/notes', { body: { title: 'Keep' } });
  const canceled = assert.rejects(first, error => error.name === 'AbortError');
  await entered.promise;
  controller.abort();
  await canceled;
  const refreshSignal = h.calls.find(call => call.url === '/api/bootstrap').options.signal;
  assert.notEqual(refreshSignal, controller.signal);
  assert.equal(refreshSignal.aborted, false);
  pending.resolve(response(200, { workspace: 'personal', csrf: 'fresh-token' }));
  assert.deepEqual(await second, { ok: true });
  assert.equal(h.calls.filter(call => call.url === '/api/tasks').length, 1);
  assert.equal(h.calls.filter(call => call.url === '/api/notes').length, 2);
  assert.equal(h.calls.filter(call => call.url === '/api/bootstrap').length, 1);
});

test('refresh deadline rejects rather than replaying a write', async () => {
  const h = harness((url, options) => {
    if (url !== '/api/bootstrap') return expired();
    return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true }));
  }, { refreshTimeoutMs: 10 });
  await assert.rejects(h.request('/tasks', { body: {} }), error => error.name === 'AbortError');
  assert.equal(h.calls.length, 2);
  assert.equal(h.commits.length, 0);
});

test('GET/HEAD csrf failures and ordinary login/setup403 do not refresh', async () => {
  for (const [path, options] of [['/state', {}], ['/state', { method: 'HEAD' }],
                               ['/auth/login', { method: 'POST' }], ['/auth/setup', { method: 'POST' }]]) {
    const h = harness(() => path.startsWith('/auth/') ? response(403, { error: 'Ordinary authentication rejection' }) : expired());
    await assert.rejects(h.request(path, options), error => error.status === 403 && error.code === (path.startsWith('/auth/') ? '' : 'csrf_expired'));
    assert.equal(h.calls.length, 1);
    assert.equal(h.commits.length, 0);
  }
});

test('explicit csrf_expired logout refreshes and succeeds exactly once at the auth path', async () => {
  let successfulLogouts = 0;
  const h = harness((url, options) => {
    if (url === '/api/bootstrap') return response(200, { workspace: 'personal', csrf: 'fresh-token' });
    assert.equal(url, '/auth/logout');
    if (options.headers['X-CSRF-Token'] === 'old-token') return expired();
    successfulLogouts++;
    return response(200, { ok: true });
  });
  assert.deepEqual(await h.request('/auth/logout', { method: 'POST', headers: { 'X-Request-Id': 'synthetic-logout' } }), { ok: true });
  assert.deepEqual(h.calls.map(call => call.url), ['/auth/logout', '/api/bootstrap', '/auth/logout']);
  assert.equal(h.commits.length, 1);
  assert.equal(successfulLogouts, 1);
  for (const call of h.calls.filter(call => call.url === '/auth/logout')) {
    assert.equal(call.options.method, 'POST');
    assert.equal(call.options.headers['X-Workspace'], 'personal');
    assert.equal(call.options.headers['X-Request-Id'], 'synthetic-logout');
    assert.ok(!('body' in call.options));
  }
});

test('normal GET,raw response and204 return without extra requests or JSON parsing', async () => {
  const h = harness(() => response(200, { projects: [] }));
  assert.deepEqual(await h.request('/state'), { projects: [] });
  assert.equal(h.calls[0].options.method, 'GET');
  assert.ok(!('body' in h.calls[0].options));
  const raw = response(200, null, new Error('Raw response must not parse JSON'));
  const rawClient = harness(() => raw);
  assert.equal(await rawClient.request('/export', { raw: true }), raw);
  assert.equal(rawClient.calls.length, 1);
  const noContent = harness(() => response(204, null, new Error('204 must not parse JSON')));
  assert.deepEqual(await noContent.request('/tasks/synthetic', { method: 'DELETE' }), {});
  assert.equal(noContent.calls.length, 1);
});

test('a pending download refuses browser effects after an epoch or workspace change', async () => {
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const start = source.indexOf('  async function download(');
  const end = source.indexOf('  async function exportDeliverable(', start);
  assert.ok(start >= 0 && end > start, 'Extract the actual application download function');
  for (const change of [{ epoch: 2 }, { workspace: 'demo' }, null]) {
    const pending = deferred(), started = deferred(), effects = [], requests = [];
    const app = { epoch: 1, workspace: 'personal' };
    const context = vm.createContext({
      app,
      StaleRequestError: class extends Error { constructor() { super('Workspace changed'); this.name = 'StaleRequestError'; } },
      api: async (url, options) => {
        requests.push({ url, options });
        return { headers: { get: () => 'attachment; filename="synthetic.xlsx"' }, blob: () => { started.resolve(); return pending.promise; } };
      },
      URL: { createObjectURL: () => { effects.push('url'); return 'blob:synthetic'; }, revokeObjectURL: () => effects.push('revoke') },
      document: { createElement: () => { effects.push('link'); return { click: () => effects.push('click'), remove: () => effects.push('remove') }; }, body: { append: () => effects.push('append') } },
      setTimeout: () => effects.push('timer'),
      notify: () => effects.push('notify')
    });
    const download = vm.runInContext(source.slice(start, end) + '\ndownload;', context);
    const body = { title: 'Synthetic model' };
    const result = download('/model/export-xlsx', 'fallback.xlsx', { method: 'POST', body });
    const completed = change ? assert.rejects(result, error => error.name === 'StaleRequestError') : result;
    await started.promise;
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/model/export-xlsx');
    assert.equal(requests[0].options.raw, true);
    assert.equal(requests[0].options.method, 'POST');
    assert.equal(requests[0].options.body, body);
    assert.deepEqual(effects, []);
    if (change) Object.assign(app, change);
    pending.resolve({ synthetic: true });
    await completed;
    assert.deepEqual(effects, change ? [] : ['url', 'link', 'append', 'click', 'remove', 'timer', 'notify']);
  }
});

(async () => {
  for (const { name, run } of tests) { await run(); console.log('PASS:', name); }
  console.log(`PASS: ${tests.length} API client recovery scenarios`);
})().catch(error => { console.error(error); process.exitCode = 1; });
