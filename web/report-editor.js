/* Local WorkOS standalone report editor. No network, storage or platform APIs. */
(() => {
  'use strict';
  if (document.getElementById('report-editor-ui')) return;
  const body = document.getElementById('body');
  const data = document.getElementById('report-notes-data');
  if (!body || !data) return;
  const paragraphs = () => Array.from(body.children).filter(el => el.matches('p[id],h2[id]'));
  let notes = [];
  try {
    const parsed = JSON.parse(data.textContent);
    if (Array.isArray(parsed.notes)) notes = parsed.notes.filter(n => n &&
      typeof n.id === 'string' && typeof n.paragraphId === 'string' &&
      typeof n.quote === 'string' && typeof n.text === 'string').map(n => ({
        id: n.id, paragraphId: n.paragraphId, quote: n.quote, text: n.text
      }));
  } catch (_) { /* Invalid optional annotation data cannot execute. */ }
  let editing = false;
  let selected = null;
  let dirty = false;
  const make = (tag, text, id) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (id) el.id = id;
    return el;
  };
  const ui = make('aside', undefined, 'report-editor-ui');
  ui.setAttribute('aria-label', '报告编辑器');
  const heading = make('strong', 'Local WorkOS · 报告副本');
  const mode = make('button', '编辑正文', 'report-edit');
  mode.type = 'button';
  const save = make('button', '保存 HTML 副本', 'report-save');
  save.type = 'button';
  const status = make('p', '阅读模式 · 仅修改此文件副本，不回写平台数据库。', 'report-status');
  status.setAttribute('role', 'status');
  const label = make('label', '选择同一段落的正文文字，再填写批注。');
  label.htmlFor = 'report-note-text';
  const quote = make('p', '尚未选择正文文字', 'report-selected-quote');
  const input = make('textarea', undefined, 'report-note-text');
  input.rows = 3;
  input.disabled = true;
  const add = make('button', '添加批注', 'report-add-note');
  add.type = 'button';
  add.disabled = true;
  const list = make('div', undefined, 'report-note-list');
  ui.append(heading, mode, save, status, label, quote, input, add, list);
  document.body.append(ui);
  const message = text => { status.textContent = text; };
  function renderNotes() {
    list.replaceChildren();
    notes.forEach(note => {
      const item = make('article');
      item.className = 'report-note';
      const target = paragraphs().find(el => el.id === note.paragraphId);
      item.append(make('small', '段落 ' + note.paragraphId + (target ? '' : '（原段落已不存在）')),
        make('blockquote', note.quote), make('p', note.text));
      const remove = make('button', '删除批注');
      remove.type = 'button';
      remove.disabled = !editing;
      remove.addEventListener('click', () => {
        notes = notes.filter(n => n !== note);
        dirty = true;
        renderNotes();
        message('批注已删除，需保存 HTML 副本。');
      });
      item.append(remove);
      list.append(item);
    });
  }
  mode.addEventListener('click', () => {
    editing = !editing;
    paragraphs().forEach(el => {
      if (editing) el.setAttribute('contenteditable', 'plaintext-only');
      else el.removeAttribute('contenteditable');
    });
    mode.textContent = editing ? '完成编辑 / 阅读' : '编辑正文';
    mode.setAttribute('aria-pressed', String(editing));
    input.disabled = !editing;
    add.disabled = !editing || !selected;
    message(editing ? '编辑模式 · 正文可直接修改；选中文字后填写批注。' : '阅读模式 · 保存副本以保留修改。');
    renderNotes();
  });
  function selectedParagraph(node) {
    const el = node && (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement);
    const paragraph = el && el.closest('p[id],h2[id]');
    return paragraph && paragraph.parentElement === body ? paragraph : null;
  }
  document.addEventListener('selectionchange', () => {
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed) return;
    const start = selectedParagraph(selection.anchorNode);
    const end = selectedParagraph(selection.focusNode);
    if (!start && !end) return; // Keep the quote when focusing the annotation field.
    selected = start && start === end ? {paragraphId: start.id, quote: selection.toString()} : null;
    quote.textContent = selected ? selected.quote : '请选择同一段落内的文字';
    add.disabled = !editing || !selected;
  });
  add.addEventListener('click', () => {
    if (!editing || !selected || !input.value.trim()) {
      message('请先选择正文文字并填写批注。');
      return;
    }
    const ids = new Set(notes.map(n => n.id));
    let id;
    do { id = 'note-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2); } while (ids.has(id));
    notes.push({id, paragraphId: selected.paragraphId, quote: selected.quote, text: input.value.trim()});
    input.value = '';
    dirty = true;
    renderNotes();
    message('批注已添加，原文和段落 ID 已保留；需保存副本。');
  });
  body.addEventListener('input', () => { dirty = true; });
  // Paste is plain text even on engines without plaintext-only support.
  body.addEventListener('paste', event => {
    if (!editing) return;
    event.preventDefault();
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) return;
    const paragraph = selectedParagraph(selection.anchorNode);
    if (!paragraph || paragraph !== selectedParagraph(selection.focusNode)) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();
    const text = document.createTextNode(event.clipboardData.getData('text/plain'));
    range.insertNode(text);
    range.setStartAfter(text);
    range.collapse(true);
    selection.removeAllRanges();
    selection.addRange(range);
    dirty = true;
  });
  body.addEventListener('dragover', event => event.preventDefault());
  body.addEventListener('drop', event => event.preventDefault());
  // Preserve paragraph identities rather than allowing Enter to create anonymous blocks.
  body.addEventListener('keydown', event => {
    if (editing && event.key === 'Enter') {
      event.preventDefault();
      const selection = window.getSelection();
      if (!selection || !selection.rangeCount || !selectedParagraph(selection.anchorNode)) return;
      const range = selection.getRangeAt(0);
      range.deleteContents();
      const newline = document.createTextNode('\n');
      range.insertNode(newline);
      range.setStartAfter(newline);
      range.collapse(true);
      selection.removeAllRanges();
      selection.addRange(range);
      dirty = true;
    }
  });
  function buildHTML() {
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('#report-editor-ui').forEach(el => el.remove());
    clone.querySelectorAll('[contenteditable]').forEach(el => el.removeAttribute('contenteditable'));
    // Edited markup is never trusted. Save only text under the original stable blocks.
    const cleanBody = clone.querySelector('#body');
    cleanBody.replaceChildren();
    Array.from(body.children).forEach(el => {
      if (el.matches('p[id],h2[id]')) {
        const clean = document.createElement(el.tagName.toLowerCase());
        clean.id = el.id;
        clean.textContent = el.innerText;
        cleanBody.append(clean);
      } else if (el.classList.contains('gap')) {
        const gap = document.createElement('div');
        gap.className = 'gap';
        cleanBody.append(gap);
      }
    });
    const safeJSON = JSON.stringify({version: 1, notes}).replace(/[<>&\u2028\u2029]/g,
      ch => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'));
    clone.querySelector('#report-notes-data').textContent = safeJSON;
    return '<!doctype html>\n' + clone.outerHTML;
  }
  save.addEventListener('click', () => {
    try {
      const blob = new Blob([buildHTML()], {type: 'text/html;charset=utf-8'});
      const url = URL.createObjectURL(blob);
      const link = make('a');
      link.href = url;
      link.download = 'local-workos-report.html';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      dirty = false;
      message('已请求下载 HTML 副本；请确认浏览器保存完成。重新打开可继续编辑和查看批注。');
    } catch (_) { message('保存失败，请重试并允许浏览器下载。'); }
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  window.LocalWorkOSReport = Object.freeze({buildHTML});
  renderNotes();
})();
