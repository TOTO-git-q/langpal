/* Shared sentence gloss cache. No LLM request on a warm word click. */
(function (global) {
  'use strict';
  const cache = new Map(), pending = new Map(), queue = [];
  const MAX_ENTRIES = 128;
  let running = 0;
  const normalize = text => String(text).replace(/\s+/g, ' ').trim();
  const keyFor = (language, sentence) => JSON.stringify([language, normalize(sentence)]);
  function store(key, words) {
    cache.delete(key); cache.set(key, words);
    while (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value);
    return words;
  }
  function drain() {
    while (running < 2 && queue.length) {
      const job = queue.shift(); running++;
      Promise.resolve().then(() => LP.api.explainWords({ language: job.language, sentence: normalize(job.sentence) }))
        .then(data => store(job.key, data.words || [])).then(job.resolve, job.reject)
        .finally(() => { pending.delete(job.key); running--; drain(); });
    }
  }
  function prepare(language, sentence, tokens) {
    const key = keyFor(language, sentence);
    const inline = tokens?.filter(t => t.clickable && t.gloss?.meaning_zh).map(t => t.gloss);
    if (inline?.length && tokens.filter(t => t.clickable).every(t => t.gloss?.meaning_zh)) store(key, inline);
    if (cache.has(key)) return Promise.resolve(cache.get(key));
    if (pending.has(key)) return pending.get(key);
    if (!normalize(sentence) || normalize(sentence).length > 6000 || !LP.api.explainWords) return Promise.resolve([]);
    // Avoid building an unbounded queue when rapidly scrolling/changing pages.
    if (queue.length >= 12) return Promise.resolve([]);
    const promise = new Promise((resolve, reject) => { queue.push({ key, language, sentence, resolve, reject }); });
    pending.set(key, promise); drain();
    return promise;
  }
  function find(words, token) {
    const sameSurface = words.filter(word => word.surface === token.surface);
    const sameLemma = sameSurface.filter(word => word.lemma === token.lemma);
    const matches = sameLemma.length ? sameLemma : sameSurface;
    if (Number.isInteger(token.lookup_occurrence)) return matches.find(word => (word.occurrence || 0) === token.lookup_occurrence) || null;
    // Selections in a reader need no guessed occurrence when multiple senses exist.
    return matches.length === 1 || matches.every(word => word.meaning_zh === matches[0].meaning_zh) ? matches[0] || null : null;
  }
  function peek(language, sentence, token) {
    return token.gloss || find(cache.get(keyFor(language, sentence)) || [], token);
  }
  // signal 只取消这一次查词：整句释义是多个词共用的缓存，不跟着某一个弹层的「取消」一起作废。
  async function word(body, token = {}, signal) {
    const target = { lemma: body.lemma, surface: body.surface, ...token };
    const ready = peek(body.language, body.sentence, target);
    if (ready) return ready;
    try {
      const words = await prepare(body.language, body.sentence);
      const result = find(words, target);
      if (result) return result;
    } catch { /* Only the requested word needs the slower detail fallback. */ }
    signal?.throwIfAborted();
    return { ...await LP.api.explainWord(body, signal), detail: 'full' };
  }
  global.LP = global.LP || {};
  global.LP.glosses = { prepare, peek, word, normalize };
})(window);
