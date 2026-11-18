/* util.js — tiny shared DOM helpers. Loaded first; every page script uses these instead of its own copy. */
(function (global) {
  'use strict';

  const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => HTML_ESCAPES[c]);
  }

  // el('p', '文字', 'class-name') — text goes in as textContent, never as HTML.
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function button(text, onClick, className) {
    const node = el('button', text, className);
    node.type = 'button';
    if (onClick) node.addEventListener('click', onClick);
    return node;
  }

  // 自绘确认框（删除等不可逆操作）：confirm({title, text, ok}) → Promise<boolean>。Esc、点遮罩都算取消。
  function confirm({ title, text = '', ok = '确认', cancel = '取消' } = {}) {
    return new Promise((resolve) => {
      const overlay = el('div', '', 'confirm-overlay');
      const box = el('div', '', 'confirm-box pixel-box');
      box.setAttribute('role', 'alertdialog');
      box.setAttribute('aria-modal', 'true');
      const yes = button(ok, () => done(true), 'confirm-danger');
      const no = button(cancel, () => done(false), 'confirm-cancel');
      const actions = el('div', '', 'confirm-actions');
      actions.append(no, yes);
      box.append(el('div', title, 'confirm-title'), el('div', text, 'confirm-text'), actions);
      overlay.append(box);
      const onKey = (event) => { if (event.key === 'Escape') { event.stopPropagation(); done(false); } };
      function done(value) {
        document.removeEventListener('keydown', onKey, true);
        overlay.remove();
        resolve(value);
      }
      overlay.addEventListener('click', (event) => { if (event.target === overlay) done(false); });
      document.addEventListener('keydown', onKey, true);
      ([...document.querySelectorAll('dialog[open]')].at(-1) || document.body).append(overlay);
      no.focus();
    });
  }

  // 时间：带时区的（…Z / +09:00）按本地显示；不带时区的朴素串（"2026-11-12 23:40:41"）就是后端那台机器的本地时间
  function time(value) {
    if (value == null || value === '') return null;
    if (value instanceof Date) return value;
    const text = String(value).trim();
    const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(text) ? text : text.replace(' ', 'T'));
    return Number.isFinite(d.getTime()) ? d : null;
  }
  const pad = (n) => String(n).padStart(2, '0');
  function clock(value) { const d = time(value); return d ? pad(d.getHours()) + ':' + pad(d.getMinutes()) : ''; }
  // 今天只写时刻；今年写月/日；更早写年/月/日
  function shortDate(value) {
    const d = time(value);
    if (!d) return '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return clock(d);
    if (d.getFullYear() === now.getFullYear()) return (d.getMonth() + 1) + '/' + d.getDate();
    return d.getFullYear() + '/' + (d.getMonth() + 1) + '/' + d.getDate();
  }

  // 题型的中文名以后端 GET /api/learning/settings 的 types 为准；没拿到时不露代码
  let types = null, typesTask = null;
  function loadTypes() {
    typesTask ||= fetch('/api/learning/settings').then((r) => (r.ok ? r.json() : {})).then((d) => { types = d?.types || {}; return types; })
      .catch(() => { typesTask = null; return {}; });
    return typesTask;
  }
  function typeLabel(skill, key, fallback) {
    if (!key) return '';
    return types?.[skill]?.[key] || fallback?.[key] || (/^jlpt_/.test(key) ? 'JLPT' : key);
  }
  // 证据段落：给了引文就只留含引文的那一段
  function evidenceParagraph(paragraph, quote) {
    const text = String(paragraph || '');
    const parts = text.split(/\n+/).map((p) => p.trim()).filter(Boolean);
    if (parts.length < 2) return text.trim();
    const probe = String(quote || '').trim().slice(0, 24);
    return (probe && parts.find((p) => p.includes(probe))) || text.trim();
  }

  // 连续流：一个实心「下一步」按钮（今天还没做的下一件；全做完是「去聊天」）。回今天走图标栏「学习」
  function nextActions(except) {
    const box = el('div', '', 'next-actions');
    const go = el('button', '…', 'primary next-go');
    go.type = 'button'; go.dataset.next = '';
    let target = null;
    go.addEventListener('click', () => { if (target) global.LP.appShell?.switchTab(target); });
    box.append(go);
    void (global.LP.appShell?.nextStep?.(except) || Promise.resolve({ tab: 'talk', label: '去聊天', kind: 'output' })).then((step) => {
      go.textContent = step.label; go.dataset.next = step.kind; target = step.tab;
    });
    return box;
  }

  // 就地反馈：控件旁边一个小勾（或小叉），1.6 秒后淡掉
  function tick(field, ok = true, title = '') {
    if (!field?.parentElement) return;
    field.parentElement.querySelectorAll(':scope > .save-tick').forEach((t) => t.remove());
    const mark = el('span', ok ? '✓' : '✗', 'save-tick' + (ok ? '' : ' bad'));
    mark.setAttribute('role', 'status');
    if (title) mark.title = title;
    field.after(mark);
    setTimeout(() => mark.remove(), 1600);
  }

  // 出错时给人看的那句：后端的中文 detail 照用；浏览器自己的英文异常（Failed to fetch、Unexpected token…）换成 fallback
  function message(error, fallback = '没连上，再试一次') {
    const text = String(error?.message || '');
    if (!text || error?.name === 'TypeError' || error?.name === 'SyntaxError' || /Failed to fetch|NetworkError|Load failed|Unexpected token|is not valid JSON|JSON\.parse|\[object /.test(text)) {
      if (text) console.warn(text);
      return fallback;
    }
    return text;
  }

  global.LP = global.LP || {};
  global.LP.util = { message, tick, nextActions, escapeHtml, el, button, confirm, time, clock, shortDate, loadTypes, typeLabel, evidenceParagraph };
})(window);
