/* Shared request transport: recover only an explicitly rejected, unexecuted write. */
(function (root) {
  'use strict';
  function create({ fetch, context, setToken, staleError, refreshTimeoutMs = 10000 }) {
    let refreshing = null;
    function assertCurrent(snapshot) {
      const current = context();
      if (current.epoch !== snapshot.epoch || current.workspace !== snapshot.workspace) throw staleError();
      return current;
    }
    function abortError(signal) {
      if (signal?.reason instanceof Error) return signal.reason;
      const error = new Error('请求已取消'); error.name = 'AbortError'; return error;
    }
    function assertActive(snapshot, signal) {
      assertCurrent(snapshot);
      if (signal?.aborted) throw abortError(signal);
    }
    function waitFor(promise, signal) {
      if (!signal) return promise;
      if (signal.aborted) return Promise.reject(abortError(signal));
      return new Promise((resolve, reject) => {
        const aborted = () => { cleanup(); reject(abortError(signal)); };
        const cleanup = () => signal.removeEventListener('abort', aborted);
        signal.addEventListener('abort', aborted, { once: true });
        promise.then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
      });
    }
    async function httpError(response) {
      let message = `请求失败（${response.status}）`, code = '';
      try {
        const data = await response.json();
        if (data?.error) message = String(data.error);
        if (typeof data?.code === 'string') code = data.code;
      } catch { /* A non-JSON error remains an ordinary HTTP failure. */ }
      const error = new Error(message); error.status = response.status; error.code = code; return error;
    }
    async function refreshToken(snapshot, failedToken, signal) {
      assertActive(snapshot, signal);
      if (context().csrf !== failedToken) return;
      let entry = refreshing;
      if (!entry || entry.epoch !== snapshot.epoch || entry.workspace !== snapshot.workspace) {
        entry = { epoch: snapshot.epoch, workspace: snapshot.workspace };
        refreshing = entry;
        entry.promise = (async () => {
          // The refresh belongs to the shared session, not to one caller's abort signal.
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), refreshTimeoutMs);
          try {
            const response = await fetch('/api/bootstrap', { method: 'GET', headers: { 'X-Workspace': snapshot.workspace }, cache: 'no-store', credentials: 'same-origin', signal: controller.signal });
            assertCurrent(snapshot);
            if (!response.ok) throw await httpError(response);
            const data = await response.json();
            assertCurrent(snapshot);
            if (data?.workspace !== snapshot.workspace || typeof data?.csrf !== 'string' || !data.csrf.trim() || data.csrf.length > 512) throw new Error('未能更新会话，请保留输入后重试。');
            setToken(data.csrf, snapshot);
          } finally { clearTimeout(timer); }
        })().finally(() => { if (refreshing === entry) refreshing = null; });
      }
      await waitFor(entry.promise, signal);
      assertActive(snapshot, signal);
    }
    async function request(path, options = {}) {
      const snapshot = { ...context() };
      const method = String(options.method || (options.body !== undefined ? 'POST' : 'GET')).toUpperCase();
      const write = method !== 'GET' && method !== 'HEAD';
      // Serialize once: a retry must use exactly the same data as the rejected request.
      const body = options.body !== undefined ? JSON.stringify(options.body) : undefined;
      const extraHeaders = { ...(options.headers || {}) };
      for (const key of Object.keys(extraHeaders)) if (['x-workspace', 'x-csrf-token'].includes(key.toLowerCase())) delete extraHeaders[key];
      if (body !== undefined) extraHeaders['Content-Type'] = 'application/json';
      const url = path.startsWith('/auth/') ? path : `/api${path}`;
      for (let attempt = 0; attempt < 2; attempt++) {
        assertActive(snapshot, options.signal);
        const token = attempt ? context().csrf : snapshot.csrf;
        const headers = { ...extraHeaders, 'X-Workspace': snapshot.workspace, 'X-CSRF-Token': token };
        const response = await fetch(url, { method, headers, cache: 'no-store', credentials: 'same-origin', ...(body !== undefined ? { body } : {}), ...(options.signal ? { signal: options.signal } : {}) });
        assertActive(snapshot, options.signal);
        if (!response.ok) {
          const error = await httpError(response);
          assertActive(snapshot, options.signal);
          // The server guarantees this code is returned before mutation/provider execution.
          if (write && attempt === 0 && error.status === 403 && error.code === 'csrf_expired') {
            await refreshToken(snapshot, token, options.signal);
            continue;
          }
          throw error;
        }
        if (options.raw) return response;
        if (response.status === 204) return {};
        const result = await response.json();
        assertActive(snapshot, options.signal);
        return result;
      }
    }
    return { request };
  }
  const api = { create };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root) root.WorkOSApiClient = api;
})(typeof window !== 'undefined' ? window : null);
