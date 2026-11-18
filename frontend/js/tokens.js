/* tokens.js — 把 Token[] 渲染成可点 span。原样迁移自 frontend-paper-v1。 */
(function (global) {
  'use strict';

  function reconstructSentence(tokens) {
    let out = '';
    for (const t of tokens) {
      out += t.surface;
      if (t.space_after) out += ' ';
    }
    return out;
  }

  function showReading(span) {
    const surface = span.dataset.surface || '';
    span.replaceChildren(document.createTextNode(surface));
    span.classList.remove('lp-furigana');
    const reading = span.dataset.reading;
    if (!global.LP.furigana?.enabled() || span.dataset.lang !== 'ja' || !/\p{Script=Han}/u.test(surface) || !reading || !/[ァ-ヶぁ-ゖ]/u.test(reading)) return;
    const ruby = document.createElement('ruby'), base = document.createElement('rb'), rt = document.createElement('rt');
    base.textContent = surface;
    rt.textContent = reading.replace(/[ァ-ヶ]/g, char => String.fromCharCode(char.charCodeAt(0) - 0x60));
    rt.setAttribute('aria-hidden', 'true'); ruby.append(base, rt); span.replaceChildren(ruby); span.classList.add('lp-furigana');
  }

  function renderTokens(container, tokens, language, onTokenClick) {
    container.innerHTML = '';
    container.classList.add('tok-container');
    container.dataset.lang = language;
    const sentence = reconstructSentence(tokens);
    container.dataset.sentence = sentence;
    const occurrences = new Map();

    for (const t of tokens) {
      if (t.clickable && /\p{L}/u.test(t.surface)) {
        const identity = JSON.stringify([t.lemma || t.surface, t.surface]);
        t.lookup_occurrence = occurrences.get(identity) || 0;
        occurrences.set(identity, t.lookup_occurrence + 1);
      }
      const span = document.createElement('span');
      span.className = 'tok' + (t.clickable ? ' clickable' : ' punct') + (t.collected ? ' collected' : '');
      span.textContent = t.surface;
      span.dataset.i = t.i;
      span.dataset.lemma = t.lemma || t.surface;
      span.dataset.surface = t.surface;
      span.dataset.reading = t.reading || '';
      span.dataset.pos = t.pos || '';
      span.dataset.lang = language;
      showReading(span);
      if (t.clickable && onTokenClick) {
        span.addEventListener('click', (ev) => onTokenClick(ev, span, t, sentence));
      }
      container.appendChild(span);
      if (t.space_after) container.appendChild(document.createTextNode(' '));
    }
    return sentence;
  }

  function markCollectedGlobal(language, lemma) {
    const spans = document.querySelectorAll(`.tok[data-lang="${cssEscape(language)}"][data-lemma="${cssEscape(lemma)}"]`);
    spans.forEach((s) => s.classList.add('collected'));
  }

  function cssEscape(s) { return String(s).replace(/["\\]/g, '\\$&'); }

  global.addEventListener('lp:furigana', () => document.querySelectorAll('.tok[data-lang="ja"]').forEach(showReading));
  document.addEventListener('copy', event => {
    if (!global.LP.furigana?.enabled()) return;
    const selection = global.getSelection();
    const anchorNode = selection?.anchorNode;
    const anchorElement = anchorNode?.nodeType === Node.ELEMENT_NODE ? anchorNode : anchorNode?.parentElement;
    const anchor = anchorElement?.closest('.tok-container[data-lang="ja"]');
    if (!anchor || selection.isCollapsed || !event.clipboardData || !selection.rangeCount) return;
    event.clipboardData.setData('text/plain', global.LP.furigana.rangeText(selection.getRangeAt(0))); event.preventDefault();
  });

  global.LP = global.LP || {};
  global.LP.tokens = { renderTokens, reconstructSentence, markCollectedGlobal };
})(window);
