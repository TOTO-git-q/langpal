/* Contextual meaning first; grammatical detail is an explicit expansion. */
(function (global) {
  'use strict';

  const el = document.getElementById('word-popover');
  let currentAbort = null;
  let currentToken = null;
  let slowTimer = null;

  function close() {
    if (currentAbort) { currentAbort.abort(); currentAbort = null; }
    if (slowTimer) { clearTimeout(slowTimer); slowTimer = null; }
    el.classList.add('hidden');
    el.innerHTML = '';
    if (currentToken && currentToken.tokenEl) currentToken.tokenEl.classList.remove('active');
    currentToken = null;
  }

  function position(x, y) {
    const margin = 12;
    const w = 300;
    let left = x + 10;
    let top = y + 10;
    if (left + w + margin > window.innerWidth) left = window.innerWidth - w - margin;
    if (left < margin) left = margin;
    const estH = 220;
    if (top + estH + margin > window.innerHeight) top = Math.max(margin, y - estH - 10);
    el.style.left = left + 'px';
    el.style.top = top + 'px';
  }

  function renderSkeleton() {
    el.innerHTML = `
      <div class="skeleton-line" style="width:60%"></div>
      <div class="skeleton-line" style="width:90%"></div>
      <div class="skeleton-line" style="width:80%"></div>
      <div class="skeleton-line" style="width:70%"></div>
      <div class="wp-loading-note" id="wp-slow-note" role="status">查词…</div>
      <div class="wp-loading-note"><button type="button" class="wp-cancel" id="wp-cancel-btn">取消</button></div>
    `;
    document.getElementById('wp-cancel-btn').addEventListener('click', close);
  }

  async function checkSavedState(language, lemma) {
    try {
      const res = await LP.api.getVocab(language);
      return res.items.some((v) => v.lemma === lemma);
    } catch (e) { return false; }
  }

  function renderCard(data, ctx, alreadySaved) {
    if (slowTimer) { clearTimeout(slowTimer); slowTimer = null; }
    const { language, lemma, surface, sentence, sourceMessageId } = ctx;
    const showReading = language.split('-')[0] === 'ja' && data.reading;
    ctx.saved = alreadySaved;
    el.innerHTML = `
      <div class="wp-head">
        <div class="wp-surface">${escapeHtml(data.surface || surface)}</div>
        ${showReading ? `<div class="wp-reading">${escapeHtml(data.reading)}</div>` : ''}
        ${data.pos ? `<div class="wp-pos">${escapeHtml(data.pos)}</div>` : ''}
        <div class="spacer"></div>
      </div>
      <div class="wp-meaning">${escapeHtml(data.meaning_zh || '')}</div>
      ${data.detail === 'brief' ? '<button type="button" class="wp-collect-btn" id="wp-detail-btn">用法与语法</button>' : ''}
      ${data.usage_in_context ? `
        <div class="wp-usage-box">
          <div class="lbl">在这句话里</div>
          <div class="txt">${escapeHtml(data.usage_in_context)}</div>
        </div>` : ''}
      ${data.grammar_note ? `<div class="wp-grammar">${escapeHtml(data.grammar_note)}</div>` : ''}
      <div class="wp-footer">
        <div class="wp-register">${data.register_note ? escapeHtml(data.register_note) : ''}</div>
        <div class="spacer"></div>
        <button class="wp-collect-btn" id="wp-collect-btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M6 3.5h12V21l-6-4.2L6 21V3.5z"></path></svg>
          <span id="wp-collect-label">${alreadySaved ? '再记一句' : '收藏'}</span>
        </button>
      </div>
    `;
    const detail = document.getElementById('wp-detail-btn');
    if (detail) detail.addEventListener('click', async () => {
      detail.disabled = true; detail.textContent = '…';
      if (currentAbort) currentAbort.abort();
      const controller = new AbortController();
      currentAbort = controller;
      try {
        const full = await LP.api.explainWord({ language, lemma, surface, sentence, occurrence: ctx.occurrence }, controller.signal);
        if (controller.signal.aborted || currentToken?.ctx !== ctx) return;
        renderCard({ ...full, detail: 'full' }, ctx, ctx.saved);
      } catch {
        if (controller.signal.aborted || currentToken?.ctx !== ctx) return;
        detail.disabled = false; detail.textContent = '再试一次';
      }
    });
    const btn = document.getElementById('wp-collect-btn');
    if (alreadySaved) btn.classList.add('saved');
    btn.addEventListener('click', async () => {
      if (btn.dataset.done === 'true') return;
      btn.disabled = true;
      try {
        const saved = await LP.api.addVocab({
          language, lemma: data.lemma || lemma, surface: data.surface || surface,
          reading: data.reading || null, meaning: data.meaning_zh || null, pos: data.pos || null,
          context_sentence: sentence, source_message_id: sourceMessageId ?? null,
        });
        btn.classList.add('saved');
        ctx.saved = true;
        btn.dataset.done = 'true';
        const label = btn.querySelector('#wp-collect-label');
        if (label) label.textContent = '已收藏';     // 按钮自己说，不再弹提示
        LP.tokens.markCollectedGlobal(language, data.lemma || lemma);
      } catch (e) {
        LP.toast && LP.toast('没收藏上');
        btn.disabled = false;
      }
    });
  }

  function renderError(message) {
    if (slowTimer) { clearTimeout(slowTimer); slowTimer = null; }
    el.innerHTML = '<div class="wp-meaning">没查到</div>';
  }

  const escapeHtml = (s) => global.LP.util.escapeHtml(s);

  async function open(x, y, tokenEl, token, sentence, language, sourceMessageId) {
    close();
    document.querySelectorAll('.tok.active').forEach((s) => s.classList.remove('active'));
    tokenEl.classList.add('active');
    el.classList.remove('hidden');
    position(x, y);

    const lemma = token.lemma || token.surface;
    const surface = token.surface;
    const ctx = { language, lemma, surface, sentence, sourceMessageId, occurrence: token.lookup_occurrence };
    currentToken = { tokenEl, ctx };

    const controller = new AbortController();
    currentAbort = controller;

    ctx.saved = Boolean(token.collected || tokenEl.classList.contains('collected'));
    // Never hold the meaning behind an unrelated vocabulary-list request.
    void checkSavedState(language, lemma).then(saved => {
      if (currentToken?.ctx !== ctx || !saved) return;
      ctx.saved = true;
      const btn = el.querySelector('#wp-collect-btn');
      // 收藏过的词：按钮一律是「再记一句」（点了是把这句话也记上），和一开始就知道收藏过时一样
      if (btn && btn.dataset.done !== 'true') { btn.classList.add('saved'); btn.querySelector('span').textContent = '再记一句'; }
    });
    const ready = LP.glosses?.peek(language, sentence, token);
    if (ready) { renderCard(ready, ctx, ctx.saved); position(x, y); return; }
    renderSkeleton();
    try {
      const body = { language, lemma, surface, sentence, occurrence: ctx.occurrence };
      const data = LP.glosses ? await LP.glosses.word(body, token, controller.signal) : await LP.api.explainWord(body, controller.signal);
      if (controller.signal.aborted || currentToken?.ctx !== ctx) return;
      renderCard(data, ctx, ctx.saved);
      position(x, y);
    } catch (error) {
      if (!controller.signal.aborted && currentToken?.ctx === ctx) renderError(error.message);
    }
  }

  document.addEventListener('mousedown', (ev) => {
    if (el.classList.contains('hidden')) return;
    if (el.contains(ev.target)) return;
    if (ev.target.closest && ev.target.closest('.tok.clickable')) return;
    close();
  });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') close(); });

  global.LP = global.LP || {};
  global.LP.wordcard = { open, close };
})(window);
