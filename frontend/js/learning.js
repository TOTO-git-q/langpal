/* learning.js — 学习这一侧的共用界面（docs/LEARNING.md）：
   「今天」页（GET /api/today、/api/learning/advice、/api/learning/stats）、
   复习会话（一屏一张卡：GET /api/review/queue → reveal → grade；空格翻面、1–4 评分、回车下一张；POST /api/review/session/end）、
   词条详情（GET /api/vocab/{id}，语境可删）。
   规矩：不写解释性的小字；评分按钮上直接写下次什么时候再见；不显示时间表、连续天数、等级。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const api = async (path, method = 'GET', body) => {
    const options = { method, cache: 'no-store' };
    if (body !== undefined) { options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    const response = await fetch('/api' + path, options);
    const data = await response.json().catch(() => ({}));
    // 后端的中文说明照样给；校验报错（英文）和没有说明的一律「没连上」，状态码只在 error.status 里
    if (!response.ok) { const e = new Error(typeof data.detail === 'string' ? data.detail : '没连上'); e.status = response.status; throw e; }
    return data;
  };
  const icon = (src) => { const img = el('img'); img.src = src; img.alt = ''; return img; };
  const LANG_KEY = 'jine.learning.language';
  function currentLanguage() {
    const list = LP.languages.list().map((l) => l.tag);
    let saved = null;
    try { saved = localStorage.getItem(LANG_KEY); } catch { /* 没有本地存储 */ }
    return list.includes(saved) ? saved : (LP.state.chatMain?.language && list.includes(LP.state.chatMain.language) ? LP.state.chatMain.language : list[0] || 'ja');
  }
  function setLanguage(tag) { try { localStorage.setItem(LANG_KEY, tag); } catch { /* 只记这次 */ } document.dispatchEvent(new CustomEvent('lp:learning-language', { detail: tag })); }

  // 间隔天数 → 人话：0 = 10 分钟
  function interval(days) {
    const d = Number(days);
    if (!Number.isFinite(d) || d <= 0) return '10 分钟';
    if (d < 1) return Math.max(1, Math.round(d * 24)) + ' 小时';
    if (d < 45) return Math.round(d) + ' 天';
    if (d < 365) return Math.round(d / 30) + ' 个月';
    return (d / 365).toFixed(d < 730 ? 1 : 0).replace(/\.0$/, '') + ' 年';
  }

  // 语言：一排小块，当前的实心
  function languageChips(onPick) {
    const box = el('div', '', 'lt-langs');
    box.setAttribute('role', 'radiogroup');
    const paint = () => {
      const now = currentLanguage();
      box.replaceChildren(...LP.languages.list().map((l) => {
        const b = button(l.label, () => { setLanguage(l.tag); paint(); onPick(l.tag); }, 'lt-lang');
        b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(l.tag === now)); b.lang = l.tag;
        return b;
      }));
    };
    paint();
    document.addEventListener('lp:languages', paint);
    return box;
  }

  // ================= 今天 =================
  const STEP = {
    review: { icon: 'assets/icons/review.png', label: '复习', go: () => openReview({}) },
    reading: { icon: 'assets/icons/reading.svg', label: '阅读', go: () => LP.appShell.switchTab('reading') },
    listening: { icon: 'assets/icons/listening.svg', label: '听力', go: () => LP.appShell.switchTab('listening') },
  };

  function mountToday(root) {
    root.innerHTML = '';
    const page = el('section', '', 'lt');
    const head = el('header', '', 'lt-head');
    head.append(el('h1', '今天', 'lt-title'), languageChips(() => void refresh()));
    const steps = el('div', '', 'lt-steps');
    // 上课：单独一行，点了去「学习 › 课程」上下一节（下一节由课程总览给）
    const lessonRow = el('div', '', 'lt-lesson');
    lessonRow.hidden = true;
    const stats = el('section', '', 'lt-stats');
    stats.hidden = true;
    stats.append(el('h2', '这个月', 'lt-stats-title'), el('div', '', 'lt-stats-body'));
    // 四件都做完：一行安静的完成状态，下面是「这个月」
    const done = el('p', '', 'lt-done');
    done.hidden = true;
    done.append(el('span', '✓', 'lt-done-mark'), el('span', '今天的都做完了'));
    page.append(head, done, steps, lessonRow, stats);
    root.append(page);
    root.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Enter' || ev.target.closest('button, a, input, textarea, select, summary')) return;
      const go = steps.querySelector('.lt-step.next .lt-main, .lt-step.next .lt-go');
      if (go) { ev.preventDefault(); go.click(); }
    });
    let ticket = 0;

    async function refresh() {
      const mine = ++ticket;
      const language = currentLanguage();
      let today, advice;
      try { [today, advice] = await Promise.all([api('/today?language=' + encodeURIComponent(language)), api('/learning/advice?language=' + encodeURIComponent(language)).catch(() => null)]); }
      catch (error) { steps.replaceChildren(el('p', error.message, 'lt-error')); return; }
      if (mine !== ticket) return;
      const list = today.steps || [];
      steps.replaceChildren(...list.map((step, i) => tile(step, advice?.[step.kind], i + 1)));
      paintLesson(list.find((step) => step.kind === 'output')?.target?.lesson, language);
      // 第一个没做完的是「下一步」：更重，Enter 直接进；做完的变淡
      const next = steps.querySelector('.lt-step:not(.done)');
      next?.classList.add('next');
      if (root.classList.contains('active') && !root.contains(document.activeElement)) next?.querySelector('.lt-main, .lt-go')?.focus({ preventScroll: true });
      const allDone = list.length > 0 && !next;
      page.classList.toggle('all-done', allDone);
      done.hidden = !allDone;
      const shown = await paintStats(stats.querySelector('.lt-stats-body'), language, () => mine === ticket);
      if (mine === ticket) stats.hidden = !shown;
    }

    function paintLesson(next, language) {
      lessonRow.hidden = !next;
      if (!next) { lessonRow.replaceChildren(); return; }
      const go = button('', async () => {
        go.disabled = true;
        try { await LP.lesson.start(language, next.unit_id); } catch { /* start 自己弹提示 */ } finally { go.disabled = false; }
      }, 'lt-lesson-go');
      go.append(icon('assets/icons/notebook.png'), el('span', '上课'), el('strong', next.title || ''));
      lessonRow.replaceChildren(go);
    }

    function tile(step, tip, order) {
      const box = el('article', '', 'lt-step' + (step.done ? ' done' : '') + ' lt-kind-' + step.kind);
      box.dataset.kind = step.kind;
      box.append(el('span', String(order), 'lt-order'));
      if (step.kind === 'output') {
        const main = el('div', '', 'lt-output');
        const chat = button('', () => LP.appShell.switchTab('talk'), 'lt-go');
        chat.append(icon('assets/icons/jine.png'), el('span', '聊天'));
        const coach = button('', () => LP.appShell.switchTab('coach'), 'lt-go');
        coach.append(icon('assets/icons/lesson.png'), el('span', '口语课'));
        if (step.target?.speaking_debts) coach.append(el('b', String(step.target.speaking_debts), 'lt-badge'));
        main.append(chat, coach);
        box.append(main);
        const chips = el('div', '', 'lt-chips');
        for (const w of step.target?.words || []) { const c = el('span', w.lemma, 'lt-chip'); c.title = w.meaning || ''; chips.append(c); }
        if (chips.childElementCount) box.append(chips);
        if (step.done) box.append(el('span', '✓', 'lt-check'));
        return box;
      }
      const def = STEP[step.kind];
      const go = button('', def.go, 'lt-main');
      go.append(icon(def.icon), el('strong', step.done ? '✓' : step.kind === 'review' ? String(step.count ?? 0) : '', 'lt-count'), el('span', def.label, 'lt-label'));
      go.setAttribute('aria-label', def.label + (step.kind === 'review' ? ' ' + (step.count ?? 0) + ' 张' : step.done ? ' 做过了' : ''));
      box.append(go);
      // 难度建议：一个小箭头，点开才有依据和「采纳」
      if (!step.done && (tip?.level === 'up' || tip?.level === 'down')) {
        const advice = el('details', '', 'lt-advice ' + tip.level);
        const sum = el('summary', tip.level === 'up' ? '▲' : '▼');
        sum.setAttribute('aria-label', tip.suggestion || '难度建议');
        const pop = el('div', '', 'lt-advice-pop');
        pop.append(el('strong', tip.suggestion || ''), el('p', tip.basis || ''), button(step.kind === 'reading' ? '找管家调' : '采纳', async (event) => {
          const btn = event.currentTarget;
          btn.disabled = true;
          try { const said = await adopt(step.kind, tip.level); advice.open = false; if (said) LP.toast?.(said); btn.disabled = false; }
          catch (error) { LP.toast?.(error.message); btn.disabled = false; }
        }, 'btn-sm primary'));
        advice.append(sum, pop);
        box.append(advice);
      }
      return box;
    }

    document.addEventListener('lp:learning-language', () => void refresh());
    void refresh();
    return { refresh };
  }

  // 采纳难度建议：听力挪一档听力安排里的难度，返回一句换成了什么；
  // 阅读没有单独的难度设置：去课程管家页，把这句话填进输入框，由他自己发（不说「好」）
  async function adopt(kind, level) {
    const language = currentLanguage();
    if (kind === 'listening') {
      const options = await api('/listening/options');
      const ladder = (options.difficulties || []).filter((d) => d.id !== 'default');
      const plan = options.plans?.[language] || {};
      const at = Math.max(0, ladder.findIndex((d) => d.id === plan.difficulty));
      const next = ladder[Math.min(ladder.length - 1, Math.max(0, at + (level === 'up' ? 1 : -1)))];
      if (!next) throw new Error('没有可换的难度');
      await api('/listening/plans/' + encodeURIComponent(language), 'POST', { format: plan.format, difficulty: next.id, topic: plan.topic || '' });
      return '听力难度：' + next.label;
    }
    await LP.workspaceAgent.prefill('把' + LP.languages.label(language) + '阅读的难度' + (level === 'up' ? '升' : '降') + '一档。');
    return null;
  }

  // ================= 统计：只画有数据的 =================
  const CAUSE = { not_heard: '没听清', not_understood: '没听懂', misjudged: '听懂了答错' };
  // current()：调用方的票号还有效吗（切语言后晚回来的旧结果不画）
  async function paintStats(body, language, current = () => true) {
    let s;
    try { s = await api('/learning/stats?language=' + encodeURIComponent(language) + '&days=30'); }
    catch { return false; }
    if (!current()) return false;
    const blocks = [];
    const bars = (title, rows) => {
      if (!rows.length) return;
      const box = el('section', '', 'lt-bars');
      box.append(el('h3', title));
      for (const r of rows) {
        const line = el('div', '', 'lt-bar');
        const fill = el('span', '', 'lt-bar-fill');
        fill.style.setProperty('--v', Math.round((r.value || 0) * 100) + '%');
        line.append(el('span', r.label, 'lt-bar-label'), fill, el('b', r.text));
        box.append(line);
      }
      blocks.push(box);
    };
    const pct = (v) => Math.round(v * 100) + '%';
    const skills = [];
    if (s.reading?.accuracy != null) skills.push({ label: '阅读', value: s.reading.accuracy, text: pct(s.reading.accuracy) });
    if (s.listening?.accuracy != null) skills.push({ label: '听力', value: s.listening.accuracy, text: pct(s.listening.accuracy) });
    if (s.listening?.dictation != null) skills.push({ label: '听写', value: s.listening.dictation, text: pct(s.listening.dictation) });
    if (s.review?.retention_30d != null) skills.push({ label: '记住', value: s.review.retention_30d, text: pct(s.review.retention_30d) });
    bars('正确率', skills);
    for (const skill of ['reading', 'listening']) {
      const types = s[skill]?.types;
      if (types) bars(skill === 'reading' ? '阅读题型' : '听力题型', Object.values(types).sort((a, b) => a.accuracy - b.accuracy).map((t) => ({ label: t.label, value: t.accuracy, text: t.correct + '/' + t.n })));
    }
    const causes = s.listening?.causes;
    if (causes) {
      const total = Object.values(causes).reduce((a, b) => a + b, 0) || 1;
      bars('听力错在哪', Object.entries(causes).map(([k, n]) => ({ label: CAUSE[k] || k, value: n / total, text: String(n) })));
    }
    const numbers = el('div', '', 'lt-numbers');
    if (s.review?.count) numbers.append(number(s.review.count, '张复习'), number(s.review.forgot, '张忘了'));
    if (s.words_encountered) numbers.append(number(s.words_encountered, '个词又碰到了'));
    if (s.reading?.count) numbers.append(number(s.reading.count, '篇阅读'));
    if (s.listening?.count) numbers.append(number(s.listening.count, '段听力'));
    if (numbers.childElementCount) blocks.unshift(numbers);
    body.replaceChildren(...blocks);
    return blocks.length > 0;
  }
  function number(n, label) { const b = el('div', '', 'lt-number'); b.append(el('strong', String(n)), el('span', label)); return b; }

  // ================= 复习会话 =================
  // options: { kinds, language }。复习页还没挂好时先记下，挂好后第一场就按它开
  let drill = null, waiting = null;
  function openReview(options = {}) {
    if (!drill) waiting = options;
    LP.appShell.switchTab('drill');
    drill?.start(options);
  }

  // 放一段：每个 audio 只留一个「到 end 就停」，新的一段开始前把旧的摘掉
  function playClip(audio, clip) {
    if (audio._stopClip) audio.removeEventListener('timeupdate', audio._stopClip);
    audio._stopClip = null;
    if (clip) {
      audio.currentTime = clip.start;
      const stop = () => { if (audio.currentTime >= clip.end) { audio.pause(); audio.removeEventListener('timeupdate', stop); audio._stopClip = null; } };
      audio._stopClip = stop;
      audio.addEventListener('timeupdate', stop);
    }
    void audio.play().catch(() => {});
  }

  function mountReview(root) {
    root.innerHTML = '';
    const page = el('section', '', 'rv2');
    const bar = el('div', '', 'rv2-progress');
    const fill = el('span', '', 'rv2-progress-fill');
    bar.append(fill);
    const stage = el('div', '', 'rv2-stage');
    page.append(bar, stage);
    root.append(page);
    let queue = [], done = 0, forgot = 0, total = 0, card = null, revealed = null, shownAt = 0, language = currentLanguage(), kinds = null, started = false, busy = false;
    LP.scene?.provide('drill', () => ({ language }));

    function progress() {
      const left = queue.length + (card ? 1 : 0);
      bar.hidden = !total;
      fill.style.width = (total ? Math.round((done / Math.max(total, done + left)) * 100) : 0) + '%';
      bar.setAttribute('aria-label', '还剩 ' + left + ' 张');
    }

    let startTicket = 0;
    async function start(options = {}) {
      const mine = ++startTicket;
      language = options.language || currentLanguage();
      kinds = options.kinds || null;
      done = 0; forgot = 0; card = null; revealed = null;
      stage.replaceChildren(el('div', '', 'rv2-card rv2-skeleton'));
      try {
        const q = await api('/review/queue?' + new URLSearchParams({ language, limit: 60, ...(kinds ? { kinds: kinds.join(',') } : {}) }));
        if (mine !== startTicket) return;
        queue = q.cards || [];
        total = queue.length;
        started = true;
        next();
      } catch (error) { stage.replaceChildren(el('p', error.message, 'lt-error')); }
    }

    function next() {
      card = queue.shift() || null;
      revealed = null;
      progress();
      if (!card) { void finish(); return; }
      shownAt = performance.now();
      paint();
    }

    function sentence(text) {
      const p = el('p', '', 'rv2-sentence');
      p.lang = card.language;
      const parts = String(text || '').split('____');
      parts.forEach((part, i) => { p.append(document.createTextNode(part)); if (i < parts.length - 1) p.append(el('span', '', 'rv2-blank')); });
      return p;
    }

    function paint() {
      const box = el('article', '', 'rv2-card rv2-' + card.kind);
      box.tabIndex = -1;
      const front = el('div', '', 'rv2-front');
      if (card.kind === 'vocab' || card.kind === 'pattern') {
        if (card.sentence) front.append(sentence(card.sentence));
        else front.append(el('p', card.meaning || card.explanation || '', 'rv2-prompt'));
        if (card.kind === 'vocab' && card.sentence && card.hint) front.append(el('span', card.hint + '…', 'rv2-hint'));
        if (card.kind === 'pattern' && card.translation) front.append(el('span', card.translation, 'rv2-hint'));
        box.append(front);
        if (!revealed) {
          const flip = button('翻面', () => void reveal({}), 'rv2-flip');
          flip.append(el('kbd', '空格'));
          box.append(flip, button('想不起来', () => void reveal({ gave_up: true }), 'rv2-giveup'));
        } else box.append(back(), rating());
      } else if (card.kind === 'vocab_produce') {
        front.append(el('p', card.meaning || '', 'rv2-prompt'));
        if (card.sentence) front.append(sentence(card.sentence));
        box.append(front);
        const input = el('input', '', 'rv2-type');
        input.lang = card.language; input.autocomplete = 'off'; input.spellcheck = false; input.setAttribute('aria-label', '打出这个词');
        if (revealed) { input.value = revealed.answer || ''; input.disabled = true; input.classList.add(revealed.correct ? 'ok' : 'bad'); }
        box.append(input);
        if (!revealed) {
          input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); if (input.value.trim()) void reveal({ answer: input.value.trim() }); } });
          box.append(button('看答案', () => void reveal({}), 'rv2-giveup'));
          requestAnimationFrame(() => input.focus());
        } else box.append(back(), verdict());
      } else {
        // reading_q / listening_q：选一个
        front.append(el('h3', card.title || '', 'rv2-title'));
        if (card.kind === 'listening_q' && card.audio) front.append(clipPlayer(card));
        if (card.kind === 'reading_q' && card.paragraph) {
          const para = el('blockquote', '', 'rv2-para rv2-passage'); para.lang = card.language;
          for (const p of String(card.paragraph).split(/\n+/).map((x) => x.trim()).filter(Boolean)) para.append(el('p', p));
          front.append(para);
        }
        const q = el('p', card.question || '', 'rv2-question'); q.lang = card.language;
        front.append(q);
        const options = el('div', '', 'rv2-options');
        (card.options || []).forEach((text, i) => {
          const b = button('', () => { if (!revealed) void reveal({ answer: i }); }, 'rv2-option');
          b.append(el('kbd', String(i + 1)), el('span', text));
          b.lang = card.language;
          if (revealed) {
            if (i === revealed.back.answer) b.classList.add('right');
            else if (i === revealed.answer) b.classList.add('wrong');
            b.disabled = true;
          }
          options.append(b);
        });
        front.append(options);
        box.append(front);
        if (!revealed) box.append(button('看答案', () => void reveal({}), 'rv2-giveup'));
        else box.append(back(), verdict());
      }
      stage.replaceChildren(box);
      if (!stage.querySelector('input:not([disabled])')) box.focus({ preventScroll: true });
    }

    function back() {
      const b = revealed.back || {};
      const box = el('div', '', 'rv2-back');
      if (card.kind === 'vocab' || card.kind === 'vocab_produce') {
        const word = el('div', '', 'rv2-word'); word.lang = card.language;
        word.append(el('strong', b.surface || b.lemma || ''));
        if (b.reading && b.reading !== (b.surface || b.lemma)) word.append(el('span', b.reading, 'rv2-reading'));
        box.append(word, el('p', b.meaning || '', 'rv2-meaning'));
        for (const s of [b.sentence, ...(b.other_sentences || [])].filter(Boolean).slice(0, 4)) { const p = el('p', s, 'rv2-example'); p.lang = card.language; box.append(p); }
      } else if (card.kind === 'pattern') {
        const name = el('strong', b.pattern || '', 'rv2-word'); name.lang = card.language;
        box.append(name, el('p', b.explanation || '', 'rv2-meaning'));
        if (b.example) { const p = el('p', b.example, 'rv2-example'); p.lang = card.language; box.append(p); }
      } else {
        if (b.explanation) box.append(el('p', b.explanation, 'rv2-meaning'));
        if (b.quote) { const q = el('blockquote', b.quote, 'rv2-para'); q.lang = card.language; box.append(q); }
        for (const line of b.evidence || []) { const q = el('blockquote', (line.speaker ? line.speaker + ' · ' : '') + line.text, 'rv2-para'); q.lang = card.language; box.append(q); }
      }
      return box;
    }

    // 自评：四个按钮，按钮上写下次什么时候再见；1–4
    function rating() {
      const row = el('div', '', 'rv2-rating');
      for (const r of [1, 2, 3, 4]) {
        const b = button('', () => void grade({ rating: r }), 'rv2-rate r' + r);
        b.append(el('kbd', String(r)), el('span', interval(revealed.intervals?.[r] ?? revealed.intervals?.[String(r)])));
        if (revealed.peeked && r > 1) b.disabled = true;
        row.append(b);
      }
      return row;
    }
    // 作答卡：服务端判了对错；显示下次间隔，回车下一张
    function verdict() {
      const ok = revealed.correct === true;
      const r = revealed.peeked ? 1 : ok ? 3 : 1;
      const row = el('div', '', 'rv2-verdict ' + (ok ? 'ok' : 'bad'));
      row.append(el('span', ok ? '✓' : '✗', 'rv2-mark'), el('span', interval(revealed.intervals?.[r] ?? revealed.intervals?.[String(r)]), 'rv2-next'));
      const go = button('下一张', () => void grade({}), 'primary rv2-next-btn');
      go.append(el('kbd', '↵'));
      row.append(go);
      return row;
    }

    function clipPlayer(c) {
      const wrap = el('div', '', 'rv2-clip');
      const audio = el('audio'); audio.preload = 'none'; audio.src = c.audio;
      const clips = c.clips?.length ? c.clips : [null];
      clips.forEach((clip, i) => {
        const b = button('▶' + (clips.length > 1 ? ' ' + (i + 1) : ''), () => playClip(audio, clip), 'rv2-play');
        wrap.append(b);
      });
      wrap.append(audio);
      return wrap;
    }

    async function reveal(body) {
      if (busy || revealed || !card) return;
      busy = true;
      try {
        const r = await api('/review/cards/' + card.id + '/reveal', 'POST', body);
        revealed = { ...r, answer: body.answer };
        paint();
      } catch (error) { LP.toast?.(error.message); }
      finally { busy = false; }
    }

    async function grade({ rating }) {
      if (busy || !revealed || !card) return;
      busy = true;
      const body = { request_id: 'g' + card.id + '-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), answer_ms: Math.round(performance.now() - shownAt) };
      if (rating) body.rating = rating;
      if (revealed.answer !== undefined) body.answer = revealed.answer;
      try {
        const r = await api('/review/cards/' + card.id + '/grade', 'POST', body);
        done += 1;
        if ((r.rating ?? rating) === 1) forgot += 1;
        if (r.again_in_session) queue.push(card);
        next();
      } catch (error) { LP.toast?.(error.message); }
      finally { busy = false; }
    }

    async function finish() {
      started = false;
      stage.replaceChildren(el('p', '…', 'rv2-wait'));
      let summary = null;
      try { await api('/review/session/end', 'POST', { language }); } catch { /* 记录失败不挡结束画面 */ }
      try { summary = await api('/review/summary?language=' + encodeURIComponent(language)); } catch { /* 没有就不画 */ }
      const end = el('section', '', 'rv2-end');
      const nums = el('div', '', 'rv2-end-numbers');
      const big = (n, label, cls = '') => { const b = el('div', '', 'rv2-end-number ' + cls); b.append(el('strong', String(n)), el('span', label)); return b; };
      if (done) { nums.append(big(done, '张做完'), big(forgot, '张忘了', forgot ? 'bad' : '')); end.append(nums); }
      const days = (summary?.forecast || []).slice(0, 7);
      if (days.length) {
        const max = Math.max(1, ...days.map((d) => d.due || 0));
        const chart = el('div', '', 'rv2-forecast');
        chart.setAttribute('aria-label', '接下来 7 天要复习的张数');
        days.forEach((d, i) => {
          const col = el('div', '', 'rv2-day' + (i === 0 ? ' today' : ''));
          const bar = el('span', '', 'rv2-day-bar');
          bar.style.height = Math.round(((d.due || 0) / max) * 100) + '%';
          const when = new Date(String(d.date) + 'T00:00:00');
          col.append(el('b', String(d.due || 0)), el('span', '', 'rv2-day-track'), el('small', i === 0 ? '今天' : i === 1 ? '明天' : '周' + (['日', '一', '二', '三', '四', '五', '六'][when.getDay()] || '')));
          col.querySelector('.rv2-day-track').append(bar);
          chart.append(col);
        });
        end.append(chart);
      }
      const next = LP.util.nextActions('review');
      next.querySelector('.next-go').classList.add('rv2-home');
      end.append(next);
      stage.replaceChildren(end);
      next.querySelector('.next-go').focus();
      progress();
      bar.hidden = true;
    }

    document.addEventListener('keydown', (ev) => {
      if (!root.classList.contains('active') || !card || ev.ctrlKey || ev.metaKey || ev.altKey || ev.isComposing) return;
      if (ev.target.matches?.('input:not([disabled]), textarea')) return;
      const self = card.kind === 'vocab' || card.kind === 'pattern';
      if (ev.key === ' ' && self && !revealed) { ev.preventDefault(); void reveal({}); }
      else if (/^[1-4]$/.test(ev.key) && self && revealed) { ev.preventDefault(); const b = stage.querySelector('.rv2-rate.r' + ev.key); if (!b?.disabled) void grade({ rating: Number(ev.key) }); }
      else if (/^[1-9]$/.test(ev.key) && !self && card.kind !== 'vocab_produce' && !revealed) { const i = Number(ev.key) - 1; if (i < (card.options || []).length) { ev.preventDefault(); void reveal({ answer: i }); } }
      else if (ev.key === 'Enter' && !self && revealed) { ev.preventDefault(); void grade({}); }
    });
    // 离开复习页：停掉卡上的录音，结束这次会话
    const leave = () => {
      stage.querySelectorAll('audio').forEach((audio) => audio.pause());
      if (started && done) void api('/review/session/end', 'POST', { language }).catch(() => {});
    };
    global.addEventListener('pagehide', leave);
    drill = { start, leave, active: () => started, refresh: () => { if (!started) void start({ kinds }); } };
    void start(waiting || {});
    waiting = null;
    return drill;
  }

  // ================= 词条详情 =================
  let vocabDialog = null;
  async function openVocab(id) {
    if (!vocabDialog) {
      vocabDialog = el('dialog', '', 'lt-vocab');
      document.body.append(vocabDialog);
      vocabDialog.addEventListener('click', (ev) => { if (ev.target === vocabDialog) vocabDialog.close(); });
    }
    vocabDialog.replaceChildren(el('p', '…', 'lt-wait'));
    if (!vocabDialog.open) vocabDialog.showModal();
    let v;
    try { v = await api('/vocab/' + id); } catch (error) { vocabDialog.replaceChildren(el('p', error.message, 'lt-error')); return; }
    const head = el('header', '', 'lt-vocab-head');
    const word = el('strong', v.surface || v.lemma); word.lang = v.language;
    head.append(word);
    if (v.reading && v.reading !== (v.surface || v.lemma)) head.append(el('span', v.reading, 'lt-vocab-reading'));
    head.append(button('×', () => vocabDialog.close(), 'lt-close'));
    const facts = el('div', '', 'lt-numbers');
    facts.append(number(v.encounters ?? 0, '次遇见'));
    if (v.remember_days != null) facts.append(number(Math.max(0, Math.round(v.remember_days)), '天大约记得住'));
    const due = v.card?.due_at || v.due_at;
    if (due) { const d = new Date(String(due).replace(' ', 'T')); if (Number.isFinite(d.getTime())) facts.append(number((d.getMonth() + 1) + '/' + d.getDate(), '下次')); }
    const list = el('ul', '', 'lt-contexts');
    const contexts = v.contexts || [];
    for (const c of contexts) {
      const li = el('li');
      const s = el('span', c.sentence, 'lt-context'); s.lang = v.language;
      const src = el('span', { chat: '聊天', reading: '阅读', listening: '听力' }[c.source_kind] || c.source_kind || '', 'lt-context-src');
      const del = button('×', async () => {
        const ok = await LP.util.confirm({ title: '删掉这句？', text: c.sentence, ok: '删除' });
        if (!ok) return;
        try { await api('/vocab/' + id + '/contexts?context_id=' + c.id, 'DELETE'); await openVocab(id); } catch (error) { LP.toast?.(error.message); }
      }, 'lt-context-del');
      del.setAttribute('aria-label', '删掉这句');
      del.disabled = contexts.length <= 1;
      li.append(src, s, del);
      list.append(li);
    }
    const meaning = el('p', '', 'lt-vocab-meaning');
    const showMeaning = () => meaning.replaceChildren(document.createTextNode(v.meaning || ''), button('改', editMeaning, 'lt-context-del'));
    function editMeaning() {
      const input = el('input'); input.type = 'text'; input.value = v.meaning || ''; input.maxLength = 300;
      let saving = false;
      const save = button('存', async () => {
        if (saving || !input.value.length) return;
        saving = true; save.disabled = true;
        try {
          const updated = await api('/notebook/' + id, 'PUT', { meaning: input.value });
          v.meaning = updated.meaning; showMeaning();
          void LP.notebook?.refresh();
        } catch (error) { LP.toast?.(error.message); }
        finally { saving = false; save.disabled = false; }
      }, 'lt-context-del');
      const cancel = button('取消', showMeaning, 'lt-context-del');
      input.onkeydown = event => {
        if (event.isComposing) return;
        if (event.key === 'Enter') { event.preventDefault(); save.click(); }
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); showMeaning(); }
      };
      meaning.replaceChildren(input, save, cancel); input.focus();
    }
    showMeaning();
    vocabDialog.replaceChildren(head, meaning, facts, list);
  }

  global.LP = global.LP || {};
  global.LP.learning = { mountToday, mountReview, openReview, openVocab, paintStats, playClip, interval, currentLanguage };
})(window);
