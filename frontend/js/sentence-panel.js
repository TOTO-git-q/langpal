/* sentence-panel.js — 句子解析：聊天区右侧滑出面板（取代旧版 sentence-window.js 的独立 wm 窗口）。
   #sentence-panel 是 index.html 里的静态顶层元素（position:fixed，右侧滑入），跟 #word-popover 同类做法。
   数据流程（POST /explain/sentence + 语法点收藏）原样保留。 */
(function (global) {
  'use strict';

  const el = document.getElementById('sentence-panel');
  let closeTimer = null;

  const escapeHtml = (s) => global.LP.util.escapeHtml(s);

  function header() {
    return `<div class="sp-header"><div class="sp-title">句子解析</div><button class="sp-close" id="sp-close-btn" title="关闭">×</button></div>`;
  }
  function wireHeader() {
    const btn = document.getElementById('sp-close-btn');
    if (btn) btn.addEventListener('click', close);
  }

  function renderLoading() {
    el.innerHTML = `${header()}
      <div class="sp-body">
        <div class="skeleton-line" style="width:95%"></div>
        <div class="skeleton-line" style="width:80%"></div>
        <div class="skeleton-line" style="width:60%"></div>
      </div>`;
    wireHeader();
  }

  let ticket = 0;   // 先点 A 再点 B：A 晚回来的结果不盖住 B
  function open(sentence, language, sourceMessageId) {
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    el.classList.remove('hidden');
    renderLoading();
    // 先去掉 hidden 再下一帧加 open，才能触发 transform 过渡（display:none -> flex 之间不能直接过渡）
    requestAnimationFrame(() => el.classList.add('open'));

    const mine = ++ticket;
    LP.api.explainSentence({ language, sentence }).then(
      (data) => { if (mine === ticket) renderResult(data, sentence, language, sourceMessageId); },
      () => { if (mine !== ticket) return; el.innerHTML = `${header()}<div class="sp-body hint-text">没查到</div>`; wireHeader(); }
    );
  }

  function close() {
    el.classList.remove('open');
    if (closeTimer) clearTimeout(closeTimer);
    closeTimer = setTimeout(() => el.classList.add('hidden'), 220);
  }

  function renderResult(data, sentence, language, sourceMessageId) {
    const chunks = data.chunks || [];
    const grammarPoints = data.grammar_points || [];

    let html = header() + `<div class="sp-body">`;
    html += `<div class="drawer-sentence">${escapeHtml(sentence)}</div>`;
    html += `
      <div class="drawer-translation">
        <div class="drawer-section-label">中文翻译</div>
        <div class="txt">${escapeHtml(data.translation_zh || '')}</div>
      </div>`;

    if (chunks.length) {
      html += `<div class="drawer-section-label">成分</div><div class="chunk-row">`;
      for (const c of chunks) {
        html += `<div class="chunk" title="${escapeHtml(c.note || '')}"><div class="ctext">${escapeHtml(c.text)}</div><div class="crole">${escapeHtml(c.role || '')}</div></div>`;
      }
      html += `</div>`;
    }

    if (grammarPoints.length) {
      html += `<div class="drawer-section-label">语法点</div>`;
      grammarPoints.forEach((g, idx) => {
        html += `
          <div class="grammar-card" data-idx="${idx}">
            <div class="g-head">
              <div class="g-name">${escapeHtml(g.pattern || '')}</div>
              <div class="spacer"></div>
              <button class="star-btn" data-idx="${idx}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M6 3.5h12V21l-6-4.2L6 21V3.5z"></path></svg>
              </button>
            </div>
            <div class="g-exp">${escapeHtml(g.explanation_zh || '')}</div>
            ${g.example ? `<div class="g-example">例：${escapeHtml(g.example)}</div>` : ''}
          </div>`;
      });
    }
    html += `</div>`;
    el.innerHTML = html;
    wireHeader();

    el.querySelectorAll('.star-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (btn.classList.contains('saved')) return;
        const idx = Number(btn.dataset.idx);
        const g = grammarPoints[idx];
        btn.disabled = true;
        try {
          await LP.api.addPattern({
            language, pattern_name: g.pattern || '', explanation: g.explanation_zh || null,
            example_sentence: g.example || sentence, translation: data.translation_zh || null,
            source_message_id: sourceMessageId ?? null,
          });
          btn.classList.add('saved');
          LP.toast && LP.toast('已收藏到句型本');
        } catch (e) {
          LP.toast && LP.toast('没收藏上');
          btn.disabled = false;
        }
      });
    });
  }

  async function collectWholeSentence(sentence, language, sourceMessageId) {
    const data = await LP.api.explainSentence({ language, sentence });
    await LP.api.addPattern({
      language,
      pattern_name: sentence.length > 24 ? sentence.slice(0, 24) + '…' : sentence,
      explanation: data.translation_zh || null,
      example_sentence: sentence,
      translation: data.translation_zh || null,
      source_message_id: sourceMessageId ?? null,
    });
  }

  document.addEventListener('mousedown', (ev) => {
    if (!el.classList.contains('open')) return;
    if (el.contains(ev.target)) return;
    if (ev.target.closest && ev.target.closest('[data-action="sentence"]')) return;
    close();
  });
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') close(); });

  global.LP = global.LP || {};
  global.LP.sentencePanel = { open, close, collectWholeSentence };
})(window);
