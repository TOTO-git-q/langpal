/* app.js — 启动入口（appShell）：单窗口应用编排。标题栏（桌面壳三键）、图标栏 + 二级导航的页签切换、
   各页签的脚本按需加载（第一次打开时才插 <script>，按依赖顺序）、health/usage 轮询（页面隐藏时暂停）、toast。
   首屏只等聊天：chat/main 和最近一页消息；人设、语言表、贴图、额度都并行，不挡首屏。 */
(function (global) {
  'use strict';

  // ---------- 按需加载（没有打包器：按顺序插 script 标签，同一个文件只加载一次） ----------
  const BUNDLES = {
    teach: ['settings-teaching'],
    storage: ['study-storage'],
    settings: ['@teach', 'settings-sources', 'settings-reading', 'settings-providers', 'settings-voice', 'reading-preferences', 'conditions',
      'settings-models', 'settings-lore', 'settings-hooks', 'settings-chat-room', 'settings'],
    agent: ['workspace-agent'],
    learning: ['learning'],
    course: ['course-page'],
    reading: ['@storage', 'reading-preferences', 'reading'],
    listening: ['@storage', '@teach', 'listening'],
    notebook: ['@learning', 'notebook'],
    review: ['@learning', 'review'],
    coach: ['coach'],
  };
  const scripts = {};
  function loadScript(name) {
    const src = 'js/' + name + '.js';
    if (scripts[name]) return scripts[name];
    if ([...document.scripts].some((s) => s.getAttribute('src') === src)) return (scripts[name] = Promise.resolve());
    scripts[name] = new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      tag.src = src;
      tag.async = false;
      tag.onload = () => resolve();
      tag.onerror = () => { delete scripts[name]; reject(new Error('这页没打开，再点一次')); };
      document.body.append(tag);
    });
    return scripts[name];
  }
  const bundles = {};
  function need(name) {
    if (bundles[name]) return bundles[name];
    bundles[name] = (async () => {
      for (const item of BUNDLES[name] || [name]) {
        if (item.startsWith('@')) await need(item.slice(1));
        else await loadScript(item);
      }
    })();
    bundles[name].catch(() => { delete bundles[name]; });
    return bundles[name];
  }

  // 别的模块会在它们加载之前就调到这几个：先放一个替身，调的时候把真身加载进来再转过去
  function stand(key, bundle, methods) {
    if (global.LP[key]) return;
    const stub = { __stub: true };
    for (const m of methods) stub[m] = (...args) => need(bundle).then(() => (global.LP[key] === stub ? undefined : global.LP[key][m]?.(...args)));
    global.LP[key] = stub;
  }
  stand('settings', 'settings', ['open', 'newPersona', 'refresh']);
  stand('workspaceAgent', 'agent', ['prefill', 'openLibrary']);
  stand('learning', 'learning', ['openReview', 'openVocab']);

  // tab id -> 需要的脚本 + 挂载 / 刷新
  const APP_DEFS = [
    { id: 'today', needs: 'learning', mount: (body) => { mounted.todayView = LP.learning.mountToday(body); }, refresh: () => mounted.todayView?.refresh() },
    { id: 'drill', needs: 'learning', mount: (body) => { mounted.drillView = LP.learning.mountReview(body); }, refresh: () => mounted.drillView?.refresh() },
    { id: 'course', needs: 'course', mount: (body) => { mounted.courseView = LP.coursePage.mount(body); }, refresh: () => mounted.courseView?.refresh() },
    { id: 'reading', needs: 'reading', mount: (body) => LP.reading.mount(body) },
    { id: 'listening', needs: 'listening', mount: (body) => LP.listening.mount(body) },
    { id: 'notebook', needs: 'notebook', mount: (body) => LP.notebook.mount(body), refresh: () => LP.notebook.refresh() },
    { id: 'review', needs: 'review', mount: (body) => LP.review.mount(body), refresh: () => LP.review.refresh() },
    { id: 'workspace-agent', needs: 'agent', mount: (body) => LP.workspaceAgent.mount(body) },
    { id: 'coach', needs: 'coach', mount: (body) => LP.coach.mount(body), refresh: () => LP.coach.refresh() },
    { id: 'settings', needs: 'settings', mount: (body) => LP.settings.mount(body), refresh: () => LP.settings.refresh() },
  ];
  const HEALTH_EVERY = 30000;
  const USAGE_EVERY = 120000;

  const toastEl = document.getElementById('toast');
  let toastTimer = null;
  let toastDone = null; // 正在显示的那条撤销提示到时要做的事；被下一条顶掉时先做掉
  // toast 只用来「撤销」（和极少数没有控件可挂的消息）：toast('已删除', { undo }) 停 5 秒
  function toast(msg, options = {}) {
    if (toastTimer) clearTimeout(toastTimer);
    const previous = toastDone;
    toastDone = null;
    previous?.();
    toastEl.replaceChildren(document.createTextNode(msg));
    if (options.undo) {
      const undo = document.createElement('button');
      undo.type = 'button'; undo.className = 'toast-undo'; undo.textContent = '撤销';
      undo.addEventListener('click', () => { toastEl.classList.add('hidden'); clearTimeout(toastTimer); toastDone = null; void options.undo(); });
      toastEl.append(' · ', undo);
    }
    toastEl.classList.remove('hidden');
    toastDone = options.done || null;
    toastTimer = setTimeout(() => { toastEl.classList.add('hidden'); const done = toastDone; toastDone = null; done?.(); }, options.undo ? 5000 : 2400);
  }
  // 先删、再给 5 秒撤销：remove() 立刻把东西从界面拿掉，5 秒没撤销才 commit()
  function undoable(message, { remove, restore, commit }) {
    remove?.();
    let undone = false;
    toast(message, { undo: () => { undone = true; restore?.(); }, done: () => { if (!undone) void commit(); } });
  }

  // ---------- 记住上次（localStorage；读写失败就当没有） ----------
  const store = {
    get(key) { try { return JSON.parse(localStorage.getItem('lp.' + key)); } catch { return null; } },
    set(key, value) { try { localStorage.setItem('lp.' + key, JSON.stringify(value)); } catch { /* 隐私模式 */ } },
  };

  const mounted = {}; // tab id -> 挂载状态（true / 正在加载的 Promise）
  let currentTab = 'talk';
  let leaving = null, leaveTarget = null;
  // 学习先落在「今天」，复习先落在复习会话
  const sections = { study: ['today', 'course', 'reading', 'listening', 'coach'], revise: ['drill', 'review', 'notebook'] };
  const lastPage = { study: 'today', revise: 'drill', ...(store.get('lastPage') || {}) };

  function switchTab(tab, { waitForLeave = false } = {}) {
    if (Object.hasOwn(lastPage, tab)) tab = lastPage[tab];
    // 设置里有没存的长文本：先问
    if (currentTab === 'settings' && tab !== 'settings' && LP.settings?.isDirty?.()) {
      leaveTarget = tab;
      // 已经有一个「没存，离开吗」在等：不再叠一个，只记下最后想去哪
      leaving ||= LP.settings.leaveOk().then((ok) => {
        leaving = null;
        if (ok) return switchTab(leaveTarget, { waitForLeave });
      });
      if (waitForLeave) return leaving;
      return;
    }
    const panel = document.getElementById('page-' + tab);
    if (!panel) return;
    const section = Object.keys(sections).find((key) => sections[key].includes(tab));
    if (section) { lastPage[section] = tab; store.set('lastPage', lastPage); }
    store.set('lastTab', tab);
    for (const key of Object.keys(sections)) {
      document.getElementById('app-' + key + '-nav').hidden = key !== section;
    }
    if (currentTab === 'review' && tab !== 'review') LP.review?.pause?.();
    if (currentTab === 'drill' && tab !== 'drill') mounted.drillView?.leave();
    if (currentTab === 'coach' && tab !== 'coach') LP.coach?.leave();
    if (currentTab === 'settings' && tab !== 'settings') LP.settings?.leave?.();
    document.querySelectorAll('.page-panel').forEach((p) => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach((b) => {
      const active = b.dataset.tab === tab || b.dataset.tab === section;
      b.classList.toggle('active', active);
      if (active) b.setAttribute('aria-current', 'page');
      else b.removeAttribute('aria-current');
    });
    panel.classList.add('active');

    const previous = currentTab;
    currentTab = tab;
    if (tab !== 'talk') {
      const def = APP_DEFS.find((d) => d.id === tab);
      if (!def) return;
      if (mounted[tab] === true) { def.refresh?.(); document.dispatchEvent(new CustomEvent('lp:tab', { detail: tab })); return; }
      if (mounted[tab]) return; // 正在加载
      panel.classList.add('loading');
      mounted[tab] = need(def.needs).then(() => {
        panel.classList.remove('loading');
        def.mount(panel);
        mounted[tab] = true;
        document.dispatchEvent(new CustomEvent('lp:tab', { detail: tab }));   // 这一页挂好了（在这一页上的课等的就是它）
      }).catch((error) => {
        panel.classList.remove('loading');
        delete mounted[tab];
        toast(error.message);
      });
    } else if (previous !== 'talk') {
      void LP.jine?.opened(); // 回到聊天页也算「打开」她的对话（chat.open 自带 10 分钟节流）
    }
  }
  // 测试和别的模块用：等某个页签挂好
  function ready(tab) { return Promise.resolve(mounted[tab]); }

  function openMistakes(kind, language) {
    switchTab('review');
    void ready('review').then(() => {
      LP.review.setFilter(kind, language);
      document.querySelector('#page-review [data-kind][aria-pressed="true"]')?.focus();
    });
  }

  // 键盘：Ctrl+1…5 切图标栏五个分区，Ctrl+K 去聊天并聚焦输入框
  const RAIL = ['talk', 'study', 'revise', 'workspace-agent', 'settings'];
  function wireKeys() {
    // 所有「⋯」弹层：Esc 关、点外面关，焦点回到「⋯」
    document.addEventListener('keydown', (ev) => {
      if (ev.key !== 'Escape') return;
      const open = document.querySelector('details.row-more[open], details.lp-more[open], details.rd-more[open]');
      if (open) { open.open = false; open.querySelector('summary')?.focus(); }
    });
    document.addEventListener('pointerdown', (ev) => {
      document.querySelectorAll('details.row-more[open]').forEach((d) => { if (!d.contains(ev.target)) d.open = false; });
    });
    document.addEventListener('keydown', (ev) => {
      if (!(ev.ctrlKey || ev.metaKey) || ev.altKey || ev.shiftKey) return;
      const n = Number(ev.key);
      if (n >= 1 && n <= RAIL.length) { ev.preventDefault(); switchTab(RAIL[n - 1]); return; }
      if (ev.key.toLowerCase() === 'k') {
        ev.preventDefault();
        switchTab('talk');
        const focusInput = () => document.getElementById('jine-input')?.focus();
        requestAnimationFrame(focusInput);
        setTimeout(() => { if (document.activeElement?.id !== 'jine-input' && currentTab === 'talk') focusInput(); }, 200);
      }
    });
  }

  // 今天还没做的下一件：连续流的主按钮都指向它。返回 { tab, label }；全做完了是「去聊天」
  const NEXT = { review: { tab: 'drill', label: '去复习' }, reading: { tab: 'reading', label: '读一篇' }, listening: { tab: 'listening', label: '听一段' }, output: { tab: 'talk', label: '去聊天' } };
  async function nextStep(except) {
    try {
      const language = LP.learning?.currentLanguage?.() || LP.currentPersona?.()?.language || 'ja';
      const r = await fetch('/api/today?language=' + encodeURIComponent(language), { cache: 'no-store' });
      const today = r.ok ? await r.json() : null;
      const step = (today?.steps || []).find((s) => !s.done && s.kind !== except && s.kind !== 'output' && NEXT[s.kind]);
      return step ? { ...NEXT[step.kind], kind: step.kind } : { ...NEXT.output, kind: 'output' };
    } catch { return { ...NEXT.output, kind: 'output' }; }
  }

  function wireNav() {
    document.querySelectorAll('.nav-btn').forEach((btn) => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
      // 鼠标停在图标上时先把脚本拿下来，点的时候就是现成的
      btn.addEventListener('pointerenter', () => {
        const tab = Object.hasOwn(lastPage, btn.dataset.tab) ? lastPage[btn.dataset.tab] : btn.dataset.tab;
        const def = APP_DEFS.find((d) => d.id === tab);
        if (def && !mounted[tab]) void need(def.needs).catch(() => {});
      }, { once: true });
    });
  }

  // ---------- 标题栏三键：接桌面壳（window.langpalDesktop）；浏览器里没有就隐藏 ----------
  function wireTitlebar() {
    const desktop = global.langpalDesktop;
    const btns = document.getElementById('app-winbtns');
    if (desktop && desktop.isDesktop) {
      document.getElementById('app-btn-min').addEventListener('click', () => desktop.minimize());
      document.getElementById('app-btn-max').addEventListener('click', () => desktop.toggleMaximize());
      document.getElementById('app-btn-close').addEventListener('click', () => desktop.close());
    } else {
      btns.classList.add('hidden');
    }
  }

  async function reloadPersonas() {
    const res = await LP.api.getPersonas();
    const items = (res.items || []).filter((p) => !p.archived_at).sort((a, b) => a.id - b.id);
    LP.state.personas = items;
    await LP.jine?.personasChanged();
  }

  // ---------- 侧栏底部：健康圆点 + 周额度角标 ----------
  function renderHealthDot(h) {
    const dot = document.getElementById('nav-health-dot');
    if (!dot) return;
    dot.classList.remove('bad', 'warn');
    if (!h || h.status !== 'ok') dot.classList.add('bad');
    else if (h.degraded) dot.classList.add('warn');
  }

  function renderUsageChip(u) {
    // 角标显示【周额度剩余】；周数据缺失时退回 5 小时窗口剩余
    const chip = document.getElementById('nav-usage-chip');
    if (!chip) return;
    const used = u && u.available ? (u.seven_day_pct != null ? u.seven_day_pct : u.five_hour_pct) : null;
    if (used == null) { chip.hidden = true; return; }
    const left = Math.round(100 - used);
    chip.hidden = false;
    chip.textContent = `周额度剩 ${left}%`;
    chip.classList.toggle('hot', left <= 20);
  }

  async function pollHealth() {
    try {
      const h = await LP.api.getHealth();
      LP.state.health = h;
      renderHealthDot(h);
    } catch {
      renderHealthDot({ status: 'error' });
    }
  }

  async function pollUsage() {
    try {
      const u = await LP.api.getUsage();
      LP.state.usage = u;
      renderUsageChip(u);
      if (!LP.settings?.__stub) LP.settings?.renderUsage?.(u);
    } catch {
      renderUsageChip(null);
    }
  }

  // 页面隐藏（最小化/切走）时停掉轮询；回来时立刻补一次再恢复。
  const pollers = [
    { run: pollHealth, every: HEALTH_EVERY, timer: null },
    { run: pollUsage, every: USAGE_EVERY, timer: null },
  ];
  function startPolling() {
    for (const p of pollers) {
      if (p.timer) continue;
      void p.run();
      p.timer = setInterval(p.run, p.every);
    }
  }
  function stopPolling() {
    for (const p of pollers) { clearInterval(p.timer); p.timer = null; }
  }

  async function boot() {
    wireTitlebar();
    wireNav();
    wireKeys();
    // 聊天先画：mount 自己并行拉 chat/main 和最近一页消息
    LP.jine.mount(document.getElementById('page-talk'));
    // 其余并行，不挡首屏
    const [personas] = await Promise.allSettled([reloadPersonas(), LP.languages.reload()]);
    if (personas.status === 'rejected') toast('角色列表没打开，刷新试试');
    else if (!LP.state.personas.length) switchTab('settings');
    else {
      // 回到上次的页面
      const last = store.get('lastTab');
      if (last && last !== 'talk' && document.getElementById('page-' + last) && currentTab === 'talk') switchTab(last);
    }
    document.addEventListener('visibilitychange', () => (document.hidden ? stopPolling() : startPolling()));
    if (!document.hidden) startPolling();
    // 空闲时把课程脚本拿下来（聊天顶栏的课程小标签要用）
    const idle = global.requestIdleCallback || ((fn) => setTimeout(fn, 600));
    idle(() => void need('teach').then(() => document.dispatchEvent(new Event('lp:teaching-ready'))).catch(() => {}));
  }

  document.addEventListener('DOMContentLoaded', boot);

  global.LP = global.LP || {};
  global.LP.appShell = { switchTab, openMistakes, reloadPersonas, need, ready, nextStep, undoable, store, current: () => currentTab };
  LP.scene.provide('reading', () => {
    const reader = document.querySelector('#page-reading .rd-open');
    return { language: reader && !reader.hidden ? reader.querySelector('[data-rd="language"]')?.value : LP.preferences?.get('readerLanguage') || 'en' };
  });
  LP.scene.provide('notebook', () => ({ language: document.querySelector('#page-notebook .nb-chip[aria-pressed="true"]')?.dataset.lang || null }));
  LP.scene.provide('review', () => ({ language: document.querySelector('#page-review .rv-languages')?.value || null }));
  global.LP.need = need;
  global.LP.toast = toast;
})(window);
