/* 口语页。首页和听力页一个样子：上面一张主操作卡（选中的练法 + 开始），左边练法格子和最近几节，右边这个月。
   上课、跟读是口语程序自己的页面（iframe），开着的课换页也不断；点最近的一节看反馈和字幕。 */
(function (global) {
  'use strict';
  const scoreLabels = { fluency: '流利度', accuracy: '准确度', vocabulary_register: '用词与语域', pronunciation: '发音', interaction: '互动' };
  const tabs = [['feedback', '反馈'], ['captions', '字幕']];
  const KIND = { lesson: '对话课', placement: '定级', shadowing: '跟读' };
  const LANG_TAG = { ja: '日', en: 'EN', de: 'DE', fr: 'FR', zh: '中', ko: '韩' };
  let root, frame, shadowFrame, connecting, voiceOpening, visible = 'home', generation = 0, homeTicket = 0;
  const picked = { feedback: '', captions: '' };
  let practice = null, practiceTab = null, practiceBrief = null;
  let chosen = (() => { try { return localStorage.getItem('lp.coach.pick') || 'voice'; } catch { return 'voice'; } })();

  const { el: node, button } = global.LP.util;

  async function ensure() {
    const response = await fetch('/api/listening/coach', { cache: 'no-store' });
    if (!response.ok) return { ok: false, error: '口语课没打开' };
    const settings = await response.json();
    const desktop = global.langpalDesktop;
    if (settings.desktop_managed && typeof desktop?.ensureCoach === 'function') {
      const result = await desktop.ensureCoach();
      return { ...settings, ...result, url: result?.url || settings.url, error: result?.error || '口语课没打开' };
    }
    try {
      await fetch(new URL('/api/health', settings.url), { mode: 'no-cors', cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(5000) });
      return { ...settings, ok: true };
    } catch {
      return { ok: false, error: '口语课没打开' };
    }
  }

  function connect() {
    if (!connecting) {
      connecting = ensure().then(service => {
        if (!service.ok) throw new Error(service.error);
        return service;
      }).finally(() => { connecting = null; });
    }
    return connecting;
  }

  function makeFrame(service, path, title) {
    const result = node('iframe', '', 'coach-frame');
    result.title = title;
    result.allow = 'microphone; autoplay; clipboard-write';
    const url = new URL(path, service.url);
    const language = global.LP.currentPersona?.()?.language;
    if (!service.desktop_managed && language && service.languages?.includes(language)) url.searchParams.set('language', language);
    result.src = url.href;
    return result;
  }

  async function read(path) {
    const response = await fetch('/api/speaking/lessons' + path, { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '暂时读不到口语记录');
    return data;
  }

  function status(target, message, retry) {
    const box = node('div', '', 'coach-state');
    box.append(node('p', message));
    if (retry) box.append(button('再试一次', retry));
    target.replaceChildren(box);
  }

  const when = (value) => { const date = value ? new Date(value) : null; return date && Number.isFinite(date.valueOf()) ? date : null; };

  function lessonLabel(item) {
    const date = when(item.createdAt);
    const label = date ? date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : item.id;
    return [global.LP.languages?.label(item.lang) || item.lang, label, item.status === 'complete' ? '' : '未结束'].filter(Boolean).join(' · ');
  }

  function feedback(target, lesson, lessonId, service) {
    const report = lesson.report;
    if (!report) return;
    if (report.comment) target.append(node('p', report.comment, 'coach-comment'));
    const scores = node('div', '', 'coach-scores');
    for (const [key, label] of Object.entries(scoreLabels)) {
      const value = report.scores?.[key];
      if (!Number.isFinite(value)) continue;
      const score = node('div');
      const meter = node('progress');
      meter.max = 5;
      meter.value = value;
      meter.setAttribute('aria-label', label);
      score.append(node('span', label), node('strong', value + ' / 5'), meter);
      scores.append(score);
    }
    if (scores.childElementCount) target.append(scores);
    if (Array.isArray(report.errors) && report.errors.length) {
      target.append(node('h3', '值得重练'));
      for (const error of report.errors) target.append(correction(error, lessonId, service));
    }
    if (report.homework?.task || report.next_lesson_suggestion) {
      target.append(node('h3', '下一步'));
      if (report.homework?.task) target.append(node('p', report.homework.task));
      if (report.next_lesson_suggestion) target.append(node('p', report.next_lesson_suggestion));
    }
  }

  function correction(error, lessonId, service) {
    const item = node('article', '', 'coach-correction');
    item.append(node('p', error.said, 'coach-before'), node('p', error.correct, 'coach-after'));
    if (error.reason) item.append(node('p', error.reason));
    const audio = recording(error.audio, lessonId, service);
    if (audio) item.append(audio);
    return item;
  }

  // service 为 null（口语程序没开）时不给回听，记录照样显示
  function recording(path, id, service) {
    if (!service || typeof path !== 'string' || !/^audio\/[\w-]+\.(wav|webm)$/.test(path)) return null;
    const media = node('audio');
    media.controls = true;
    media.preload = 'none';
    media.setAttribute('aria-label', '回听原音');
    media.src = new URL('/api/lessons/' + encodeURIComponent(id) + '/' + path, service.url);
    return media;
  }

  function clock(seconds, srt = false) {
    const ms = Math.max(0, Math.round(seconds * 1000));
    const pad = (value, length = 2) => String(value).padStart(length, '0');
    const mmss = pad(Math.floor(ms / 60000) % 60) + ':' + pad(Math.floor(ms / 1000) % 60);
    return srt ? pad(Math.floor(ms / 3600000)) + ':' + mmss + ',' + pad(ms % 1000, 3) : mmss;
  }

  function captions(target, lesson, lessonId, service) {
    const all = Array.isArray(lesson.transcript) ? lesson.transcript : [];
    if (!all.length) {
      status(target, '没有逐字稿');
      return;
    }
    const lines = all.filter(item => typeof item?.text === 'string' && item.text.trim() && item.asrStatus !== 'failed');
    const role = item => item.role === 'teacher' ? '老师' : '我';
    const tools = node('div', '', 'coach-caption-tools');
    const notice = node('span');
    notice.setAttribute('role', 'status');
    const copy = button('复制逐字稿', async () => {
      try {
        await navigator.clipboard.writeText(lines.map(line => role(line) + '  ' + line.text).join('\n'));
        notice.textContent = '已复制';
      } catch { notice.textContent = '暂时无法复制'; }
    });
    copy.disabled = !lines.length;
    const timed = lines.filter(line => Number.isFinite(line.start) && line.start >= 0 && Number.isFinite(line.duration) && line.duration > 0);
    const download = button('下载字幕', () => {
      const text = timed.map((line, index) => [
        index + 1, clock(line.start, true) + ' --> ' + clock(line.start + line.duration, true),
        role(line) + '  ' + line.text.trim(),
      ].join('\r\n')).join('\r\n\r\n') + '\r\n';
      const url = URL.createObjectURL(new Blob([text], { type: 'application/x-subrip;charset=utf-8' }));
      const link = node('a');
      link.href = url;
      link.download = lessonId + '.srt';
      link.hidden = true;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    });
    download.disabled = !timed.length;
    tools.append(copy, download, notice);
    const transcript = node('ol', '', 'coach-caption-lines');
    for (const line of all) {
      if (!line) continue;
      const row = node('li');
      const time = Number.isFinite(line.start) ? clock(line.start) : '—';
      const text = node('div');
      text.append(node('strong', role(line)), node('p', line.asrStatus === 'failed' ? '转写失败' : line.text));
      const audio = recording(line.audio, lessonId, service);
      if (audio) text.append(audio);
      if (line.asrStatus === 'failed' && service) {
        const retry = node('a', '去重试');
        retry.href = new URL('/report/' + encodeURIComponent(lessonId), service.url);
        retry.target = '_blank';
        retry.rel = 'noopener noreferrer';
        text.append(retry);
      }
      row.append(node('small', time), text);
      transcript.append(row);
    }
    target.append(tools, transcript);
  }

  // ---------- 首页 ----------

  const minutes = (lesson) => {
    const ends = (Array.isArray(lesson?.transcript) ? lesson.transcript : [])
      .map(line => Number(line?.start) + Number(line?.duration)).filter(Number.isFinite);
    return ends.length ? Math.max(...ends) / 60 : 0;
  };
  const average = (report) => {
    const values = Object.keys(scoreLabels).map(key => report?.scores?.[key]).filter(Number.isFinite);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  };

  // 现在选用的课里，开口练的那几部分（托福的跟读、面试）；没有就是空的
  async function speakingParts(language) {
    try {
      const api = global.LP.api;
      if (!language || !api?.getTeachingPresets || !api?.getCourse) return [];
      const [presets, bundle] = await Promise.all([api.getTeachingPresets(), api.getCourse(language)]);
      const teaching = bundle?.teaching;
      const course = teaching?.mode === 'ambient' ? (presets?.items || []).find(item => item.id === teaching.preset_id) : null;
      if (!course) return [];
      const unit = id => (course.units || []).find(item => item.id === id);
      const known = id => bundle.progress?.units?.find(item => item.id === id)?.status === 'known';
      return (course.sections || []).flatMap(section => section.parts || []).filter(part => part.practice?.open).map(part => ({
        // 「托福跟读」：带上考试名，和自由跟读分开
        key: 'part:' + part.practice.lesson, name: String(course.title || '').split(/[\s（(]/)[0] + String(part.title || '').split('　')[0], course: course.title,
        open: part.practice.open, brief: part.practice.brief, language,
        lessons: part.lessons.filter(id => unit(id)).map(id => ({ id, known: known(id) })),
        links: [...new Set(Object.values(part.practice.points || {}))].map(id => ({ id, title: unit(id)?.title || course.titles?.[id] || id, ready: Boolean(unit(id)) })),
      }));
    } catch { return []; }
  }

  function bars(title, rows) {
    const box = node('div', '', 'lp-bars');
    box.append(node('h4', title));
    for (const row of rows) {
      const line = node('div', '', 'lp-bar' + (row.value == null ? ' empty' : ''));
      const track = node('span', '', 'lp-bar-track'), fill = node('span', '', 'lp-bar-fill');
      fill.style.width = row.value == null ? '0%' : Math.round(Math.max(0, Math.min(1, row.value)) * 100) + '%';
      track.append(fill);
      line.append(node('span', row.label, 'lp-bar-label'), track, node('b', row.text || ''));
      box.append(line);
    }
    return box;
  }

  function big(value, label) {
    const box = node('div', '', 'lp-big-number');
    box.append(node('strong', value), node('span', label));
    return box;
  }

  function activity(items) {
    const grid = node('div', '', 'lp-activity');
    grid.setAttribute('aria-label', '30 天');
    const key = d => d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate();
    const perDay = new Map();
    for (const item of items) { const d = when(item.createdAt); if (d) perDay.set(key(d), (perDay.get(key(d)) || 0) + 1); }
    const today = new Date();
    for (let i = 29; i >= 0; i -= 1) {
      const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
      const n = perDay.get(key(d)) || 0;
      const cell = node('i', '', 'l' + Math.min(3, n) + (i === 0 ? ' today' : ''));
      cell.title = (d.getMonth() + 1) + '/' + d.getDate() + (n ? ' · ' + n : '');
      grid.append(cell);
    }
    return grid;
  }

  function tile(option, selected) {
    const box = node('button', '', 'lp-format-tile');
    box.type = 'button';
    box.dataset.coachPick = option.key;
    box.setAttribute('role', 'radio');
    box.setAttribute('aria-checked', String(selected));
    box.append(node('strong', option.name, 'lp-format-name'));
    const marks = node('span', '', 'lp-format-marks');
    if (option.speakers) {
      const people = node('span', '', 'lp-speakers');
      people.setAttribute('aria-label', option.speakers + ' 人');
      for (let i = 0; i < option.speakers; i += 1) people.append(node('i'));
      marks.append(people);
    }
    if (option.lessons?.length) {
      const dots = node('span', '', 'lp-dots');
      for (const lesson of option.lessons) dots.append(node('i', '', lesson.known ? 'ok' : 'open'));
      marks.append(dots);
      const done = option.lessons.filter(lesson => lesson.known).length;
      const stat = node('span', '', 'lp-format-stat');
      const track = node('span', '', 'lp-bar-track'), fill = node('span', '', 'lp-bar-fill');
      fill.style.width = Math.round(done / option.lessons.length * 100) + '%';
      track.append(fill);
      stat.append(track, node('b', done + '/' + option.lessons.length));
      box.append(stat);
    } else if (option.count) {
      const stat = node('span', option.count + ' 节', 'lp-format-count');
      box.append(stat);
    }
    box.append(marks);
    return box;
  }

  async function paintHome() {
    const mine = ++homeTicket;
    const home = root.querySelector('.coach-home');
    const language = global.LP.currentPersona?.()?.language || '';
    let items = [];
    try { items = (await read('')).filter(item => typeof item.id === 'string' && item.status !== 'draft'); } catch { items = []; }
    items.sort((a, b) => (when(b.createdAt)?.valueOf() || 0) - (when(a.createdAt)?.valueOf() || 0));
    const monthAgo = Date.now() - 30 * 86400000;
    const recent = items.slice(0, 8);
    const month = items.filter(item => (when(item.createdAt)?.valueOf() || 0) >= monthAgo);
    const wanted = [...new Map([...recent, ...month.slice(0, 30)].map(item => [item.id, item])).values()];
    // 口语程序只用来回听原音：三秒内没连上就先不给回听，页面不等它
    const linking = Promise.race([connect().catch(() => null), new Promise(resolve => setTimeout(() => resolve(null), 3000))]);
    const [details, parts, service] = await Promise.all([
      Promise.all(wanted.map(item => read('/' + encodeURIComponent(item.id)).then(detail => [item.id, detail]).catch(() => [item.id, null]))),
      speakingParts(language),
      linking,
    ]);
    if (mine !== homeTicket || !root) return;
    const detail = new Map(details);

    const label = global.LP.languages?.label(language) || language;
    const last = items.find(item => item.kind !== 'placement');
    const lastTitle = last ? detail.get(last.id)?.title || '' : '';
    const lastDate = last ? when(last.createdAt) : null;
    const lastLine = last ? ['上次', lastDate ? (lastDate.getMonth() + 1) + '/' + lastDate.getDate() : '', lastTitle].filter(Boolean).join(' ') : '';
    const options = [
      { key: 'voice', name: '对话课', speakers: 2, count: items.filter(item => item.kind !== 'placement').length, start: '上课',
        line: [label, lastLine].filter(Boolean).join(' · ') },
      { key: 'shadowing', name: '跟读', speakers: 1, start: '开始跟读', line: label },
      ...parts.map(part => ({ ...part, start: '开始练习', line: part.course + ' · ' + part.lessons.filter(l => l.known).length + ' / ' + part.lessons.length + ' 课' })),
    ];
    let current = options.find(option => option.key === chosen) || options[0];

    // 主操作卡
    const setup = node('form', '', 'lp-listening-setup coach-setup');
    const preview = node('div', '', 'listen-plan-preview');
    const head = node('div', '', 'lp-plan-head');
    const name = node('strong', current.name), line = node('p', current.line);
    const tips = node('ul', '', 'coach-tips');      // 选了课里的一部分：这种题的解题要点
    const paintTips = (option) => { tips.replaceChildren(...(option.brief || []).map(text => node('li', text))); tips.hidden = !option.brief?.length; };
    paintTips(current);
    head.append(name, line, tips);
    const tags = node('div', '', 'lp-tags');
    preview.append(head, tags);
    const actions = node('div', '', 'listen-start-actions');
    const start = node('button', current.start);
    start.type = 'submit';
    actions.append(start);
    setup.append(preview, actions);
    const asr = asrCard(mine);
    setup.addEventListener('submit', (event) => {
      event.preventDefault();
      if (asr.blocks()) { asr.flash(); return; }      // 识别模型还没下好：先下模型
      if (current.key === 'voice' || current.key === 'shadowing') show(current.key);
      else practise(current.open, { brief: current.brief, lessons: current.links, language: current.language });
    });

    // 左：练法格子 + 最近
    const left = node('div', '', 'lp-left');
    const grid = node('div', '', 'lp-formats');
    grid.setAttribute('role', 'radiogroup');
    grid.setAttribute('aria-label', '练法');
    for (const option of options) {
      const box = tile(option, option === current);
      box.addEventListener('click', () => {
        current = option; chosen = option.key;
        try { localStorage.setItem('lp.coach.pick', chosen); } catch { /* 只是记住上次选的 */ }
        grid.querySelectorAll('.lp-format-tile').forEach(other => other.setAttribute('aria-checked', String(other === box)));
        name.textContent = option.name; line.textContent = option.line; start.textContent = option.start; paintTips(option);
      });
      grid.append(box);
    }
    left.append(grid);
    if (recent.length) {
      const section = node('section', '', 'lp-recent');
      section.append(node('h3', '最近'));
      const list = node('ol', '', 'lp-recent-list');
      for (const item of recent) {
        const lesson = detail.get(item.id);
        const row = node('button', '', 'lp-recent-row' + (item.status === 'complete' ? '' : ' pending'));
        row.type = 'button';
        row.dataset.lesson = item.id;
        const mean = average(lesson?.report);
        const date = when(item.createdAt);
        row.append(node('span', LANG_TAG[item.lang] || String(item.lang || '').slice(0, 2).toUpperCase(), 'lp-lang-tag'),
          node('strong', lesson?.title || KIND[item.kind] || '对话课'),
          node('span', mean == null ? '' : mean.toFixed(1), 'coach-mean'),
          node('time', date ? (date.getMonth() + 1) + '/' + date.getDate() : ''),
          node('span', '›', 'lp-recent-go'));
        if (lesson?.report?.comment) row.append(node('span', lesson.report.comment, 'lp-recent-preview'));
        row.addEventListener('click', () => { picked.feedback = picked.captions = item.id; show(lesson?.report ? 'feedback' : 'captions'); });
        const li = node('li');
        li.append(row);
        list.append(li);
      }
      section.append(list);
      left.append(section);
    }

    // 右：这个月
    const right = node('section', '', 'lp-month');
    right.append(node('h3', '这个月'));
    const body = node('div', '', 'lp-month-body');
    const reports = month.map(item => detail.get(item.id)?.report).filter(Boolean);
    const spoken = month.reduce((sum, item) => sum + minutes(detail.get(item.id)), 0);
    const means = reports.map(average).filter(value => value != null);
    const numbers = node('div', '', 'lp-month-numbers');
    numbers.append(big(String(month.length), '节'), big(String(Math.round(spoken)), '分钟'));
    if (means.length) numbers.append(big((means.reduce((a, b) => a + b, 0) / means.length).toFixed(1), '平均分'));
    const scoreRows = Object.entries(scoreLabels).map(([key, label]) => {
      const values = reports.map(report => report.scores?.[key]).filter(Number.isFinite);
      const value = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
      return { key, label, value: value == null ? null : value / 5, text: value == null ? '' : value.toFixed(1) };
    });
    const scored = scoreRows.filter(row => row.value != null);
    if (scored.length > 1) {
      const weakest = scored.reduce((a, b) => (b.value < a.value ? b : a));
      if (weakest.value < 1) tags.append(node('span', weakest.label + '最弱', 'lp-tag weak'));
    }
    body.append(numbers, activity(items), bars('五项得分', scoreRows));
    // 值得重练：最近几节里挑出来的错句，带原音
    const redo = [];
    for (const item of recent) {
      for (const error of detail.get(item.id)?.report?.errors || []) {
        if (error?.said && error?.correct && redo.length < 4) redo.push([error, item.id]);
      }
    }
    if (redo.length) {
      const box = node('div', '', 'coach-redo');
      box.append(node('h4', '值得重练'));
      for (const [error, id] of redo) box.append(correction(error, id, service));
      body.append(box);
    }
    const homework = recent.map(item => detail.get(item.id)?.report?.homework?.task).find(Boolean);
    if (homework) {
      const box = node('div', '', 'coach-homework');
      box.append(node('h4', '作业'), node('p', homework));
      body.append(box);
    }
    right.append(body);

    const columns = node('div', '', 'lp-home');
    columns.append(left, right);
    home.replaceChildren(setup, asr.box, columns);
    void asr.check();
  }

  // 识别模型（约 1.6 GB）：没下过时口语课用不了，在首页给一张卡：下载 / 下载中 / 再下一次
  let asrState = null, asrFlash = false;
  const asrBlocked = (state) => Boolean(state?.running && !state.ready && (state.missing || state.downloading || state.failed));
  async function asrCall(method, path) {
    try {
      const response = await fetch('/api/speaking/asr' + path, { method, cache: 'no-store' });
      return response.ok ? await response.json() : null;
    } catch { return null; }
  }
  // 从别处（课程页的口语练习）直接进上课、跟读时也看一眼：模型没好就回首页，卡片闪一下
  async function asrGuard(mode) {
    const state = await asrCall('GET', '');
    if (state) asrState = state;
    if (visible === mode && asrBlocked(asrState)) { asrFlash = true; clearPractice(); show('home'); }
  }

  function asrCard(ticket) {
    const box = node('section', '', 'coach-asr');
    box.hidden = true;
    let status = asrState, timer = 0;
    const live = () => ticket === homeTicket && root?.contains(box);
    const megabytes = (bytes) => Math.round(bytes / 1048576).toLocaleString('zh-CN') + ' MB';
    const call = asrCall;
    function paint() {
      asrState = status;
      clearTimeout(timer);
      if (!live()) return;
      const needed = status?.running && !status.ready && (status.missing || status.downloading || status.failed);
      box.hidden = !needed;
      if (!needed) return;
      const head = node('strong', status.downloading ? '识别模型下载中' : status.failed ? '识别模型没下载成功' : '识别模型还没下载');
      const size = status.total ? megabytes(status.total) : '约 1.6 GB';
      const parts = [head];
      if (status.downloading) {
        const done = status.downloaded || 0, share = status.total ? Math.min(1, done / status.total) : null;
        const track = node('span', '', 'lp-bar-track'), fill = node('span', '', 'lp-bar-fill');
        fill.style.width = share == null ? '0%' : Math.round(share * 100) + '%';
        track.append(fill);
        parts.push(track, node('span', share == null ? megabytes(done) : Math.round(share * 100) + '%', 'coach-asr-amount'));
        timer = setTimeout(() => void check(), 2000);
      } else {
        parts.push(node('span', '口语课要用，' + size, 'coach-asr-amount'));
        const go = node('button', status.failed ? '再下载' : '下载');
        go.type = 'button';
        go.addEventListener('click', async () => {
          go.disabled = true;
          status = (await call('POST', '/download')) || status;
          paint();
        });
        parts.push(go);
      }
      box.replaceChildren(...parts);
      if (asrFlash) { asrFlash = false; flash(); }
    }
    function flash() { box.classList.remove('flash'); void box.offsetWidth; box.classList.add('flash'); }
    async function check() {
      status = await call('GET', '');
      // 口语程序刚拉起时识别服务还没起来：稍后再看一次
      if (!status?.running && live()) timer = setTimeout(() => { if (live()) void call('GET', '').then(s => { status = s; paint(); }); }, 4000);
      paint();
      if (status?.ready && box.dataset.was === 'downloading') void paintHome();
      box.dataset.was = status?.downloading ? 'downloading' : '';
    }
    return { box, check, flash, blocks: () => asrBlocked(status) };
  }

  // ---------- 记录（反馈、字幕） ----------

  function updateFeedback(lesson) {
    const control = root.querySelector('[data-coach-view="feedback"]');
    if (control) control.disabled = !lesson?.report;
    if (!lesson?.report && visible === 'feedback') show('captions');
  }

  async function records(mode, run) {
    const target = root.querySelector('.coach-records');
    status(target, '…');
    // 记录在本机读得到；口语程序连上了才多给回听原音，没连上不挡记录
    const linking = connect().catch(() => null);
    try {
      const items = (await read('')).filter(item => typeof item.id === 'string' && item.status !== 'draft');
      if (run !== generation) return;
      if (!items.length) {
        status(target, '还没有记录');
        return;
      }
      const select = node('select');
      select.setAttribute('aria-label', '选择课时');
      select.append(...items.map(item => new Option(lessonLabel(item), item.id)));
      select.value = items.find(item => item.id === picked[mode])?.id || items.find(item => item.status === 'complete')?.id || items[0].id;
      const header = node('header', '', 'coach-record-head');
      const content = node('div', '', 'coach-record-content');
      header.append(select);
      target.replaceChildren(header, content);
      let currentRead = 0;
      async function load() {
        const id = select.value;
        picked.feedback = picked.captions = id;
        const readNumber = ++currentRead;
        status(content, '…');
        try {
          const [result, service] = await Promise.all([read('/' + encodeURIComponent(id)), linking]);
          if (run !== generation || readNumber !== currentRead) return;
          updateFeedback(result);
          if (run !== generation) return;
          content.replaceChildren();
          if (result.title) content.append(node('h3', result.title));
          (mode === 'feedback' ? feedback : captions)(content, result, id, service);
        } catch (error) {
          if (run === generation && readNumber === currentRead) status(content, error.message, load);
        }
      }
      select.onchange = load;
      void load();
    } catch (error) {
      if (run === generation) status(target, error.message, () => show(mode));
    }
  }

  async function openVoice(slot) {
    if (frame || voiceOpening) return;
    voiceOpening = true;
    status(slot, '…');
    try {
      frame = makeFrame(await connect(), '/voice', '口语练习');
      slot.replaceChildren(frame);
    } catch (error) { status(slot, error.message, () => void openVoice(slot)); }
    finally { voiceOpening = false; }
  }

  // 工具栏：首页只有标题；别的页左边一个「← 口语」，看记录时右边是反馈、字幕
  function paintToolbar(mode) {
    const back = root.querySelector('.coach-back');
    const navigation = root.querySelector('.coach-toolbar nav');
    back.hidden = mode === 'home';
    root.querySelector('.coach-toolbar h1').hidden = mode !== 'home';
    navigation.hidden = mode !== 'feedback' && mode !== 'captions';
    for (const control of navigation.querySelectorAll('[data-coach-view]')) {
      control.setAttribute('aria-pressed', String(control.dataset.coachView === mode));
    }
  }

  function show(mode) {
    if (!root) return;
    if (mode === 'feedback' && root.querySelector('[data-coach-view="feedback"]').disabled) mode = 'captions';
    if ((mode === 'voice' || mode === 'shadowing') && asrBlocked(asrState)) { asrFlash = true; clearPractice(); mode = 'home'; }
    visible = mode;
    if (practiceBrief) practiceBrief.hidden = mode !== practiceTab;
    const run = ++generation;
    const home = root.querySelector('.coach-home');
    const voice = root.querySelector('.coach-voice');
    const shadow = root.querySelector('.coach-shadowing');
    const history = root.querySelector('.coach-records');
    home.hidden = mode !== 'home';
    voice.hidden = mode !== 'voice';
    shadow.hidden = mode !== 'shadowing';
    history.hidden = mode !== 'feedback' && mode !== 'captions';
    paintToolbar(mode);
    if (mode === 'voice' || mode === 'shadowing') void asrGuard(mode);
    if (mode === 'home') void paintHome();
    else if (mode === 'voice') void openVoice(voice);
    else if (mode === 'shadowing' && !shadowFrame) {
      status(shadow, '…');
      connect().then(service => {
        if (run !== generation) return;
        shadowFrame = makeFrame(service, '/shadowing', '跟读练习');
        shadow.replaceChildren(shadowFrame);
      }).catch(error => { if (run === generation) status(shadow, error.message, () => show(mode)); });
    } else if (mode === 'feedback' || mode === 'captions') void records(mode, run);
  }

  function mount(panel) {
    root = panel;
    root.innerHTML = `
      <header class="coach-toolbar workspace-tools">
        <button type="button" class="coach-back" hidden>← 口语</button>
        <h1><img src="assets/icons/lesson.png" alt="">口语</h1>
        <nav aria-label="课后记录" hidden></nav>
      </header>
      <div class="coach-home"></div>
      <div class="coach-voice" hidden></div>
      <div class="coach-shadowing" hidden></div>
      <section class="coach-records" aria-label="课后记录" hidden></section>`;
    root.querySelector('.coach-back').addEventListener('click', () => { clearPractice(); show('home'); });
    const navigation = root.querySelector('nav');
    for (const [mode, label] of tabs) {
      const control = button(label, () => show(mode));
      control.dataset.coachView = mode;
      navigation.append(control);
    }
    show('home');
  }

  function clearPractice() {
    practiceBrief?.remove();
    practice = practiceTab = practiceBrief = null;
  }

  function practise(tab, details) {
    clearPractice();
    practice = details;
    practiceTab = tab;
    practiceBrief = global.LP.lessonCards.brief(practice, (item) => {
      const link = button(item.title, () => { void global.LP.lesson.start(practice.language, item.id).catch(() => {}); }, 'cp-link');
      link.disabled = !item.ready;
      return link;
    });
    root.querySelector('.coach-toolbar').after(practiceBrief);
    show(tab);
  }

  global.LP ||= {};
  global.LP.coach = { mount, practise, leave: clearPractice, show, refresh: () => show(visible), ensure, serviceChanged: () => Boolean(frame || shadowFrame || voiceOpening) };
})(window);
