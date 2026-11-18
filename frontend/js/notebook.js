/* notebook.js — 単語帳页面：单词本/句型本 tabs + 语言筛选 + 删除 + 跳回原对话。
   数据流程不变，挂载点是应用内的 tab 页面容器（mount(root)，root=#page-notebook）。 */
(function (global) {
  'use strict';

  const nbState = { tab: 'vocab', lang: '' };
  const LANG_TAG = { ja: '日', en: '英', de: '德' };
  const languageLabel = tag => LANG_TAG[tag] || global.LP.languages?.label(tag) || tag;
  let els = {};
  let refreshVersion = 0;
  let removeLanguageListener = () => {};
  const removing = new Set();   // 'vocab:12' / 'pattern:3'：删了还能撤销的

  const escapeHtml = (s) => global.LP.util.escapeHtml(s);
  function fmtDate(createdAt) {
    if (!createdAt) return '';
    const [, m, d] = createdAt.slice(0, 10).split('-');
    return `${Number(m)}月${Number(d)}日`;
  }

  function vocabCard(item) {
    const div = document.createElement('div');
    div.className = 'nb-card';
    div.innerHTML = `
      <div class="nb-top">
        <div class="nb-word">${escapeHtml(item.surface || item.lemma)}</div>
        ${item.reading ? `<div class="nb-reading">${escapeHtml(item.reading)}</div>` : ''}
        <div class="spacer"></div>
        <div class="nb-lang-tag">${escapeHtml(languageLabel(item.language))}</div>
      </div>
      <div class="nb-meaning">${escapeHtml(item.meaning || '')}</div>
      <div class="nb-context" data-msgid="${item.source_message_id ?? ''}">${escapeHtml(item.context_sentence || '')}</div>
      <div class="nb-foot">
        <div class="nb-date">${fmtDate(item.created_at)}</div>
        <div class="spacer"></div>
        <details class="nb-actions row-more">
          <summary aria-label="更多" title="更多">⋯</summary>
          <div class="row-more-pop pixel-box"><button type="button" class="nb-jump">回到原对话</button><button type="button" class="nb-del row-danger">删除</button></div>
        </details>
      </div>`;
    wireCard(div, item, 'vocab');
    return div;
  }

  function patternCard(item) {
    const div = document.createElement('div');
    div.className = 'nb-card';
    div.innerHTML = `
      <div class="nb-top">
        <div class="nb-word">${escapeHtml(item.pattern_name)}</div>
        <div class="spacer"></div>
        <div class="nb-lang-tag">${escapeHtml(languageLabel(item.language))}</div>
      </div>
      <div class="nb-meaning">${escapeHtml(item.explanation || '')}</div>
      <div class="nb-context" data-msgid="${item.source_message_id ?? ''}">${escapeHtml(item.example_sentence || '')}</div>
      ${item.translation ? `<div class="nb-meaning nb-translation">${escapeHtml(item.translation)}</div>` : ''}
      <div class="nb-foot">
        <div class="nb-date">${fmtDate(item.created_at)}</div>
        <div class="spacer"></div>
        <details class="nb-actions row-more">
          <summary aria-label="更多" title="更多">⋯</summary>
          <div class="row-more-pop pixel-box"><button type="button" class="nb-jump">回到原对话</button><button type="button" class="nb-del row-danger">删除</button></div>
        </details>
      </div>`;
    wireCard(div, item, 'pattern');
    return div;
  }

  function wireCard(div, item, kind) {
    if (kind === 'vocab' && item.id != null && LP.learning?.openVocab) {
      const word = div.querySelector('.nb-word');
      word.classList.add('nb-word-open');
      word.setAttribute('role', 'button');
      word.tabIndex = 0;
      word.addEventListener('click', () => void LP.learning.openVocab(item.id));
      word.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') void LP.learning.openVocab(item.id); });
    }
    const ctx = div.querySelector('.nb-context');
    const jumpBtn = div.querySelector('.nb-jump');
    const delBtn = div.querySelector('.nb-del');
    const jump = () => jumpToMessage(item.source_message_id);
    if (item.source_message_id != null) {
      ctx.addEventListener('click', jump);
      jumpBtn.addEventListener('click', jump);
    } else {
      jumpBtn.hidden = true;
    }
    // 删除：先拿掉，5 秒内能撤销，过了才真的删（撤销期里刷新列表也不画回来）
    delBtn.addEventListener('click', () => {
      const grid = div.parentElement, after = div.nextSibling, key = kind + ':' + item.id;
      div.querySelector('details')?.removeAttribute('open');
      LP.appShell.undoable('已删除', {
        remove: () => { removing.add(key); div.remove(); updateCountFromDom(); },
        restore: () => { removing.delete(key); grid?.insertBefore(div, after && after.parentElement === grid ? after : null); updateCountFromDom(); },
        commit: async () => {
          try { if (kind === 'vocab') await LP.api.deleteVocab(item.id); else await LP.api.deletePattern(item.id); removing.delete(key); }
          catch { removing.delete(key); grid?.insertBefore(div, after && after.parentElement === grid ? after : null); updateCountFromDom(); LP.toast?.('没删掉'); }
        },
      });
    });
  }

  function updateCountFromDom() {
    const q = (els.search?.value || '').trim().toLowerCase();
    let n = 0;
    for (const card of els.grid.children) {
      const hit = !q || card.textContent.toLowerCase().includes(q);
      card.hidden = !hit;
      if (hit) n += 1;
    }
    els.count.textContent = `${n} 条`;
    els.empty.classList.toggle('hidden', els.grid.children.length > 0);
  }

  async function refresh() {
    if (!els.grid) return;
    const version = ++refreshVersion;
    const view = els;
    const tab = nbState.tab;
    const lang = nbState.lang || undefined;
    const isCurrent = () => version === refreshVersion && view === els;
    view.grid.replaceChildren();
    view.grid.setAttribute('aria-busy', 'true');
    view.empty.classList.add('hidden');
    view.count.textContent = '';
    view.grid.append(...Array.from({ length: 3 }, () => { const s = document.createElement('div'); s.className = 'nb-card nb-skeleton'; s.setAttribute('aria-hidden', 'true'); return s; }));
    try {
      const res = await (tab === 'vocab' ? LP.api.getVocab(lang) : LP.api.getPatterns(lang));
      if (!isCurrent()) return;
      const fragment = document.createDocumentFragment();
      res.items.filter(item => !removing.has(tab + ':' + item.id))
        .forEach(item => fragment.appendChild(tab === 'vocab' ? vocabCard(item) : patternCard(item)));
      view.grid.replaceChildren(fragment);
      updateCountFromDom();
    } catch (e) {
      if (!isCurrent()) return;
      view.grid.replaceChildren();
      view.count.textContent = '没加载出来';
    } finally {
      if (isCurrent()) view.grid.removeAttribute('aria-busy');
    }
  }

  async function jumpToMessage(sourceMessageId) {
    if (sourceMessageId == null) return;
    try {
      const response = await fetch('/api/messages/' + encodeURIComponent(sourceMessageId) + '/location');
      if (!response.ok) throw new Error();
      const { session_id } = await response.json();
      LP.appShell.switchTab('talk');
      if (!await LP.jine.openMessage(session_id, sourceMessageId)) LP.toast?.('未能定位到原对话');
    } catch { LP.toast?.('未能定位到原对话'); }
  }

  function mount(root) {
    removeLanguageListener();
    ++refreshVersion;
    els = {};
    nbState.lang = LP.preferences.get('notebookLanguage') || '';
    root.innerHTML = `
      <section class="nb-workspace" aria-labelledby="nb-page-title">
        <h1 id="nb-page-title" class="visually-hidden">单词本</h1>
        <div class="workspace-tools">
          <input type="search" class="list-search" id="nb-search" placeholder="搜索" aria-label="搜索收藏">
          <div class="nb-tabs" role="group" aria-label="收藏类型">
            <button type="button" class="nb-tab" data-tab="vocab" aria-pressed="true">单词本</button>
            <button type="button" class="nb-tab" data-tab="pattern" aria-pressed="false">句型本</button>
          </div>
          <div class="nb-filter" role="group" aria-label="收藏语言">
            <span class="nb-count" id="nb-count"></span>
          </div>
          <button type="button" class="nb-start-review" data-start-review>开始复习</button>
        </div>
        <div class="nb-grid" id="nb-grid"></div>
        <div class="nb-empty empty-state hidden" id="nb-empty"><img src="assets/icons/notebook.png" alt=""><button type="button" class="primary" data-go-chat>去聊天</button></div>
      </section>`;
    root.querySelector('[data-start-review]').addEventListener('click', () => {
      const tab = root.querySelector('.nb-tab[aria-pressed="true"]')?.dataset.tab;
      LP.learning?.openReview({ kinds: tab === 'pattern' ? ['pattern'] : ['vocab', 'vocab_produce'], ...(nbState.lang ? { language: nbState.lang } : {}) });
    });
    els.grid = root.querySelector('#nb-grid');
    els.empty = root.querySelector('#nb-empty');
    els.count = root.querySelector('#nb-count');
    els.search = root.querySelector('#nb-search');
    els.search.addEventListener('input', updateCountFromDom);
    root.querySelector('[data-go-chat]').addEventListener('click', () => LP.appShell.switchTab('talk'));
    root.querySelectorAll('.nb-tab').forEach((tab) => {
      tab.setAttribute('aria-pressed', String(tab.dataset.tab === nbState.tab));
      tab.addEventListener('click', () => {
        root.querySelectorAll('.nb-tab').forEach((t) => t.setAttribute('aria-pressed', t === tab));
        nbState.tab = tab.dataset.tab;
        refresh();
      });
    });
    const renderFilters = () => {
      const group = els.count.parentElement;
      const locales = LP.languages?.list() || Object.keys(LANG_TAG).map(tag => ({ tag }));
      const chips = ['', ...locales.map(item => item.tag)].map(tag => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'nb-chip'; button.dataset.lang = tag;
        button.textContent = tag ? languageLabel(tag) : '全部';
        button.setAttribute('aria-pressed', String(tag === nbState.lang));
        button.onclick = () => { nbState.lang = tag; LP.preferences?.set?.('notebookLanguage', tag); renderFilters(); void refresh(); };
        return button;
      });
      group.replaceChildren(...chips, els.count);
    };
    renderFilters();
    document.addEventListener('lp:languages', renderFilters);
    removeLanguageListener = () => document.removeEventListener('lp:languages', renderFilters);
    refresh();
  }

  global.LP = global.LP || {};
  global.LP.notebook = { mount, refresh };
})(window);
