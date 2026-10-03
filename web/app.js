/* Local WorkOS — no framework, no CDN, no outbound requests from the browser. */
(() => {
  'use strict';

  // Raw/user text is escaped; rich AI text uses the bounded, HTML-escaping Markdown renderer.
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
  const readable = value => window.WorkOSMarkdown ? window.WorkOSMarkdown.render(value) : `<p>${esc(value)}</p>`;
  const ICONS = {
    home: '<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    projects: '<path d="M4 21V6h10v15M14 10h6v11M2 21h20M7 9h4M7 13h4M7 17h4M17 13v1M17 17v1M7 6V3h4v3"/>',
    research: '<path d="M5 3h10l4 4v7M15 3v5h4M5 3v18h8M8 11h6M8 15h3"/><circle cx="17" cy="17" r="4"/><path d="m20 20 2 2"/>',
    meetings: '<path d="M3 4h18v13H8l-5 4zM7 8h10M7 12h7"/>',
    tasks: '<rect x="4" y="4" width="16" height="17" rx="2"/><path d="M9 4V2h6v2M8 10l2 2 5-5M8 16h8"/>',
    memory: '<path d="M12 4C8 1 5 3 5 6c-4 0-4 7-1 8-2 3 1 7 4 6 1 2 4 1 4-1V4zm0 0c4-3 7-1 7 2 4 0 4 7 1 8 2 3-1 7-4 6-1 2-4 1-4-1M5 6l3 2M4 14h4M16 8l3-2M16 14h4M8 17l4-2 4 2"/>',
    finance: '<path d="M3 3v18h18M7 17v-5M12 17V8M17 17V5M6 7l5-3 4 2 5-4"/>',
    deliverables: '<path d="M4 8h16v13H4zM3 4h18v4H3zM9 12h6M12 12v5m-3-3 3 3 3-3"/>',
    settings: '<path d="m10 3-1 3-3 1-3-1-1 4 3 2 1 3-1 3 4 2 2-2h3l2 2 4-3-1-3 1-3 2-2-2-4-3 1-3-1-1-3z" transform="translate(1 0) scale(.9)"/><circle cx="12" cy="12" r="3"/>',
    search: '<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    circleCheck: '<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    warning: '<path d="m12 3 10 18H2zM12 9v5M12 17v.5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 10v7M12 7v.5"/>',
    edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14zM3 22h18"/>',
    trash: '<path d="M3 6h18M8 6V3h8v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5"/>',
    download: '<path d="M12 3v13m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    file: '<path d="M5 3h10l4 4v14H5zM15 3v5h4M8 12h8M8 16h6"/>',
    book: '<path d="M12 5C9 3 5 3 2 4v16c4-1 7-1 10 1 3-2 6-2 10-1V4c-3-1-7-1-10 1v16"/>',
    lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 14v3"/>',
    shield: '<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6zM8 12l3 3 5-6"/>',
    user: '<circle cx="12" cy="7" r="4"/><path d="M4 21v-3a8 8 0 0 1 16 0v3"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 11h18M7 15h3M14 15h3"/>',
    spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z"/>',
    quote: '<path d="M3 12V5h7v8H6c0 3-1 5-4 6M14 12V5h7v8h-4c0 3-1 5-4 6"/>',
    link: '<path d="m10 7 3-3a5 5 0 0 1 7 7l-3 3M14 17l-3 3a5 5 0 0 1-7-7l3-3M8 16l8-8"/>',
    refresh: '<path d="M20 4v6h-6M4 20v-6h6M4 9a8 8 0 0 1 14-5l2 3M4 17l2 3a8 8 0 0 0 14-5"/>',
    menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
    switch: '<path d="M3 7h17m-4-4 4 4-4 4M21 17H4m4-4-4 4 4 4"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    logout: '<path d="M9 3H4v18h5M13 7l5 5-5 5M8 12h13"/>',
    external: '<path d="M14 3h7v7M21 3 10 14M10 4H3v17h17v-7"/>',
    briefcase: '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12c6 4 12 4 18 0M10 14h4"/>'
  };
  const icon = name => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.file}</svg>`;
  const ROUTES = [
    ['overview', '工作首页', 'WORK HOME', 'grid'], ['projects', '工作首页', 'WORK HOME', 'projects'],
    ['research', '基本面研究', 'FUNDAMENTALS', 'research'], ['meetings', '会议与纪要', 'MEETINGS', 'meetings'],
    ['tasks', '行动跟进', 'ACTIONS', 'tasks'], ['memory', '知识与记忆', 'KNOWLEDGE', 'memory'],
    ['finance', '估值与回报模型', 'VALUATION', 'finance'], ['deliverables', '研究交付', 'DELIVERABLES', 'deliverables'],
    ['settings', '设置', 'SETTINGS', 'settings']
  ];
  const STAGES = ['线索', '初筛', '尽调', '投委会', '投后', '归档'];
  const CREATE_PROJECT_VALUE = '__create_project__';
  const PRIORITIES = ['高', '中', '低'];
  const STATUSES = ['待办', '进行中', '完成'];
  const NOTE_STATUSES = ['待核实', '已核实', '暂不采用'];
  const KINDS = ['研究简报', '会议纪要', '项目周报', '自定义'];
  const VALUATION_METHODS = [['net_income', '净利润 × P/E'], ['ps', 'P/S（股权价值）'], ['dcf', 'DCF / FCFF'], ['lbo', 'LBO / Sponsor Returns']];
  const VALUATION_LABELS = { currency: '币种', unit: '金额单位', period: '期间', net_income: '净利润', pe_multiple: 'P/E', diluted_shares: '稀释后股数', revenue: '收入', ps_multiple: 'P/S', net_debt: '净债务', valuation_date: '估值日', wacc: 'WACC', discount_timing: '折现时点', terminal_method: '终值方法', terminal_growth: '永续增长率', terminal_multiple: '退出倍数', minority_interest: '少数股东权益', entry_date: '进入日', exit_date: '退出日', entry_ev: '进入企业价值', entry_debt: '初始债务', entry_fees: '进入费用', minimum_cash: '最低现金', initial_cash: '初始现金', seller_rollover: '卖方滚存', exit_fees: '退出费用', exit_multiple: '退出倍数', tax_rate: '税率', interest_rate: '利率', mandatory_amortization: '强制偿还', cash_sweep_pct: '超额现金偿债比例', forecasts: '年度预测' };
  const FINANCE_DEFAULTS = Object.freeze({ revenue: 120, growth: .25, margin: .2, entry_multiple: 12, exit_multiple: 14, leverage: .35, years: 5, cash_conversion: .5, interest_rate: .06 });
  const FINANCE_FIELDS = [
    ['revenue', '起始收入', '百万元', 0.01, 1000000000, .01], ['growth', '收入年增长率', '%', -50, 100, .1],
    ['margin', 'EBITDA 利润率', '%', 1, 100, .1], ['entry_multiple', '进入倍数', '× EBITDA', .1, 50, .1],
    ['exit_multiple', '退出倍数', '× EBITDA', 0, 50, .1], ['leverage', '初始债务 / EV', '%', 0, 80, .1],
    ['years', '持有期', '年', 1, 10, 1], ['cash_conversion', '现金转化率', '%', 0, 100, .1],
    ['interest_rate', '债务年利率', '%', 0, 50, .1]
  ];
  const PERCENT_FIELDS = new Set(['growth', 'margin', 'leverage', 'cash_conversion', 'interest_rate']);
  const LABELS = { projects: '项目', tasks: '任务', documents: '资料', meetings: '会议', notes: '研究结论', deliverables: '交付' };
  const DSH_MODEL_IDS = new Set(['gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-5.6-luna','gpt-5.6-sol','gpt-5.6-terra','gpt-5.5']);
  const LOCAL_MODEL_IDS = new Set(['deepseek-v4.1-flash','deepseek-v4-pro','deepseek-v3-2-volc','glm-5.2','kimi-k2.7','hy3','hunyuan-2.0-instruct']);
  const app = { workspace: 'personal', csrf: '', boot: null, data: null, workflows: [], page: 'overview', epoch: 0, modalBusy: false, mutations: 0, stopped: false, uploadBusy: false };
  let workflowPollTimer = null;
  const views = new Map();
  function freshView() {
    return { page: 'overview', startMessage: '', startProject: '', startPurpose: '', startSourceIds: new Set(), startBusy: false, workflowKey: 'brief', workflowMessage: '', workflowBusy: false, workflowError: '', workflowResults: [], projectStage: '全部', projectQuery: '', projectId: '', libraryQuery: '', libraryGroup: '', taskProject: '', taskQuery: '', taskPriority: '', highlightTask: '', researchProject: '', sourceGroup: '', sourceQuery: '', selectedSources: new Set(), answers: [], researchIntent: 'ask', askMode: 'deepseek', dshModel: loadDshModel(), localModel: loadLocalModel(), agentOpen: false, agentMessage: '', agentBusy: false, agentSteps: [], agentAnswer: '', agentResultProject: null, agentProjectScope: true, agentHistoryByScope: new Map(), question: '', asking: false, meetingProject: '', meetingId: '', drafts: new Map(), meetingTranscriptDraft: '', meetingModel: 'deepseek-v4.1-flash', meetingAiBusy: false, meetingSaveTimer: null, meetingSaveState: '', memoryCategory: '全部', memoryQuery: '', deliverableId: '', deliverableDirty: false, finance: loadFinance(), financeResult: null, financePending: false, financeError: '', financeAutoStarted: false, financeDirty: false, valuationMethod: 'net_income', valuationText: '', valuationProposal: null, valuationJson: '', valuationResult: null, valuationPending: false, valuationError: '', valuationProjectId: '', valuationModel: 'gpt-6-luna' };
  }
  function view() {
    if (!views.has(app.workspace)) {
      const state = freshView();
      Object.assign(state, {workflowQuality:'',workflowJobs:[],workflowJobConnectionError:'',workflowPollFailures:0,workflowPollBusy:false,workflowSeenCompletions:new Set(),workflowRetryBusy:new Set()});
      views.set(app.workspace, state);
    }
    return views.get(app.workspace);
  }
  function loadDshModel() { try { const model = localStorage.getItem('local-workos:dsh-model'); return DSH_MODEL_IDS.has(model) ? model : 'gpt-6-luna'; } catch { return 'gpt-6-luna'; } }
  function loadLocalModel() { try { const model = localStorage.getItem('local-workos:local-model'); return LOCAL_MODEL_IDS.has(model) ? model : 'deepseek-v4.1-flash'; } catch { return 'deepseek-v4.1-flash'; } }
  function loadFinance() {
    try { const value = JSON.parse(localStorage.getItem(`local-workos:${app.workspace}:assumptions`) || 'null'); return { ...FINANCE_DEFAULTS, ...(value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).filter(([key, number]) => key in FINANCE_DEFAULTS && Number.isFinite(number))) : {}) }; }
    catch { return { ...FINANCE_DEFAULTS }; }
  }
  function persistFinance() { try { localStorage.setItem(`local-workos:${app.workspace}:assumptions`, JSON.stringify(view().finance)); } catch { /* Private browsing can deny optional preference storage. */ } }
  const list = collection => Array.isArray(app.data?.[collection]) ? app.data[collection] : [];
  const record = (collection, id) => list(collection).find(item => String(item.id) === String(id));
  const projectName = id => record('projects', id)?.name || (id ? '未关联项目' : '未关联项目');
  const workspaceName = () => app.workspace === 'personal' ? '个人工作区' : '演示工作区';
  const today = () => { const date = new Date(); return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`; };
  function dateLabel(value, withTime = false) {
    if (!value) return '未设置';
    const date = new Date(String(value).includes('T') || String(value).includes(' ') ? value : `${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + (withTime ? ` ${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '');
  }
  const overdue = task => Boolean(task.due && task.due < today() && task.status !== '完成');
  const number = value => Number.isFinite(Number(value)) && value !== null && value !== '' ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—';
  const percent = value => Number.isFinite(Number(value)) && value !== null && value !== '' ? `${(Number(value) * 100).toFixed(1)}%` : '不可计算';
  const excerpt = (value, max = 120) => { const text = String(value || '').trim(); return text.length > max ? `${text.slice(0, max)}…` : text; };
  const selectedAttr = (value, expected) => String(value ?? '') === String(expected ?? '') ? ' selected' : '';
  const localModelOptions = (mode, current) => {
    const presets = app.boot?.ai?.presets || [];
    const preset = presets.find(item => item.id === (mode === 'deepseek' ? 'deepseek' : 'local'));
    const models = preset?.models || [];
    const fallback = mode === 'deepseek' ? [['deepseek-v4.1-flash', 'DeepSeek V4.1 Flash · 最快最省'], ['deepseek-v4-pro', 'DeepSeek V4 Pro · 重活']] : [['glm-5.2', 'GLM-5.2'], ['kimi-k2.7', 'Kimi K2.7'], ['hy3', 'Hunyuan 3']];
    const items = models.length ? models.map(item => [item.id, item.name]) : fallback;
    return items.map(([id, name]) => `<option value="${esc(id)}"${selectedAttr(id, current)}>${esc(name)}</option>`).join('');
  };
  const dshModelOptions = current => (app.boot?.dsh?.models || []).map(item => `<option value="${esc(item.id)}"${selectedAttr(item.id, current)}>${esc(item.name)}</option>`).join('');
  function researchModelStatus(state) {
    if (state.askMode === 'dsh') return banner('ChatGPT', app.boot?.dsh?.available ? `当前模型：${(app.boot.dsh.models || []).find(item => item.id === state.dshModel)?.name || 'GPT-6 Luna'}。提交后使用已选材料。` : '未检测到模型连接，请到设置连接后重试。', app.boot?.dsh?.available ? 'blue' : 'amber', 'external');
    const preset = (app.boot?.ai?.presets || []).find(item => item.id === (state.askMode === 'deepseek' ? 'deepseek' : 'local'));
    const fallback = state.askMode === 'deepseek' ? [{id:'deepseek-v4.1-flash',name:'DeepSeek V4.1 Flash'},{id:'deepseek-v4-pro',name:'DeepSeek V4 Pro'}] : [{id:'glm-5.2',name:'GLM-5.2'},{id:'kimi-k2.7',name:'Kimi K2.7'},{id:'hy3',name:'Hunyuan 3'}];
    const models = preset?.models?.length ? preset.models : fallback;
    const model = models.find(item => item.id === state.localModel) || models[0];
    return banner(state.askMode === 'deepseek' ? 'DeepSeek' : 'GLM / Kimi / 混元', `当前模型：${model?.name || '已选模型'}。连接不可用时会保留你的输入，便于重试。`, 'blue', 'external');
  }
  const options = (values, selected) => values.map(value => `<option value="${esc(value)}"${selectedAttr(value, selected)}>${esc(value)}</option>`).join('');
  const projectOptions = selected => `<option value="">不关联项目</option>${list('projects').map(item => `<option value="${esc(item.id)}"${selectedAttr(item.id, selected)}>${esc(item.name)}</option>`).join('')}`;
  const projectFilter = (id, selected, label = '全部项目', allowCreate = false, disabled = false) => `<select id="${esc(id)}" class="compact-select" aria-label="${allowCreate?'关联项目':'按项目筛选'}" ${disabled?'disabled':''}><option value="">${esc(label)}</option>${list('projects').map(item => `<option value="${esc(item.id)}"${selectedAttr(item.id, selected)}>${esc(item.name)}</option>`).join('')}${allowCreate?`<option value="${CREATE_PROJECT_VALUE}">＋ 新建项目…</option>`:''}</select>`;
  const badge = (value, tone) => `<span class="tag ${tone || ({ 高: 'red', 中: 'amber', 低: 'gray', 待核实: 'amber', 已核实: 'green', 暂不采用: 'gray', 尽调: 'green', 初筛: 'blue', 投委会: 'amber', 归档: 'gray', 完成: 'green', 进行中: 'blue' }[value] || '')}">${esc(value)}</span>`;
  const actionButton = (label, action, symbol = '', classes = '', attrs = '') => `<button type="button" class="button ${classes}" data-action="${esc(action)}" ${attrs}>${symbol ? icon(symbol) : ''}${esc(label)}</button>`;
  const iconButton = (label, action, symbol, attrs = '', classes = '') => `<button type="button" class="icon-button ${classes}" title="${esc(label)}" aria-label="${esc(label)}" data-action="${esc(action)}" ${attrs}>${icon(symbol)}</button>`;
  const empty = (symbol, title, text, button = '', compact = false) => `<div class="empty${compact ? ' compact' : ''}"><span class="empty-icon">${icon(symbol)}</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${button}</div>`;
  const heading = (title, eyebrow, description, actions = '') => `<div class="page-heading"><div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1><p>${esc(description)}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
  const banner = (title, message, tone = '', symbol = 'shield') => `<div class="banner ${tone}">${icon(symbol)}<div>${title ? `<strong>${esc(title)}</strong>` : ''}${esc(message)}</div></div>`;
  const panelTitle = (title, symbol, action = '') => `<div class="panel-header"><div class="panel-title">${icon(symbol)}<h2>${esc(title)}</h2></div>${action}</div>`;
  const searchInput = (id, placeholder, value) => `<div class="input-search">${icon('search')}<input id="${esc(id)}" type="search" placeholder="${esc(placeholder)}" aria-label="${esc(placeholder)}" value="${esc(value)}" autocomplete="off"></div>`;
  const loading = text => `<div class="inline-loading"><span class="spinner"></span>${esc(text)}</div>`;
  const inputField = (name, label, value = '', opts = {}) => `<div class="field"><label for="field-${esc(name)}">${esc(label)}${opts.required ? '' : '<span class="optional">选填</span>'}</label><input id="field-${esc(name)}" name="${esc(name)}" type="${opts.type || 'text'}" value="${esc(value)}" ${opts.required ? 'required' : ''} maxlength="${opts.maxlength || 500}" ${opts.placeholder ? `placeholder="${esc(opts.placeholder)}"` : ''}>${opts.hint ? `<span class="hint">${esc(opts.hint)}</span>` : ''}</div>`;
  const textareaField = (name, label, value = '', opts = {}) => `<div class="field"><label for="field-${esc(name)}">${esc(label)}${opts.required ? '' : '<span class="optional">选填</span>'}</label><textarea id="field-${esc(name)}" name="${esc(name)}" rows="${opts.rows || 4}" ${opts.required ? 'required' : ''} maxlength="${opts.maxlength || 1000000}" placeholder="${esc(opts.placeholder || '')}">${esc(value)}</textarea>${opts.hint ? `<span class="hint">${esc(opts.hint)}</span>` : ''}</div>`;
  const selectField = (name, label, content) => `<div class="field"><label for="field-${esc(name)}">${esc(label)}</label><select id="field-${esc(name)}" name="${esc(name)}">${content}</select></div>`;
  const projectField = value => selectField('project_id', '关联项目', projectOptions(value));
  const materialCollections = ['documents', 'notes', 'meetings', 'deliverables', 'tasks'];
  const taskGroup = item => String(item.task_group || '项目资料');
  const projectRecords = projectId => materialCollections.flatMap(collection => list(collection).filter(item => String(item.project_id) === String(projectId)).map(item => ({ ...item, collection })));
  const projectGroups = projectId => [...new Set(projectRecords(projectId).map(taskGroup))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
  const groupFilter = (id, selected, projectId) => `<select id="${esc(id)}" class="compact-select" aria-label="按子任务筛选"><option value="">全部子任务</option>${options(projectGroups(projectId), selected)}</select>`;
  function organizationField(item, preset) {
    const selected = Object.prototype.hasOwnProperty.call(preset, 'task_group') ? preset.task_group : item.task_group_source === 'manual' ? item.task_group : '';
    const groups = projectGroups(item.project_id);
    if (selected && !groups.includes(selected)) groups.push(selected);
    return `<div class="field"><label for="field-task_group">归入子任务<span class="optional">选填</span></label><select id="field-task_group" name="task_group"><option value="">自动整理</option>${options(groups, selected)}</select><span class="hint">留空会自动判断子任务、材料类型及版本关系${item.task_group && !selected ? `；当前归入「${esc(item.task_group)}」` : ''}。</span></div>`;
  }
  const hasOriginal = doc => !!(doc.attachment_ref && doc.attachment_name && doc.attachment_hash);
  const workflowInfo = key => app.workflows.find(item => item.key === key);
  const workflowOptions = key => app.workflows.map(item => `<option value="${esc(item.key)}"${selectedAttr(item.key,key)}>${esc(item.title)}</option>`).join('');
  const deliverableKindOptions = selected => options([...new Set([...KINDS, ...app.workflows.map(item=>item.kind), selected].filter(Boolean))], selected);

  class StaleRequestError extends Error { constructor() { super('工作区已切换'); this.name = 'StaleRequestError'; } }
  async function api(path, options = {}) {
    const epoch = app.epoch;
    const headers = { 'X-Workspace': app.workspace, 'X-CSRF-Token': app.csrf, ...(options.headers || {}) };
    const method = options.method || (options.body !== undefined ? 'POST' : 'GET');
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (method !== 'GET') app.mutations++;
    try {
      const response = await fetch(path.startsWith('/auth/') ? path : `/api${path}`, { method, headers, cache: 'no-store', credentials: 'same-origin', ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}), ...(options.signal ? { signal: options.signal } : {}) });
      if (epoch !== app.epoch) throw new StaleRequestError();
      if (!response.ok) {
        let message = `请求失败（${response.status}）`;
        try { const error = await response.json(); if (error.error) message = String(error.error); } catch { /* HTTP status remains useful when the server cannot return JSON. */ }
        throw new Error(message);
      }
      if (options.raw) return response;
      if (response.status === 204) return {};
      const result = await response.json();
      if (epoch !== app.epoch) throw new StaleRequestError();
      return result;
    } catch (error) {
      if (error instanceof TypeError && /fetch|network|failed/i.test(error.message)) throw new Error('无法连接本地服务。请确认 Local WorkOS 启动器仍在运行，然后重试。');
      throw error;
    } finally { if (method !== 'GET') app.mutations--; }
  }
  function notify(message, error = false) {
    const element = document.createElement('div'); element.className = `toast${error ? ' error' : ''}`;
    element.innerHTML = `${icon(error ? 'warning' : 'circleCheck')}<span>${esc(message)}</span><button type="button" aria-label="关闭提示">${icon('close')}</button>`;
    $('button', element).onclick = () => element.remove(); const region=$('#toast-region');region.append(element);while(region.children.length>2)region.firstElementChild.remove();
    setTimeout(() => element.remove(), error ? 10000 : 3000);
  }
  function showError(error) { if (error?.name !== 'StaleRequestError' && error?.name !== 'AbortError') notify(error?.message || '操作未完成，请重试。', true); }
  async function withBusy(button, label, action) {
    if (button?.disabled) return;
    const original = button?.innerHTML;
    if (button) { button.disabled = true; button.innerHTML = `<span class="spinner"></span>${esc(label)}`; }
    try { return await action(); } catch (error) { showError(error); }
    finally { if (button?.isConnected) { button.disabled = false; button.innerHTML = original; } }
  }
  async function refreshData() {
    const [data, sync] = await Promise.all([api('/state'), api('/sync/status')]);
    app.data = data; if (app.boot) app.boot.sync = sync;
    const available = new Set(list('documents').map(item => String(item.id)));
    view().selectedSources = new Set([...view().selectedSources].filter(id => available.has(String(id))));
    return data;
  }
  async function boot() {
    app.stopped = false; $('#main').setAttribute('aria-busy', 'true');
    try {
      app.boot = await api('/bootstrap');
      app.csrf = app.boot.csrf;
      if (!app.boot.dsh?.available && view().askMode === 'dsh') view().askMode = 'local';
      if (!app.csrf) throw new Error('本地服务未返回安全令牌，请重启服务后重试。');
      await refreshData();
      const catalog = await api('/workflows'); app.workflows = Array.isArray(catalog.workflows) ? catalog.workflows : [];
      await restoreWorkflowJobs();
      const hash = location.hash.slice(1);
      app.page = ROUTES.some(route => route[0] === hash) ? hash : view().page;
      if(app.page==='projects')app.page='overview';
      view().page = app.page; render();
      $('#connection-label').innerHTML = '<span class="status-dot"></span>本地连接';
    } catch (error) {
      if (error.name === 'StaleRequestError') return;
      renderShell();
      $('#main').innerHTML = `<section class="state-error"><div class="eyebrow">LOCAL CONNECTION</div><h1>还没有连接到本地工作空间</h1><p>${esc(error.message)}</p>${actionButton('重新连接', 'retry', 'refresh', 'primary')}</section>`;
      $('#connection-label').textContent = '连接中断';
    } finally { $('#main').setAttribute('aria-busy', 'false'); }
  }
  function renderShell() {
    const route = ROUTES.find(item => item[0] === app.page) || ROUTES[0];
    document.title = `${route[1]} · Local WorkOS`;
    const counts = { projects: list('projects').filter(item => item.stage !== '归档').length, tasks: list('tasks').filter(item => item.status !== '完成').length, deliverables: list('deliverables').length };
    $('#primary-nav').innerHTML = ROUTES.filter(item => !['settings','tasks','projects'].includes(item[0])).map(([id, title, , symbol]) => `<button type="button" class="nav-item${app.page === id ? ' active' : ''}" data-page="${id}"${app.page === id ? ' aria-current="page"' : ''}>${icon(symbol)}<span>${title}</span>${counts[id] ? `<span class="nav-count">${counts[id]}</span>` : ''}</button>`).join('');
    $('#settings-nav').className = `nav-item settings-nav${app.page === 'settings' ? ' active' : ''}`;
    $('#settings-nav').innerHTML = `${icon('settings')}<span>设置与连接</span>`;
    if (app.page === 'settings') $('#settings-nav').setAttribute('aria-current', 'page'); else $('#settings-nav').removeAttribute('aria-current');
    $('#workspace-switch').innerHTML = `<span class="workspace-icon">${icon(app.workspace === 'personal' ? 'user' : 'briefcase')}</span><span class="workspace-copy">${workspaceName()}<small>${app.workspace === 'personal' ? 'PERSONAL · 仅自己可见' : 'DEMO · 全部为合成数据'}</small></span>${icon('down')}`;
    $('#breadcrumb').innerHTML = `<span>${workspaceName()}</span><span class="slash">/</span><span class="current">${route[1]}</span>`;
    $('#footer-workspace').textContent = `${workspaceName()} · ${app.workspace === 'demo' ? '合成演示数据' : '本地存储'}`;
    $('#version-label').textContent = app.boot?.version ? `v${String(app.boot.version).replace(/^v/, '')}` : 'v1.4';
  }
  function render() {
    renderShell();
    if (!app.data) return;
    const renderers = { overview: renderOverview, projects: renderOverview, tasks: renderTasks, research: renderResearch, meetings: renderMeetings, memory: renderMemory, finance: renderFinance, deliverables: renderDeliverables, settings: renderSettings };
    $('#main').innerHTML = renderers[app.page]();
    $('#main').setAttribute('aria-busy', 'false');
    bindPage();
  }
  function closeSidebar() { $('#sidebar').classList.remove('open'); $('#sidebar-scrim').hidden = true; $('#mobile-menu').setAttribute('aria-expanded', 'false'); }
  async function canLeave() {
    if (view().deliverableSaving) { notify('交付正在保存，请稍候。'); return false; }
    if (view().deliverableDirty) return confirmDialog('放弃尚未保存的交付修改？', '页面中的修改尚未写入本地。你可以取消并先保存，或放弃修改后继续。', '放弃修改', true);
    return true;
  }
  async function navigate(page, opts = {}) {
    if(page==='projects')page='overview';
    if (!ROUTES.some(route => route[0] === page)) return false;
    if (page !== app.page && !await canLeave()) return false;
    if (page === app.page && page === 'deliverables' && view().deliverableDirty) { closeSidebar(); return true; }
    if (app.page === 'meetings') captureMeetingDraft();
    if (page !== app.page) { view().deliverableDirty = false; $$('#toast-region .toast:not(.error)').forEach(item => item.remove()); }
    app.page = page; view().page = page;
    if (opts.projectId !== undefined) {
      if (page === 'overview') { if(String(view().projectId)!==String(opts.projectId)){view().libraryGroup='';view().libraryQuery='';}view().projectId = opts.projectId; }
      if (page === 'tasks') view().taskProject = opts.projectId;
      if (page === 'research') { if(String(view().researchProject)!==String(opts.projectId)){view().selectedSources.clear();view().sourceGroup='';}view().researchProject=opts.projectId; }
      if (page === 'meetings') view().meetingProject = opts.projectId;
    }
    history.replaceState(null, '', `#${page}`); closeSidebar(); render();
    $('#main').focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: 'instant' });
    return true;
  }
  async function switchWorkspace(next) {
    if (!['personal', 'demo'].includes(next) || next === app.workspace) return;
    if (app.mutations || app.uploadBusy) { notify('当前操作尚未完成，请稍后切换工作区。', true); return; }
    if (!await canLeave()) return;
    if (app.page === 'meetings') captureMeetingDraft();
    view().deliverableDirty = false;
    if (app.page === 'settings') $('#ai-settings-form')?.reset();
    $$('dialog[open]').forEach(dialog => dialog.close());
    clearTimeout(workflowPollTimer); workflowPollTimer = null;
    app.workspace = next; app.epoch++; app.csrf = ''; app.data = null; app.boot = null;
    app.page = view().page; history.replaceState(null, '', `#${app.page}`);
    closeSidebar(); renderShell(); $('#main').innerHTML = loading(`正在切换到${workspaceName()}…`);
    await boot();
    if (app.data) notify(`已切换到${workspaceName()}，两套数据独立保存。`);
  }

  // Accessible native dialogs, including inline validation and destructive confirmations.
  function openModal(title, body, onSubmit, options = {}) {
    const dialog = $('#modal');
    if (dialog.open) dialog.close();
    dialog.returnValue = '';
    dialog.className = `modal${options.wide ? ' wide' : ''}`;
    dialog.innerHTML = `<form id="modal-form"><div class="modal-header"><h2 id="modal-title">${esc(title)}</h2><button type="button" class="icon-button" data-close-dialog="modal" aria-label="关闭">${icon('close')}</button></div><div class="modal-content"><div id="modal-error" class="form-error" role="alert"></div>${body}</div><div class="modal-footer">${options.deleteCollection ? `<button type="button" class="text-button danger-link" data-action="modal-delete" data-collection="${esc(options.deleteCollection)}" data-id="${esc(options.deleteId)}">${icon('trash')}删除</button>` : ''}<button type="button" class="button" data-close-dialog="modal">${esc(options.cancelText || '取消')}</button><button type="submit" class="button ${options.danger ? 'danger solid' : 'primary'}" id="modal-submit">${esc(options.submitText || '保存')}</button></div></form>`;
    $('#modal-form').onsubmit = async event => {
      event.preventDefault();
      if (app.modalBusy || !event.currentTarget.reportValidity()) return;
      const formData = new FormData(event.currentTarget);
      const submit = $('#modal-submit'); const html = submit.innerHTML;
      const controls = $$('input,select,textarea,button', dialog).filter(element => !element.disabled);
      app.modalBusy = true; controls.forEach(element => { element.disabled = true; });
      submit.innerHTML = `<span class="spinner"></span>${esc(options.busyText || '正在保存…')}`; $('#modal-error').textContent = '';
      try { await onSubmit(formData, event.currentTarget); app.modalBusy = false; dialog.close('saved'); }
      catch (error) { if (error.name !== 'StaleRequestError') { $('#modal-error').textContent = error.message || '操作未完成。'; $('#modal-error').scrollIntoView({ block: 'nearest' }); } }
      finally { app.modalBusy = false; controls.forEach(element => { element.disabled = false; }); if (submit.isConnected) submit.innerHTML = html; }
    };
    dialog.showModal();
    return dialog;
  }
  function confirmDialog(title, message, label = '确认', danger = false) {
    return new Promise(resolve => {
      // A separate native dialog avoids reusing an editor whose close event is queued.
      const dialog = document.createElement('dialog'); dialog.className = 'modal';
      dialog.setAttribute('aria-label', title);
      dialog.innerHTML = `<form method="dialog"><div class="modal-header"><h2>${esc(title)}</h2><button type="submit" value="cancel" class="icon-button" aria-label="取消">${icon('close')}</button></div><div class="modal-content"><p class="confirm-copy">${esc(message)}</p></div><div class="modal-footer"><button type="submit" value="cancel" class="button" autofocus>取消</button><button type="submit" value="confirm" class="button ${danger ? 'danger solid' : 'primary'}">${esc(label)}</button></div></form>`;
      dialog.addEventListener('close', () => { const confirmed = dialog.returnValue === 'confirm'; dialog.remove(); resolve(confirmed); }, { once: true });
      document.body.append(dialog); dialog.showModal();
    });
  }
  function workspaceDialog() {
    let next = app.workspace;
    const dialog = openModal('选择工作区', `<div class="banner mb-15">${icon('database')}<div>个人与演示使用独立本地数据库。切换不会复制、合并或向外发送数据。</div></div><div class="field"><label for="workspace-choice">工作区</label><select name="workspace" id="workspace-choice">${options(['personal', 'demo'], app.workspace).replace('>personal<', '>个人工作区 · 我的工作<').replace('>demo<', '>演示工作区 · 合成示例<')}</select></div>`, async form => {
      next = String(form.get('workspace'));
    }, { submitText: '切换工作区', busyText: '正在切换…' });
    dialog.addEventListener('close', () => { if (dialog.returnValue === 'saved') switchWorkspace(next).catch(showError); }, { once: true });
  }

  // Persistent core records share one CRUD implementation and one source of truth.
  async function editRecord(collection, id = '', preset = {}, context = {}) {
    if (!(collection in LABELS)) return;
    let existing = id ? record(collection, id) : null;
    if (id && !existing) { notify('这条记录已不存在，请刷新后重试。', true); return; }
    if (collection === 'documents' && id) {
      existing = await api(`/documents/${encodeURIComponent(id)}`);
      if (existing.kind === 'memory') { await openDocument(id); return; }
    }
    if (view().deliverableDirty) {
      if (!await canLeave()) return;
      view().deliverableDirty = false; render();
    }
    if (app.page === 'meetings') captureMeetingDraft();
    const item = { ...(existing || {}), ...preset };
    let body = '';
    if (collection === 'projects') {
      body = inputField('name', '项目名称', item.name, { required: true, placeholder: '输入公司或项目名称', maxlength: 200 }) + '<div class="field-row">' + inputField('sector', '行业 / 赛道', item.sector, { placeholder: '例如：企业服务' }) + inputField('owner', '负责人', item.owner) + '</div><div class="field-row">' + selectField('stage', '推进阶段', options(STAGES, item.stage || '线索')) + selectField('priority', '优先级', options(PRIORITIES, item.priority || '中')) + '</div>' + textareaField('thesis', '投资逻辑 / 核心判断', item.thesis, { rows: 4 }) + textareaField('next_step', '下一步行动', item.next_step, { rows: 2 }) + '<div class="field-row">' + inputField('valuation', '估值备注', item.valuation) + inputField('tags', '标签', item.tags, { hint: '多个标签以逗号分隔' }) + '</div>';
    } else if (collection === 'tasks') {
      body = inputField('title', '任务标题', item.title, { required: true, maxlength: 300 }) + projectField(item.project_id) + '<div class="field-row">' + selectField('status', '状态', options(STATUSES, item.status || '待办')) + selectField('priority', '优先级', options(PRIORITIES, item.priority || '中')) + '</div><div class="field-row">' + inputField('owner', '负责人', item.owner) + inputField('due', '到期日期', item.due, { type: 'date' }) + '</div>' + textareaField('description', '任务说明', item.description, { rows: 4 }) + (item.meeting_id ? banner('来自会议', record('meetings', item.meeting_id)?.title || '已关联会议', '', 'meetings') + '<div class="mb-15"></div>' : '');
    } else if (collection === 'documents') {
      body = inputField('title', '资料标题', item.title, { required: true, maxlength: 300 }) + projectField(item.project_id) + inputField('category', '分类', item.category, { placeholder: '例如：行业研究、访谈、公开资料' }) + textareaField('content', '原文内容', item.content, { required: true, rows: 12, hint: '按纯文本保存；段落用于本地检索与引用定位。修改会重新分段。' }) + inputField('source_ref', '来源备注', item.source_ref, { placeholder: '可记录文件路径或来源说明；不会自动访问' });
    } else if (collection === 'meetings') {
      body = inputField('title', '会议标题', item.title, { required: true, maxlength: 300 }) + projectField(item.project_id) + '<div class="field-row">' + inputField('date', '会议日期', item.date || today(), { type: 'date', required: true }) + inputField('participants', '参会人', item.participants, { placeholder: '用逗号分隔' }) + '</div>' + textareaField('transcript', '逐字稿 / 会议原文', item.transcript, { rows: 10, placeholder: '粘贴逐字稿。保存后可生成规则摘要与待确认行动项。' }) + textareaField('summary', '会议纪要', item.summary, { rows: 5, placeholder: '可直接编辑，也可保存后使用规则引擎生成草稿。' });
    } else if (collection === 'notes') {
      body = inputField('title', '结论标题', item.title, { required: true, maxlength: 300 }) + '<div class="field-row">' + projectField(item.project_id) + selectField('status', '核实状态', options(NOTE_STATUSES, item.status || '待核实')) + '</div>' + textareaField('body', '研究结论', item.body, { required: true, rows: 8 }) + selectField('document_id', '关联证据材料', `<option value="">暂不关联</option>${list('documents').map(doc => `<option value="${esc(doc.id)}"${selectedAttr(doc.id, item.document_id)}>${esc(doc.title)}</option>`).join('')}`) + textareaField('source_quote', '原文引用 / 证据线索', item.source_quote, { rows: 3 });
    } else if (collection === 'deliverables') {
      body = inputField('title', '交付标题', item.title, { required: true, maxlength: 300 }) + '<div class="field-row">' + projectField(item.project_id) + selectField('kind', '交付类型', deliverableKindOptions(item.kind || '自定义')) + '</div>' + textareaField('body', '正文', item.body, { rows: 12, placeholder: '使用纯文本或 Markdown 编写。保存后可继续编辑、导出。' });
    }
    if (collection !== 'projects') body += organizationField(item, preset);
    if (collection === 'projects' && context.quickProject) {
      const detailsAt = body.indexOf('<div class="field-row">');
      body = body.slice(0, detailsAt) + '<p class="inline-note">填写名称即可创建，其他资料可以以后补充。</p><details class="project-create-details"><summary>更多项目资料（选填）</summary>' + body.slice(detailsAt) + '</details>';
    }
    const dialog = openModal(`${id ? '编辑' : '新建'}${LABELS[collection]}`, body, async form => {
      const payload = Object.fromEntries(form.entries());
      for (const key of Object.keys(payload)) payload[key] = String(payload[key]).trim();
      if (collection === 'documents' && !id) { payload.kind = 'research'; payload.private = true; }
      if (collection === 'tasks' && item.meeting_id) payload.meeting_id = item.meeting_id;
      const saved = await api(`/${collection}${id ? `/${encodeURIComponent(id)}` : ''}`, { method: id ? 'PATCH' : 'POST', body: payload });
      if (collection === 'documents' || collection === 'projects') view().workflowRequest = null;
      const savedId = saved.id || id;
      if (collection === 'projects') view().projectId = savedId;
      if (collection === 'meetings') { view().meetingId = savedId; view().drafts.delete(String(savedId)); }
      if (collection === 'deliverables') { view().deliverableId = savedId; view().deliverableDirty = false; }
      if (context.onSaved) context.onSaved(saved);
      await refreshData(); render(); notify(`${LABELS[collection]}已${id ? '更新' : '保存'}到${workspaceName()}。`);
    }, { wide: ['documents', 'meetings', 'deliverables'].includes(collection), ...(context.quickProject?{submitText:'创建并使用'}:{}), ...(id ? { deleteCollection: collection, deleteId: id } : {}) });
    if (collection !== 'projects') $('#field-project_id')?.addEventListener('change', event => {
      const select = $('#field-task_group'); if (!select) return;
      const groups = projectGroups(event.target.value), selected = groups.includes(select.value) ? select.value : '';
      select.innerHTML = '<option value="">自动整理</option>' + options(groups, selected);
    });
    if (context.quickProject) $('#field-name')?.focus();
    return dialog;
  }
  async function createStartProject() {
    const state = view(); if(state.startBusy || app.uploadBusy || app.modalBusy)return;
    state.startMessage = $('#start-input')?.value ?? state.startMessage;
    state.startPurpose = $('#start-purpose')?.value ?? state.startPurpose;
    const select = $('#start-project'); if(select)select.value=state.startProject;
    const dialog = await editRecord('projects', '', {}, {quickProject:true,onSaved:saved=>{state.startProject=String(saved.id);}});
    dialog?.addEventListener('close',()=>{if(view()===state && app.page==='overview')$('#start-input')?.focus();},{once:true});
  }
  async function deleteRecord(collection, id) {
    const item = record(collection, id);
    if (!item || !(collection in LABELS)) return;
    const name = item.title || item.name;
    const message = collection === 'projects' ? `确定删除“${name}”？有任务、资料、会议或交付关联的项目不能直接删除，请先解除关联。` : collection === 'documents' && item.kind === 'memory' ? `确定移除“${name}”的导入副本？只删除此工作区中的记录，不改动任何源记忆文件。` : `确定删除“${name}”？此操作无法直接撤销，可先在设置中导出备份。`;
    if (!await confirmDialog(`删除${LABELS[collection]}`, message, '确认删除', true)) return;
    await api(`/${collection}/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (collection === 'deliverables' && String(view().deliverableId) === String(id)) { view().deliverableId = ''; view().deliverableDirty = false; }
    if (collection === 'meetings') view().drafts.delete(String(id));
    await refreshData(); render(); notify(`${LABELS[collection]}已删除。`);
  }

  // PAGES
  // AI-native command bar: one free-text box; the model picks the tools, code executes them.
  function renderAgentResult() {
    const state=view(); if(!state.agentAnswer&&!state.agentSteps.length)return '';
    if(state.researchProject && state.agentResultProject && String(state.agentResultProject)!==String(state.researchProject))return '';
    return `<section class="panel agent-result">${panelTitle('工作区操作结果','spark',`<span class="small muted">${esc(state.agentResultProject ? projectName(state.agentResultProject) : '全工作区')}</span>`)}${state.agentAnswer?`<div class="agent-answer markdown-body">${readable(state.agentAnswer)}</div>`:''}${state.agentSteps.length?`<details class="agent-steps"><summary>已执行 ${state.agentSteps.length} 项操作 · 查看记录</summary>${state.agentSteps.map(step=>`<div class="agent-step"><span class="tag green">${esc(step.action)}</span><span>${esc(step.say||'')}</span><code>${esc(JSON.stringify(step.result ?? {}).slice(0,180))}</code></div>`).join('')}</details>`:''}</section>`;
  }

  async function runAgent(messageOverride) {
    const state = view(); if (state.agentBusy||state.asking||state.workflowBusy) return;
    const message = (typeof messageOverride==='string'?messageOverride:($('#agent-input')?.value||'')).trim(); state.agentMessage = message;
    if (!message) { notify('先说一句你要做什么。', true); return; }
    const model = $('#agent-model')?.value || state.localModel || 'deepseek-v4.1-flash';
    const projectId = state.agentProjectScope ? (state.researchProject || '') : '';
    const history = state.agentHistoryByScope.get(projectId) || [];
    state.agentBusy = true; state.agentSteps = []; state.agentAnswer = ''; render();
    try {
      const result = await api('/agent', { body: { message, model_id: model, project_id: projectId, history } });
      state.agentSteps = Array.isArray(result.steps) ? result.steps : [];
      state.agentAnswer = result.answer || '';
      state.agentResultProject = projectId;
      state.agentHistoryByScope.set(projectId, [...history, { role: 'user', content: message }, { role: 'assistant', content: result.answer || '' }].slice(-8));
      state.agentMessage = '';
      if (state.agentSteps.length) await refreshData();
    } catch (error) { if (error.name !== 'StaleRequestError') { state.agentAnswer = ''; showError(error); } }
    finally { state.agentBusy = false; if (view() === state) render(); }
  }
  async function startWork(purposeOverride) {
    const state = view(); if(state.startBusy || app.uploadBusy)return;
    const purpose = typeof purposeOverride === 'string' ? purposeOverride : ($('#start-purpose')?.value || state.startPurpose);
    const message = ($('#start-input')?.value || state.startMessage || '').trim(); state.startMessage = message;
    const projectId = $('#start-project')?.value ?? state.startProject; state.startProject=projectId;
    if(!message && !purpose){notify('用一句话说说你要完成什么，或选择一项工作。',true);return;}
    state.startBusy=true;render();
    try {
      const recipe=workflowInfo(purpose);
      const plan=recipe?{workflow_key:recipe.key,route:'research',question:message||recipe.description,label:recipe.title}:await api('/workflows/plan',{body:{message}});
      const question=plan.question||message, route=plan.route;
      if(route==='finance'||route==='model'){
        if(state.valuationPending){notify('当前模型还在处理，请稍后再准备新的模型。',true);return;}
        state.valuationText=question;state.valuationProjectId=projectId;state.valuationProposal=null;state.valuationJson='';state.valuationResult=null;state.valuationError='';state.valuationScenarioResult=null;state.valuationScenariosJson='';
        state.valuationMethod=/\blbo\b|杠杆收购/i.test(question)?'lbo':/\bdcf\b|现金流折现/i.test(question)?'dcf':/p\s*\/\s*s|市销率/i.test(question)?'ps':'net_income';
        if(await navigate('finance'))notify('已带入建模需求。确认方法和假设后即可计算并保存模型。');return;
      }
      if(route==='meetings'||route==='meeting'){
        if(!await navigate('meetings',{projectId}))return;
        await editRecord('meetings','',{project_id:projectId,title:'',transcript:''});
        const field=$('#field-transcript');if(field)field.placeholder='本次需求：'+question+'\n\n请粘贴这一次会议的逐字稿。';
        return;
      }
      if(route==='overview'||route==='projects'||route==='organize'){
        if(!projectId){notify('先选择要整理的项目，再继续。',true);return;}
        await navigate('overview',{projectId});requestAnimationFrame(()=>$('#project-detail')?.scrollIntoView({block:'nearest'}));notify('项目材料已按子任务与版本展示；新材料会自动整理。');return;
      }
      if(!await navigate('research',{projectId}))return;
      state.sourceGroup='';state.sourceQuery='';state.selectedSources=new Set([...state.startSourceIds].filter(id=>{const doc=record('documents',id);return doc&&(!projectId||String(doc.project_id)===String(projectId));}));
      const selected=workflowInfo(plan.workflow_key);
      state.researchIntent=selected?'workflow':'ask';
      if(selected){state.workflowKey=selected.key;state.workflowQuality='';state.workflowMessage=question;state.workflowError='';if(state.askMode==='local')state.askMode='deepseek';}else state.question=question;
      render();requestAnimationFrame(()=>$('#question-input')?.focus());
      notify(selected?.requires_sources?'已准备工作要求，请选择材料后生成草稿。':'已准备工作要求，确认后生成并保存草稿。');
    }catch(error){showError(error);}
    finally{state.startBusy=false;if(view()===state && app.page==='overview')render();}
  }
  async function runWorkflow() {
    const state=view();if(state.workflowBusy||state.asking||state.agentBusy)return;
    const recipe=workflowInfo(state.workflowKey);if(!recipe){notify('这项工作暂时不可用，请刷新页面。',true);return;}
    const message=($('#question-input')?.value||'').trim();state.workflowMessage=message;
    if(!message){notify('先描述你要交付的内容。',true);return;}
    const ids=[...state.selectedSources].sort();
    if(recipe.requires_sources&&!ids.length){notify('请先明确选中本次使用的材料。',true);return;}
    const mode=$('#ask-mode')?.value||state.askMode;
    if(mode==='local'){notify('交付草稿需要可用模型，请先选择模型；本地检索不会发送资料。',true);return;}
    if(ids.some(id=>record('documents',id)?.kind==='memory')){notify('个人记忆只用于本地检索，请取消记忆材料或切换到问资料。',true);return;}
    const modelId=mode==='dsh'?($('#dsh-model')?.value||state.dshModel):($('#local-model')?.value||state.localModel);
    const projectId=state.researchProject||'';
    const payload={workflow_key:recipe.key,message,project_id:projectId,document_ids:ids,mode,model_id:modelId,quality_mode:workflowQuality(state)};
    const signature=JSON.stringify([payload,ids.map(id=>record('documents',id)?.updated_at||''),record('projects',projectId)?.updated_at||'']);
    if(state.workflowRequest?.signature!==signature)state.workflowRequest={signature,id:crypto.randomUUID()};
    payload.request_id=state.workflowRequest.id;
    state.workflowBusy=true;state.workflowError='';render();
    try{
      const response=await api('/workflows/jobs',{body:payload});
      if(!response.job?.id)throw new Error('任务尚未登记，请重试。');
      await acceptWorkflowJobs([response.job]);
      if(response.job.status!=='completed')notify(['failed','interrupted'].includes(response.job.status)?'这项任务未完成，可在进度卡查看原因并重试。':'任务已登记，可继续工作；进度会自动更新。');
    }catch(error){if(error.name!=='StaleRequestError')state.workflowError=error.message;showError(error);}
    finally{state.workflowBusy=false;if(view()===state){if(app.page==='research')render();scheduleWorkflowPoll();}}
  }
  function workflowQuality(state=view()) {
    const recipe=workflowInfo(state.workflowKey);
    return state.workflowQuality || recipe?.default_quality || (['dd','ic','discussion','legal','technology','compare','model_review'].includes(state.workflowKey)?'thorough':'fast');
  }
  const activeWorkflowJob = job => ['queued','running'].includes(job.status);
  function workflowModelLabel(job) {
    if(job.mode==='dsh')return (app.boot?.dsh?.models||[]).find(item=>item.id===job.model_id)?.name||'ChatGPT';
    const models=(app.boot?.ai?.presets||[]).flatMap(item=>item.models||[]);
    return models.find(item=>item.id===job.model_id)?.name||(job.mode==='deepseek'?'DeepSeek':'所选模型');
  }
  function jobElapsed(job) {
    const start=Date.parse(job.created_at), finish=activeWorkflowJob(job)?Date.now():Date.parse(job.updated_at);
    if(!Number.isFinite(start)||!Number.isFinite(finish))return '';
    const seconds=Math.max(0,Math.floor((finish-start)/1000));
    return seconds<60?`${seconds}秒`:`${Math.floor(seconds/60)}分${seconds%60}秒`;
  }
  function renderWorkflowActivity() {
    const state=view(), active=state.workflowJobs.filter(activeWorkflowJob), failed=state.workflowJobs.filter(job=>['failed','interrupted'].includes(job.status));
    if(!active.length&&!failed.length&&!state.workflowJobConnectionError)return '';
    return `<div class="workflow-activity row wrap mt-12">${icon(active.length?'clock':'info')}<span>${active.length?`${active.length} 项工作正在后台整理`:failed.length?`${failed.length} 项工作未完成`:'正在恢复任务连接'}</span>${actionButton('查看进度','workflow-progress','','small ghost')}</div>`;
  }
  function renderWorkflowJobs() {
    const state=view(), jobs=state.workflowJobs.filter(job=>job.status!=='completed'&&(!state.researchProject||String(job.project_id)===String(state.researchProject)));
    const connection=state.workflowJobConnectionError?`<div class="banner amber workflow-reconnect">${icon('warning')}<div><strong>连接暂时中断</strong>任务可能仍在后台运行，将自动重新查询。${actionButton('重新查询','workflow-reconnect','','small ghost')}</div></div>`:'';
    return connection+jobs.map(job=>{
      const failed=['failed','interrupted'].includes(job.status), labels={queued:'等待处理',running:'正在整理',failed:'任务未完成',interrupted:'处理已中断'};
      const stages=Array.isArray(job.stages)?job.stages:[];
      const current=stages.find(stage=>stage.key===job.stage)||stages.find(stage=>stage.status==='running');
      return `<article class="panel workflow-job${failed?' job-failed':''}" data-job-id="${esc(job.id)}" data-job-status="${esc(job.status)}"><div class="row wrap between"><h3>${esc(workflowInfo(job.workflow_key)?.title||'交付草稿')} · ${labels[job.status]||'处理中'}</h3><span class="small muted">${job.quality_mode==='thorough'?'深入整理':'快速草稿'} · ${esc(jobElapsed(job))}</span></div><p class="small muted mt-12">${esc(projectName(job.project_id))} · ${esc(workflowModelLabel(job))} · 提交时选定 ${(job.document_ids||[]).length} 份材料</p><p class="question-history">${esc(job.message)}</p>${!failed?`<div class="job-current">${icon(job.status==='queued'?'clock':'spark')}<span>${esc(current?.label|| (typeof job.stage==='string'?job.stage:'') ||labels[job.status]||'正在处理')}${current?.detail?` · ${esc(current.detail)}`:''}</span></div>`:''}${stages.length?`<ol class="job-stages">${stages.map(stage=>`<li class="stage-${esc(stage.status||'pending')}">${['completed','done','pass'].includes(stage.status)?icon('check'):stage.status==='running'?'<span class="spinner"></span>':icon('clock')}<span>${esc(stage.label||'处理步骤')}</span></li>`).join('')}</ol>`:''}${failed?`<div class="mt-12">${banner(labels[job.status],job.error||'处理未完成，已保存任务范围。','error','warning')}</div>${job.retryable?`<div class="row mt-12">${actionButton('按原任务重试','workflow-job-retry','refresh','soft',`data-id="${esc(job.id)}" ${state.workflowRetryBusy.has(String(job.id))?'disabled':''}`)}<span class="small muted">沿用提交时的要求与材料范围。</span></div>`:''}`:'<p class="small muted mt-12">任务已保存在工作区，可离开页面或继续输入；完成后会显示草稿及检查记录。</p>'}</article>`;
    }).join('');
  }
  function updateWorkflowRegions() {
    const jobs=$('#workflow-jobs'), results=$('#workflow-results'), activity=$('#workflow-activity');
    if(jobs)jobs.innerHTML=renderWorkflowJobs();
    if(results) {
      const current=new Map([...results.children].map(node=>[node.dataset.deliverableId,node]));
      const visible=view().workflowResults.map((result,index)=>({result,index})).filter(item=>!view().researchProject||String(item.result.project_id)===String(view().researchProject));
      let cursor=results.firstElementChild;
      for(const {result,index} of visible) {
        const id=String(result.deliverable.id);let node=current.get(id);
        if(!node){const template=document.createElement('template');template.innerHTML=renderWorkflowResult(result,index);node=template.content.firstElementChild;}
        if(node!==cursor)results.insertBefore(node,cursor);else cursor=cursor.nextElementSibling;
        current.delete(id);
      }
      current.forEach(node=>node.remove());
    }
    if(activity)activity.innerHTML=renderWorkflowActivity();
  }
  async function acceptWorkflowJobs(jobs,{restore=false}={}) {
    const state=view(), byId=new Map(state.workflowJobs.map(job=>[String(job.id),job]));
    let completed=0, refresh=false;
    for(const job of jobs) {
      if(!job?.id)continue;
      const previous=byId.get(String(job.id));
      if(previous&&Number(previous.revision)>Number(job.revision))continue;
      byId.set(String(job.id),job);
      if(job.status==='completed'&&job.result?.deliverable?.id) {
        const result={...job.result,question:job.message,project_id:job.project_id,workflow_key:job.workflow_key,generation_id:job.id,created_at:job.created_at};
        const existing=state.workflowResults.find(item=>String(item.deliverable?.id)===String(result.deliverable.id));
        if(!existing){state.workflowResults.unshift(result);state.workflowResults=state.workflowResults.slice(0,30);}
        if(!record('deliverables',result.deliverable.id))refresh=true;
        if(!state.workflowSeenCompletions.has(String(job.id))) {
          state.workflowSeenCompletions.add(String(job.id));
          if(!restore){completed++;refresh=true;}
        }
      }
    }
    state.workflowJobs=[...byId.values()].sort((a,b)=>String(b.created_at).localeCompare(String(a.created_at))).slice(0,30);
    state.workflowResults.sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')));
    if(refresh){await refreshData();if(view()!==state)return;renderShell();if(completed)notify(`${completed>1?completed+' 份':'新的'}草稿已保存，可打开修改或导出。`);}
    updateWorkflowRegions();
  }
  function scheduleWorkflowPoll(delay) {
    clearTimeout(workflowPollTimer);workflowPollTimer=null;
    if(app.stopped||!app.csrf)return;
    const state=view(), active=state.workflowJobs.filter(activeWorkflowJob);
    if(!active.length&&!state.workflowJobConnectionError)return;
    const interval=delay??(state.workflowPollFailures?Math.min(30000,1500*2**Math.min(state.workflowPollFailures,5)):Math.max(1500,Math.min(12000,Number(active[0]?.poll_after_ms)||1500)));
    workflowPollTimer=setTimeout(pollWorkflowJobs,interval);
  }
  async function restoreWorkflowJobs() {
    const state=view();
    try { const response=await api('/workflows/jobs');state.workflowJobConnectionError='';state.workflowPollFailures=0;await acceptWorkflowJobs(Array.isArray(response.jobs)?response.jobs:[],{restore:true}); }
    catch(error){if(error.name==='StaleRequestError')throw error;state.workflowJobConnectionError=error.message;state.workflowPollFailures++;}
    scheduleWorkflowPoll();
  }
  async function pollWorkflowJobs() {
    const state=view();if(state.workflowPollBusy){scheduleWorkflowPoll();return;}
    state.workflowPollBusy=true;
    try {
      const active=state.workflowJobs.filter(activeWorkflowJob);
      if(!active.length){const response=await api('/workflows/jobs');await acceptWorkflowJobs(response.jobs||[]);}
      else {
        const results=await Promise.allSettled(active.map(job=>api(`/workflows/jobs/${encodeURIComponent(job.id)}`)));
        if(view()!==state)return;
        const snapshots=results.filter(item=>item.status==='fulfilled').map(item=>item.value.job);
        await acceptWorkflowJobs(snapshots);
        const failure=results.find(item=>item.status==='rejected');if(failure)throw failure.reason;
      }
      state.workflowJobConnectionError='';state.workflowPollFailures=0;
    }catch(error){if(error.name!=='StaleRequestError'){state.workflowJobConnectionError=error.message;state.workflowPollFailures++;}}
    finally{state.workflowPollBusy=false;if(view()===state){updateWorkflowRegions();scheduleWorkflowPoll();}}
  }
  async function retryWorkflowJob(id,button) {
    const state=view();if(state.workflowRetryBusy.has(String(id)))return;
    state.workflowRetryBusy.add(String(id));
    try {const response=await api(`/workflows/jobs/${encodeURIComponent(id)}/retry`,{body:{}});if(!response.job?.id)throw new Error('任务尚未重新登记，请重试。');await acceptWorkflowJobs([response.job]);notify('已按原任务重新处理。');}
    catch(error){showError(error);}finally{state.workflowRetryBusy.delete(String(id));if(view()===state){updateWorkflowRegions();scheduleWorkflowPoll();}}
  }
  function staleQualityReport(report) {
    return {...report,stale:true,status:'needs_review',label:'编辑后未重新检查',checks:[],review:{status:'stale'},facts_verified:false};
  }
  function renderQualityReport(report,coverage=[]) {
    if(!report||typeof report!=='object'||!Object.keys(report).length)return '';
    const stale=report.stale||report.review?.status==='stale';
    const checks=!stale&&Array.isArray(report.checks)?report.checks:[], issues=!stale&&Array.isArray(report.review?.issues)?report.review.issues:[];
    const statusLabels={pass:'通过',warn:'需注意',fail:'未通过',not_checked:'未检查'};
    const checkLabels={provider_completion:'模型响应完整性',nonempty:'正文内容',source_labels:'来源标签',cited_source_coverage:'引用范围',honest_coverage:'资料覆盖边界',model_review_scope:'模型审阅边界',requested_table:'表格呈现',table_count:'表格数量',table_rows:'表格行数',table_columns:'表格列数',table_structure:'表格结构',min_chars:'最少字数',max_chars:'篇幅上限',max_words:'英文词数上限',max_lines:'行数上限',question_count:'问题数量',bullet_count:'要点数量',required_section:'必需章节',forbidden_section:'不追加的章节',language:'正文语言',financial_labels:'财务口径标注'};
    const constraintLabels={table_required:'表格要求',table_rows:'表格行数',table_count:'表格数量',table_columns:'表格列数',table_rows_include_header:'行数包含表头',question_count:'问题数量',bullet_count:'要点数量',min_chars:'最少字数',max_chars:'字数上限',max_words:'英文词数上限',max_lines:'行数上限',required_sections:'必需章节',forbidden_sections:'不追加的章节',language:'语言',require_all_sources:'引用全部材料'};
    const text=item=>typeof item==='string'?item:item?.message||item?.detail||item?.label||'';
    const notes=(Array.isArray(report.limitations)?report.limitations:[]).map(text).filter(Boolean);
    if(report.review?.scope)notes.unshift(report.review.scope);
    const constraints=Array.isArray(report.constraints)?report.constraints.map(text):Object.entries(report.constraints||{}).filter(([key])=>constraintLabels[key]).map(([key,value])=>`${constraintLabels[key]}：${Array.isArray(value)?value.join('、'):value===true?'是':value===false?'否':value==='zh'?'中文':value==='en'?'英文':value}`);
    const sources=Array.isArray(coverage)?coverage:[];
    const sourceHtml=sources.length?`<h4>${stale?'生成时的':'本次'}资料覆盖</h4>${sources.map(item=>`<p><strong>${esc(item.title||'选定材料')}</strong> · ${item.truncated?'使用部分原文，需结合完整材料':'使用已导入原文'}${Number.isFinite(item.excerpt_chars)&&Number.isFinite(item.total_chars)?`（${number(item.excerpt_chars)} / ${number(item.total_chars)} 字）`:''}</p>`).join('')}`:'<p>本次没有选定证据材料；请核实概念草稿和用户提供的要点。</p>';
    const checkHtml=checks.length?`<div class="table-scroll"><table><thead><tr><th>检查</th><th>结果</th><th>说明</th></tr></thead><tbody>${checks.map(item=>`<tr><td>${esc(checkLabels[item.id]||item.label||'流程检查')}</td><td>${badge(statusLabels[item.status]||'待检查',item.status==='pass'?'green':item.status==='fail'?'red':'amber')}</td><td>${esc(item.detail||'')}</td></tr>`).join('')}</tbody></table></div>`:'';
    const verdicts={no_obvious_issues:'未发现明显问题，仍需人工判断。',insufficient_evidence:'证据不足，仍需进一步核实。',issues_found:'复核发现需要进一步判断的问题。'};
    const reviewHtml=stale?'<p>正文或来源记录已修改，当前草稿尚未重新检查。生成时的检查不能用于确认编辑后的内容。</p>':report.review?.status==='not_run'?'<h4>复核范围</h4><p>快速草稿未进行独立模型复核。</p>':`<h4>复核意见</h4><p>${esc(report.review?.summary||verdicts[report.review?.verdict]||report.review?.label||'复核状态以保存记录为准；仍需人工判断。')}</p>`;
    const issueHtml=issues.length?`<ul class="review-issues">${issues.map(item=>`<li>${badge({blocking:'需修订',warning:'需核实',info:'审阅线索'}[item.severity]||'需核实',item.severity==='blocking'?'red':'amber')} <strong>${esc(item.criterion||'复核事项')}</strong><p>${esc(item.message||item.explanation||'需进一步核实')}</p>${item.quote?`<blockquote>${esc(item.quote)}</blockquote>`:''}${item.proposed_fix?`<p>建议：${esc(item.proposed_fix)}</p>`:''}${Array.isArray(item.source_ids)&&item.source_ids.length?`<p class="muted">依据：${esc(item.source_ids.map(id=>'['+id+']').join('、'))}</p>`:''}</li>`).join('')}</ul>`:'';
    const noteHtml=constraints.length||notes.length?`<h4>检查范围与限制</h4><ul>${[...constraints,...notes].filter(Boolean).map(item=>`<li>${esc(item)}</li>`).join('')}</ul>`:'';
    const label=typeof report.label==='string'?report.label:'流程检查记录';
    const trace=!stale&&Array.isArray(report.harness?.read_ranges)&&report.harness.read_ranges.length?`<p class="small muted">已保留 ${report.harness.read_ranges.length} 段原文的读取记录；读取记录不代表事实核实。</p>`:'';
    return `<details class="quality-report workflow-coverage${stale?' quality-stale':''}" data-quality-stale="${stale?'true':'false'}"><summary>${stale?'编辑后未重新检查':'检查与待核实事项 · '+checks.filter(item=>item.status==='pass').length+' 项通过'+(issues.length?' · '+issues.length+' 项复核意见':'')}</summary><p class="quality-status"><strong>${esc(label)}</strong>${label.includes('事实仍需核实')?'':' · 事实仍需核实'}</p>${reviewHtml}${sourceHtml}${checkHtml}${issueHtml}${noteHtml}${trace}</details>`;
  }
  function renderWorkflowResult(result,index){
    const recipe=workflowInfo(result.workflow_key), coverage=Array.isArray(result.coverage)?result.coverage:[];
    const citations=Array.isArray(result.citations)?result.citations:[];
    const limits=Array.isArray(result.limitations)?result.limitations:result.limitations?[result.limitations]:[];
    const doc=result.deliverable;
    return `<article class="panel workflow-result" data-deliverable-id="${esc(doc.id)}"><div class="answer-heading"><span>${esc(recipe?.title||'工作草稿')} · 已保存</span><span>${esc(projectName(result.project_id))}</span></div><div class="question-history">${esc(result.question)}</div><div class="answer-text markdown-body">${readable(result.answer)}</div>${(result.quality_report||doc.quality_report)?renderQualityReport(result.quality_report||doc.quality_report,coverage):coverage.length?`<details class="workflow-coverage"><summary>材料覆盖 · ${coverage.length} 份${coverage.some(item=>item.truncated)?' · 含节选材料':''}</summary>${coverage.map(item=>`<p><strong>${esc(item.title||'选定材料')}</strong>${item.truncated?' · 本次使用部分原文，请结合完整材料核实':' · 本次使用已导入原文'}</p>`).join('')}${limits.map(item=>`<p>${esc(typeof item==='string'?item:JSON.stringify(item))}</p>`).join('')}</details>`:''}<div class="citation-grid">${citations.map((cite,citationIndex)=>`<button type="button" class="citation" data-action="workflow-citation" data-id="${esc(doc.id)}" data-citation="${citationIndex}"><span class="citation-number">${citationIndex+1}</span><div><strong>${esc(cite.title)}${cite.page!=null?' · 第 '+esc(cite.page)+' 页':''}</strong><p>${esc(cite.quote)}</p></div></button>`).join('')}</div><div class="row wrap mt-18">${actionButton('打开草稿','open-record','edit','primary',`data-collection="deliverables" data-id="${esc(doc.id)}"`)}${actionButton('HTML','export','download','small soft',`data-id="${esc(doc.id)}" data-format="html"`)}${result.workflow_key==='technology'?'':actionButton('Word','export','download','small soft',`data-id="${esc(doc.id)}" data-format="docx"`)}${['brief','dd','ic','discussion','weekly'].includes(result.workflow_key)?actionButton('PPTX','export','download','small soft',`data-id="${esc(doc.id)}" data-format="pptx"`):''}<span class="small muted">${esc(doc.title)}</span></div></article>`;
  }
  function renderStartWork(){
    const state=view(), busy=state.startBusy||app.uploadBusy;
    const selected=list('documents').filter(doc=>state.startSourceIds.has(String(doc.id))&&String(doc.project_id||'')===String(state.startProject));
    return `<section class="panel start-work"><h2>今天要完成什么？</h2><p class="small muted">研究、Memo、协议、技术解释、邮件和模型，用一句话开始。</p><form id="start-form"><label for="start-input" class="sr-only">描述工作需求</label><div class="start-input-row"><input id="start-input" maxlength="8000" value="${esc(state.startMessage)}" placeholder="例如：为这个项目写一份投委会 Memo，并列出仍需核实的问题" ${busy?'disabled':''}><button type="submit" class="button primary" ${busy?'disabled':''}>${busy?'<span class="spinner"></span>准备中…':icon('arrow')+'开始工作'}</button></div><div class="row wrap start-controls">${projectFilter('start-project',state.startProject,'关联项目（可选）',true,busy)}${actionButton('新建项目','start-create-project','plus','small soft',busy?'disabled':'')}<select id="start-purpose" class="compact-select" aria-label="工作用途" ${busy?'disabled':''}><option value="">自动识别用途</option>${workflowOptions(state.startPurpose)}</select>${actionButton('添加文件','start-upload','upload','small soft',busy?'disabled':'')}${actionButton('添加文件夹','start-folder','upload','small soft',busy?'disabled':'')}</div></form><div class="row wrap start-shortcuts" aria-label="常用工作">${['dd','ic','legal','technology','email','expert_request'].filter(key=>workflowInfo(key)).map(key=>actionButton(workflowInfo(key).title,'start-workflow','','small ghost',`data-key="${esc(key)}" ${busy?'disabled':''}`)).join('')}${actionButton('会议整理','start-route','meetings','small ghost',`data-request="整理会议纪要" ${busy?'disabled':''}`)}${actionButton('财务建模','start-route','finance','small ghost',`data-request="建立财务估值模型" ${busy?'disabled':''}`)}${actionButton('整理项目材料','start-route','file','small ghost',`data-request="整理项目材料和版本" ${busy?'disabled':''}`)}</div>${selected.length?`<p class="small muted mt-12">已添加 ${selected.length} 份材料：${selected.map(doc=>esc(doc.title)).join('、')}。开始工作后可核对范围，再生成草稿。</p>`:''}</section>`;
  }
  function renderOverview() {
    const recentMeetings=[...list('meetings')].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).slice(0,3);
    const recentNotes=[...list('notes')].sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at))).slice(0,3);
    return heading('工作首页','YOUR WORK, ONE PLACE','围绕你要完成的工作，串起项目资料、判断、模型与交付。') +
      (app.workspace==='demo'?banner('合成示例','当前演示内容与个人工作区分开保存。','blue','info'):'') +
      renderStartWork() + `<div id="workflow-activity">${renderWorkflowActivity()}</div>` +
      renderProjects(true) +
      `<div class="overview-grid mt-18"><section class="panel">${panelTitle('最近研究判断','quote')}<div class="panel-body">${recentNotes.length?recentNotes.map(note=>`<div class="task-line"><div class="task-copy"><button type="button" class="task-title" data-action="edit" data-collection="notes" data-id="${esc(note.id)}">${esc(note.title)}</button><div class="task-meta">${badge(note.status)}<span>${esc(projectName(note.project_id))}</span></div></div></div>`).join(''):empty('quote','从一个研究问题开始','选择资料提问，再保存有依据的结论。','',true)}</div></section><section class="panel">${panelTitle('最近访谈与会议','meetings')}<div class="panel-body">${recentMeetings.length?recentMeetings.map(meeting=>`<div class="task-line"><div class="task-copy"><button type="button" class="task-title" data-action="open-record" data-collection="meetings" data-id="${esc(meeting.id)}">${esc(meeting.title)}</button><div class="task-meta"><span>${esc(projectName(meeting.project_id))}</span><span>${esc(dateLabel(meeting.date))}</span></div></div></div>`).join(''):empty('meetings','开始整理一次讨论','原文、专家口径和后续核实事项一起保留。','',true)}</div></section></div>`;
  }

  function renderProjects(embedded=false) {
    const state = view(); const query = state.projectQuery.toLowerCase();
    const projects = list('projects').filter(item => (state.projectStage === '全部' || item.stage === state.projectStage) && `${item.name} ${item.sector} ${item.owner} ${item.tags} ${item.thesis}`.toLowerCase().includes(query));
    const selected = record('projects', state.projectId);
    return (embedded ? `<section class="project-library"><div class="section-label"><div><h2>按公司继续研究</h2><p class="small muted">项目不是额外的工作流，而是归集资料、纪要、判断与模型的公司档案。也可以先研究，再关联项目。</p></div>${actionButton('新建公司档案','create','plus','small','data-collection="projects"')}</div>` : heading('公司研究档案','PROJECT RESEARCH','把同一公司的证据、会议和研究判断放在一起。',actionButton('新建公司档案','create','plus','primary','data-collection="projects"'))) +
      `<div class="toolbar"><div class="tabs" aria-label="按阶段筛选">${['全部', ...STAGES].map(stage => `<button type="button" class="tab${state.projectStage === stage ? ' active' : ''}" data-action="project-stage" data-value="${stage}">${stage}</button>`).join('')}</div>${searchInput('project-search', '搜索项目、行业、负责人', state.projectQuery)}</div>
      <div class="project-grid">${projects.map(project => `<article class="panel project-card${String(project.id) === String(state.projectId) ? ' selected' : ''}"><div class="row"><span class="project-symbol">${icon('projects')}</span><div class="spacer"><button type="button" class="project-title" data-action="project-detail" data-id="${esc(project.id)}">${esc(project.name)}</button><p class="project-sector">${esc(project.sector || '待完善行业')} · ${esc(project.owner || '待分配负责人')}</p></div>${iconButton('编辑项目', 'edit', 'edit', `data-collection="projects" data-id="${esc(project.id)}"`)}</div><p class="project-thesis">${esc(project.thesis || '尚未记录核心判断。编辑项目，写下你的研究起点。')}</p><div class="row wrap">${badge(project.stage || '线索')}${badge(`${project.priority || '中'}优先级`, project.priority === '高' ? 'red' : 'gray')}${String(project.tags || '').split(/[，,]/).filter(Boolean).slice(0, 2).map(tag => badge(excerpt(tag.trim(), 18), 'gray')).join('')}</div><div class="project-bottom"><div class="project-counts"><span>${icon('file')}${list('documents').filter(item => String(item.project_id) === String(project.id)).length} 资料</span><span>${icon('meetings')}${list('meetings').filter(item => String(item.project_id) === String(project.id)).length} 纪要</span></div><button type="button" class="text-button tiny" data-action="project-go" data-page-target="research" data-id="${esc(project.id)}">开始研究 ${icon('arrow')}</button><button type="button" class="text-button tiny" data-action="project-detail" data-id="${esc(project.id)}">项目详情 ${icon('arrow')}</button></div></article>`).join('')}</div>
      ${!projects.length ? `<section class="panel">${empty('projects', list('projects').length ? '没有符合筛选的项目' : '让每个项目有一条清晰的推进线', list('projects').length ? '试试其他阶段或搜索词。' : '创建项目后，资料、任务、会议与交付都可以归集到这里。', actionButton('新建项目', 'create', 'plus', 'primary', 'data-collection="projects"'))}</section>` : ''}
      ${selected ? renderProjectDetail(selected) : ''}${embedded ? '</section>' : ''}`;
  }
  function renderProjectDetail(project) {
    return `<section class="panel project-detail" id="project-detail"><div class="detail-header"><div><div class="eyebrow">PROJECT BRIEF</div><h2>${esc(project.name)}</h2><div class="row wrap mt-12">${badge(project.stage)}${badge(project.priority + '优先级', project.priority === '高' ? 'red' : 'gray')}<span class="small muted">${esc(project.valuation || '估值待补充')}</span></div></div><div class="row wrap">${actionButton('编辑', 'edit', 'edit', 'small', `data-collection="projects" data-id="${esc(project.id)}"`)}${actionButton('生成项目简报', 'project-deliverable', 'deliverables', 'small soft', `data-id="${esc(project.id)}"`)}${iconButton('关闭项目详情', 'project-close', 'close')}</div></div><div class="detail-columns"><div><div class="detail-label">核心判断</div><div class="detail-text">${esc(project.thesis || '尚未记录')}</div></div><div><div class="detail-label">下一步行动</div><div class="detail-text">${esc(project.next_step || '尚未记录')}</div></div></div>${renderMaterialLibrary(project)}</section>`;
  }

  function materialOrder(a, b) {
    const version = String(b.version_label || '').localeCompare(String(a.version_label || ''), 'zh-CN', { numeric: true });
    return version || String(b.created_at || b.updated_at || '').localeCompare(String(a.created_at || a.updated_at || '')) || String(b.updated_at || '').localeCompare(String(a.updated_at || ''));
  }
  function renderMaterialRow(item, recentId) {
    return `<div class="material-row" data-material-id="${esc(item.id)}"><div class="material-copy"><button type="button" class="material-title" data-action="open-record" data-collection="${esc(item.collection)}" data-id="${esc(item.id)}">${esc(item.title || item.filename || '未命名材料')}</button><div class="material-meta">${badge(item.material_type || LABELS[item.collection], 'gray')}${item.version_label ? badge(item.version_label, 'blue') : ''}${String(item.id) === String(recentId) ? badge('最近导入', 'green') : ''}<span>${esc(dateLabel(item.updated_at, true))}</span><span>${item.task_group_source === 'manual' ? '指定子任务' : '自动整理'}</span></div>${item.organization_reason ? `<p class="tiny muted">${esc(item.organization_reason)}</p>` : ''}</div><div class="row wrap">${item.collection === 'documents' && hasOriginal(item) ? actionButton('原文件', 'original-download', 'download', 'small ghost', `data-id="${esc(item.id)}"`) : ''}${iconButton('编辑归类', 'edit', 'edit', `data-collection="${esc(item.collection)}" data-id="${esc(item.id)}"`)}</div></div>`;
  }
  function renderMaterialLibrary(project) {
    const state = view(), records = projectRecords(project.id), query = state.libraryQuery.toLowerCase();
    const visible = records.filter(item => (!state.libraryGroup || taskGroup(item) === state.libraryGroup) && `${item.title || ''} ${item.filename || ''} ${item.task_group || ''} ${item.material_type || ''} ${item.version_family || ''} ${item.version_label || ''}`.toLowerCase().includes(query));
    const groups = new Map();
    visible.forEach(item => { const key = taskGroup(item); if (!groups.has(key)) groups.set(key, []); groups.get(key).push(item); });
    const sections = [...groups].sort((a, b) => a[0].localeCompare(b[0], 'zh-CN')).map(([group, items]) => {
      const families = new Map();
      items.forEach(item => { const key = `${item.collection}:${item.material_type || ''}:${item.version_family || item.id}`; if (!families.has(key)) families.set(key, []); families.get(key).push(item); });
      const familiesHTML = [...families.values()].sort((a, b) => String(b.reduce((d, i) => String(i.updated_at || '') > d ? String(i.updated_at) : d, '')).localeCompare(a.reduce((d, i) => String(i.updated_at || '') > d ? String(i.updated_at) : d, ''))).map(versions => {
        versions.sort(materialOrder);
        const recent = [...versions].sort((a, b) => String(b.created_at || b.updated_at || '').localeCompare(String(a.created_at || a.updated_at || '')))[0];
        if (versions.length === 1) return renderMaterialRow(versions[0], '');
        return `<details class="material-family"><summary><span>${esc(versions[0].title || versions[0].filename || '同一材料')}</span><span class="count-pill">${versions.length} 个版本</span><span class="tiny muted">展开全部版本</span></summary>${versions.map(item => renderMaterialRow(item, recent.id)).join('')}</details>`;
      }).join('');
      return `<section class="material-group" data-task-group="${esc(group)}"><div class="material-group-heading"><div><h3>${esc(group)} <span class="count-pill">${items.length}</span></h3></div><div class="row wrap">${actionButton('研究此任务', 'group-research', 'research', 'small soft', `data-project-id="${esc(project.id)}" data-group="${esc(group)}"`)}${actionButton('导入资料', 'project-upload', 'upload', 'small ghost', `data-project-id="${esc(project.id)}" data-group="${esc(group)}"`)}${[['documents','资料'],['notes','结论'],['meetings','会议'],['deliverables','交付']].map(([collection,label]) => actionButton(`新建${label}`, 'project-create', 'plus', 'small ghost', `data-collection="${collection}" data-project-id="${esc(project.id)}" data-group="${esc(group)}"`)).join('')}</div></div>${familiesHTML}</section>`;
    }).join('');
    return `<div class="material-library"><div class="material-library-heading"><div><h2>项目材料 · 自动整理</h2><p class="small muted">新建和导入时自动归入子任务，同一材料的多个版本放在一起；也可按你的习惯指定子任务。</p></div><div class="row wrap">${actionButton('新建子任务', 'project-subtask', 'plus', 'small', `data-id="${esc(project.id)}"`)}${actionButton('导入文件夹', 'project-folder', 'upload', 'small soft', `data-project-id="${esc(project.id)}"`)}${actionButton('导入文件', 'project-upload', 'upload', 'small soft', `data-project-id="${esc(project.id)}"`)}${actionButton('重新整理', 'project-organize', 'refresh', 'small ghost', `data-id="${esc(project.id)}"`)}</div></div><div class="toolbar"><div class="toolbar-group">${groupFilter('library-group', state.libraryGroup, project.id)}<span class="small muted">${visible.length} / ${records.length} 条记录</span></div>${searchInput('library-search', '搜索材料、版本、子任务', state.libraryQuery)}</div>${sections || empty('file', records.length ? '没有符合筛选的材料' : '直接放入材料，自动整理', records.length ? '试试其他子任务或搜索词。' : 'Memo、协议、会议与研究结论会自动分类；你也可以先建立自己的子任务。', '', true)}</div>`;
  }
  function createSubtask(projectId) {
    openModal('新建子任务', inputField('title', '子任务名称', '', { required: true, maxlength: 120, placeholder: '例如：商业尽调、交易协议、投委会 Memo' }) + '<p class="small muted">保存后即可在此子任务内创建或导入材料。其他材料仍会自动整理。</p>', async form => {
      const title = String(form.get('title') || '').trim();
      await api('/tasks', { body: { title, task_group: title, project_id: projectId, status: '待办', priority: '中' } });
      await refreshData(); view().libraryGroup = title; render(); notify('子任务已创建。');
    });
  }

  function renderTasks() {
    const state = view(); const query = state.taskQuery.toLowerCase();
    const tasks = list('tasks').filter(item => (!state.taskProject || String(item.project_id) === state.taskProject) && (!state.taskPriority || item.priority === state.taskPriority) && `${item.title} ${item.description} ${item.owner}`.toLowerCase().includes(query)).sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999'));
    return heading('任务中心', 'MAKE IT HAPPEN', '把下一步变得具体。每一项行动，都有状态、负责人和时间。', actionButton('新建任务', 'create', 'plus', 'primary', 'data-collection="tasks"')) +
      `<div class="toolbar"><div class="toolbar-group">${projectFilter('task-project', state.taskProject)}<select id="task-priority" class="compact-select" aria-label="按优先级筛选"><option value="">全部优先级</option>${options(PRIORITIES, state.taskPriority)}</select></div>${searchInput('task-search', '搜索任务、负责人', state.taskQuery)}</div>
      <div class="kanban">${STATUSES.map(status => { const items = tasks.filter(task => task.status === status); return `<section class="kanban-column"><header class="kanban-head"><span><span class="kanban-dot"></span>${status} <span class="count-pill">${items.length}</span></span>${iconButton(`新建${status}任务`, 'task-new-status', 'plus', `data-status="${status}"`)}</header>${items.length ? items.map(task => `<article class="task-card${String(task.id) === String(state.highlightTask) ? ' highlight' : ''}" id="task-${esc(task.id)}"><div class="row between">${badge(task.priority || '中', task.priority === '高' ? 'red' : task.priority === '中' ? 'amber' : 'gray')}${iconButton('编辑任务', 'edit', 'edit', `data-collection="tasks" data-id="${esc(task.id)}"`)}</div><button type="button" class="task-card-title" data-action="edit" data-collection="tasks" data-id="${esc(task.id)}">${esc(task.title)}</button>${task.description ? `<p class="task-card-description">${esc(task.description)}</p>` : ''}<div class="task-meta"><span>${esc(projectName(task.project_id))}</span>${task.meeting_id ? '<span>· 来自会议</span>' : ''}</div><div class="task-card-footer"><span><span${overdue(task) ? ' class="color-red"' : ''}>${task.due ? `${overdue(task) ? '逾期 ' : ''}${esc(dateLabel(task.due))}` : '无到期日'}</span> · ${esc(task.owner || '未分配')}</span><select class="status-select" data-task-status="${esc(task.id)}" aria-label="${esc(task.title)}的状态">${options(STATUSES, status)}</select></div></article>`).join('') : empty(status === '完成' ? 'circleCheck' : 'tasks', status === '完成' ? '完成的事情会留在这里' : '当前没有任务', status === '待办' ? '点击上方加号，安排下一步。' : '可从其他列调整任务状态。', '', true)}</section>`; }).join('')}</div>`;
  }

  function filteredSources() {
    const state = view(); const query = state.sourceQuery.toLowerCase();
    return list('documents').filter(doc => (!state.researchProject || String(doc.project_id) === state.researchProject) && (!state.sourceGroup || taskGroup(doc) === state.sourceGroup) && `${doc.title} ${doc.category} ${doc.filename}`.toLowerCase().includes(query));
  }
  function renderResearch() {
    const state = view(); const sources = filteredSources();
    const selected = list('documents').filter(doc => state.selectedSources.has(String(doc.id)));
    const dshAvailable = Boolean(app.boot?.dsh?.available);
    const notes = list('notes').filter(note => !state.researchProject || String(note.project_id) === state.researchProject);
    const memorySelected = selected.some(doc => doc.kind === 'memory');
    const actionMode=state.researchIntent==='actions', workflowMode=state.researchIntent==='workflow', busy=state.asking||state.agentBusy||state.workflowBusy;
    const activeWorkflow=workflowInfo(state.workflowKey);
    const visibleWorkflowResults=state.workflowResults.map((result,index)=>({result,index})).filter(item=>!state.researchProject||String(item.result.project_id)===String(state.researchProject));
    const visibleAnswers=state.answers.map((answer,index)=>({answer,index})).filter(item=>!state.researchProject||String(item.answer.project_id)===String(state.researchProject));
    return heading('研究工作台', 'EVIDENCE BEFORE OPINION', '选项目资料、点一键提纲或直接提问；GPT / DSH 回答保留出处并可转为结论与行动。', actionButton('新建研究结论', 'create', 'plus', '', 'data-collection="notes"') + actionButton('导入材料', 'upload', 'upload', 'primary', app.uploadBusy ? 'disabled' : '')) +
      `<div class="toolbar"><div class="toolbar-group">${projectFilter('research-project', state.researchProject)}${state.researchProject ? groupFilter('source-group', state.sourceGroup, state.researchProject) : ''}<span class="small muted">${list('documents').length} 份可用资料 · ${notes.length} 条研究结论</span></div></div>
      ${app.uploadBusy ? '<div class="file-progress"><span class="spinner"></span>正在解析并导入文件，请稍候…</div>' : ''}
      <div class="research-layout"><section class="panel source-panel">${panelTitle('证据材料', 'file', `<span class="count-pill">${sources.length}</span>`)}<div class="panel-body" style="padding:0 16px 13px">${searchInput('source-search', '搜索材料标题', state.sourceQuery)}</div><div class="sources-toolbar"><label><input type="checkbox" id="source-select-all" ${sources.length && sources.every(doc => state.selectedSources.has(String(doc.id))) ? 'checked' : ''} ${!sources.length ? 'disabled' : ''}>选中筛选结果</label><span>已选 ${selected.length} 份</span></div><div class="source-list">${sources.length ? sources.map(doc => `<div class="source-row${state.selectedSources.has(String(doc.id)) ? ' selected' : ''}"><input type="checkbox" data-source-id="${esc(doc.id)}" aria-label="选择材料：${esc(doc.title)}" ${state.selectedSources.has(String(doc.id)) ? 'checked' : ''}><div class="source-info"><button type="button" class="source-name" data-action="document" data-id="${esc(doc.id)}">${esc(doc.title)}</button><div class="source-meta"><span>${doc.kind === 'memory' ? '记忆 · 仅本地' : esc(doc.material_type || doc.category || '研究材料')}${doc.task_group ? ' · ' + esc(doc.task_group) : ''}${doc.version_label ? ' · ' + esc(doc.version_label) : ''}</span><span>${doc.page_count ? `${esc(doc.page_count)} 页` : esc(doc.filename?.split('.').pop()?.toUpperCase() || '纯文本')}</span></div></div></div>`).join('') : empty('file', '还没有证据材料', '导入 TXT / MD / PDF / DOCX，或直接粘贴原文。扫描 PDF 暂不支持 OCR。', '', true)}</div><div class="source-footer">${actionButton('粘贴导入', 'paste-import', 'plus', 'small', app.uploadBusy ? 'disabled' : '')}${actionButton('导入文件', 'upload', 'upload', 'small', app.uploadBusy ? 'disabled' : '')}${actionButton('导入文件夹', 'upload-folder', 'upload', 'small', app.uploadBusy ? 'disabled' : '')}</div></section>
      <div class="stack"><section class="panel question-panel"><div class="question-heading"><span class="question-icon">${icon('research')}</span><div><h2>研究助理</h2><small>一个输入区：研究资料时保留引用，操作工作区时明确说明要创建或保存的记录。</small></div></div><div class="composer-mode"><label for="research-intent">用途</label><select id="research-intent" aria-label="AI任务类型" ${busy ? 'disabled' : ''}><option value="ask"${selectedAttr('ask',state.researchIntent)}>问资料 · 不改记录</option><option value="workflow"${selectedAttr('workflow',state.researchIntent)}>生成交付草稿</option><option value="actions"${selectedAttr('actions',state.researchIntent)}>操作工作区 · 创建/保存记录</option></select>${workflowMode?`<select id="workflow-purpose" aria-label="交付用途" ${busy?'disabled':''}>${workflowOptions(state.workflowKey)}</select><select id="workflow-quality" aria-label="整理深度" ${busy?'disabled':''}><option value="thorough"${selectedAttr('thorough',workflowQuality(state))}>深入整理 · 分析、复核、修订</option><option value="fast"${selectedAttr('fast',workflowQuality(state))}>快速草稿</option></select>`:''}</div>${workflowMode?`<p class="small muted">${esc(activeWorkflow?.description||'描述你要完成的交付，再确认使用的材料。')}</p>${state.workflowError?`<div class="mt-12">${banner('草稿未生成',state.workflowError,'error','warning')}</div>`:''}`:`<div class="row wrap mt-12" aria-label="常用研究任务"><button type="button" class="button small soft" data-action="research-template" data-template="brief">项目速览</button><button type="button" class="button small soft" data-action="research-template" data-template="gaps">尽调缺口</button><button type="button" class="button small soft" data-action="research-template" data-template="compare">口径差异</button></div>`}<form id="ask-form"><div class="question-box"><label for="question-input" class="sr-only">研究问题</label><textarea id="question-input" name="question" required maxlength="8000" placeholder="${actionMode?'例如：把我输入的访谈文字保存成资料，并创建三条待核实任务。':workflowMode?'描述交付要求、对象、结构，以及希望重点解决的问题。':'例如：收入增长的主要驱动是什么？这些资料有哪些矛盾或缺口？'}" ${busy ? 'disabled' : ''}>${esc(actionMode?state.agentMessage:workflowMode?state.workflowMessage:state.question)}</textarea>
      <div class="question-bottom">
      ${actionMode ? `<select id="agent-model" aria-label="操作助手模型" ${busy?'disabled':''}>${localModelOptions('deepseek',state.localModel)}</select><label class="agent-toggle"><input type="checkbox" id="agent-project-scope" ${state.researchProject && state.agentProjectScope?'checked':''} ${state.researchProject ? '' : 'disabled'}>关联当前公司</label>` :
      `<select id="ask-mode" aria-label="回答引擎" ${busy?'disabled':''}><option value="deepseek"${selectedAttr('deepseek',state.askMode)}>DeepSeek · 快</option>${workflowMode?'':`<option value="local"${selectedAttr('local',state.askMode)}>本地检索 · 无外发</option>`}<option value="local-models"${selectedAttr('local-models',state.askMode)}>GLM / Kimi / 混元</option><option value="dsh" ${!dshAvailable?'disabled':''}${selectedAttr('dsh',state.askMode)}>ChatGPT</option></select>${state.askMode==='dsh'?'<select id="dsh-model" aria-label="GPT模型">'+dshModelOptions(state.dshModel)+'</select>':''}${(state.askMode==='deepseek'||state.askMode==='local-models')?'<select id="local-model" aria-label="本机模型">'+localModelOptions(state.askMode,state.localModel)+'</select>':''}`}
      <button type="submit" class="button primary" ${busy?'disabled':''}>${busy?'<span class="spinner"></span>正在处理…':icon('arrow')+(actionMode?'执行工作区操作':workflowMode?'生成并保存草稿':'查阅选定材料')}</button></div></div>
      ${actionMode?`<div class="source-scope">操作范围：${esc(state.researchProject && state.agentProjectScope?projectName(state.researchProject):'工作区')}。选中资料正文不会自动随操作请求发送；分析资料请切回“问资料”。</div>`:`<div class="source-scope"><span>本次范围：</span>${selected.length ? selected.map(doc => `<span class="tag ${doc.kind === 'memory' ? 'amber' : 'green'}">${esc(doc.title)}</span>`).join('') : workflowMode&&!activeWorkflow?.requires_sources?'<span>可直接填写工作要求；选定材料时会显示在这里。</span>':'<span>请先在左侧明确选择材料，不会默认检索或发送全库。</span>'}</div>`}
      ${!actionMode && state.askMode !== 'local' ? `<div class="mt-12">${researchModelStatus(state)}</div>${memorySelected ? `<div class="mt-12">${banner('', '选中范围含个人记忆。记忆只做本地检索；请切换“本地检索”，或取消记忆来源。', 'amber', 'lock')}</div>` : ''}<p class="inline-note">${workflowMode?'确认后生成并保存草稿，使用左侧已勾选材料或本次工作要求。':'提交问题时按左侧已勾选范围提问。'}不发送未选资料与个人记忆。</p>` : ''}</form></section>
      ${renderAgentResult()}
      <div id="workflow-jobs" class="workflow-jobs" aria-live="polite">${renderWorkflowJobs()}</div><div id="workflow-results" class="workflow-results">${visibleWorkflowResults.map(({result,index})=>renderWorkflowResult(result,index)).join('')}</div>
      ${visibleAnswers.length ? visibleAnswers.map(({answer,index})=>renderAnswer(answer,index)).join('') : `<section class="panel">${empty('quote', '从有出处的回答开始', '选中一份或多份资料。本地检索会给出原文摘录，点击引用可定位页码或段落；没有证据时不会补写事实。', '', true)}</section>`}
      <section class="panel">${panelTitle('研究结论', 'book', actionButton('新建结论', 'create', 'plus', 'small ghost', 'data-collection="notes"'))}${notes.length ? notes.map(note => `<article class="note-item"><div class="row between"><h3 class="notes-title">${esc(note.title)}</h3>${badge(note.status)}</div><div class="note-body markdown-body">${readable(note.body)}</div>${note.source_quote ? `<div class="note-quote">${esc(note.source_quote)}</div>` : ''}<div class="row wrap"><span class="tiny muted">${esc(projectName(note.project_id))}</span><span class="spacer"></span>${note.document_id ? actionButton('查看证据', 'note-source', 'quote', 'small ghost', `data-id="${esc(note.id)}"`) : ''}${actionButton('编辑 / 核实', 'edit', 'edit', 'small ghost', `data-collection="notes" data-id="${esc(note.id)}"`)}${actionButton('转为交付', 'note-deliverable', 'deliverables', 'small soft', `data-id="${esc(note.id)}"`)}</div></article>`).join('') : empty('book', '先留存结论，再持续核实', '问答可保存为研究结论，也可手动记录判断、证据与核实状态。', '', true)}</section></div></div>`;
  }
  function renderAnswer(answer, index) {
    const citations = Array.isArray(answer.citations) ? answer.citations : [];
    return `<article class="panel answer-card"><div class="answer-heading"><span>${answer.mode === 'dsh' ? `${esc(answer.model || 'GPT via DSH')} · 草稿需核验` : answer.mode === 'model' ? '外部模型回答 · 需自行核验' : '本地证据摘录 · 非大模型'}</span><span>${Number.isFinite(Number(answer.elapsed_ms)) ? `${number(answer.elapsed_ms)} ms` : ''}</span></div><div class="question-history">${esc(answer.question)}</div><div class="answer-text markdown-body">${readable(answer.answer)}</div>${answer.warning ? `<div class="mt-12">${banner('', answer.warning, 'amber', 'info')}</div>` : ''}<div class="citation-grid">${citations.map((citation, citationIndex) => `<button type="button" class="citation" data-action="citation" data-answer="${index}" data-citation="${citationIndex}"><span class="citation-number">${citationIndex + 1}</span><div><strong>${esc(citation.title)} · ${citation.page != null ? `第 ${esc(citation.page)} 页 · ` : ''}第 ${esc(citation.ordinal ?? citationIndex + 1)} 段</strong><p>${esc(citation.quote)}</p></div></button>`).join('')}</div><div class="answer-footer"><span class="tiny muted spacer">${citations.length} 处可定位引用</span>${actionButton('保存为研究结论', 'answer-note', 'book', 'small soft', `data-index="${index}"`)}</div></article>`;
  }
  async function askQuestion() {
    const state = view(); if (state.asking||state.agentBusy||state.workflowBusy) return;
    if(state.researchIntent==='actions') return runAgent($('#question-input')?.value||'');
    if(state.researchIntent==='workflow') return runWorkflow();
    const question = $('#question-input').value.trim(); state.question = question;
    if (!question) { notify('请先输入一个研究问题。', true); return; }
    const ids = [...state.selectedSources];
    if (!ids.length) { notify('请先明确选中至少一份资料。', true); return; }
    const mode = $('#ask-mode').value;
    const allowExternal = mode !== 'local'; // Selection itself is the scope; no per-request consent gate.
    const modelId = mode === 'dsh' ? ($('#dsh-model')?.value || state.dshModel || 'gpt-6-luna') : (mode === 'deepseek' || mode === 'local-models') ? ($('#local-model')?.value || state.localModel || 'deepseek-v4.1-flash') : '';
    if (mode !== 'local') {
      if (ids.some(id => record('documents', id)?.kind === 'memory')) { notify('个人记忆只做本地检索：请改用“本地检索”，或取消记忆来源。', true); return; }
      if (mode === 'dsh' && !app.boot?.dsh?.available) { notify('没有检测到本机 DSH，请检查 DSH 安装。', true); return; }
      if (mode === 'model' && !app.boot?.ai?.configured) { notify('请先在设置中配置可选模型。', true); return; }
    }
    const projectId = state.researchProject || '';
    state.asking = true; render();
    try {
      const response = await api('/ask', { body: { question, project_id: projectId, document_ids: ids, mode, model_id: modelId, allow_external: allowExternal } });
      state.answers.unshift({ ...response, question, project_id: projectId }); state.answers = state.answers.slice(0, 8);
    } catch (error) { showError(error); }
    finally { state.asking = false; if (view() === state && app.page === 'research') render(); }
  }
  function applyResearchTemplate(key) {
    if(view().asking||view().agentBusy||view().workflowBusy)return;
    const prompts = {
      brief: '请基于选中材料制作一页项目速览：项目/公司概况、核心判断、支持证据、主要风险、仍缺信息、下一步建议。逐项标注来源[S#]；资料没有写到的内容请标为未知。',
      gaps: '请梳理选中材料反映的尽调缺口：待核实问题、为什么重要、目前已有证据[S#]、还需要向谁或哪份资料核实。不要把资料未提及误写成事实。',
      compare: '请比对选中材料中对同一经营指标、日期、定义或交易条件的不同表述，整理为“事项｜来源A口径｜来源B口径｜差异是否可解释｜建议核实问题”，每个来源标注[S#]。不预设任何一方错误。'
    };
    const state = view(); const question = prompts[key]; if (!question) return;
    state.researchIntent='ask';
    if (!state.selectedSources.size) {
      let candidates = filteredSources().filter(doc => doc.kind !== 'memory');
      if (!state.researchProject && candidates.length > 5) candidates = [];
      candidates.forEach(doc => state.selectedSources.add(String(doc.id)));
    }
    state.question = question;
    const selected = list('documents').filter(doc => state.selectedSources.has(String(doc.id)));
    if(selected.some(doc=>doc.kind==='memory'))state.askMode='local';
    render();
    if (!state.selectedSources.size) notify('先筛选项目或选择资料；为避免误发，不会默认选中全库。', true);
    else notify('已准备 ' + state.selectedSources.size + ' 份资料和研究提纲，请核对范围后提交。');
    requestAnimationFrame(() => $('#question-input')?.focus());
  }
  // Fast intake: paste or drop anywhere on the page and the content becomes a document.
  function isTypingTarget(target) {
    if (!target) return false;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
  }
  function pastedName(text) {
    const first = String(text || '').trim().split(/\r?\n/).find(line => line.trim());
    return excerpt((first || '粘贴内容').replace(/[\\/:*?"<>|]/g, ' ').trim(), 40) || '粘贴内容';
  }
  async function importPastedText(text, label = '') {
    const content = String(text || '').trim();
    if (!content) { notify('剪贴板里没有可导入的文本。', true); return null; }
    if (app.uploadBusy) return null;
    const title = label || pastedName(content);
    app.uploadBusy = true;
    if (app.page === 'research' || app.page === 'memory') render();
    try {
      const doc = await api('/documents', { body: { title, kind: 'research', project_id: view().researchProject || '', source_ref: '粘贴导入', content, private: true, ...(view().sourceGroup ? { task_group: view().sourceGroup } : {}) } });
      await refreshData();
      if (app.page === 'research') view().selectedSources.add(String(doc.id));
      notify('已作为资料“' + title + '”保存（' + content.length + ' 字），可直接勾选提问。');
      return doc;
    } catch (error) { showError(error); return null; }
    finally { app.uploadBusy = false; if (app.page === 'research' || app.page === 'memory') render(); }
  }
  function handlePastedText(text) {
    const value=String(text||'').trim(); if(!value)return;
    if(value.length>2_000_000){notify('粘贴文本超过2MB，分段导入更快。',true);return;}
    importPastedText(value);
  }
  async function filesFromDataTransfer(transfer) {
    const files = [...(transfer?.files || [])];
    if (files.length) return { files, text: '' };
    const text = transfer?.getData ? transfer.getData('text/plain') : '';
    return { files: [], text };
  }
  async function uploadFiles(files, kind = 'research') {
    if (app.uploadBusy || !files.length) return;
    if (kind === 'memory' && app.workspace !== 'personal') { notify('真实记忆只能导入个人工作区。', true); return; }
    if (files.length > 150) { notify('一次最多导入150个文件；请分批选择。', true); return; }
    if (files.reduce((sum, file) => sum + file.size, 0) > 200 * 1024 * 1024) { notify('所选文件合计超过200 MB；请分批导入。', true); return; }
    app.uploadBusy = true; const state = view(); const projectId = kind === 'memory' ? '' : (state.researchProject || ''); const group = kind === 'research' ? state.sourceGroup : ''; const fromHome=app.page==='overview'; const epoch = app.epoch;
    if (app.page === 'research' || app.page === 'memory' || app.page === 'overview') render();
    let imported = 0; let updated = 0; let unchanged = 0; let failed = 0;
    try {
      for (const file of files) {
        if (epoch !== app.epoch) throw new StaleRequestError();
        if (!/\.(txt|md|pdf|docx|pptx|xlsx|xlsm)$/i.test(file.name)) { notify(`“${file.name}”格式不支持，请使用 TXT / MD / PDF / DOCX / PPTX / XLSX / XLSM。`, true); failed++; continue; }
        if (file.size > 20 * 1024 * 1024) { notify(`“${file.name}”超过 20 MB，未导入。`, true); failed++; continue; }
        try {
          const base64 = await new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = () => reject(new Error(`无法读取“${file.name}”。`)); reader.readAsDataURL(file); });
          const source = file.webkitRelativePath || file.name;
          const doc = await api('/upload', { body: { name: file.name, base64, project_id: projectId, kind, source_ref: source, ...(group ? { task_group: group } : {}) } });
          if (kind === 'research') { if(fromHome&&doc.id)state.startSourceIds.add(String(doc.id));if (doc.id && String(state.researchProject)===String(projectId) && (!state.sourceGroup || taskGroup(doc)===state.sourceGroup)) state.selectedSources.add(String(doc.id)); imported++; }
          else if (doc.unchanged) unchanged++;
          else if (doc.updated) updated++;
          else imported++;
        } catch (error) { if (error.name === 'StaleRequestError') throw error; failed++; showError(error); }
      }
      if (kind === 'memory' && imported + updated + unchanged) { await refreshData(); notify('记忆导入完成：新增 ' + imported + '，更新 ' + updated + '，未变化 ' + unchanged + (failed ? '，失败 ' + failed : '') + '。仅保存在本机，源文件未修改。'); }
      else if (kind === 'research' && imported) { await refreshData(); notify(`已导入 ${imported} 份资料${failed ? `，${failed} 份未导入` : ''}。`); }
      else if (!imported && !updated && !unchanged && failed) notify('没有文件导入成功，请检查文件类型或大小。', true);
    } catch (error) { showError(error); }
    finally { app.uploadBusy = false; $('#upload-input').value = ''; $('#research-folder-input').value = ''; $('#memory-file-input').value = ''; $('#memory-folder-input').value = ''; if (epoch === app.epoch) render(); }
  }
  async function openDocument(id, citation = null) {
    const dialog = $('#document-dialog');
    dialog.innerHTML = `<div class="document-top"><div><h2 id="document-title">正在载入原文</h2></div><button type="button" class="icon-button" data-close-dialog="document-dialog" aria-label="关闭原文">${icon('close')}</button></div>${loading('正在从本地读取材料…')}`;
    if (!dialog.open) dialog.showModal();
    const ticket = String(id) + ':' + Date.now(); dialog.dataset.ticket = ticket;
    try {
      const doc = await api(`/documents/${encodeURIComponent(id)}`);
      if (!dialog.open || dialog.dataset.ticket !== ticket) return;
      const chunks = Array.isArray(doc.chunks) ? doc.chunks : [];
      let targetIndex = -1;
      if (citation) {
        targetIndex = chunks.findIndex(chunk => citation.id && String(chunk.id) === String(citation.id));
        if (targetIndex < 0 && citation.ordinal != null) targetIndex = chunks.findIndex(chunk => String(chunk.ordinal) === String(citation.ordinal) && (citation.page == null || String(chunk.page) === String(citation.page)));
        if (targetIndex < 0 && citation.quote) targetIndex = chunks.findIndex(chunk => chunk.text && String(chunk.text).includes(String(citation.quote).slice(0, 60)));
      }
      dialog.innerHTML = `<div class="document-top"><div><h2 id="document-title">${esc(doc.title)}</h2><div class="document-metadata">${badge(doc.kind === 'memory' ? '只读记忆副本' : '研究材料', doc.kind === 'memory' ? 'amber' : 'green')}<span>${esc(projectName(doc.project_id))}</span><span>${chunks.length} 段${doc.page_count ? ` · ${esc(doc.page_count)} 页` : ''}</span><span>${esc(dateLabel(doc.updated_at, true))} 更新</span></div></div><div class="row">${hasOriginal(doc) ? actionButton('原文件', 'original-download', 'download', 'small soft', `data-id="${esc(doc.id)}"`) : ''}${doc.kind !== 'memory' ? iconButton('编辑原文', 'document-edit', 'edit', `data-id="${esc(doc.id)}"`) : ''}${iconButton(doc.kind === 'memory' ? '删除导入副本' : '删除材料', 'document-delete', 'trash', `data-id="${esc(doc.id)}"`, 'danger')}<button type="button" class="icon-button" data-close-dialog="document-dialog" aria-label="关闭原文">${icon('close')}</button></div></div><div class="document-reader"><div class="document-origin">来源：${esc(doc.source_ref || doc.filename || '手动创建')}<br>分类：${esc(doc.category || '未分类')}${doc.hash ? `<br>内容指纹：${esc(doc.hash)}` : ''}${doc.kind === 'memory' ? '<br>这是只读导入副本，删除副本不会修改来源文件。' : ''}</div>${citation && targetIndex < 0 ? `<div class="mb-15">${banner('', '原文可能已被编辑，未能匹配原引用段落。请结合下方全文重新核实。', 'amber', 'warning')}</div>` : ''}${chunks.length ? chunks.map((chunk, index) => `<section class="document-chunk${index === targetIndex ? ' highlight' : ''}" id="document-chunk-${index}" tabindex="-1"><div class="chunk-label">${chunk.page != null ? `<span>第 ${esc(chunk.page)} 页</span>` : ''}<span>第 ${esc(chunk.ordinal ?? index + 1)} 段</span>${index === targetIndex ? '<span>当前引用</span>' : ''}</div><p>${esc(chunk.text)}</p></section>`).join('') : `<section class="document-chunk"><p>${esc(doc.content || '此材料没有可显示的原文。')}</p></section>`}</div>`;
      if (targetIndex >= 0) requestAnimationFrame(() => { const chunk = $(`#document-chunk-${targetIndex}`, dialog); chunk?.scrollIntoView({ block: 'center', behavior: 'instant' }); chunk?.focus({ preventScroll: true }); });
    } catch (error) {
      if (dialog.dataset.ticket === ticket && dialog.open) dialog.innerHTML = `<div class="document-top"><h2 id="document-title">原文读取失败</h2><button type="button" class="icon-button" data-close-dialog="document-dialog" aria-label="关闭">${icon('close')}</button></div><div class="document-reader">${banner('', error.message, 'error', 'warning')}</div>`;
    }
  }

  function meetingSelection() {
    const state = view(); const meetings = list('meetings').filter(meeting => !state.meetingProject || String(meeting.project_id) === state.meetingProject).sort((a, b) => String(b.date).localeCompare(String(a.date)));
    if (!meetings.some(meeting => String(meeting.id) === String(state.meetingId))) state.meetingId = meetings[0]?.id || '';
    return { meetings, meeting: meetings.find(item => String(item.id) === String(state.meetingId)) };
  }
  const formatMinuteText = text => String(text || '').replace(/(^|\n)([•\-])\s*/g, '$1• ').replace(/(^|\n)o\s+/g, '$1o ').replace(/(^|\n)[➢➤]\s*/g, '$1➢ ').replace(/([\d])\s*[–—]\s*([\d])/g, '$1-$2');
  function renderMeetings() {
    const state = view(); const { meetings, meeting } = meetingSelection();
    const localModels=localModelOptions('deepseek',state.meetingModel||state.localModel||'deepseek-v4.1-flash');
    const modeLabel='DeepSeek Flash (V4.1)';
    return heading('会议纪要', 'EXPERT CALL NOTES', '粘贴原文，'+modeLabel+' 自动整理成册，编辑后直接导出 Word / PDF。', actionButton('新建会议', 'create', 'plus', 'primary', 'data-collection="meetings"')) +
      `<div class="toolbar"><div class="toolbar-group">${projectFilter('meeting-project', state.meetingProject)}<span class="small muted">${meetings.length} 场会议</span></div></div>
      <div class="split-layout"><section class="panel">${panelTitle('会议记录', 'meetings')}<div class="record-list">${meetings.length ? meetings.map(item => `<button type="button" class="record-item${String(item.id) === String(state.meetingId) ? ' active' : ''}" data-action="select-meeting" data-id="${esc(item.id)}"><h3>${esc(item.title)}</h3><p>${esc(projectName(item.project_id))}</p><span class="record-date">${esc(item.date || '日期待补充')} · ${esc(item.participants || '参会人待补充')}</span></button>`).join('') : empty('meetings', '尚无会议记录', '粘贴逐字稿即可开始。', '', true)}</div></section>
      <div>${meeting ? renderMeetingDetail(meeting, {localModels, actionButton, iconButton, banner, esc, projectName, list}) : `<section class="panel">${empty('meetings', '让会议形成可跟进的行动', '新建会议并粘贴逐字稿。规则引擎生成的是可编辑草稿，不会自动创建任务或作出承诺。', actionButton('记录第一场会议', 'create', 'plus', 'primary', 'data-collection="meetings"'))}</section>`}</div></div>`;
  }
  function renderMeetingDetail(meeting, h) {
    const state = view(); const draft = state.drafts.get(String(meeting.id)); const summary = draft?.summary ?? meeting.summary ?? '';
    const relatedTasks = list('tasks').filter(task => String(task.meeting_id) === String(meeting.id));
    const header = '<section class="panel"><div class="meeting-header"><div><h2>' + h.esc(meeting.title) + '</h2><div class="meeting-meta">' + h.esc(meeting.date || '日期待补充') + ' · ' + h.esc(h.projectName(meeting.project_id)) + ' · ' + h.esc(meeting.participants || '') + '</div></div>' + h.iconButton('编辑会议与逐字稿','edit','edit','data-collection="meetings" data-id="' + h.esc(meeting.id) + '"') + h.iconButton('删除会议','delete','trash','data-collection="meetings" data-id="' + h.esc(meeting.id) + '"','danger') + '</div><div class="meeting-body">';
    const transcript = '<details class="transcript-details"' + (meeting.transcript ? '' : ' open') + '><summary>逐字稿 · ' + String((meeting.transcript || '').length) + ' 字</summary><div class="transcript-text">' + h.esc(meeting.transcript || '尚未粘贴逐字稿。可直接 Ctrl+V 粘贴。') + '</div></details>';
    const warnings = draft?.warnings?.length ? h.banner('AI 整理说明', draft.warnings.join('；'), 'amber', 'info') : '';
    const intake = '<div class="field mt-18"><label for="meeting-transcript-input">原文转写 · 粘贴或拖入 TXT / DOCX / PDF</label><div class="meeting-transcript-drop" data-meeting-transcript-drop="true"><textarea id="meeting-transcript-input" rows="7" placeholder="Ctrl+V 粘贴逐字稿；也可把 TXT / DOCX / PDF 拖到此区域。原文会自动保存。">' + h.esc(state.meetingTranscriptDraft || meeting.transcript || '') + '</textarea></div><div class="row wrap mt-12"><select id="meeting-model">' + h.localModels + '</select>' + h.actionButton(state.meetingAiBusy ? '正在整理…' : '一键整理并保存纪要','meeting-ai-draft','spark','primary','data-id="' + h.esc(meeting.id) + '" ' + (state.meetingAiBusy ? 'disabled' : '')) + '</div></div>';
    const form = '<form id="meeting-summary-form" data-id="' + h.esc(meeting.id) + '"><div class="field mt-18"><label for="meeting-summary">可编辑会议纪要</label><textarea id="meeting-summary" name="summary" class="summary-textarea" placeholder="生成后可直接编辑；自动保存。">' + h.esc(summary) + '</textarea></div><div class="row wrap"><span class="tiny muted" id="meeting-save-state">' + h.esc(state.meetingSaveState || '本机自动保存，并同步项目文件') + '</span><span class="spacer"></span>' + h.actionButton('Word','meeting-export','download','small soft','data-id="' + h.esc(meeting.id) + '" data-format="docx"') + h.actionButton('PDF','meeting-export','download','small primary','data-id="' + h.esc(meeting.id) + '" data-format="pdf"') + '</div></form>';
    const tasks = relatedTasks.length ? '<div class="subsection-title"><h3>已识别行动 (' + relatedTasks.length + ')</h3></div>' + relatedTasks.map(task => '<div class="task-line"><span class="tag ' + (task.status === '完成' ? 'green' : 'blue') + '">' + h.esc(task.status) + '</span><span class="task-title">' + h.esc(task.title) + '</span></div>').join('') : '';
    return header + transcript + intake + warnings + form + tasks + '</div></section>';
  }

  async function generateExpertNotes(id,button){
    const meeting=record('meetings',id);if(!meeting)return;
    const transcript=(view().meetingTranscriptDraft||'').trim()||String(meeting.transcript||'').trim();
    if(!transcript){notify('先粘贴或拖入逐字稿。',true);return;}
    await withBusy(button,'正在整理并保存…',async()=>{
      view().meetingAiBusy=true;render();
      try{
        const result=await api('/meeting-draft',{body:{provider:'deepseek',model_id:view().meetingModel||view().localModel||'deepseek-v4.1-flash',transcript,title:meeting.title,date:meeting.date,participants:meeting.participants}});
        const normalized=formatMinuteText(result.summary||'');
        await api('/meetings/'+encodeURIComponent(id),{method:'PATCH',body:{transcript,summary:normalized,experts:result.experts||[],matrix:result.matrix||{},contents:result.contents||[]}});
        view().drafts.set(String(id),{...result,summary:normalized,actions:result.actions||[]});
        await refreshData();notify('纪要已整理并自动保存。可编辑后直接导出 Word / PDF。');
      }finally{view().meetingAiBusy=false;render();}
    });
  }
  async function autoSaveMeeting(form){
    const id=form.dataset.id;const summary=$('#meeting-summary',form)?.value??'';const state=view();
    state.meetingSaveState='正在保存…';
    try{await api('/meetings/'+encodeURIComponent(id),{method:'PATCH',body:{summary}});const draft=state.drafts.get(String(id));if(draft)draft.summary=summary;state.meetingSaveState='已自动保存到本机与 OneDrive';const label=$('#meeting-save-state');if(label)label.textContent=state.meetingSaveState;}
    catch(error){state.meetingSaveState='保存失败：'+error.message;const label=$('#meeting-save-state');if(label)label.textContent=state.meetingSaveState;}
  }
  async function exportMeeting(id,format,button){
    const meeting=record('meetings',id);if(!meeting)return;
    const summary=$('#meeting-summary')?.value;
    if(summary!=null&&summary!==meeting.summary){await api('/meetings/'+encodeURIComponent(id),{method:'PATCH',body:{summary}});await refreshData();}
    const title=encodeURIComponent(meeting.title+' Expert Call Notes');
    await withBusy(button,'正在生成…',()=>download('/meeting-export/'+encodeURIComponent(id)+'?format='+format,title+(format==='pdf'?'.pdf':'.docx')));
  }
  async function generateMeetingDraft(id, button) {
    const meeting = record('meetings', id);
    if (!meeting?.transcript?.trim()) { notify('请先录入会议逐字稿。', true); return; }
    if (view().drafts.has(String(id)) && !await confirmDialog('重新生成规则草稿？', '这会替换页面中尚未保存的规则草稿及候选行动编辑，不影响已经创建的任务。', '重新生成')) return;
    await withBusy(button, '正在生成规则草稿…', async () => {
      const draft = await api('/meeting-draft', { body: { provider: 'rules', transcript: meeting.transcript } });
      view().drafts.set(String(id), { ...draft, actions: Array.isArray(draft.actions) ? draft.actions.map(action => ({ ...action })) : [] });
      render(); notify('规则草稿已生成。请核对、编辑纪要并逐项确认行动。');
    });
  }
  async function saveMeetingSummary(form) {
    const id = form.dataset.id; const summary = $('#meeting-summary', form).value.trim();
    await withBusy($('button[type="submit"]', form), '保存中…', async () => {
      await api(`/meetings/${encodeURIComponent(id)}`, { method: 'PATCH', body: { summary } });
      const draft = view().drafts.get(String(id)); if (draft) draft.summary = summary;
      await refreshData(); render(); notify('会议纪要已保存。');
    });
  }
  async function createMeetingTasks(form) {
    const id = form.dataset.id; const meeting = record('meetings', id); const draft = view().drafts.get(String(id));
    if (!meeting || !draft) return;
    const formData = new FormData(form); const indexes = formData.getAll('confirmed').map(Number);
    if (!indexes.length) { notify('请先逐项核实并勾选需要创建的行动项。', true); return; }
    const pending = indexes.map(index => ({ index, title: String(formData.get(`title-${index}`) || '').trim(), owner: String(formData.get(`owner-${index}`) || '').trim(), due: String(formData.get(`due-${index}`) || ''), action: draft.actions[index] })).filter(item => item.action && !item.action.created);
    if (pending.some(item => !item.title)) { notify('已选行动项的标题不能为空。', true); return; }
    if (!pending.length) { notify('这些行动项已经创建过任务。'); return; }
    await withBusy($('button[type="submit"]', form), '正在逐项创建…', async () => {
      let count = 0; let failure = null;
      for (const item of pending) {
        try {
          await api('/tasks', { body: { title: item.title, owner: item.owner, due: item.due, description: `会议行动项（已人工确认）\n\n原文：${item.action.source_quote || '未提供摘录'}`, project_id: meeting.project_id || '', meeting_id: meeting.id, status: '待办', priority: '中' } });
          Object.assign(item.action, { title: item.title, owner: item.owner, due: item.due, created: true }); count++;
        } catch (error) { failure = error; break; }
      }
      await refreshData(); render();
      if (count) notify(`已将 ${count} 个已确认行动项创建为任务。`);
      if (failure) throw failure;
    });
  }

  function renderMemory() {
    const state = view(); const memories = list('documents').filter(doc => doc.kind === 'memory');
    const categories = ['全部', ...new Set(['偏好', '方法', '会话', ...memories.map(doc => doc.category).filter(Boolean)])];
    const query = state.memoryQuery.toLowerCase();
    const filtered = memories.filter(doc => (state.memoryCategory === '全部' || doc.category === state.memoryCategory) && `${doc.title} ${doc.source_ref} ${doc.category}`.toLowerCase().includes(query));
    const importActions = app.workspace === 'personal' ? actionButton('导入记忆文件', 'memory-upload-files', 'upload', 'primary', app.uploadBusy ? 'disabled' : '') + actionButton('导入文件夹', 'memory-upload-folder', 'upload', 'soft', app.uploadBusy ? 'disabled' : '') + (app.boot?.memory_root_available ? actionButton('扫描已配置目录', 'memory-scan', 'refresh', 'small soft', app.uploadBusy ? 'disabled' : '') : '') : '';
    return heading('知识与记忆', 'YOUR KNOWLEDGE, CONNECTED', '把积累接入当下的工作，而不是再造一个信息孤岛。', importActions) +
      `<div class="section-gap">${banner('只读导入 · 不改动原文件 · 记忆禁止外发', app.workspace === 'personal' ? (app.boot?.memory_root_available ? '你可以导入指定文件/文件夹；另已配置扫描根目录。仅个人本地保存，凭证、隐藏文件及归档目录会跳过或脱敏，记忆只允许本地检索。' : '默认不扫描磁盘，所以之前看起来不可用。现在可直接选记忆文件或整个文件夹导入；不用配置路径，源文件不修改，记忆不会发送给 GPT/DSH。') : '当前展示合成记忆。扫描与导入真实记忆仅在个人工作区可用，不会将真实文件放进演示库。', '', 'lock')}</div>
      <div class="toolbar"><div class="tabs" aria-label="按记忆分类筛选">${categories.map(category => `<button type="button" class="tab${state.memoryCategory === category ? ' active' : ''}" data-action="memory-category" data-value="${esc(category)}">${esc(category)}</button>`).join('')}</div>${searchInput('memory-search', '搜索标题、来源、分类', state.memoryQuery)}</div><div class="memory-grid">${filtered.map(doc => `<article class="panel memory-card"><div class="row between"><span class="quick-icon">${icon('memory')}</span>${badge(doc.category || '未分类', 'green')}</div><button type="button" class="memory-title mt-12" data-action="document" data-id="${esc(doc.id)}">${esc(doc.title)}</button><p class="memory-source">${esc(doc.source_ref || '合成演示来源')}</p><div class="row between"><span class="tiny muted">只读导入副本</span><button type="button" class="text-button tiny" data-action="document" data-id="${esc(doc.id)}">查看原文 ${icon('arrow')}</button></div><div class="memory-footer"><span>导入 / 更新 ${esc(dateLabel(doc.updated_at || doc.created_at, true))}</span>${iconButton('删除导入副本', 'delete', 'trash', `data-collection="documents" data-id="${esc(doc.id)}"`, 'danger')}</div></article>`).join('')}</div>${!filtered.length ? `<section class="panel">${empty('memory', memories.length ? '没有符合筛选的记忆' : '连接你已经积累的知识', memories.length ? '可调整分类或搜索词。全文内容可通过 Ctrl+K 搜索。' : (app.workspace === 'personal' ? '选择 TXT、MD、PDF、DOCX、PPTX、XLSX 或 XLSM 文件，或一次选取整个文件夹。内容仅用于本地检索，原文件不修改，也不会外发。' : '演示空间仅展示合成记忆；切换到个人工作区后可导入自己的文件。'), app.workspace === 'personal' ? actionButton('选择记忆文件', 'memory-upload-files', 'upload', 'primary') + actionButton('选择文件夹', 'memory-upload-folder', 'upload', 'soft') : '')}</section>` : ''}`;
  }
  async function scanMemory(button) {
    if (app.workspace !== 'personal') { notify('真实记忆仅能导入个人工作区。请先切换到个人工作区。', true); return; }
    await withBusy(button, '正在扫描…', async () => {
      const scan = await api('/memory/scan'); const files = Array.isArray(scan.files) ? scan.files : [];
      const skipped = Array.isArray(scan.skipped) ? scan.skipped.length : Number(scan.skipped) || 0;
      const body = `${banner('扫描只返回文件列表，不发送任何内容', `${files.length} 个文件可导入，${skipped} 个项目已跳过。请检查来源并选择要导入的文件。`, '', 'lock')}${files.length ? `<div class="row mt-18"><input type="checkbox" id="memory-select-all"><label for="memory-select-all" class="small muted">选择列表中的全部文件</label></div><div class="scan-list">${files.map(file => `<label class="scan-item"><input type="checkbox" name="paths" value="${esc(file.path)}"><span class="scan-copy"><strong>${esc(file.title || file.path)}</strong><small>${esc(file.path)}</small><small>${esc(file.category || '未分类')} · ${number(Number(file.size || 0) / 1024)} KB · ${esc(dateLabel(file.modified, true))}</small></span></label>`).join('')}</div>` : empty('memory', scan.root_available ? '未发现可导入文件' : '当前记忆根目录不可用', '不会自动查找其他目录。请设置 WORKOS_MEMORY_ROOT 为你选择的文件夹绝对路径，再重启服务。', '', true)}<p class="inline-note mt-12">重复扫描不会反复创建相同记录；内容发生变化时更新导入副本。</p><div class="mb-15"></div>`;
      const dialog = openModal('导入当前知识与记忆', body, async form => {
        const paths = form.getAll('paths'); if (!paths.length) throw new Error('请至少选择一个允许导入的文件。');
        const result = await api('/memory/import', { body: { paths } });
        const count = value => Array.isArray(value) ? value.length : Number(value) || 0;
        await refreshData(); render(); notify(`导入完成：新增 ${count(result.imported)}，更新 ${count(result.updated)}，未变化 ${count(result.unchanged)}，跳过 ${count(result.skipped)}。`);
      }, { wide: true, submitText: '导入选中记忆', busyText: '正在导入…' });
      if (!files.length) $('#modal-submit').disabled = true;
      $('#memory-select-all', dialog)?.addEventListener('change', event => { $$('input[name="paths"]', dialog).forEach(input => { input.checked = event.target.checked; }); });
    });
  }

  function renderFinance() {
    return window.LocalWorkOSValuation.render({ state: view(), boot: app.boot, helpers: { heading, actionButton, icon, banner, empty, esc, projectOptions, selectedAttr, dshModelOptions, number, percent } });
    const state = view(); const result = state.financeResult;
    return heading('回报测算', 'ASSUMPTIONS, NOT PROMISES', '所有数字由本地代码计算。展示假设、公式与边界，不让模型代算。', actionButton('保存测算简报', 'finance-deliverable', 'deliverables', '', !result || state.financeDirty ? 'disabled title="请先用当前假设完成测算"' : '')) +
      `<div class="section-gap">${banner('简化权益回报模型 · 非完整 LBO', '单位：人民币百万元。不包含税务、营运资本明细、交易费用及完整债务契约；情景和敏感性不是收益承诺。现金流、IRR / MOIC 的定义请查看下方公式。', 'amber', 'info')}</div>
      <div class="finance-layout"><section class="panel assumption-panel"><h2>核心假设</h2><p>百分比在界面输入，提交时转换为小数。</p><form id="finance-form"><fieldset ${state.financePending ? 'disabled' : ''}><div class="assumption-fields">${FINANCE_FIELDS.map(([key, label, unit, min, max, step]) => `<div class="field"><label for="assumption-${key}">${label}</label><div class="input-unit"><input id="assumption-${key}" type="number" name="${key}" required min="${min}" max="${max}" step="${step}" value="${Number((state.finance[key] * (PERCENT_FIELDS.has(key) ? 100 : 1)).toFixed(6))}"><span>${unit}</span></div></div>`).join('')}</div><button type="submit" class="button primary full">${state.financePending ? '<span class="spinner"></span>正在计算…' : icon('finance') + '运行本地测算'}</button>${actionButton('恢复默认假设', 'finance-reset', 'refresh', 'ghost small full mt-12')}</fieldset><p class="inline-note mt-12" id="finance-dirty-note">仅假设数值按工作区保存在本机。${state.financeDirty ? '假设已改变，请重新计算。' : '修改后点击运行，更新右侧结果。'}</p></form></section><div class="stack">${state.financeError ? banner('测算未完成', state.financeError, 'error', 'warning') : ''}${result ? renderFinanceResult(result, state.financeDirty) : `<section class="panel">${state.financePending ? loading('正在计算现金流、IRR 与敏感性…') : empty('finance', '用一致的假设，检验不同情景', '输入核心假设并运行测算。结果来自本地计算接口，不展示模拟占位数字。')}</section>`}</div></div>`;
  }
  function renderFinanceResult(result, dirty) {
    const rows = Array.isArray(result.base?.rows) ? result.base.rows : [];
    const sensitivity = result.sensitivity || {};
    let formulas = '';
    if (Array.isArray(result.formulas)) formulas = result.formulas.map(value => `<p>${esc(typeof value === 'string' ? value : JSON.stringify(value))}</p>`).join('');
    else if (result.formulas && typeof result.formulas === 'object') formulas = Object.entries(result.formulas).map(([key, value]) => `<p><strong>${esc(key)}</strong>：${esc(typeof value === 'string' ? value : JSON.stringify(value))}</p>`).join('');
    else formulas = esc(result.formulas || '请以服务端返回的计算口径为准。');
    return `${dirty ? banner('', '当前展示上一次已完成的测算。新假设尚未计算，不可直接保存为简报。', 'amber', 'warning') : ''}<div class="scenario-grid">${[['bear', '保守情景'], ['base', '基准情景'], ['bull', '乐观情景']].map(([key, label]) => `<section class="scenario-card ${key === 'base' ? 'base' : ''}"><div class="scenario-label">${label} · 股权 IRR</div><div class="scenario-irr">${percent(result[key]?.irr)}</div><div class="scenario-moic">MOIC <b>${number(result[key]?.moic)}×</b></div><div class="scenario-sub">${key === 'base' ? '基于当前已计算假设' : '按后端情景规则计算'}</div></section>`).join('')}</div>
      <section class="panel">${panelTitle('基准现金流', 'finance', '<span class="tiny muted">人民币百万元</span>')}<div class="table-scroll"><table><thead><tr><th>年份</th><th class="number">收入</th><th class="number">EBITDA</th><th class="number">利息</th><th class="number">现金流</th><th class="number">债务</th></tr></thead><tbody>${rows.map(row => `<tr><td>第 ${esc(row.year)} 年</td><td class="number">${number(row.revenue)}</td><td class="number">${number(row.ebitda)}</td><td class="number">${number(row.interest)}</td><td class="number">${number(row.cash_flow)}</td><td class="number">${number(row.debt)}</td></tr>`).join('') || '<tr><td colspan="6">服务端未返回逐年现金流。</td></tr>'}</tbody></table></div><div class="finance-stats"><div><span>进入企业价值 EV</span><b>${number(result.base?.entry_ev)}</b></div><div><span>初始股权投入</span><b>${number(result.base?.entry_equity)}</b></div><div><span>退出股权价值</span><b>${number(result.base?.exit_equity)}</b></div></div></section>
      <section class="panel">${panelTitle('敏感性 · 股权 IRR', 'grid', '<span class="tiny muted">增长率 × 退出倍数</span>')}<div class="table-scroll"><table class="sensitivity-table"><thead><tr><th>增长率 / 退出倍数</th>${(sensitivity.columns || []).map(value => `<th>${number(value)}×</th>`).join('')}</tr></thead><tbody>${(sensitivity.rows || []).map((growth, rowIndex) => `<tr><th>${percent(growth)}</th>${(sensitivity.values?.[rowIndex] || []).map(value => `<td class="heat-cell">${percent(value)}</td>`).join('')}</tr>`).join('') || '<tr><td>本次未返回敏感性数据。</td></tr>'}</tbody></table></div></section>
      <section class="panel">${panelTitle('计算口径与简化边界', 'info')}<div class="panel-body"><div class="formula-list">${formulas}</div>${result.warning ? `<div class="mt-18">${banner('', typeof result.warning === 'string' ? result.warning : JSON.stringify(result.warning), 'amber', 'warning')}</div>` : ''}</div></section>`;
  }
  async function calculateFinance() {
    const state = view(); if (state.financePending) return;
    const form = $('#finance-form');
    if (form && !form.reportValidity()) return;
    if (form) {
      const fields = new FormData(form);
      for (const [key] of FINANCE_FIELDS) state.finance[key] = Number(fields.get(key)) / (PERCENT_FIELDS.has(key) ? 100 : 1);
    }
    state.financePending = true; state.financeError = ''; persistFinance(); render();
    try { state.financeResult = await api('/model/calculate', { body: { ...state.finance } }); state.financeDirty = false; }
    catch (error) { if (error.name !== 'StaleRequestError') state.financeError = error.message; }
    finally { state.financePending = false; if (view() === state && app.page === 'finance') render(); }
  }

  async function parseValuationAssumptions() {
    const state = view(); if (state.valuationPending) return;
    const text = $('#valuation-text')?.value.trim() || ''; state.valuationText = text;
    if (!text) { notify('请先用自然语言描述交易和主要假设。', true); return; }
    state.valuationPending = true; state.valuationError = ''; state.valuationResult = null; render();
    try {
      const result = await api('/model/parse-assumptions', { body: { method: state.valuationMethod, text, model_id: state.valuationModel || 'gpt-6-luna', allow_external: true } });
      state.valuationProposal = result; state.valuationJson = JSON.stringify(result.assumptions || {}, null, 2);
    } catch (error) { if (error.name !== 'StaleRequestError') state.valuationError = error.message; }
    finally { state.valuationPending = false; if (view() === state && app.page === 'finance') render(); }
  }
  async function calculateValuation() {
    const state = view(); if (state.valuationPending) return;
    const text = $('#valuation-json')?.value || state.valuationJson;
    let assumptions;
    try { assumptions = JSON.parse(text || '{}'); }
    catch { notify('结构化假设 JSON 格式不正确。', true); return; }
    state.valuationJson = text; state.valuationPending = true; state.valuationError = ''; state.valuationResult = null; render();
    try { state.valuationResult = await api('/model/valuation', { body: { method: state.valuationMethod, assumptions } }); state.valuationAssumptions = assumptions; }
    catch (error) { if (error.name !== 'StaleRequestError') state.valuationError = error.message; }
    finally { state.valuationPending = false; if (view() === state && app.page === 'finance') render(); }
  }
  async function exportValuationXlsx(button){
    const state=view();if(!state.valuationResult||!state.valuationAssumptions){notify('请先计算估值结果。',true);return;}
    const title=(state.valuationResult.method_label||'Valuation Model')+' '+today();
    await withBusy(button,'正在生成 Excel…',()=>download('/model/export-xlsx',title+'.xlsx',{method:'POST',body:{method:state.valuationMethod,assumptions:state.valuationAssumptions,title}}));
  }
  async function saveValuation() {
    const state = view(); if (!state.valuationResult || !state.valuationAssumptions) return;
    const result = state.valuationResult; const assumptions = state.valuationAssumptions;
    const body = ['# '+result.method_label, '', '## 假设（用户确认）', 'JSON:', JSON.stringify(assumptions, null, 2), '', '## 计算结果', 'JSON:', JSON.stringify(result, null, 2), '', '> 模型计算为确定性输出；源假设需回到项目资料核实。'].join('\n');
    const title = result.method_label + ' · ' + today();
    await withBusy($('[data-action="valuation-save"]'), '正在保存…', async () => {
      await api('/deliverables', { body: { title, kind: '自定义', project_id: state.valuationProjectId || '', body, method:state.valuationMethod, assumptions, result } });
      await refreshData(); notify('模型快照已保存到交付中心。');
    });
  }
  function loadValuationTemplate() {
    const state = view(); const templates = window.LocalWorkOSValuation?.templates || {};
    state.valuationText = templates[state.valuationMethod] || ''; state.valuationProposal = null; state.valuationJson = ''; state.valuationResult = null; state.valuationError = '';
    render(); requestAnimationFrame(() => $('#valuation-text')?.focus());
  }
  async function loadSavedModel(id){
    if(view().valuationPending){notify('当前模型还在处理，请稍后再打开。',true);return;}
    const item=record('deliverables',id);
    if(!item?.method||!item.assumptions||!item.result){notify('这份交付没有保存可恢复的模型假设。',true);return;}
    if(!await navigate('finance'))return;
    const state=view();state.valuationMethod=item.method;state.valuationJson=JSON.stringify(item.assumptions,null,2);state.valuationAssumptions=item.assumptions;state.valuationResult=item.result;state.valuationProjectId=item.project_id||'';state.valuationProposal={assumptions:item.assumptions,missing:[],unmapped_fields:[]};state.valuationText='';state.valuationError='';state.valuationPending=false;state.valuationScenarioResult=null;state.valuationScenariosJson='';
    render();notify('模型与原假设已恢复，可修改后重新计算。');
  }
  function presetValuationScenarios(){
    const state=view();if(state.valuationPending)return false;
    if(!state.valuationAssumptions||!window.LocalWorkOSValuation?.presetScenarios){notify('先完成基准模型计算，再比较情景。',true);return false;}
    const scenarios=window.LocalWorkOSValuation.presetScenarios(state.valuationMethod,state.valuationAssumptions);
    if(!scenarios.length){notify('基准模型缺少可比较的倍数或折现率，请先补充假设。',true);return false;}
    state.valuationScenariosJson=JSON.stringify(scenarios,null,2);state.valuationScenarioResult=null;render();return true;
  }
  async function calculateValuationScenarios(){
    const state=view();if(state.valuationPending||!state.valuationAssumptions)return;
    let scenarios;try{scenarios=JSON.parse($('#valuation-scenarios-json')?.value||state.valuationScenariosJson||'[]');}catch{notify('情景格式不正确，请检查后重试。',true);return;}
    state.valuationScenariosJson=JSON.stringify(scenarios,null,2);state.valuationPending=true;state.valuationError='';state.valuationScenarioResult=null;render();
    try{state.valuationScenarioResult=await api('/model/scenarios',{body:{method:state.valuationMethod,assumptions:state.valuationAssumptions,scenarios}});}catch(error){if(error.name!=='StaleRequestError')state.valuationError=error.message;}
    finally{state.valuationPending=false;if(view()===state&&app.page==='finance')render();}
  }
  function renderDeliverables() {
    const state = view(); const items = [...list('deliverables')].sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    if (!items.some(item => String(item.id) === String(state.deliverableId))) state.deliverableId = items[0]?.id || '';
    const saved = record('deliverables', state.deliverableId);
    const selected = saved && state.deliverableDirty && String(state.deliverableDraft?.id) === String(saved.id) ? { ...saved, ...state.deliverableDraft } : saved;
    const draftReport=selected&&state.deliverableDirty&&selected.body!==saved.body&&Object.keys(selected.quality_report||{}).length?staleQualityReport(selected.quality_report):selected?.quality_report;
    return heading('交付中心', 'TURN INSIGHT INTO OUTPUT', '把研究、会议与项目推进，整理成可以继续编辑的工作成果。', actionButton('备份工作区', 'backup', 'database') + actionButton('新建交付', 'create', 'plus', 'primary', 'data-collection="deliverables"')) +
      `<div class="split-layout"><section class="panel">${panelTitle('我的交付', 'deliverables', `<span class="count-pill">${items.length}</span>`)}<div class="record-list">${items.length ? items.map(item => `<button type="button" class="record-item${String(item.id) === String(state.deliverableId) ? ' active' : ''}" data-action="select-deliverable" data-id="${esc(item.id)}"><h3>${esc(item.title)}</h3><p>${esc(item.method ? '财务模型' : item.kind)} · ${esc(projectName(item.project_id))}</p><span class="record-date">更新于 ${esc(dateLabel(item.updated_at, true))}</span></button>${item.method && item.assumptions && item.result ? actionButton('打开模型','model-load','finance','small ghost',`data-id="${esc(item.id)}"`) : ''}`).join('') : empty('deliverables', '还没有保存的交付', '研究结论、会议纪要和测算均可转成可编辑交付。', '', true)}</div></section><section class="panel">${selected ? `<form id="deliverable-form" class="deliverable-editor" data-id="${esc(selected.id)}"><label for="deliverable-title" class="sr-only">交付标题</label><input id="deliverable-title" name="title" class="editor-title" required maxlength="300" value="${esc(selected.title)}" placeholder="交付标题"><div class="editor-meta"><label class="sr-only" for="deliverable-kind">交付类型</label><select id="deliverable-kind" name="kind">${deliverableKindOptions(selected.kind)}</select><label class="sr-only" for="deliverable-project">关联项目</label><select id="deliverable-project" name="project_id">${projectOptions(selected.project_id)}</select></div><label for="deliverable-body" class="sr-only">交付正文</label><textarea id="deliverable-body" name="body" class="editor-body" spellcheck="false" placeholder="开始写作，支持纯文本与 Markdown 内容。">${esc(selected.body)}</textarea><div class="editor-bar"><div class="row"><button type="submit" class="button primary">${icon('check')}保存修改</button><span class="save-state" id="deliverable-save-state">已保存 · ${String(selected.body || '').length} 字</span></div>${iconButton('删除此交付', 'delete', 'trash', `data-collection="deliverables" data-id="${esc(selected.id)}"`, 'danger')}</div>${renderQualityReport(draftReport,selected.coverage||[])}<div class="separator"></div>${selected.method && selected.assumptions && selected.result ? `<div class="row wrap mb-15">${actionButton('恢复模型并继续计算','model-load','finance','soft',`data-id="${esc(selected.id)}"`)}</div>` : ''}<div class="row wrap"><span class="tiny muted spacer">导出前会先保存当前编辑</span>${actionButton('Markdown', 'export', 'download', 'small', `data-id="${esc(selected.id)}" data-format="md"`)}${actionButton('可编辑 HTML', 'export', 'download', 'small', `data-id="${esc(selected.id)}" data-format="html"`)}${actionButton('Word', 'export', 'download', 'small', `data-id="${esc(selected.id)}" data-format="docx"`)}${actionButton('PPTX', 'export', 'download', 'small primary', `data-id="${esc(selected.id)}" data-format="pptx"`)}</div><p class="inline-note mt-12">HTML 为单文件交付，可编辑、添加批注并保存修改；导出文件中的修改不会自动回写本地工作区。正文不执行 HTML 或脚本。PPTX 支持可编辑 Markdown 表格，以及提供明确数据的 chart JSON 图表块；不会补造数值。</p></form>` : empty('deliverables', '把一个清晰的判断，变成一份交付', '可从研究结论、会议纪要、项目详情和回报测算生成草稿，或从空白开始。所有正文都可继续编辑。', actionButton('新建交付', 'create', 'plus', 'primary', 'data-collection="deliverables"'))}</section></div>`;
  }
  async function saveDeliverable(form) {
    const state = view();
    if (state.deliverableSaving || !form?.reportValidity()) return false;
    const payload = Object.fromEntries(new FormData(form).entries());
    if (!String(payload.title).trim()) throw new Error('交付标题不能为空。');
    payload.title = String(payload.title).trim(); state.deliverableSaving = true;
    $$('input,textarea,select,button', form).forEach(element => { element.disabled = true; });
    try {
      await api(`/deliverables/${encodeURIComponent(form.dataset.id)}`, { method: 'PATCH', body: payload });
      state.deliverableDirty = false; state.deliverableDraft = null; await refreshData(); return true;
    } finally { state.deliverableSaving = false; if (view() === state && app.page === 'deliverables') render(); else renderShell(); }
  }
  async function download(path, fallbackName, request = {}) {
    const response = await api(path, { ...request, raw: true }); const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    let filename = fallbackName;
    try { const utf = disposition.match(/filename\*=UTF-8''([^;]+)/i); const ascii = disposition.match(/filename="?([^";]+)"?/i); if (utf) filename = decodeURIComponent(utf[1]); else if (ascii) filename = ascii[1]; } catch { /* Fall back to the safe local title. */ }
    filename = String(filename).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 180);
    const url = URL.createObjectURL(blob); const link = document.createElement('a');
    link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000); notify('文件已生成，下载已交给浏览器。');
  }
  async function exportDeliverable(id, format, button) {
    if (!['md', 'html', 'docx', 'pptx'].includes(format)) return;
    await withBusy(button, '正在导出…', async () => {
      if (view().deliverableDirty && !await saveDeliverable($('#deliverable-form'))) return;
      const item = record('deliverables', id); if (!item) throw new Error('交付记录不存在。');
      await download(`/export/${encodeURIComponent(id)}?format=${format}`, `${item.title}.${format}`);
    });
  }
  async function restoreBackup(file) {
    if (!file) return;
    try {
      if (file.size > 64 * 1024 * 1024) throw new Error('备份文件过大，浏览器仅接收 64 MB 以内的 JSON 备份。');
      let backup; try { backup = JSON.parse(await file.text()); } catch { throw new Error('无法解析备份，请选择有效的 Local WorkOS JSON 备份。'); }
      if (backup.format !== 'local-workos' || backup.version !== 1 || !backup.data) throw new Error('不是受支持的 Local WorkOS v1 备份。');
      if (backup.workspace !== app.workspace) throw new Error(`此备份属于${backup.workspace === 'demo' ? '演示' : '个人'}工作区。请先切换到对应工作区再恢复，不允许跨工作区混入数据。`);
      const count = Object.values(backup.data).filter(Array.isArray).reduce((total, items) => total + items.length, 0);
      openModal('恢复当前工作区备份', `${banner('将替换当前工作区数据', '服务端校验后事务恢复，并先备份当前数据库。另一工作区不受影响。', 'amber', 'warning')}<p class="confirm-copy mt-18">文件：${esc(file.name)}<br>目标：${workspaceName()}<br>备份导出时间：${esc(backup.exported_at || '未知')}<br>记录总数（含活动）：${count}</p><label class="consent mb-15"><input type="checkbox" name="confirmed" required><span>我确认用此备份替换当前${workspaceName()}。</span></label>`, async form => {
        if (!form.get('confirmed')) throw new Error('请明确勾选恢复确认。');
        const result = await api('/restore', { body: { backup, confirm: true } });
        if (!result.restored) throw new Error('服务端没有确认恢复完成。');
        views.delete(app.workspace); await refreshData(); render(); notify('当前工作区已恢复，另一工作区未改变。');
      }, { submitText: '确认替换并恢复', danger: true, busyText: '正在事务恢复…' });
    } catch (error) { showError(error); }
    finally { $('#restore-input').value = ''; }
  }
  function renderSettings() {
    const ai = app.boot?.ai || {}; const sync = app.boot?.sync || {}; const personalSync = sync.workspaces?.personal || {};
    return heading('设置与连接', 'LOCAL BY DEFAULT', '工作区、可选模型与数据安全，在这里保持透明。') +
      `<div class="settings-grid"><div class="stack"><section class="panel settings-section"><h2>你的工作区</h2><p>默认打开个人空间。演示仅包含合成记录；两套本地数据库完全隔离。</p><div class="mode-options">${[['personal', '个人工作区', '我的项目、资料与稳定记忆', 'user'], ['demo', '演示工作区', '合成示例，可安全体验完整流程', 'briefcase']].map(([mode, title, text, symbol]) => `<button type="button" class="mode-card${app.workspace === mode ? ' active' : ''}" data-action="workspace" data-workspace="${mode}" aria-pressed="${app.workspace === mode}">${icon(symbol)}<strong>${title}${app.workspace === mode ? ' · 当前' : ''}</strong><small>${text}</small></button>`).join('')}</div></section>
      <section class="panel settings-section"><h2>GPT / DSH 模型</h2><p>研究页默认通过本机 DSH 调用 ChatGPT，不用在 WorkOS 粘贴 API Key；OAuth 凭据留在 DSH。也可切换本地证据检索，或连接其他兼容模型。</p><div class="model-state"><span class="status-dot"></span>${app.boot?.dsh?.available ? `DSH 已接入 · 默认 ${esc((app.boot.dsh.models || []).find(item => item.id === app.boot.dsh.model)?.name || "GPT-6 Luna")}` : "未检测到 DSH；仍可使用本地检索或其他兼容模型。"}</div><p>研究页显示本次资料范围；提交问题时仅发送已勾选的证据片段，个人记忆只做本地检索。</p><h3>其他兼容模型（可选）</h3><p>兼容 OpenAI Chat Completions。此配置仅在本次 WorkOS 服务进程内存，不保存密钥；连接需要由你自行配置。</p><div class="model-state"><span class="status-dot"></span>${ai.configured ? `已配置 ${esc(ai.model || '')} · 不代表已验证连通` : '未配置外部模型 · 当前离线工作'}</div><form id="ai-settings-form" autocomplete="off"><div class="field"><label for="ai-base-url">Base URL</label><input id="ai-base-url" name="base_url" type="url" required value="${esc(ai.base_url || '')}" placeholder="https://你的服务地址/v1" autocomplete="off"></div><div class="field"><label for="ai-model">模型名称</label><input id="ai-model" name="model" required value="${esc(ai.model || '')}" placeholder="填写服务商提供的模型标识" autocomplete="off"></div><div class="field"><label for="ai-api-key">API Key · 仅服务器进程内存</label><input id="ai-api-key" name="api_key" type="password" required placeholder="重新输入密钥后保存，不回显已有密钥" autocomplete="new-password" spellcheck="false"><span class="hint">输入不会写入浏览器存储或备份；提交后清空，服务重启后需重新填写。</span></div><button type="submit" class="button primary">${icon('lock')}保存连接，不测试网络</button></form><div class="mt-18">${banner('按你选定的资料范围回答', '提交问题时，仅选中的非记忆资料可外发。个人记忆始终只用于本地检索。', 'amber', 'shield')}</div></section></div>
      <div class="stack"><section class="panel settings-section"><h2>本地服务</h2><p>仅供本机单用户使用，不是云端或多人协作系统。</p><dl class="settings-dl"><div class="settings-row"><dt>服务状态</dt><dd><span class="tag green">已连接本地服务</span></dd></div><div class="settings-row"><dt>版本</dt><dd>${esc(app.boot?.version || '1.3')}</dd></div><div class="settings-row"><dt>当前工作区</dt><dd>${workspaceName()}</dd></div><div class="settings-row"><dt>数据目录</dt><dd>${esc(app.boot?.data_dir || '由本地服务管理')}</dd></div><div class="settings-row"><dt>记忆根目录</dt><dd>${app.boot?.memory_root_available ? '可用 · 需手动扫描导入' : '当前不可用'}</dd></div></dl><div class="mt-18">${actionButton('刷新服务状态', 'refresh-status', 'refresh', 'small')}${app.boot?.auth?.public_login ? actionButton('退出公网登录', 'logout-public', 'lock', 'small soft') : ''}</div></section>
      <section class="panel settings-section"><h2>OneDrive 项目文件同步</h2><p>主机是唯一写入端；项目元数据、已导入资料文本、原文件、会议/研究/交付记录和 JSON 快照会在保存时镜像到 OneDrive 的 AI Agent/Local WorkOS。活动中的 SQLite/WAL 保留在本机，避免 OneDrive 文件锁与并发同步损坏；其他设备可经远程入口使用同一主机。</p><div class="model-state"><span class="status-dot"></span>${sync.enabled ? (sync.error ? esc(sync.error) : '已配置 · ' + Number(personalSync.counts?.projects || 0) + ' 个项目 · ' + Number(personalSync.counts?.documents || 0) + ' 份资料') : '未配置 OneDrive 同步根目录'}</div><div class="mt-18">${actionButton('立即同步', 'sync-onedrive', 'refresh', 'small', !sync.enabled ? 'disabled' : '')}</div><p class="inline-note mt-12">OneDrive 镜像包含原文件；旧记录若未保存原文件，需要重新导入后才能下载。${Number(sync.missing_originals_by_workspace?.[app.workspace] || 0) ? '当前有 ' + Number(personalSync.missing_originals) + ' 份原文件缺失，请重新导入。' : ''}不要手动替换活动中的 .sqlite3/WAL 文件。</p></section>

      <section class="panel settings-section"><h2>数据备份与恢复</h2><p>导出当前工作区的 JSON 备份，不包含 API Key。备份包含记录、解析文本与记忆副本，不包含原文件的二进制内容。请同时保留本机附件目录或 OneDrive 原文件镜像。</p><div class="row wrap">${actionButton('导出当前备份', 'backup', 'download', 'soft')}${actionButton('选择备份恢复', 'restore', 'upload')}</div><p class="inline-note mt-18">恢复前校验格式、关联和大小；服务端先备份现有数据库，再事务替换当前工作区。不跨工作区恢复。</p></section>
      <section class="panel settings-section"><h2>隐私边界</h2><p class="no-margin">无遥测；OneDrive 仅同步本地项目文件镜像与 JSON 快照，不同步活动 SQLite/WAL，也不发送记忆给模型。不连接邮箱、微信、日历，不录音、不发邮件。记忆连接器不扫描凭证、浏览器配置、机器环境或设备配置。</p></section>
      <section class="panel settings-section danger-zone"><h2>关闭本地服务</h2><p>仅停止 Local WorkOS 当前服务。数据保留，但页面将失去连接；再次使用需重新运行启动器。</p>${actionButton('关闭服务', 'shutdown', 'logout', 'danger small')}</section></div></div>`;
  }
  async function saveAISettings(form) {
    if (!form.reportValidity()) return;
    const payload = { base_url: $('#ai-base-url').value.trim(), model: $('#ai-model').value.trim(), api_key: $('#ai-api-key').value };
    $('#ai-api-key').value = '';
    await withBusy($('button[type="submit"]', form), '正在保存到进程内存…', async () => {
      const result = await api('/ai/settings', { body: payload }); payload.api_key = '';
      app.boot.ai = result.ai || result; render(); notify('连接配置已保存到服务器内存，未测试网络、未发送资料。');
    });
    payload.api_key = '';
  }

  // Linked documents are generated as editable drafts, never as claims of verified facts.
  async function deliverFromNote(id) {
    const note = record('notes', id); if (!note) return;
    await editRecord('deliverables', '', { title: note.title, project_id: note.project_id || '', kind: '研究简报', body: `# ${note.title}\n\n核实状态：${note.status}\n关联项目：${projectName(note.project_id)}\n\n## 研究结论\n${note.body || ''}\n\n## 证据与来源\n${note.source_quote || '尚未记录，请补充证据。'}${note.document_id ? `\n\n来源材料：${record('documents', note.document_id)?.title || note.document_id}` : ''}\n\n## 仍需核实\n${note.status === '已核实' ? '请在交付前再次检查证据的时效性与适用范围。' : '本条结论尚未完成核实，不应作为已确认事实。'}` });
  }
  async function deliverFromMeeting(id) {
    const meeting = record('meetings', id); if (!meeting) return;
    const summary = $('#meeting-summary')?.value ?? view().drafts.get(String(id))?.summary ?? meeting.summary;
    const tasks = list('tasks').filter(task => String(task.meeting_id) === String(id));
    await editRecord('deliverables', '', { title: `${meeting.title} · 纪要`, project_id: meeting.project_id || '', kind: '会议纪要', body: `# ${meeting.title}\n\n日期：${meeting.date || '未设置'}\n参会人：${meeting.participants || '未记录'}\n项目：${projectName(meeting.project_id)}\n\n## 会议纪要\n${summary || '请补充会议纪要。'}\n\n## 已确认并创建的行动项\n${tasks.length ? tasks.map(task => `- [${task.status === '完成' ? 'x' : ' '}] ${task.title}｜${task.owner || '未分配'}｜${task.due || '未定日期'}｜${task.status}`).join('\n') : '暂无已确认任务。候选行动不代表承诺。'}\n\n说明：会议草稿使用确定性规则整理，请核对原文。` });
  }
  async function deliverFromProject(id) {
    const project = record('projects', id); if (!project) return;
    const tasks = list('tasks').filter(task => String(task.project_id) === String(id)); const notes = list('notes').filter(note => String(note.project_id) === String(id));
    await editRecord('deliverables', '', { title: `${project.name} · 项目简报`, project_id: id, kind: '项目周报', body: `# ${project.name} · 项目简报\n\n日期：${today()}\n阶段：${project.stage}\n行业：${project.sector || '未设置'}\n负责人：${project.owner || '未分配'}\n估值备注：${project.valuation || '未设置'}\n\n## 核心判断\n${project.thesis || '待补充'}\n\n## 下一步\n${project.next_step || '待补充'}\n\n## 研究结论\n${notes.map(note => `- ${note.title}（${note.status}）\n  ${note.body}`).join('\n') || '暂无'}\n\n## 任务进展\n${tasks.map(task => `- [${task.status === '完成' ? 'x' : ' '}] ${task.title}｜${task.status}｜${task.due || '未定日期'}`).join('\n') || '暂无'}` });
  }
  async function deliverFromFinance() {
    const state = view(); const result = state.financeResult;
    if (!result || state.financeDirty) { notify('请先用当前假设重新计算。', true); return; }
    const assumptions = FINANCE_FIELDS.map(([key, label, unit]) => `${label}：${number(state.finance[key] * (PERCENT_FIELDS.has(key) ? 100 : 1))} ${unit}`).join('\n');
    await editRecord('deliverables', '', { title: `简化回报测算 · ${today()}`, kind: '自定义', body: `# 简化权益回报测算\n\n人民币百万元 · 非完整 LBO · 非投资建议\n\n## 假设\n${assumptions}\n\n## 情景结果\n${[['bear', '保守'], ['base', '基准'], ['bull', '乐观']].map(([key, label]) => `${label}：IRR ${percent(result[key]?.irr)}；MOIC ${number(result[key]?.moic)}×`).join('\n')}\n\n## 基准股权价值\n进入EV：${number(result.base?.entry_ev)}\n初始股权投入：${number(result.base?.entry_equity)}\n退出股权价值：${number(result.base?.exit_equity)}\n\n## 计算口径\n${typeof result.formulas === 'string' ? result.formulas : JSON.stringify(result.formulas, null, 2)}\n\n## 简化边界\n${typeof result.warning === 'string' ? result.warning : JSON.stringify(result.warning || '')}` });
  }

  // Global search is explicitly scoped to the current workspace by the shared API client.
  let searchTimer = null; let searchSequence = 0;
  function openSearch() {
    if (!app.data || app.stopped) return;
    const dialog = $('#search-dialog');
    if (dialog.open) { $('#global-search').focus(); return; }
    dialog.innerHTML = `<div class="search-dialog-top">${icon('search')}<label class="sr-only" for="global-search">搜索工作空间</label><input id="global-search" type="search" placeholder="搜索项目、材料原文、任务、会议…" autocomplete="off"><button type="button" class="icon-button" data-close-dialog="search-dialog" aria-label="关闭搜索"><kbd>Esc</kbd></button></div><div class="search-results" id="search-results">${empty('search', '让需要的信息，回到眼前', '输入关键词搜索当前工作区。结果中的材料可直接定位原文。', '', true)}</div><div class="search-footer"><span>${workspaceName()} · 只搜索本地业务记录</span><span>↑ ↓ 选择 · Enter 打开 · Esc 关闭</span></div>`;
    dialog.showModal(); $('#global-search').focus();
    $('#global-search').addEventListener('input', () => { clearTimeout(searchTimer); const query = $('#global-search').value.trim(); const sequence = ++searchSequence; searchTimer = setTimeout(() => runSearch(query, sequence), 180); });
    dialog.onkeydown = event => {
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      const buttons = $$('.search-result', dialog); if (!buttons.length) return;
      event.preventDefault(); const index = buttons.indexOf(document.activeElement);
      const next = event.key === 'ArrowDown' ? (index + 1) % buttons.length : (index <= 0 ? buttons.length - 1 : index - 1); buttons[next].focus();
    };
  }
  async function runSearch(query, sequence) {
    const resultsElement = $('#search-results'); if (!resultsElement || !$('#search-dialog').open) return;
    if (!query) { resultsElement.innerHTML = empty('search', '输入关键词开始搜索', '仅搜索当前工作区。', '', true); return; }
    resultsElement.innerHTML = loading('正在检索本地工作空间…');
    try {
      const result = await api(`/search?${new URLSearchParams({ q: query })}`);
      if (sequence !== searchSequence || !$('#search-dialog').open) return;
      const typeMap = { project: ['项目', 'projects', 'projects'], projects: ['项目', 'projects', 'projects'], task: ['任务', 'tasks', 'tasks'], tasks: ['任务', 'tasks', 'tasks'], document: ['资料', 'file', 'documents'], documents: ['资料', 'file', 'documents'], meeting: ['会议', 'meetings', 'meetings'], meetings: ['会议', 'meetings', 'meetings'], note: ['结论', 'book', 'notes'], notes: ['结论', 'book', 'notes'], deliverable: ['交付', 'deliverables', 'deliverables'], deliverables: ['交付', 'deliverables', 'deliverables'] };
      resultsElement.innerHTML = result.results?.length ? result.results.map(item => { const [label, symbol, collection] = typeMap[item.type] || ['记录', 'file', 'documents']; return `<button type="button" class="search-result" data-action="search-result" data-collection="${collection}" data-id="${esc(item.id)}">${icon(symbol)}<div><h3>${esc(item.title)}</h3><p>${esc(item.excerpt)}</p></div><span class="tag">${label}</span></button>`; }).join('') : empty('search', '未找到匹配记录', '试试更短的关键词，或确认当前工作区。', '', true);
    } catch (error) { if (sequence === searchSequence && $('#search-dialog').open) resultsElement.innerHTML = banner('搜索未完成', error.message, 'error', 'warning'); }
  }
  async function openRecord(collection, id) {
    if (collection === 'documents') return openDocument(id);
    if (collection === 'projects') { if (!await navigate('projects')) return; view().projectId = id; render(); requestAnimationFrame(() => $('#project-detail')?.scrollIntoView({ block: 'nearest' })); }
    else if (collection === 'tasks') { if (!await navigate('tasks')) return; view().taskProject = ''; view().taskQuery = ''; view().taskPriority = ''; view().highlightTask = id; render(); }
    else if (collection === 'meetings') { if (!await navigate('meetings')) return; view().meetingProject = ''; view().meetingId = id; render(); }
    else if (collection === 'notes') { if (!await navigate('research')) return; await editRecord('notes', id); }
    else if (collection === 'deliverables') { if (!await canLeave()) return; view().deliverableDirty = false; view().deliverableId = id; await navigate('deliverables'); }
  }

  // Page-specific bindings keep render functions side-effect free.
  function bindSearchInput(id, property) {
    const input = $(`#${id}`); if (!input) return;
    input.addEventListener('input', event => {
      const value = event.target.value; const position = event.target.selectionStart;
      view()[property] = value; render(); const replacement = $(`#${id}`); replacement?.focus();
      if (replacement && position != null) replacement.setSelectionRange(position, position);
    });
  }
  function bindSelect(id, handler) { $(`#${id}`)?.addEventListener('change', event => handler(event.target.value)); }
  function bindSubmit(id, handler) { $(`#${id}`)?.addEventListener('submit', event => { event.preventDefault(); Promise.resolve(handler(event.currentTarget)).catch(showError); }); }
  function bindPage() {
    bindSearchInput('project-search', 'projectQuery'); bindSearchInput('library-search', 'libraryQuery'); bindSearchInput('task-search', 'taskQuery'); bindSearchInput('source-search', 'sourceQuery'); bindSearchInput('memory-search', 'memoryQuery');
    bindSelect('task-project', value => { view().taskProject = value; render(); });
    bindSelect('task-priority', value => { view().taskPriority = value; render(); });
    bindSelect('research-project', value => { view().researchProject = value; view().sourceGroup = ''; view().selectedSources.clear(); render(); });
    bindSelect('library-group', value => { view().libraryGroup = value; render(); });
    bindSelect('source-group', value => { view().sourceGroup = value; view().selectedSources.clear(); render(); });
    bindSelect('start-project', value=>{if(value===CREATE_PROJECT_VALUE){createStartProject().catch(showError);return;}view().startProject=value;render();});
    bindSelect('start-purpose', value=>{view().startPurpose=value;});
    $('#start-input')?.addEventListener('input',event=>{view().startMessage=event.target.value;});
    bindSubmit('start-form',startWork);
    bindSelect('meeting-project', value => { captureMeetingDraft(); view().meetingProject = value; render(); });
    bindSelect('ask-mode', value => { view().askMode = value; render(); });
    bindSelect('local-model', value => { view().localModel = value; try { localStorage.setItem('local-workos:local-model', value); } catch { /* Optional preference. */ } });
    bindSelect('agent-model', value => { view().localModel = value; try { localStorage.setItem('local-workos:local-model', value); } catch { /* Optional preference. */ } });
    $('#agent-project-scope')?.addEventListener('change', event => { view().agentProjectScope = event.target.checked; render(); });
    bindSelect('dsh-model', value => { view().dshModel = value; try { localStorage.setItem('local-workos:dsh-model', value); } catch { /* Selection is optional. */ } render(); });
    bindSelect('research-intent', value=>{view().researchIntent=value;if(value==='workflow'&&view().askMode==='local'){view().askMode='deepseek';notify('交付草稿需要模型。请核对模型和资料范围后再生成。');}render();requestAnimationFrame(()=>$('#question-input')?.focus());});
    bindSelect('workflow-purpose', value=>{view().workflowKey=value;view().workflowQuality='';view().workflowError='';render();requestAnimationFrame(()=>$('#question-input')?.focus());});
    bindSelect('workflow-quality', value=>{view().workflowQuality=value;});
    $('#question-input')?.addEventListener('input', event => { if(view().researchIntent==='actions')view().agentMessage=event.target.value;else if(view().researchIntent==='workflow')view().workflowMessage=event.target.value;else view().question=event.target.value; });
    $$('[data-source-id]').forEach(input => input.addEventListener('change', () => { if (input.checked) view().selectedSources.add(String(input.dataset.sourceId)); else view().selectedSources.delete(String(input.dataset.sourceId)); render(); }));
    $('#source-select-all')?.addEventListener('change', event => { filteredSources().forEach(doc => { if (event.target.checked) view().selectedSources.add(String(doc.id)); else view().selectedSources.delete(String(doc.id)); }); render(); });
    $$('[data-task-status]').forEach(select => select.addEventListener('change', async () => {
      const id = select.dataset.taskStatus; const previous = record('tasks', id)?.status; select.disabled = true;
      try { await api(`/tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status: select.value } }); await refreshData(); render(); notify('任务状态已更新。'); }
      catch (error) { select.value = previous; select.disabled = false; showError(error); }
    }));
    bindSubmit('agent-form', runAgent);
    $('#agent-input')?.addEventListener('input', event => { view().agentMessage = event.target.value; });
    bindSubmit('ask-form', askQuestion); bindSubmit('meeting-summary-form', saveMeetingSummary); bindSubmit('meeting-actions-form', createMeetingTasks); bindSubmit('finance-form', calculateFinance); bindSubmit('ai-settings-form', saveAISettings);
    bindSelect('meeting-model', value => { const state=view(); state.meetingModel=value; try{localStorage.setItem('local-workos:meeting-model',value);}catch{/* Optional preference. */} });
    bindSelect('valuation-method', value => { const state = view(); state.valuationMethod = value; state.valuationProposal = null; state.valuationJson = ''; state.valuationResult = null; state.valuationScenarioResult=null;state.valuationScenariosJson='';state.valuationError = ''; render(); });
    bindSelect('valuation-project', value => { view().valuationProjectId = value; });
    bindSelect('valuation-model', value => { view().valuationModel = value; try { localStorage.setItem('local-workos:dsh-model', value); } catch { /* Optional preference. */ } });
    $('#meeting-transcript-input')?.addEventListener('input',event=>{const state=view();const text=event.target.value;state.meetingTranscriptDraft=text;const id=state.meetingId;if(!id)return;clearTimeout(state.transcriptSaveTimer);const label=$('#meeting-save-state');if(label)label.textContent='正在保存原文…';state.transcriptSaveTimer=setTimeout(async()=>{try{await api('/meetings/'+encodeURIComponent(id),{method:'PATCH',body:{transcript:text}});await refreshData();const node=$('#meeting-save-state');if(node)node.textContent='逐字稿已保存在本机并同步';}catch(error){notify('逐字稿保存失败：'+error.message,true);}},700);});
    const meetingDrop=$('[data-meeting-transcript-drop]');
    meetingDrop?.addEventListener('dragover',event=>{event.preventDefault();meetingDrop.classList.add('drag-over');});
    meetingDrop?.addEventListener('dragleave',()=>meetingDrop.classList.remove('drag-over'));
    meetingDrop?.addEventListener('drop',async event=>{event.preventDefault();meetingDrop.classList.remove('drag-over');const file=event.dataTransfer?.files?.[0];if(!file)return;try{if(file.size>20*1024*1024)throw new Error('文件最大20MB');const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('读取文件失败'));reader.readAsDataURL(file)});const extracted=await api('/meeting-transcript-extract',{body:{name:file.name,base64}});const input=$('#meeting-transcript-input');input.value=extracted.transcript;input.dispatchEvent(new Event('input',{bubbles:true}));notify('已提取 '+file.name+'，正在自动保存逐字稿。');}catch(error){notify('提取逐字稿失败：'+error.message,true);}});
    $('#meeting-summary')?.addEventListener('input', event => { const state=view(); const form=$('#meeting-summary-form'); if(!form)return; clearTimeout(state.meetingSaveTimer); const label=$('#meeting-save-state'); if(label)label.textContent='正在编辑…'; state.meetingSaveTimer=setTimeout(()=>autoSaveMeeting(form),700); });
    $('#valuation-text')?.addEventListener('input', event => { const state = view(); state.valuationText = event.target.value; if (state.valuationProposal) { state.valuationProposal = null; state.valuationJson = ''; state.valuationResult = null; $('.valuation-review')?.remove(); $('.valuation-result')?.remove(); } });
    $('#valuation-json')?.addEventListener('input', event => { view().valuationJson = event.target.value; view().valuationResult = null; view().valuationScenarioResult = null;view().valuationScenariosJson='';$('.valuation-result')?.remove();$('#valuation-scenarios-json')?.closest('section')?.remove(); });
    $('#valuation-scenarios-json')?.addEventListener('input',event=>{view().valuationScenariosJson=event.target.value;view().valuationScenarioResult=null;});
    $('#meeting-actions-form')?.addEventListener('input', captureMeetingDraft);
    bindSubmit('deliverable-form', async form => withBusy($('button[type="submit"]', form), '正在保存…', async () => { if (await saveDeliverable(form)) notify('交付修改已保存。'); }));
    const editor = $('#deliverable-form');
    if (editor) {
      const capture = () => {
        view().deliverableDirty = true;
        view().deliverableDraft = { id: editor.dataset.id, ...Object.fromEntries(new FormData(editor).entries()) };
        $('#deliverable-save-state').textContent = `尚未保存 · ${$('#deliverable-body').value.length} 字`;
        const saved=record('deliverables',editor.dataset.id), node=$('.quality-report',editor);
        if(saved&&node&&view().deliverableDraft.body!==saved.body&&node.dataset.qualityStale!=='true')node.outerHTML=renderQualityReport(staleQualityReport(saved.quality_report),saved.coverage||[]);
      };
      editor.addEventListener('input', capture); editor.addEventListener('change', capture);
      if (view().deliverableDirty) $('#deliverable-save-state').textContent = `尚未保存 · ${$('#deliverable-body').value.length} 字`;
      if (view().deliverableSaving) { $$('input,textarea,select,button', editor).forEach(element => { element.disabled = true; }); $('#deliverable-save-state').textContent = '正在保存…'; }
    }
    $('#finance-form')?.addEventListener('input', event => {
      const key = event.target.name;
      if (key in FINANCE_DEFAULTS && event.target.value !== '' && Number.isFinite(Number(event.target.value))) view().finance[key] = Number(event.target.value) / (PERCENT_FIELDS.has(key) ? 100 : 1);
      view().financeDirty = true; persistFinance(); $('#finance-dirty-note').textContent = '假设已改变，右侧仍为上次结果。请重新运行测算。';
      const saveButton = $('[data-action="finance-deliverable"]'); if (saveButton) saveButton.disabled = true;
    });
  }
  function captureMeetingDraft() {
    const form = $('#meeting-summary-form'); if (!form) return;
    const id = String(form.dataset.id); const draft = view().drafts.get(id) || { summary: '', actions: [], mode: 'ai' };
    draft.summary = $('#meeting-summary').value;
    const actionForm = $('#meeting-actions-form');
    if (actionForm) draft.actions.forEach((action, index) => {
      const title = $(`[name="title-${index}"]`, actionForm); const owner = $(`[name="owner-${index}"]`, actionForm); const due = $(`[name="due-${index}"]`, actionForm);
      if (title && !title.disabled) { action.title = title.value; action.owner = owner.value; action.due = due.value; }
    });
    view().drafts.set(id, draft);
  }

  async function handleAction(button) {
    const { action, id, collection } = button.dataset;
    switch (action) {
      case 'start-create-project': return createStartProject();
      case 'start-workflow': return startWork(button.dataset.key);
      case 'start-route': view().startMessage=button.dataset.request||'';view().startPurpose='';render();return startWork();
      case 'start-folder':
      case 'start-upload': {const state=view();if(app.uploadBusy)return;if(String(state.researchProject)!==String(state.startProject)||state.sourceGroup)state.selectedSources.clear();state.researchProject=state.startProject;state.sourceGroup='';state.selectedSources=new Set([...state.startSourceIds].filter(id=>{const doc=record('documents',id);return doc&&(!state.startProject||String(doc.project_id)===String(state.startProject));}));$(action==='start-folder'?'#research-folder-input':'#upload-input').click();return;}
      case 'retry': return boot();
      case 'create': return editRecord(collection, '', { project_id: app.page === 'research' ? view().researchProject : app.page === 'tasks' ? view().taskProject : app.page === 'meetings' ? view().meetingProject : '', ...(app.page === 'research' && view().sourceGroup ? { task_group: view().sourceGroup } : {}) });
      case 'edit': return editRecord(collection, id);
      case 'delete': return deleteRecord(collection, id);
      case 'modal-delete': $('#modal').close(); return deleteRecord(collection, id);
      case 'workspace': return switchWorkspace(button.dataset.workspace);
      case 'project-stage': view().projectStage = button.dataset.value; render(); return;
      case 'project-detail': if(String(view().projectId)!==String(id)){view().libraryGroup='';view().libraryQuery='';}view().projectId = id; render(); requestAnimationFrame(() => $('#project-detail')?.scrollIntoView({ block: 'nearest' })); return;
      case 'project-close': view().projectId = ''; render(); return;
      case 'project-create': return editRecord(collection, '', { project_id: button.dataset.projectId, ...(button.dataset.group ? { task_group: button.dataset.group } : {}) });
      case 'project-go': return navigate(button.dataset.pageTarget, { projectId: id });
      case 'project-subtask': return createSubtask(id);
      case 'project-organize': return withBusy(button, '整理中…', async () => { await api(`/projects/${encodeURIComponent(id)}/organize`, { body: {} }); await refreshData(); render(); notify('项目材料已重新整理。'); });
      case 'group-research': if(!await navigate('research', { projectId: button.dataset.projectId }))return;view().sourceGroup=button.dataset.group||'';view().selectedSources.clear();render();return;
      case 'project-folder':
      case 'project-upload': if(!await navigate('research', { projectId: button.dataset.projectId }))return;view().sourceGroup=button.dataset.group||'';view().selectedSources.clear();render();$(action==='project-folder'?'#research-folder-input':'#upload-input').click();return;
      case 'project-deliverable': return deliverFromProject(id);
      case 'task-new-status': return editRecord('tasks', '', { status: button.dataset.status, project_id: view().taskProject });
      case 'task-toggle': return withBusy(button, '', async () => { const task = record('tasks', id); if (!task) return; await api(`/tasks/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status: task.status === '完成' ? '待办' : '完成' } }); await refreshData(); render(); notify('任务已完成。'); });
      case 'research-ask': return navigate('research');
      case 'research-template': return applyResearchTemplate(button.dataset.template);
      case 'research-import': await navigate('research'); $('#upload-input').click(); return;
      case 'upload': if (!app.uploadBusy) $('#upload-input').click(); return;
      case 'upload-folder': if (!app.uploadBusy) $('#research-folder-input').click(); return;
      case 'paste-import': return importClipboard();
      case 'agent-focus': if(!await navigate('research'))return;view().researchIntent='actions';render();$('#question-input')?.focus();return;
      case 'go-meetings': return navigate('meetings');
      case 'new-meeting': await navigate('meetings'); return editRecord('meetings');
      case 'new-deliverable': await navigate('deliverables'); return editRecord('deliverables');
      case 'go-finance': return navigate('finance');
      case 'document': return openDocument(id);
      case 'original-download': return withBusy(button, '下载中…', () => download(`/documents/${encodeURIComponent(id)}/original`, record('documents', id)?.attachment_name || '原文件'));
      case 'document-edit': $('#document-dialog').close(); return editRecord('documents', id);
      case 'document-delete': $('#document-dialog').close(); return deleteRecord('documents', id);
      case 'citation': { const citation = view().answers[Number(button.dataset.answer)]?.citations?.[Number(button.dataset.citation)]; if (citation) return openDocument(citation.document_id, citation); return; }
      case 'workflow-citation': { const result=view().workflowResults.find(item=>String(item.deliverable?.id)===String(id));const citation=result?.citations?.[Number(button.dataset.citation)];if(citation)return openDocument(citation.document_id,citation);return;}
      case 'workflow-job-retry': return retryWorkflowJob(id,button);
      case 'workflow-reconnect': return pollWorkflowJobs();
      case 'workflow-progress': view().researchProject='';await navigate('research');$('#workflow-jobs')?.scrollIntoView({block:'start',behavior:'smooth'});return;
      case 'answer-note': { const answer = view().answers[Number(button.dataset.index)]; if (!answer) return; return editRecord('notes', '', { title: excerpt(answer.question, 90), project_id: answer.project_id, body: answer.answer, status: '待核实', document_id: answer.citations?.[0]?.document_id || '', source_quote: (answer.citations || []).map((cite, index) => `[${index + 1}] ${cite.title} · ${cite.page != null ? `第${cite.page}页 / ` : ''}第${cite.ordinal}段\n${cite.quote}`).join('\n\n') }); }
      case 'note-source': { const note = record('notes', id); if (note?.document_id) return openDocument(note.document_id, { quote: note.source_quote }); return; }
      case 'note-deliverable': return deliverFromNote(id);
      case 'select-meeting': captureMeetingDraft(); view().meetingId = id; render(); return;
      case 'meeting-draft': return generateMeetingDraft(id, button);
      case 'meeting-ai-draft': return generateExpertNotes(id, button);
      case 'meeting-export': return exportMeeting(id, button.dataset.format, button);
      case 'meeting-deliverable': return deliverFromMeeting(id);
      case 'meeting-new-task': { const meeting = record('meetings', id); return editRecord('tasks', '', { meeting_id: id, project_id: meeting?.project_id || '' }); }
      case 'memory-category': view().memoryCategory = button.dataset.value; render(); return;
      case 'memory-scan': return scanMemory(button);
      case 'memory-upload-files': if (app.workspace !== 'personal') { notify('真实记忆只能导入个人工作区。', true); return; } if (!app.uploadBusy) $('#memory-file-input').click(); return;
      case 'memory-upload-folder': if (app.workspace !== 'personal') { notify('真实记忆只能导入个人工作区。', true); return; } if (!app.uploadBusy) $('#memory-folder-input').click(); return;
      case 'finance-reset': view().finance = { ...FINANCE_DEFAULTS }; view().financeDirty = true; persistFinance(); render(); return calculateFinance();
      case 'finance-deliverable': return deliverFromFinance();
      case 'valuation-template': return loadValuationTemplate();
      case 'valuation-parse': return parseValuationAssumptions();
      case 'valuation-calculate': return calculateValuation();
      case 'valuation-save': return saveValuation();
      case 'model-load': return loadSavedModel(id);
      case 'valuation-scenarios-preset': return presetValuationScenarios();
      case 'valuation-scenarios-quick': if(!presetValuationScenarios())return;return calculateValuationScenarios();
      case 'valuation-scenarios-calculate': return calculateValuationScenarios();
      case 'valuation-export-xlsx': return exportValuationXlsx(button);
      case 'select-deliverable': if (String(view().deliverableId) === String(id)) return; if (!await canLeave()) return; view().deliverableDirty = false; view().deliverableId = id; render(); return;
      case 'export': return exportDeliverable(id, button.dataset.format, button);
      case 'backup': return withBusy(button, '正在备份…', () => download('/backup', `LocalWorkOS-${app.workspace}-${today()}.json`));
      case 'restore': $('#restore-input').click(); return;
      case 'logout-public': await api('/auth/logout', {body:{}}); app.data=null; window.location.replace('/auth/login'); return;
      case 'refresh-status': return withBusy(button, '正在检查…', async () => { app.boot = await api('/bootstrap'); app.csrf = app.boot.csrf; await refreshData(); render(); notify('本地服务已连接，数据已刷新。'); });
      case 'sync-onedrive': return withBusy(button, '正在同步…', async () => { const status = await api('/sync', { body: {} }); app.boot.sync = status; render(); if (status.error) notify(status.error, true); else notify('项目文件与 JSON 快照已同步到 OneDrive。'); });
      case 'shutdown': if (await confirmDialog('关闭 Local WorkOS 本地服务？', '数据仍保存在本机。页面将断开连接，再次使用需重新运行启动器。', '确认关闭服务', true)) { await api('/shutdown', { body: {} }); app.stopped = true; $('#main').innerHTML = `<section class="state-error"><h1>本地服务已关闭</h1><p>数据已保留。请重新运行 Local WorkOS 启动器，然后点击重新连接。</p>${actionButton('重新连接', 'retry', 'refresh', 'primary')}</section>`; $('#connection-label').textContent = '服务已关闭'; } return;
      case 'search-result': $('#search-dialog').close(); return openRecord(collection, id);
      case 'open-record': return openRecord(collection, id);
      default: notify('此操作暂时不可用，请刷新页面后重试。', true);
    }
  }
  function initialize() {
    $('#mobile-menu').innerHTML = icon('menu'); $('#search-icon').innerHTML = icon('search');
    $('#mobile-menu').addEventListener('click', () => { const open = !$('#sidebar').classList.contains('open'); $('#sidebar').classList.toggle('open', open); $('#sidebar-scrim').hidden = !open; $('#mobile-menu').setAttribute('aria-expanded', String(open)); });
    $('#sidebar-scrim').addEventListener('click', closeSidebar);
    $('#search-trigger').addEventListener('click', openSearch);
    $('#workspace-switch').addEventListener('click', () => { if (app.data) workspaceDialog(); });
    $('#upload-input').addEventListener('change', event => uploadFiles([...event.target.files]));
    $('#research-folder-input').addEventListener('change', event => uploadFiles([...event.target.files]));
    $('#memory-file-input').addEventListener('change', event => uploadFiles([...event.target.files], 'memory'));
    $('#memory-folder-input').addEventListener('change', event => uploadFiles([...event.target.files], 'memory'));
    $('#restore-input').addEventListener('change', event => restoreBackup(event.target.files[0]));
    // Ctrl/Cmd+V anywhere outside a text field imports the clipboard as a research document.
    document.addEventListener('paste', event => {
      if (app.stopped || !app.data) return;
      const text = event.clipboardData?.getData('text/plain') || '';
      if (!text.trim()) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      importPastedText(text);
    });
    // Drag and drop files (or pasted text) onto the window.
    ['dragenter', 'dragover'].forEach(type => document.addEventListener(type, event => {
      if (app.stopped) return;
      if (![...(event.dataTransfer?.types || [])].some(item => item === 'Files' || item === 'text/plain')) return;
      event.preventDefault();
      document.body.classList.add('drop-active');
    }));
    ['dragleave', 'dragend'].forEach(type => document.addEventListener(type, event => {
      if (event.relatedTarget) return;
      document.body.classList.remove('drop-active');
    }));
    document.addEventListener('drop', async event => {
      document.body.classList.remove('drop-active');
      if (app.stopped || !app.data || isTypingTarget(event.target)) return;
      event.preventDefault();
      const { files, text } = await filesFromDataTransfer(event.dataTransfer);
      if (files.length) uploadFiles(files, app.page === 'memory' ? 'memory' : 'research');
      else if (text.trim()) importPastedText(text);
    });
    $('#modal').addEventListener('cancel', event => { if (app.modalBusy) event.preventDefault(); });
    $('#search-dialog').addEventListener('close', () => { clearTimeout(searchTimer); searchSequence++; });
    document.addEventListener('click', async event => {
      const close = event.target.closest('[data-close-dialog]');
      if (close) { if (close.dataset.closeDialog === 'modal' && app.modalBusy) return; document.getElementById(close.dataset.closeDialog)?.close(); return; }
      const page = event.target.closest('[data-page]');
      if (page) { event.preventDefault(); if (!app.data || app.stopped) return; captureMeetingDraft(); await navigate(page.dataset.page); return; }
      const button = event.target.closest('[data-action]');
      if (button && !button.disabled) { event.preventDefault(); try { await handleAction(button); } catch (error) { showError(error); } }
    });
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); if (!$$('dialog[open]').some(dialog => dialog.id !== 'search-dialog')) openSearch(); }
      if (event.key === 'Escape') { if ($('#search-dialog').open) { event.preventDefault(); $('#search-dialog').close(); } closeSidebar(); }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && app.page === 'deliverables' && $('#deliverable-form') && !$$('dialog[open]').length) { event.preventDefault(); $('#deliverable-form').requestSubmit(); }
    });
    window.addEventListener('beforeunload', event => { if (view().deliverableDirty || app.mutations) { event.preventDefault(); event.returnValue = ''; } });
    window.addEventListener('hashchange', async () => { const target = location.hash.slice(1); if (ROUTES.some(route => route[0] === target)) await navigate(target); });
    boot();
  }
  initialize();
})();
