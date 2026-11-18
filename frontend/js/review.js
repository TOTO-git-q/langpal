/* review.js — 错题本：阅读和听力的错题回看（题目、证据段落、你当时选的、正确答案、依据；听力带原音频片段）。
   要练就点「开始复习」进统一复习会话（learning.js），这里不再有作答界面。 */
(function (global) {
  'use strict';
  const kinds = {
    reading: { label: '阅读', api: '/api/reader/errors', icon: 'reading.svg' },
    listening: { label: '听力', api: '/api/listening/errors', icon: 'listening.svg' },
  };
  let root, controller, kind, language;
  const removing = new Set();   // 删了还在 5 秒撤销期里的听力练习：刷新时不画回来
  const make = (tag, text, className) => global.LP.util.el(tag, text, className);
  const shortDate = (value) => global.LP.util.shortDate(value);

  function mount(panel) {
    root = panel;
    root.innerHTML = `
      <section class="rv-shell" aria-labelledby="rv-page-title">
        <h1 id="rv-page-title" class="visually-hidden">错题本</h1>
        <div class="rv-toolbar workspace-tools">
          <div class="rv-kinds" role="group" aria-label="错题类型">
            <button type="button" data-kind="all">全部</button>
            <button type="button" data-kind="reading"><img src="assets/icons/reading.svg" alt="">阅读</button>
            <button type="button" data-kind="listening"><img src="assets/icons/listening.svg" alt="">听力</button>
          </div>
          <input type="search" class="list-search" data-search placeholder="搜索" aria-label="搜索错题">
          <select class="rv-languages" aria-label="错题语言"></select>
          <span class="rv-count"></span>
          <button type="button" class="rv-start-review" data-start-review>开始复习</button>
        </div>
        <p class="rv-status" role="status"></p>
        <div class="rv-items"></div>
      </section>`;
    root.querySelector('[data-start-review]').addEventListener('click', () => {
      LP.learning?.openReview({ kinds: kind === 'reading' ? ['reading_q'] : kind === 'listening' ? ['listening_q'] : ['reading_q', 'listening_q'], ...(language ? { language } : {}) });
    });
    root.querySelectorAll('[data-kind]').forEach((button) => button.addEventListener('click', () => { setFilter(button.dataset.kind, language); void refresh(); }));
    root.querySelector('[data-search]').addEventListener('input', applySearch);
    renderLanguages();
    document.addEventListener('lp:languages', renderLanguages);
    root.addEventListener('play', (event) => { pause(!document.hidden && root.getClientRects().length ? event.target : null); }, true);
    document.addEventListener('visibilitychange', () => { if (document.hidden) pause(); });
    setFilter(kind ?? global.LP.preferences?.get('reviewKind'), language ?? global.LP.preferences?.get('reviewLanguage'));
    void refresh();
  }

  function renderLanguages() {
    const items = global.LP.languages?.list() || [];
    // 语言是一个下拉：少一排按钮
    const group = root.querySelector('.rv-languages');
    group.replaceChildren(...[{ tag: '', label: '全部语言' }, ...items].map(({ tag, label }) => new Option(label, tag)));
    group.value = language || '';
    group.onchange = () => { if (group.value !== language) { setFilter(kind, group.value); void refresh(); } };
  }

  function setFilter(type, lang = '') {
    kind = Object.hasOwn(kinds, type) ? type : 'all';
    language = /^[a-z]{2,3}(?:-[a-zA-Z0-9]{2,4}){0,2}$/.test(lang) ? lang : '';
    if (!root) return;
    root.querySelectorAll('[data-kind]').forEach((button) => button.setAttribute('aria-pressed', button.dataset.kind === kind));
    const select = root.querySelector('.rv-languages');
    if (select) select.value = language;
  }

  function applySearch() {
    const q = (root?.querySelector('[data-search]')?.value || '').trim().toLowerCase();
    let n = 0;
    root?.querySelectorAll('.rv-entry').forEach((entry) => { const hit = !q || entry.textContent.toLowerCase().includes(q); entry.hidden = !hit; if (hit) n += 1; });
    const count = root?.querySelector('.rv-count');
    if (count && root.querySelector('.rv-entry')) count.textContent = n + ' 题';
  }

  function pause(except = null) { root?.querySelectorAll('audio').forEach((audio) => { if (audio !== except) audio.pause(); }); }

  // 一道错题：展开是回看
  function renderEntry(item) {
    const listening = item.kind === 'listening';
    const definition = kinds[item.kind];
    const entry = make('details', '', 'rv-entry');
    if (item.practice_id) entry.dataset.practice = item.practice_id;
    const summary = make('summary');
    const badge = make('span', '', 'rv-kind');
    const icon = make('img'); icon.src = 'assets/icons/' + definition.icon; icon.alt = '';
    badge.append(icon);
    badge.setAttribute('aria-label', definition.label);
    const heading = make('span', '', 'rv-question');
    const question = make('strong', listening ? item.prompt : item.question);
    question.lang = item.language;
    heading.append(question, make('small', item.title));
    summary.append(badge, heading, make('time', shortDate(item.updated_at), 'rv-date'));
    entry.append(summary);

    const body = make('div', '', 'rv-detail');
    // 证据：阅读是原文段落；听力是依据句，每句能单独听
    if (listening) {
      const audio = make('audio');
      audio.preload = 'none';
      entry.addEventListener('toggle', () => {
        if (!entry.open) audio.pause();
        else if (!audio.hasAttribute('src')) audio.src = kinds.listening.api + '/' + encodeURIComponent(item.practice_id) + '/audio';
      });
      const quote = make('div', '', 'rv-evidence');
      (item.evidence || []).forEach((line, i) => {
        const row = make('p', '', 'rv-line');
        row.lang = item.language;
        const clip = (item.clips || [])[i]; // clips 和 evidence 一一对应
        const play = make('button', '▶', 'rv-line-play');
        play.type = 'button';
        play.setAttribute('aria-label', '听这一句');
        play.addEventListener('click', () => {
          if (!audio.hasAttribute('src')) audio.src = kinds.listening.api + '/' + encodeURIComponent(item.practice_id) + '/audio';
          global.LP.learning.playClip(audio, clip);
        });
        row.append(play, make('span', (line.speaker ? line.speaker + ' · ' : '') + line.text));
        quote.append(row);
      });
      body.append(quote, audio);
    } else if (item.paragraph || item.quote) {
      // 只留那一段，引文高亮
      const text = global.LP.util.evidenceParagraph(item.paragraph || item.quote, item.quote);
      const quote = make('blockquote', '', 'rv-evidence');
      quote.lang = item.language;
      const at = item.quote ? text.indexOf(item.quote) : -1;
      if (at >= 0) quote.append(text.slice(0, at), make('mark', item.quote), text.slice(at + item.quote.length));
      else quote.textContent = text;
      body.append(quote);
    }
    // 选项：你当时选的打叉，正确答案打勾
    const options = listening ? item.choices : item.options;
    const picked = listening ? item.selection : item.selected;
    const list = make('ol', '', 'rv-options');
    (options || []).forEach((text, index) => {
      const li = make('li', '', 'rv-option' + (index === item.answer ? ' right' : index === picked ? ' wrong' : ''));
      li.lang = item.language;
      li.append(make('span', index === item.answer ? '✓' : index === picked ? '✗' : String(index + 1), 'rv-mark'), make('span', text));
      list.append(li);
    });
    body.append(list);
    if (item.explanation) body.append(make('p', item.explanation, 'rv-explain'));
    const foot = make('div', '', 'rv-foot');
    if (!listening) {
      const remove = make('button', '删除这题', 'row-danger');
      remove.type = 'button';
      remove.onclick = async () => {
        if (!await LP.util.confirm({ title: '删掉这道错题？' })) return;
        try {
          const ident = item.exercise_id + ':' + item.item_index;
          const response = await fetch('/api/reading/errors/' + encodeURIComponent(ident), { method: 'DELETE' });
          if (!response.ok) throw new Error();
          await refresh();
        } catch { LP.toast?.('没删掉'); }
      };
      foot.append(remove);
    }
    if (!listening && /^https?:\/\//i.test(item.source_url || '')) {
      const source = make('a', '原文');
      source.href = item.source_url; source.target = '_blank'; source.rel = 'noopener noreferrer';
      foot.append(source);
    }
    if (listening) {
      // 听力错题按「一组练习」删：收在行内「⋯」里；先拿掉，5 秒内能撤销
      const more = make('details', '', 'row-more');
      more.append(make('summary', '⋯'));
      more.querySelector('summary').setAttribute('aria-label', '更多');
      const pop = make('div', '', 'row-more-pop pixel-box');
      const removeGroup = make('button', '删除这组', 'row-danger');
      removeGroup.type = 'button';
      removeGroup.addEventListener('click', () => {
        more.open = false;
        const group = [...root.querySelectorAll('.rv-entry')].filter((e) => e.dataset.practice === item.practice_id);
        const spots = group.map((e) => [e, e.nextSibling, e.parentElement]);
        global.LP.appShell.undoable('已删除这组', {
          remove: () => { removing.add(item.practice_id); group.forEach((e) => e.remove()); applySearch(); },
          restore: () => { removing.delete(item.practice_id); spots.forEach(([e, after, parent]) => parent?.insertBefore(e, after && after.parentElement === parent ? after : null)); applySearch(); },
          commit: async () => {
            const response = await fetch(kinds.listening.api + '/' + encodeURIComponent(item.practice_id), { method: 'DELETE' }).catch(() => null);
            removing.delete(item.practice_id);
            if (!response?.ok) { global.LP.toast?.('没删掉'); void refresh(); }
          },
        });
      });
      pop.append(removeGroup);
      more.append(pop);
      foot.append(more);
    }
    if (foot.childElementCount) body.append(foot);
    entry.append(body);
    return entry;
  }

  async function refresh() {
    if (!root) return;
    controller?.abort();
    const load = new AbortController();
    controller = load;
    const list = root.querySelector('.rv-items');
    const status = root.querySelector('.rv-status');
    const count = root.querySelector('.rv-count');
    pause();
    list.replaceChildren(...Array.from({ length: 3 }, () => { const s = make('div', '', 'rv-entry rv-skeleton'); s.setAttribute('aria-hidden', 'true'); return s; }));
    count.textContent = '';
    status.textContent = '';
    const selected = kind === 'all' ? Object.keys(kinds) : [kind];
    const query = language ? '?' + new URLSearchParams({ lang: language }) : '';
    const responses = await Promise.allSettled(selected.map(async (type) => {
      const response = await fetch(kinds[type].api + query, { signal: load.signal });
      if (!response.ok) throw new Error(response.statusText);
      const { items } = await response.json();
      return items.map((item) => ({ ...item, kind: type }));
    }));
    if (load.signal.aborted) return;
    list.replaceChildren();
    const unavailable = selected.filter((_, i) => responses[i].status === 'rejected');
    const items = responses.flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
      .filter((item) => !(item.kind === 'listening' && removing.has(item.practice_id)));
    items.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    status.textContent = unavailable.length ? unavailable.map((type) => kinds[type].label).join('、') + '错题没打开' : '';
    if (unavailable.length < selected.length) count.textContent = items.length + ' 题';
    root.querySelector('[data-start-review]').disabled = !items.length;
    if (items.length) { list.replaceChildren(...items.map(renderEntry)); applySearch(); }
    else if (!unavailable.length) {
      // 空：一个图标 + 一个动作
      const empty = make('div', '', 'empty-state');
      const icon = make('img'); icon.src = 'assets/icons/review.png'; icon.alt = '';
      const go = make('button', '读一篇', 'primary'); go.type = 'button';
      go.addEventListener('click', () => global.LP.appShell?.switchTab('reading'));
      empty.append(icon, go);
      list.append(empty);
    }
  }

  global.LP = global.LP || {};
  global.LP.review = { mount, refresh, setFilter, pause };
})(window);
