/* jine.js — 主聊天（docs/MAIN-CHAT.md）。全应用只有一条时间线：没有联系人列，图标栏右边整块是对话。
   外观照原作 JINE：粉紫云朵底、她的浅蓝九宫格气泡在左、你的绿色在右，同一个人连发只有第一条带头像、名字和尾巴，
   时间和「已读」贴在气泡旁。顶栏：主人设、在场的副人设（点一下 = 下一条对她说）、语言拨片、骰子、课程、旧对话。
   接口：GET/PUT /api/chat/main、GET /api/chat/main/messages、POST /api/chat（SSE，新增 read / speaker 事件）、
   GET /api/chat/archives(/{id})、GET /api/stickers。点词、句解析、收藏整句、图片、注音、打断照旧。 */
(function (global) {
  'use strict';

  const { escapeHtml, el, button } = global.LP.util;
  const CHO_NAME = '糖糖'; // 真实后端里她叫"糖糖（あめ）"，用 startsWith 匹配
  const ACCEPTED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
  const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
  const PAGE = 40; // 先画最近一屏多一点，往上翻再取

  let els = {};
  let main = null;            // GET /api/chat/main
  let stickers = [];          // [{id,url,meaning}]
  let target = null;          // 点名的人设 id（发完自动取消）
  let pendingImageFile = null;
  let sending = false;
  let archive = null;         // 正在看的旧对话 {session_id, ...}
  let oldestId = null;        // 主聊天里已载入的最早一条
  let exhausted = false;      // 更早的已经没有了
  let loadingOlder = false;
  let historyRead = 0;
  const activeTurns = new Set();
  let actionQueue = Promise.resolve();

  const persona = (id) => LP.getPersona(id);
  // 角色窗口只听事件；没打开时这些调用什么都不做。reacts = 说话的这个人设有没有对应的角色
  const stage = (name, data) => { try { LP.stage?.emit(name, data); } catch (e) { /* 角色窗口出错不影响聊天 */ } };
  const reacts = (p) => Boolean(LP.stage?.reactsTo(p));
  const primary = () => persona(main?.primary_id) || LP.state.personas[0] || null;
  const isCho = (p) => Boolean(p && p.name && p.name.startsWith(CHO_NAME));
  const languages = () => LP.languages.list();   // 和语言抽屉同一份（后端 chat/main 里的 languages 也是这份登记表）

  // ---------- 贴图 ----------
  async function loadStickers() {
    try { stickers = (await LP.api.getStickers()).items || []; }
    catch {
      // 后端没有贴图表时退回本地清单
      try { stickers = (await (await fetch('assets/stickers/manifest.json')).json()).map((s) => ({ id: s.id, url: 'assets/stickers/' + s.file, meaning: s.desc })); }
      catch { stickers = []; }
    }
    paintStickerDrawer();
  }
  const stickerUrl = (id) => stickers.find((s) => s.id === id)?.url || (/^[\w-]+$/.test(id || '') ? 'assets/stickers/' + id + '.png' : null);

  // ---------- 头像 ----------
  // 自定义头像 > 糖糖的情绪帧 > 语言色底 + 名字首字母
  function avatar(p, cls = '') {
    const box = el('span', '', 'jm-ava ' + cls);
    if (p?.avatar_url) { const img = el('img'); img.src = p.avatar_url; img.alt = ''; box.append(img); }
    else if (isCho(p)) { const img = el('img', '', 'cho-avatar-img'); img.src = 'assets/avatars/normal.png'; img.alt = ''; box.append(img); }
    else { box.classList.add('lang-' + (p?.language || 'x')); box.textContent = Array.from(p?.name || '?')[0]; }
    return box;
  }
  function setMood(row, mood) {
    const img = row?.querySelector('.cho-avatar-img');
    if (img && /^[a-z0-9_-]+$/i.test(mood || '')) img.src = `assets/avatars/${mood}.png`;
  }

  // ---------- 外壳 ----------
  function renderShell(root) {
    root.innerHTML = `
      <section class="jm" aria-label="聊天">
        <header class="jm-top">
          <span class="jm-top-who" id="jm-who"></span>
          <div class="jm-top-name">
            <div class="jm-top-line"><h1 id="jm-name"></h1><span class="jm-guests" id="jm-guests" role="group" aria-label="在场的人"></span></div>
            <span class="jm-status" id="jm-status" role="status"></span>
          </div>
          <div class="jm-top-tools">
            <div class="jm-dial" id="jm-dial" role="radiogroup" aria-label="聊天语言"></div>
            <button type="button" class="jm-dice" id="jm-dice" aria-pressed="false" aria-label="趣味模式"></button>
            <div class="jm-more">
              <button type="button" class="jm-more-btn" id="jm-more" aria-haspopup="menu" aria-expanded="false" aria-controls="jm-menu" aria-label="更多" title="更多">⋯</button>
              <div class="jm-menu pixel-box" id="jm-menu" role="menu" hidden>
                <button type="button" id="jm-lesson-start" role="menuitem" hidden>上课</button>
                <button type="button" class="jine-course-tag" id="jine-course" role="menuitem" hidden></button>
                <button type="button" class="jm-archive-btn" id="jm-archives" role="menuitem" aria-expanded="false"><img src="assets/jine/icon_desktop_text.png" alt=""><span>旧对话</span></button>
                <button type="button" id="jm-add-language" role="menuitem">添加语言</button>
                <button type="button" id="jm-persona-card" role="menuitem">角色</button>
              </div>
            </div>
          </div>
        </header>
        <section class="jm-lesson" id="jm-lesson" hidden aria-label="正在上课">
          <header class="jm-lesson-head"><strong id="jm-lesson-title"></strong><button type="button" id="jm-lesson-stop">下课</button></header>
        </section>
        <div class="jm-archive-bar" id="jm-archive-bar" hidden><span id="jm-archive-title"></span><button type="button" id="jm-archive-back">回到主聊天</button></div>
        <div class="jm-skywrap">
          <div class="jm-sky" id="jm-sky"><div class="jine-msgs" id="jine-messages" role="log" aria-live="off" aria-label="聊天记录"><div class="jm-cards" id="jm-cards"></div></div></div>
          <button type="button" class="jm-latest" id="jm-latest" aria-label="回到最新" hidden><img src="assets/jine/JINE_button_tobottom.png" alt=""></button>
          <aside class="jm-archives" id="jm-archive-panel" hidden aria-label="旧对话"></aside>
        </div>
        <div class="jine-attach-preview hidden" id="jine-attach-preview">
          <img id="jine-attach-thumb" alt="待发送的图片">
          <button type="button" class="attach-remove" id="jine-attach-remove" aria-label="移除图片">×</button>
        </div>
        <form class="jine-composer" id="jine-composer">
          <button type="button" class="jm-tool" id="jine-attach-btn" aria-label="发送图片" title="图片"><img src="assets/jine/icon_picture.png" alt=""></button>
          <button type="button" class="jm-tool" id="jm-sticker-btn" aria-label="贴图" title="贴图" aria-pressed="false" aria-controls="jm-stickers"><img src="assets/jine/icon_pien_cat.png" alt=""></button>
          <input type="file" id="jine-file-input" accept="image/png,image/jpeg,image/gif,image/webp" class="hidden">
          <span class="jm-to" id="jm-to" hidden></span>
          <textarea id="jine-input" aria-label="消息" placeholder="Aa" rows="1"></textarea>
          <button type="submit" class="send-btn" id="jine-send">发送</button>
        </form>
        <div class="jm-stickers" id="jm-stickers" hidden aria-label="贴图"></div>
      </section>
      <dialog class="jine-lightbox" id="jine-lightbox" aria-label="聊天图片"><img id="jine-lightbox-img" alt="聊天图片"></dialog>`;
    const q = (sel) => root.querySelector(sel);
    els = {
      root, who: q('#jm-who'), name: q('#jm-name'), guests: q('#jm-guests'), status: q('#jm-status'),
      dial: q('#jm-dial'), dice: q('#jm-dice'), course: q('#jine-course'), archivesBtn: q('#jm-archives'),
      more: q('#jm-more'), menu: q('#jm-menu'), addLanguage: q('#jm-add-language'), personaCard: q('#jm-persona-card'),
      lesson: q('#jm-lesson'), lessonTitle: q('#jm-lesson-title'), cards: q('#jm-cards'),
      lessonStop: q('#jm-lesson-stop'), lessonStart: q('#jm-lesson-start'),
      archiveBar: q('#jm-archive-bar'), archiveTitle: q('#jm-archive-title'), archiveBack: q('#jm-archive-back'),
      sky: q('#jm-sky'), messages: q('#jine-messages'), latest: q('#jm-latest'), archivePanel: q('#jm-archive-panel'),
      composer: q('#jine-composer'), input: q('#jine-input'), send: q('#jine-send'), to: q('#jm-to'),
      attachBtn: q('#jine-attach-btn'), stickerBtn: q('#jm-sticker-btn'), stickerDrawer: q('#jm-stickers'), fileInput: q('#jine-file-input'),
      attachPreview: q('#jine-attach-preview'), attachThumb: q('#jine-attach-thumb'), attachRemove: q('#jine-attach-remove'),
      lightbox: q('#jine-lightbox'), lightboxImg: q('#jine-lightbox-img'),
    };
  }

  // ---------- 顶栏 ----------
  let typingNames = new Set();
  function renderStatus() {
    if (archive) { els.status.textContent = ''; return; }
    els.status.dataset.typing = String(typingNames.size > 0);
    els.status.textContent = typingNames.size ? [...typingNames].join('、') + ' 正在输入…' : '在线';
  }

  function renderTopbar() {
    if (!els.who) return;
    const p = primary();
    LP.stage?.sync(p);
    els.who.replaceChildren(avatar(p, 'lg'));
    els.name.textContent = p ? p.name : 'JINE';
    // 在场的副人设：小头像，点一下 = 下一条对她说
    const present = (main?.present_guest_ids || []).map(persona).filter(Boolean);
    els.guests.replaceChildren(...present.map((g) => {
      const b = button('', () => setTarget(target === g.id ? null : g.id), 'jm-guest');
      b.append(avatar(g, 'sm'));
      b.title = '对' + g.name + '说';
      b.setAttribute('aria-label', '下一条对' + g.name + '说');
      b.setAttribute('aria-pressed', String(target === g.id));
      return b;
    }));
    // 语言拨片：当前语言实心；趣味模式开着时整条变虚线（这一轮由骰子决定）
    const current = main?.language || p?.language;
    els.dial.classList.toggle('fun', Boolean(main?.fun));
    els.dial.replaceChildren(...languages().map((l) => {
      const b = button(l.label, () => void setLanguage(l.tag), 'jm-dial-opt');
      b.lang = l.tag;
      b.setAttribute('role', 'radio');
      b.setAttribute('aria-checked', String(l.tag === current));
      return b;
    }), els.dice);
    els.dice.setAttribute('aria-pressed', String(Boolean(main?.fun)));
    renderStatus();
    // 课程项和「上课」要读接口：只在语言变了时重读（课程变了走 lp:teaching-settings / lp:lesson 事件）
    if (current !== courseLanguage) { courseLanguage = current; renderCourseTag(); void renderLessonStart(); }
  }
  let courseLanguage;

  let drawer = null;
  function languageDrawer() {
    drawer ||= LP.languageDrawer.create({ title: '聊天语言', selected: () => main?.language, onSelect: (tag) => void setLanguage(tag) });
    return drawer;
  }

  // 连点骰子、拨片：只认最后一次的回应；失败只退回这一次改的那几项
  let putTicket = 0;
  async function putMain(patch) {
    const ticket = ++putTicket;
    const before = Object.fromEntries(Object.keys(patch).map((key) => [key, main?.[key]]));
    main = { ...main, ...patch };
    renderTopbar();
    try {
      const next = await LP.api.putMainChat(patch);
      if (ticket !== putTicket) return;
      if (next && typeof next === 'object' && 'primary_id' in next) main = { ...main, ...next };
      renderTopbar();
      document.dispatchEvent(new CustomEvent('lp:chat-main', { detail: main }));
    } catch (error) {
      if (ticket === putTicket) { main = { ...main, ...before }; renderTopbar(); }
      LP.toast?.(LP.util.message(error, '没换成，再试一次'));
    }
  }
  async function setLanguage(tag) {
    if (!tag || tag === main?.language) return;
    await putMain({ language: tag });
  }

  function setTarget(id) {
    target = id;
    const p = persona(id);
    els.to.hidden = !p;
    els.to.replaceChildren();
    if (p) els.to.append(avatar(p, 'xs'), el('span', '@' + p.name));
    renderTopbar();
  }

  // 「⋯」里的课程项：拨片当前语言的课程；点了弹出选课框（settings-teaching.js 的 openPicker）
  function renderCourseTag() {
    const tag = els.course;
    const language = main?.language || primary()?.language;
    if (!tag || !language || !LP.settingsTeaching) { if (tag) tag.hidden = true; return; }
    tag.hidden = false;
    void LP.settingsTeaching.paintChatButton(tag, language);
  }

  let lessonRunId = null, lessonStartRequest = 0;
  const lessonNodes = new Map();
  function renderLesson() {
    if (!els.lesson) return;
    const running = LP.lesson.current();
    const view = running && running.venue === 'chat' ? running : null;
    els.lesson.hidden = !view || Boolean(archive);
    els.cards.hidden = Boolean(archive);
    if (!view || lessonRunId !== view.id) {
      LP.lessonCards.clear(els.cards, lessonNodes);
      lessonRunId = view?.id ?? null;
      els.messages.append(els.cards);   // 这节课的卡片从现在的末尾开始；之后的聊天排在卡片后面
      if (view?.practice) {               // 练习：题目上面先放这种题的解题要点和讲它的课
        els.cards.append(LP.lessonCards.brief(view.practice, (item) => {
          const link = document.createElement('button');
          link.type = 'button'; link.className = 'cp-link'; link.textContent = item.title; link.disabled = !item.ready;
          link.onclick = () => { void LP.lesson.start(view.language, item.id).catch(() => {}); };
          return link;
        }));
      }
    }
    if (!view) return;
    els.lessonTitle.textContent = view.title;
    els.lessonStop.textContent = view.ended ? '收起' : '下课';
    const moved = !lessonNodes.size;
    const node = LP.lessonCards.sync(els.cards, lessonNodes, view);
    if (moved && !archive) {
      requestAnimationFrame(() => {
        if (node?.isConnected && !archive && lessonRunId === view.id && talkVisible()) {
          els.sky.scrollTop += node.getBoundingClientRect().top - els.sky.getBoundingClientRect().top;
        }
      });
    }
  }
  async function renderLessonStart() {
    const request = ++lessonStartRequest;
    if (!els.lessonStart) return;
    els.lessonStart.hidden = true;
    const language = main?.language || primary()?.language;
    if (!language || (LP.lesson.current() && !LP.lesson.current().ended)) return;
    try {
      const bundle = await LP.api.getCourse(language);
      if (request === lessonStartRequest) els.lessonStart.hidden = !bundle.progress?.next || Boolean(LP.lesson.current() && !LP.lesson.current().ended);
    } catch { /* Keep the entry hidden until the course is available. */ }
  }

  // ---------- 时间线 ----------
  const pad = (n) => String(n).padStart(2, '0');
  // 解析和 util.js 同一套；没有时间（刚发出去、正在打字）的当作现在
  const parseTime = (value) => LP.util.time(value) || new Date();
  const clock = (value) => { const d = parseTime(value); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  function dayLabel(value) {
    const d = parseTime(value), now = new Date();
    if (d.toDateString() === now.toDateString()) return '今天';
    return (d.getFullYear() !== now.getFullYear() ? d.getFullYear() + '年' : '') + (d.getMonth() + 1) + '月' + d.getDate() + '日';
  }

  // 每一行记住是谁说的；和上一行同一个人、中间没有日期/系统胶囊时不重复头像、名字、尾巴
  function speakerOf(node) { return node?.dataset?.speaker || null; }
  function place(node, { before = null } = {}) {
    const list = els.messages;
    list.querySelector('.jine-empty')?.remove();
    list.insertBefore(node, before);
    regroup(node);
    const next = node.nextElementSibling;
    if (next) regroup(next);
  }
  function regroup(node) {
    if (!node?.classList.contains('jm-row')) return;
    const prev = node.previousElementSibling;
    node.classList.toggle('first', !(prev?.classList.contains('jm-row') && speakerOf(prev) === speakerOf(node)));
  }
  function datePill(value) {
    const pill = el('div', dayLabel(value), 'jm-date');
    pill.dataset.day = parseTime(value).toDateString();
    return pill;
  }
  // 时间线末尾的日期和这条不同才插日期胶囊
  function dateBefore(value, { before = null } = {}) {
    const day = parseTime(value).toDateString();
    const list = els.messages;
    const pills = [...list.querySelectorAll('.jm-date')];
    const prev = before ? pills.filter((p) => p.compareDocumentPosition(before) & Node.DOCUMENT_POSITION_FOLLOWING).at(-1) : pills.at(-1);
    if (prev?.dataset.day === day) return;
    place(datePill(value), { before });
  }
  function sysPill(text) { place(el('div', text, 'jm-sys')); }

  function scrollBottom() { els.sky.scrollTop = els.sky.scrollHeight; if (els.latest) els.latest.hidden = true; }
  function nearBottom(px = 120) { return els.sky.scrollHeight - els.sky.scrollTop - els.sky.clientHeight < px; }

  // 一行消息：她（左，头像 + 名字 + 浅蓝气泡）或你（右，绿色气泡，「已读」+ 时间在左边）
  function makeRow({ mine, who, messageId, time, read }) {
    const row = el('article', '', 'jm-row ' + (mine ? 'me' : 'her'));
    row.dataset.speaker = mine ? 'me' : 'p' + (who?.id ?? who?.persona_id ?? '?');
    if (messageId != null) row.id = 'msg-' + messageId;
    if (!mine) row.append(avatar(who));
    const stack = el('div', '', 'jm-stack');
    if (!mine) stack.append(el('span', who?.name || who?.persona_name || '', 'jm-name'));
    const line = el('div', '', 'jm-line');
    const meta = el('div', '', 'jm-meta');
    if (mine) { const r = el('span', '已读', 'jm-read'); r.hidden = !read; meta.append(r); }
    const t = el('time', clock(time));
    t.dateTime = parseTime(time).toISOString();
    meta.append(t);
    line.append(meta);
    stack.append(line);
    row.append(stack);
    return { row, line, meta };
  }

  function makeBubble(language, messageId, mine) {
    const bubble = el('div', '', 'bubble');
    if (language) bubble.lang = language;
    if (messageId != null) bubble.dataset.messageId = messageId;
    const tail = el('img', '', 'jm-tail');
    tail.src = mine ? 'assets/jine/pi-tail.png' : 'assets/jine/ame-tail.png';
    tail.alt = '';
    const container = el('span', '', 'tok-container');
    container.dataset.lang = language || '';
    bubble.append(tail, container);
    return { bubble, container };
  }

  // 她的气泡旁边的两个小工具：句解析、收藏整句（悬停出现在时间上方）
  function tools(row, container, bubble) {
    const box = el('span', '', 'jm-tools');
    const messageIdOf = () => (bubble.dataset.messageId ? Number(bubble.dataset.messageId) : null);
    const sentence = button('句解析', () => {
      if (container.dataset.sentence) LP.sentencePanel.open(container.dataset.sentence, container.dataset.lang, messageIdOf());
    }, 'tool-btn');
    sentence.dataset.action = 'sentence';
    const collect = button('收藏整句', async () => {
      if (!container.dataset.sentence || collect.classList.contains('saved')) return;
      collect.classList.add('saved'); collect.textContent = '已收藏';
      try { await LP.sentencePanel.collectWholeSentence(container.dataset.sentence, container.dataset.lang, messageIdOf()); }
      catch (e) { collect.classList.remove('saved'); collect.textContent = '没收上'; console.warn('collect:', e?.message); setTimeout(() => { collect.textContent = '收藏整句'; }, 2400); }
    }, 'tool-btn');
    collect.dataset.action = 'collect-sentence';
    const read = button('朗读', () => void speak(read, messageIdOf(), row), 'tool-btn');
    read.dataset.action = 'speak';
    read.addEventListener('pointerenter', () => warmSpeech(messageIdOf()));
    read.addEventListener('focus', () => warmSpeech(messageIdOf()));
    box.append(sentence, collect, read);
    row.querySelector('.jm-meta').prepend(box);
    // 键盘能走到这条气泡，聚焦时两个小工具出现
    if (!bubble.hasAttribute('tabindex')) bubble.tabIndex = 0;
  }

  // 朗读一条：用设置里给这门语言配的听力声音念出来。是她的消息，角色窗口里她就对着口型念
  let speech = null;   // { audio, btn, url }
  let warmedAt = 0;
  function warmSpeech(id) {                      // 本机声音模型冷启动要二三十秒：鼠标移上来就先让它加载
    if (id == null || Date.now() - warmedAt < 5 * 60 * 1000) return;
    warmedAt = Date.now();
    LP.api.warmMessageSpeech(id).catch(() => {});
  }
  function stopSpeech() {
    if (!speech) return;
    const { audio, btn, url } = speech;
    speech = null;
    audio.pause(); URL.revokeObjectURL(url);
    btn.textContent = '朗读'; btn.classList.remove('saved');
  }
  async function speak(btn, id, row) {
    if (speech && speech.btn === btn) { stopSpeech(); return; }
    stopSpeech();
    LP.stage?.stopSpeech();   // 角色窗口正在自动念的那条先停，两段声音不叠在一起
    if (id == null || btn.dataset.busy) return;
    btn.dataset.busy = '1'; btn.textContent = '准备中';
    try {
      const url = URL.createObjectURL(await LP.api.messageSpeech(id));
      const audio = new Audio(url);
      const who = persona(Number(String(row.dataset.speaker || '').replace(/^p/, '')));
      audio.dataset.voice = reacts(who) ? 'stage' : 'off';
      audio.addEventListener('ended', () => { if (speech?.audio === audio) stopSpeech(); });
      speech = { audio, btn, url };
      btn.textContent = '停'; btn.classList.add('saved');
      LP.stage?.voice(audio);
      await audio.play();
    } catch (e) {
      if (speech?.btn === btn) stopSpeech();
      if (e?.message) console.warn('speech:', e.message);
      btn.textContent = '念不了';
      setTimeout(() => { if (!speech || speech.btn !== btn) btn.textContent = '朗读'; }, 2600);
    } finally { delete btn.dataset.busy; }
  }

  function onTokenClick(ev, span, token, sentence) {
    const container = span.closest('.tok-container');
    const bubble = span.closest('.bubble');
    const messageId = bubble?.dataset.messageId ? Number(bubble.dataset.messageId) : null;
    LP.wordcard.open(ev.clientX, ev.clientY, span, token, sentence, container.dataset.lang, messageId);
  }
  function fill(container, message) {
    if (message.tokens?.length) LP.tokens.renderTokens(container, message.tokens, container.dataset.lang, onTokenClick);
    else { container.textContent = message.content || ''; container.dataset.sentence = message.content || ''; }
  }

  function imageTile(url) {
    const b = button('', () => openLightbox(url), 'jm-photo');
    b.setAttribute('aria-label', '查看大图');
    const img = el('img'); img.src = url; img.alt = '';
    b.append(img);
    return b;
  }
  function stampImg(id) {
    const url = stickerUrl(id);
    if (!url) return el('span', '[贴图]', 'jm-stamp-missing');
    const img = el('img', '', 'jm-stamp'); img.src = url; img.alt = stickers.find((s) => s.id === id)?.meaning || '贴图';
    return img;
  }

  // 旧数据里贴图写成 "[sticker:id]"
  const legacySticker = (m) => (typeof m.content === 'string' && /^\[sticker:[\w-]+\]$/.test(m.content) ? m.content.slice(9, -1) : null);

  function messageRow(m) {
    const mine = m.role === 'user';
    if (m.role === 'system') { const pill = el('div', m.content || '', 'jm-sys'); if (m.id != null) pill.id = 'msg-' + m.id; return pill; }
    const who = mine ? null : (persona(m.persona_id) || { id: m.persona_id, name: m.persona_name, language: m.language });
    const { row, line, meta } = makeRow({ mine, who, messageId: m.id, time: m.created_at, read: m.read });
    const sticker = m.sticker || legacySticker(m);
    // 图片单独一行在上，文字气泡在下；只有图片时时间贴在图片旁
    if (m.image_url && (m.content || sticker)) {
      const photo = el('div', '', 'jm-line');
      photo.append(imageTile(m.image_url));
      line.before(photo);
    } else if (m.image_url) line.insertBefore(imageTile(m.image_url), meta);
    if (sticker) line.insertBefore(stampImg(sticker), meta);
    else if (m.content || !m.image_url) {
      const { bubble, container } = makeBubble(m.language || who?.language, m.id, mine);
      line.insertBefore(bubble, meta);
      fill(container, m);
      if (m.guard_flag) bubble.classList.add('guard-flag');
      if (!mine) tools(row, container, bubble);
    }
    return row;
  }

  function renderMessages(items, { prepend = false } = {}) {
    const anchor = prepend ? els.messages.firstElementChild : null;
    for (const m of items) {
      dateBefore(m.created_at, { before: anchor });
      place(messageRow(m), { before: anchor });
    }
  }

  function showEmpty() {
    const p = primary();
    const box = el('div', '', 'jine-empty');
    box.append(avatar(p, 'xl'), el('span', p ? p.name : 'JINE'));
    els.messages.insertBefore(box, els.cards);
  }

  // ---------- 主聊天 ----------
  async function loadMain() {
    try { main = await LP.api.getMainChat(); }
    catch { main = main || { primary_id: LP.state.personas[0]?.id ?? null, language: null, fun: false, fun_languages: [], guests: [], present_guest_ids: [], pending: 0 }; }
    LP.state.currentPersonaId = main.primary_id ?? LP.state.personas[0]?.id ?? null;
    LP.state.currentSessionId = main.session_id ?? null;
    LP.state.chatMain = main;
    applyPending(main.pending);
    renderTopbar();
    // 设置 › 角色 › 聊天安排靠这个同步（她用指令切了骰子、语言也走这里）
    document.dispatchEvent(new CustomEvent('lp:chat-main', { detail: main }));
  }

  // 正在载入的那一次：单词本跳转要等它载完再找
  let historyTask = Promise.resolve();
  let reloadAfterTurn = false;   // 她正在回的时候不重画（会把半截气泡清掉）；这一轮结束再重读
  function loadHistory({ force = false } = {}) {
    if (!force && activeTurns.size) { reloadAfterTurn = true; return historyTask; }
    historyTask = readHistory(); return historyTask;
  }
  async function readHistory() {
    if (!els.messages) return;
    const read = ++historyRead;
    let items = [];
    try {
      const data = await LP.api.getMainMessages({ limit: PAGE });
      items = data.items || [];
      if (data.session_id != null) { LP.state.currentSessionId = data.session_id; if (main) main.session_id = data.session_id; }
    } catch { items = []; }
    if (read !== historyRead || archive) return;
    els.messages.replaceChildren(els.cards);
    oldestId = items[0]?.id ?? null;
    exhausted = items.length < PAGE;
    if (!items.length) showEmpty();
    else renderMessages(items);
    els.messages.append(els.cards);
    scrollBottom();
    els.messages.querySelectorAll('img').forEach((img) => {
      if (!img.complete) img.addEventListener('load', () => { if (read === historyRead && nearBottom(360)) scrollBottom(); }, { once: true });
    });
  }

  async function loadOlder() {
    if (loadingOlder || exhausted || archive || oldestId == null) return false;
    loadingOlder = true;
    try {
      const items = (await LP.api.getMainMessages({ before: oldestId, limit: PAGE })).items || [];
      exhausted = items.length < PAGE;
      if (!items.length) return false;
      const height = els.sky.scrollHeight;
      // 第一条的日期胶囊可能要合并：先拿掉，再按新的顺序补
      const firstPill = els.messages.firstElementChild?.classList.contains('jm-date') ? els.messages.firstElementChild : null;
      firstPill?.remove();
      const anchor = els.messages.firstElementChild;
      renderMessages(items, { prepend: true });
      // 原来最早那一条前面补日期胶囊；它没有时间（系统胶囊）就不补，免得多插一个「今天」
      if (anchor) { const time = anchor.querySelector('time')?.dateTime; if (time) dateBefore(time, { before: anchor }); regroup(anchor); }
      oldestId = items[0].id;
      els.sky.scrollTop += els.sky.scrollHeight - height;
      return true;
    } catch { return false; }
    finally { loadingOlder = false; }
  }

  // ---------- 旧对话（只读） ----------
  async function toggleArchives(force) {
    const open = force ?? els.archivePanel.hidden;
    els.archivePanel.hidden = !open;
    els.archivesBtn.setAttribute('aria-expanded', String(open));
    if (!open) return;
    els.archivePanel.replaceChildren(el('p', '…', 'jm-archives-empty'));
    try {
      const items = (await LP.api.getChatArchives()).items || [];
      const heading = el('h2', '旧对话', 'jm-archives-head');
      heading.append(button('开新对话', async () => {
        if (!await LP.util.confirm({ title: '开一段新对话？', ok: '开新的' })) return;
        try {
          const response = await fetch('/api/chat/main/new', { method: 'POST' });
          if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '没开成，再试一次');
          await loadMain();
          toggleArchives(false);
          await closeArchive();
          await loadHistory({ force: true });
        } catch (error) { LP.toast?.(LP.util.message(error, '没开成，再试一次')); }
      }, 'jm-archive-btn'));
      els.archivePanel.replaceChildren(heading, ...items.map((a) => {
        const p = persona(a.persona_id) || { id: a.persona_id, name: a.persona_name };
        const b = button('', () => void openArchive(a), 'jm-archive-row');
        const text = el('span', '', 'jm-archive-text');
        const count = a.count ?? a.message_count;
        text.append(el('strong', a.title || p.name || a.persona_name || '对话'), el('small', [a.started_at ? dayLabel(a.started_at) : '', a.last_at ? '→ ' + dayLabel(a.last_at) : '', count != null ? count + ' 条' : ''].filter(Boolean).join(' ')));
        b.append(avatar(p, 'sm'), text);
        if (archive?.session_id === a.session_id) b.setAttribute('aria-current', 'true');
        const row = el('div', '', 'jm-archive-item');
        const remove = button('×', async () => {
          if (!await LP.util.confirm({ title: '删掉这段？', ok: '删掉' })) return;
          try {
            const response = await fetch('/api/chat/archives/' + a.session_id, { method: 'DELETE' });
            if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || '没删掉，再试一次');
            row.remove();
            if (archive?.session_id === a.session_id) await closeArchive();
          } catch (error) { LP.toast?.(LP.util.message(error, '没删掉，再试一次')); }
        }, 'jm-archive-btn');
        remove.setAttribute('aria-label', '删除');
        row.append(b, remove);
        return row;
      }));
    } catch (error) { els.archivePanel.replaceChildren(el('p', LP.util.message(error, '没打开，再试一次'), 'jm-archives-empty')); }
  }

  async function openArchive(a) {
    toggleArchives(false);
    const data = await LP.api.getChatArchive(a.session_id).catch((error) => { LP.toast?.(LP.util.message(error, '没打开，再试一次')); return null; });
    if (!data) return false;
    archive = { ...a, ...(data.session || {}) };
    renderLesson();
    ++historyRead;
    els.root.classList.add('archived');
    els.archiveBar.hidden = false;
    const p = persona(a.persona_id);
    els.archiveTitle.textContent = '旧对话 · ' + (a.title || p?.name || a.persona_name || '');
    els.composer.hidden = true;
    els.stickerDrawer.hidden = true;
    els.attachPreview.hidden = true;
    els.messages.replaceChildren(els.cards);
    const items = (data.items || data.messages || []).map((m) => ({ persona_id: a.persona_id, persona_name: a.persona_name, ...m }));
    if (items.length) renderMessages(items); else showEmpty();
    renderStatus();
    scrollBottom();
    return true;
  }

  async function closeArchive() {
    if (!archive) return;
    archive = null;
    renderLesson();
    els.root.classList.remove('archived');
    els.archiveBar.hidden = true;
    els.composer.hidden = false;
    els.attachPreview.hidden = false;
    renderStatus();
    await loadHistory({ force: true });
    if (activeTurns.size) reloadAfterTurn = true;   // 看旧对话时她回的那几句没画上：这一轮结束再重读
  }

  function highlight(node) {
    node.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const bubble = node.querySelector('.bubble, .jm-stamp') || node;
    bubble.classList.remove('jump-highlight');
    void bubble.offsetWidth;
    bubble.classList.add('jump-highlight');
  }

  // 单词本「回到原句」：消息在主聊天就在主聊天里翻上去找；在旧对话里就打开那段旧对话
  async function openMessage(sessionId, messageId) {
    LP.appShell?.switchTab('talk');
    const mainSession = main?.session_id ?? LP.state.currentSessionId;
    if (sessionId == null || sessionId === mainSession) {
      if (archive) await closeArchive();
      await historyTask;
      let node = document.getElementById('msg-' + messageId);
      for (let i = 0; !node && i < 20; i++) {
        if (!(await loadOlder())) break;
        node = document.getElementById('msg-' + messageId);
      }
      if (!node) return false;
      highlight(node);
      return true;
    }
    const items = (await LP.api.getChatArchives().catch(() => ({ items: [] }))).items || [];
    const a = items.find((x) => x.session_id === sessionId);
    if (!a || !(await openArchive(a))) return false;
    const node = document.getElementById('msg-' + messageId);
    if (!node) return false;
    highlight(node);
    return true;
  }

  // ---------- 图片 ----------
  function openLightbox(url) { els.lightboxImg.src = url; if (!els.lightbox.open) els.lightbox.showModal(); }
  function setPendingImage(file) {
    if (!file) return;
    if (!ACCEPTED_IMAGE_TYPES.includes(file.type)) { LP.toast?.('这张图发不了'); return; }
    if (file.size > MAX_IMAGE_BYTES) { LP.toast?.('图片太大，8MB 以内'); return; }
    pendingImageFile = file;
    const reader = new FileReader();
    reader.onload = () => { if (pendingImageFile !== file) return; els.attachThumb.src = reader.result; els.attachPreview.classList.remove('hidden'); };
    reader.readAsDataURL(file);
  }
  function clearPendingImage() {
    pendingImageFile = null;
    if (!els.attachThumb) return;
    els.attachThumb.removeAttribute('src');
    els.attachPreview.classList.add('hidden');
    els.fileInput.value = '';
  }

  // ---------- 贴图抽屉 ----------
  let stickerScroll = 0;
  // ---------- 「⋯」菜单：打开、Esc/点外面/选完就关，焦点回到「⋯」 ----------
  function toggleMenu(force) {
    const open = force ?? els.menu.hidden;
    els.menu.hidden = !open;
    els.more.setAttribute('aria-expanded', String(open));
    if (open) els.menu.querySelector('button:not([hidden])')?.focus();
  }
  function paintStickerDrawer() {
    if (!els.stickerDrawer) return;
    const recent = LP.appShell?.store?.get('recentStickers') || [];
    const order = [...recent.map((id) => stickers.find((s) => s.id === id)).filter(Boolean), ...stickers.filter((s) => !recent.includes(s.id))];
    els.stickerDrawer.replaceChildren(...order.map((s) => {
      const b = button('', () => {
        LP.appShell?.store?.set('recentStickers', [s.id, ...recent.filter((id) => id !== s.id)].slice(0, 8));
        toggleStickers(false); void send({ sticker: s.id }); paintStickerDrawer();
      }, 'jm-sticker');
      const img = el('img'); img.src = s.url; img.alt = ''; img.loading = 'lazy';
      b.append(img);
      b.title = s.meaning || s.id;
      b.setAttribute('aria-label', s.meaning || s.id);
      return b;
    }));
  }
  function toggleStickers(force) {
    const open = force ?? els.stickerDrawer.hidden;
    if (!open && !els.stickerDrawer.hidden) stickerScroll = els.stickerDrawer.scrollTop;
    els.stickerDrawer.hidden = !open;
    if (open) els.stickerDrawer.scrollTop = stickerScroll;
    els.stickerBtn.setAttribute('aria-pressed', String(open));
    if (open && nearBottom()) requestAnimationFrame(scrollBottom);
  }

  // ---------- 发送 ----------
  function refreshSend() { if (els.send) els.send.disabled = sending || !primary(); }
  function autoGrow() { els.input.style.height = 'auto'; els.input.style.height = Math.min(els.input.scrollHeight, 120) + 'px'; }

  function wireComposer() {
    els.input.addEventListener('input', autoGrow);
    els.input.addEventListener('input', () => stage('user_typing'));
    els.input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing && ev.keyCode !== 229) { ev.preventDefault(); els.composer.requestSubmit(); }
      if (ev.key === 'Backspace' && !els.input.value && target != null) setTarget(null);
    });
    els.composer.addEventListener('submit', (ev) => { ev.preventDefault(); void send({}); });
    els.attachBtn.addEventListener('click', () => els.fileInput.click());
    els.stickerBtn.addEventListener('click', () => toggleStickers());
    els.fileInput.addEventListener('change', () => { const file = els.fileInput.files?.[0]; if (file) setPendingImage(file); });
    els.attachRemove.addEventListener('click', clearPendingImage);
    els.to.addEventListener('click', () => setTarget(null));
    els.input.addEventListener('paste', (ev) => {
      for (const item of ev.clipboardData?.items || []) {
        if (item.kind === 'file' && item.type?.startsWith('image/')) { const file = item.getAsFile(); if (file) { setPendingImage(file); ev.preventDefault(); } break; }
      }
    });
    const drop = els.sky;
    ['dragover', 'dragenter'].forEach((evt) => drop.addEventListener(evt, (ev) => {
      if ([...(ev.dataTransfer?.types || [])].includes('Files') && !archive) { ev.preventDefault(); drop.classList.add('drag-over'); }
    }));
    ['dragleave', 'dragend'].forEach((evt) => drop.addEventListener(evt, () => drop.classList.remove('drag-over')));
    drop.addEventListener('drop', (ev) => { ev.preventDefault(); drop.classList.remove('drag-over'); const file = ev.dataTransfer?.files?.[0]; if (file && !archive) setPendingImage(file); });
    drop.addEventListener('scroll', () => {
      els.latest.hidden = nearBottom(240);
      if (drop.scrollTop < 80) void loadOlder();
    });
    els.latest.addEventListener('click', scrollBottom);
    els.lightbox.addEventListener('click', () => els.lightbox.close());
    els.lightbox.addEventListener('close', () => els.lightboxImg.removeAttribute('src'));
    els.dice.addEventListener('click', () => void putMain({ fun: !main?.fun }));
    els.archivesBtn.addEventListener('click', () => { toggleMenu(false); void toggleArchives(); });
    els.more.addEventListener('click', () => toggleMenu());
    els.lessonStart.addEventListener('click', () => { toggleMenu(false); void LP.lesson.start(main?.language || primary()?.language).catch(() => {}); });
    els.lessonStop.addEventListener('click', () => {
      const view = LP.lesson.current();
      if (view?.id === lessonRunId) void LP.lesson.stop(view).catch(error => LP.toast?.(LP.util.message(error)));
    });
    els.addLanguage.addEventListener('click', () => { toggleMenu(false); languageDrawer().open(); });
    els.personaCard.addEventListener('click', () => { toggleMenu(false); LP.settings?.open('chat'); });
    els.course.addEventListener('click', () => toggleMenu(false), true);
    document.addEventListener('pointerdown', (ev) => { if (!els.menu.hidden && !ev.target.closest('.jm-more')) toggleMenu(false); });
    els.menu.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') { ev.stopPropagation(); toggleMenu(false); els.more.focus(); }
      if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
        const items = [...els.menu.querySelectorAll('button:not([hidden])')];
        const i = items.indexOf(document.activeElement);
        items[(i + (ev.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus();
        ev.preventDefault();
      }
    });
    // 没发出去的字：切走、刷新都还在
    const draft = LP.appShell?.store?.get('chatDraft');
    if (draft && !els.input.value) { els.input.value = draft; autoGrow(); }
    els.input.addEventListener('input', () => LP.appShell?.store?.set('chatDraft', els.input.value));
    els.archiveBack.addEventListener('click', () => void closeArchive());
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { if (!els.stickerDrawer.hidden) toggleStickers(false); if (!els.archivePanel.hidden) toggleArchives(false); } });
  }

  function say(text, { via } = {}) {
    if (archive || !main?.primary_id || !persona(main.primary_id)) return false;
    void send({ text: String(text).trim(), via, external: true });
    return true;
  }

  async function send({ sticker = null, text: suppliedText, via = null, external = false }) {
    if ((!external && sending) || archive) return;
    const text = external ? suppliedText : (sticker ? '' : els.input.value.trim());
    const imageFile = external || sticker ? null : pendingImageFile;
    if (!text && !imageFile && !sticker) return;
    if (!primary()) return;
    LP.stage?.stopSpeech();
    if (!external) { sending = true; refreshSend(); }
    let imageUrl = null;
    if (imageFile) {
      try { imageUrl = (await LP.api.uploadChatImage(imageFile)).url; }
      catch { LP.toast?.('图片没发出去，再试一次'); sending = false; refreshSend(); return; }
    }
    stage('sent', sticker ? { sticker } : null);
    dateBefore(new Date().toISOString());
    const mine = messageRow({ role: 'user', content: text, image_url: imageUrl, sticker, created_at: new Date().toISOString(), read: false, language: main?.language });
    mine.dataset.pending = 'true';
    place(mine);
    scrollBottom();
    const to = external ? null : target;
    if (!external && !sticker) { els.input.value = ''; autoGrow(); clearPendingImage(); LP.appShell?.store?.set('chatDraft', ''); }
    if (!external) setTarget(null);
    if (!external) { sending = false; refreshSend(); }
    noteActivity();
    const body = { text };
    if (via) body.via = via;
    if (imageUrl) body.image_url = imageUrl;
    if (sticker) body.sticker = sticker;
    if (to != null) body.to = to;
    const attempt = () => runTurn((handlers) => {
      const scene = LP.scene.get();
      const stream = LP.sse.postChat({ ...body, scene }, handlers);
      LP.scene.sent(scene);
      return stream;
    }, {
      eager: true,
      to,
      via,
      onFail: () => {
        if (via === 'stage') stage('fail', { text });
        if (mine.querySelector('.jm-retry')) return;
        const retry = button('↻', () => { retry.remove(); mine.classList.remove('failed'); attempt(); }, 'jm-retry');
        retry.setAttribute('aria-label', '重发'); retry.title = '重发';
        mine.classList.add('failed');
        mine.querySelector('.jm-meta')?.prepend(retry);
      },
    });
    attempt();
  }

  // 她开始生成时：这些用户消息标「已读」。前端先画的那几条还没有 id，按顺序认领
  function markRead(ids = []) {
    for (const id of ids) {
      let node = document.getElementById('msg-' + id);
      if (!node) {
        node = els.messages.querySelector('.jm-row.me[data-pending="true"]');
        if (node) { node.id = 'msg-' + id; delete node.dataset.pending; }
      }
      const mark = node?.querySelector('.jm-read');
      if (mark) mark.hidden = false;
    }
    if (!ids.length) els.messages.querySelectorAll('.jm-row.me .jm-read[hidden]').forEach((mark) => { mark.hidden = false; });
  }

  // 一轮回复：可能有好几个说话人（主讲 + 插话），每个人开口前来一个 speaker 事件
  function runTurn(start, { eager, onFail, via = null, to = null }) {
    let speaker = null;        // {id, name, language, rows:{index->...}}
    let speakerSeq = 0;
    let typingRow = null;
    let guardMood = null;
    let finished = false;
    const shown = [];          // 已确认（bubble_done）的行
    const note = el('div', '', 'jm-sys jm-note');
    note.setAttribute('role', 'status');

    function setSpeaker(data) {
      const id = data?.persona_id ?? main?.primary_id;
      if (speaker && speaker.id === id && speaker.seq === speakerSeq) return speaker;
      if (speaker) typingNames.delete(speaker.name);
      const p = persona(id) || { id, name: data?.persona_name || '' };
      speaker = { id, name: p.name || data?.persona_name || '', language: data?.language || p.language, persona: p, seq: ++speakerSeq, bubbles: {} };
      typingNames.add(speaker.name);
      renderStatus();
      showTyping();
      if (reacts(speaker.persona)) stage('typing');
      return speaker;
    }
    function showTyping() {
      typingRow?.remove();
      if (!speaker || finished || archive) return;
      const { row, line, meta } = makeRow({ mine: false, who: speaker.persona, time: new Date() });
      row.classList.add('jm-typing');
      const { bubble } = makeBubble(speaker.language, null, false);
      bubble.querySelector('.tok-container').append(el('i'), el('i'), el('i'));
      line.insertBefore(bubble, meta);
      meta.remove();
      typingRow = row;
      const follow = nearBottom();
      place(row);
      if (follow) scrollBottom();
    }
    function ensureBubble(index) {
      const s = speaker || setSpeaker(null);
      if (s.bubbles[index]) return s.bubbles[index];
      const { row, line, meta } = makeRow({ mine: false, who: s.persona, time: new Date() });
      const { bubble, container } = makeBubble(s.language, null, false);
      line.insertBefore(bubble, meta);
      bubble.classList.add('streaming');
      if (isCho(s.persona) && guardMood) setMood(row, guardMood);
      const entry = { row, line, meta, bubble, container, text: '', completed: false };
      s.bubbles[index] = entry;
      placeLive(row);
      return entry;
    }
    // 正在看旧对话时不往页面上插（回到主聊天会重读）
    function placeLive(row) {
      if (archive) return;
      if (typingRow) { els.messages.insertBefore(row, typingRow); regroup(row); regroup(typingRow); }
      else place(row);
    }

    const turn = { spoke: false };
    activeTurns.add(turn);

    function finish(message) {
      if (finished) return;
      finished = true;
      typingRow?.remove(); typingRow = null;
      note.remove();
      typingNames.clear(); renderStatus();
      stage('idle');
      // 只有 bubble_done 确认过的气泡才落了库；半截输出撤回
      els.messages.querySelectorAll('.jm-row .bubble.streaming').forEach((b) => b.closest('.jm-row')?.remove());
      els.messages.querySelectorAll('.jm-row').forEach(regroup);
      if (message && !archive) { note.textContent = message; place(note); }
      activeTurns.delete(turn);
      turn.spoke = shown.length > 0;
      noteActivity();
      if (reloadAfterTurn && !activeTurns.size && !archive) { reloadAfterTurn = false; void loadHistory(); }
      if (!pendingCount) return;
      void refreshPending();
    }

    if (eager) { setSpeaker({ persona_id: to ?? main?.primary_id }); }

    start({
      onQueued: () => finish(null),
      onRead: (d) => { markRead(d.message_ids || []); stage('read'); },
      onSystem: (d) => { const pill = el('div', d.text || '', 'jm-sys'); if (d.message_id != null) pill.id = 'msg-' + d.message_id; placeLive(pill); },
      onSpeaker: (d) => { setSpeaker(d); },
      onGuard: (d) => {
        if (d.session_id != null) LP.state.currentSessionId = d.session_id;
        guardMood = d.mood;
        if (d.persona_id != null && speaker?.id !== d.persona_id) setSpeaker(d);
        if (reacts(speaker?.persona)) stage('mood', { mood: guardMood });
        if (typingRow && isCho(speaker?.persona)) setMood(typingRow, guardMood);
      },
      onDelta: (d) => {
        if (d.persona_id != null && speaker?.id !== d.persona_id) setSpeaker(d);
        const follow = nearBottom();
        const b = ensureBubble(d.bubble ?? 0);
        b.text += d.text || '';
        b.container.textContent = b.text;
        if (follow) scrollBottom();
      },
      onBubbleDone: (d) => {
        if (d.persona_id != null && speaker?.id !== d.persona_id) setSpeaker(d);
        const follow = nearBottom();
        const s = speaker || setSpeaker(d);
        if (d.sticker && !(d.text || s.bubbles[d.bubble ?? 0]?.text)) {
          // 贴图单独成条，不带气泡
          s.bubbles[d.bubble ?? 0]?.row.remove();
          const { row, line, meta } = makeRow({ mine: false, who: s.persona, messageId: d.message_id, time: new Date() });
          line.insertBefore(stampImg(d.sticker), meta);
          s.bubbles[d.bubble ?? 0] = { row, completed: true };
          placeLive(row);
        } else {
          const b = ensureBubble(d.bubble ?? 0);
          b.completed = true;
          b.bubble.classList.remove('streaming');
          b.row.id = 'msg-' + d.message_id;
          b.bubble.dataset.messageId = d.message_id;
          fill(b.container, { tokens: d.tokens, content: b.text || d.text || '' });
          if (d.tokens?.length) void LP.glosses?.prepare(b.container.dataset.lang, LP.tokens.reconstructSentence(d.tokens), d.tokens).catch(() => {});
          tools(b.row, b.container, b.bubble);
          if (d.sticker) { const { row, line, meta } = makeRow({ mine: false, who: s.persona, time: new Date() }); line.insertBefore(stampImg(d.sticker), meta); placeLive(row); }
        }
        shown.push(d.message_id);
        if (reacts(s.persona)) {
          const text = d.text || s.bubbles[d.bubble ?? 0]?.text || '';
          const show = via === 'stage' || !els.root?.classList.contains('active');
          const speak = show && LP.stage.voiceOn() && Boolean(text);
          stage('bubble', { mood: guardMood, sticker: d.sticker || null, text, message_id: d.message_id, language: d.language || s.language, show, speak });
          if (speak) LP.stage.speak(d.message_id);
        }
        else stage('other');
        showTyping();
        noteActivity();
        if (follow) scrollBottom();
      },
      onAction: (d) => {
        actionQueue = actionQueue.then(async () => {
          const result = await LP.actions.run(d.name, d.arg);
          stage('acted', result);
          LP.scene.noteAction(result.label);
        });
      },
      onDone: (d) => { if (d.session_id != null) LP.state.currentSessionId = d.session_id; finish(null); },
      onInterrupted: () => { finish(null); stage('interrupted'); },
      onError: (d) => {
        // 一个字都没回：是这条没发出去，标在那条消息上；回了一半才在下面写一行。原始错误只进控制台
        if (d?.message) console.warn('chat:', d.message);
        if (onFail && !shown.length) { finish(null); onFail(); return; }
        finish('没说完');
        note.classList.add('error');
      },
    });
    return turn;
  }

  // ---------- 她主动开口（docs/LORE-AND-HOOKS.md 2.5；提示在图标栏「聊天」上） ----------
  const OPEN_EVERY = 10 * 60 * 1000;
  const IDLE_AFTER = 10 * 60 * 1000;
  let pendingCount = 0;
  let lastOpenFired = 0;
  let lastActivity = Date.now();
  let idleFired = false;
  let proactiveRunning = false;

  function noteActivity() { lastActivity = Date.now(); idleFired = false; }
  function applyPending(count) {
    pendingCount = Math.max(0, Number(count) || 0);
    const nav = document.querySelector('.nav-btn[data-tab="talk"]');
    if (!nav) return;
    let dot = nav.querySelector('.nav-dot');
    if (pendingCount && !dot) { dot = el('span', '', 'nav-dot'); dot.setAttribute('aria-label', '有新消息'); nav.append(dot); }
    if (!pendingCount) dot?.remove();
  }
  const sumPending = (items) => (items || []).reduce((n, row) => n + (Number(row.count) || 0), 0);
  async function refreshPending() {
    try { applyPending(sumPending((await LP.api.getHookPending()).items)); } catch { /* 红点只是提示 */ }
    maybeProactive();
  }
  function talkVisible() { return !document.hidden && Boolean(els.root?.classList.contains('active')); }
  let proactiveQuietUntil = 0;   // 上一次主动开口没说出话（出错或空）：一分钟内不再拉，免得一直重试
  function maybeProactive() {
    if (!pendingCount || proactiveRunning || archive || !talkVisible() || activeTurns.size || Date.now() < proactiveQuietUntil) return;
    proactiveRunning = true;
    applyPending(0);
    // 出错时不在时间线上写字（onFail 什么都不做）
    const turn = runTurn((handlers) => LP.sse.postProactive({}, handlers), { eager: false, onFail: () => {} });
    const settle = setInterval(() => {
      if (activeTurns.has(turn)) return;
      clearInterval(settle);
      proactiveRunning = false;
      if (!turn.spoke) proactiveQuietUntil = Date.now() + 60000;
      void refreshPending();
    }, 400);
  }
  async function fire(event, payload = {}) {
    try { applyPending(sumPending((await LP.api.fireHook({ event, payload })).pending)); }
    catch { await refreshPending(); return; }
    maybeProactive();
  }
  function warm() { fetch('/api/chat/main/warm', { method: 'POST' }).catch(() => {}); }
  async function opened() {
    if (!talkVisible()) return;
    void LP.lesson.refresh().catch(error => LP.toast?.(LP.util.message(error)));
    warm();
    noteActivity();
    if (Date.now() - lastOpenFired < OPEN_EVERY) { await refreshPending(); return; }
    lastOpenFired = Date.now();
    await fire('chat.open'); // first_today 由后端算
  }
  function watchIdle() {
    setInterval(() => {
      if (idleFired || !talkVisible() || archive || activeTurns.size) return;
      const idle = Date.now() - lastActivity;
      if (idle < IDLE_AFTER) return;
      idleFired = true; // 要等有新的消息往来才会再发
      void fire('chat.idle', { minutes: Math.floor(idle / 60000) });
    }, 30000);
    setInterval(() => { if (!document.hidden) void refreshPending(); }, 60000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) void refreshPending(); });
  }

  // ---------- 对外入口 ----------
  function mount(root) {
    renderShell(root);
    wireComposer();
    document.addEventListener('lp:teaching-settings', renderCourseTag);
    document.addEventListener('lp:teaching-ready', renderCourseTag);
    document.addEventListener('lp:teaching-settings', () => void renderLessonStart());
    document.addEventListener('lp:lesson', () => { renderLesson(); void renderLessonStart(); });
    document.addEventListener('lp:languages', () => renderTopbar());
    renderTopbar();
    renderLesson();
    void LP.lesson.refresh().catch(error => LP.toast?.(LP.util.message(error)));
    warm();
    const first = Promise.all([loadMain(), loadHistory()]).then(() => refreshSend());
    watchIdle();
    void first.then(loadStickers);
    return first;
  }

  // 人设或聊天安排变了：重读主聊天、重画顶栏；有自定义头像的人设才重画消息（首屏用名字画过一遍了）
  let personasSeen = false;
  async function personasChanged() {
    await loadMain();
    refreshSend();
    const avatars = LP.state.personas.some((p) => p.avatar_url);
    if (!archive && (personasSeen || avatars)) await loadHistory();
    personasSeen = true;
    void opened();
  }
  async function refreshMain() { await loadMain(); }

  global.LP = global.LP || {};
  global.LP.jine = { mount, say, personasChanged, refreshMain, loadHistory, renderTopbar, openMessage, opened, refreshPending, stopSpeech,
    proactiveNow: () => { proactiveQuietUntil = 0; return refreshPending(); } };
})(window);
