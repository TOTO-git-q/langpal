/* Listening practice stays in its own workspace and uses the existing LangPal server. */
(() => {
  "use strict";

  const base = "/api/listening";
  const stages = ["选题", "听大意", "回听", "答题", "复盘"];
  const difficultyKey = "jine.listening.difficulty.";
  let startFromAction;

  async function request(path, payload, signal) {
    const init = { signal };
    if (payload !== undefined) {
      init.method = "POST";
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(payload);
    }
    const response = await fetch(base + path, init);
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === "string" ? error.detail : "没连上");
    }
    return response.json();
  }

  const element = (tag, text, className) => window.LP.util.el(tag, text, className);

  function mount(root) {
    root.innerHTML = `
      <section class="lp-listening">
        <header class="lp-listening-heading workspace-tools">
          <h1 class="visually-hidden">听力</h1><button type="button" data-listen="new-practice" hidden>换一段</button><button type="button" data-listen="notes-toggle" aria-pressed="false">随心记</button>
          <div class="lp-listening-stage">
            <progress id="lp-listening-progress" aria-label="练习进度" max="4" value="0"></progress>
            <ol class="lp-listening-steps" aria-label="练习步骤"></ol>
          </div>
        </header>
        <div class="lp-listening-desk">
        <div class="lp-listening-flow">
          <form class="lp-listening-setup" aria-label="听力安排">
            <div class="listen-plan-preview"><div class="lp-plan-head"><div class="lp-lang-dial" data-listen="dial" role="radiogroup" aria-label="听力语言"></div><p data-listen="plan-detail"></p></div><div class="lp-tags" data-listen="tags"></div></div>
            <div class="listen-plan-fields" data-listen="plan-fields" id="listen-plan-fields" hidden>
              <label>语言 <select data-listen="language"></select></label>
              <label>题型 <select data-listen="format"></select></label>
              <label>材料难度 <select data-listen="difficulty" aria-describedby="lp-listening-difficulty-help" disabled><option value="default">自动</option></select></label>
              <label>主题 <input data-listen="topic" maxlength="120" placeholder="自由选题"></label>
              <p id="lp-listening-difficulty-help" class="lp-listening-difficulty-help"></p>
              <button type="button" data-listen="save-plan">保存安排</button>
            </div>
            <div class="listen-start-actions"><button type="submit" disabled>开始听</button>
              <details class="lp-more"><summary aria-label="更多" title="更多">⋯</summary><div class="lp-more-pop pixel-box">
                <button type="button" data-listen="fresh" hidden>听新的</button>
                <button type="button" data-listen="edit-plan" aria-controls="listen-plan-fields">主题和难度</button>
                <button type="button" data-listen="ask-plan">和课程管家调整</button>
                <div data-listen="history-slot"></div>
              </div></details>
            </div>
          </form>
          <div class="lp-home" data-listen="home">
            <div class="lp-left">
              <div class="lp-formats" data-listen="formats" role="radiogroup" aria-label="题型"></div>
              <section class="lp-recent" aria-labelledby="lp-recent-title" hidden><h3 id="lp-recent-title">最近</h3><ol class="lp-recent-list" data-listen="recent-list"></ol></section>
            </div>
            <section class="lp-month" aria-labelledby="lp-month-title" data-listen="month"><h3 id="lp-month-title">这个月</h3><div class="lp-month-body" data-listen="month-body"></div></section>
          </div>
          <p class="lp-listening-status" role="status" aria-live="polite"></p>
          <button type="button" data-listen="reload" hidden>重试</button><button type="button" data-listen="configure" hidden>选择音色</button>
          <section class="lp-listening-history" aria-label="最近练习" hidden><p data-listen="history-status" role="status"></p>
            <details class="listen-manage"><summary data-listen="manage-summary">练习记录</summary>
              <div class="listen-manage-list" data-listen="manage-list"></div>
            </details>
          </section>
          <p data-listen="draft-storage-status" role="status"></p>
          <button type="button" data-listen="draft-retry" hidden>再存一次</button>
          <button type="button" data-listen="draft-reload" hidden>用另一版</button>
          <section class="lp-listening-player" aria-label="听材料" hidden>
            <h2></h2>
            <div class="lp-player-meta"><span class="lp-player-time" data-listen="time">0:00</span><span class="lp-player-total" data-listen="total"></span><span class="lp-plays" data-listen="plays" aria-label="听了几遍"></span></div>
            <div class="lp-track" data-listen="track" tabindex="0" role="slider" aria-label="进度" aria-valuemin="0" aria-valuenow="0"></div>
            <audio preload="none" aria-label="听力材料"></audio>
            <div class="lp-player-row">
              <button type="button" data-listen="back" class="lp-listening-secondary" title="回退五秒">↶ 5 秒</button>
              <button type="button" class="lp-big-play" data-listen="big-play" aria-label="播放">▶</button>
              <button type="button" data-listen="replay" class="lp-listening-secondary" hidden>从头</button>
              <button type="button" class="lp-speed" data-listen="speed" aria-label="语速 1×">1×</button>
            </div>
            <div class="lp-player-foot">
              <button type="button" data-listen="questions" hidden>开始答题</button>
              <span class="lp-dots lp-qdots" data-listen="qdots" aria-hidden="true"></span>
            </div>
          </section>
          <form class="lp-listening-questions" aria-label="听力答题" hidden></form>
          <section class="lp-listening-review" aria-label="听力复盘" hidden></section>
        </div>
        <aside class="lp-listening-notes" hidden>
          <label for="lp-listening-notes">随心记</label>
          <textarea id="lp-listening-notes" aria-label="随心记" maxlength="20000" placeholder="想写什么就写什么" spellcheck="false"></textarea>
          <p data-listen="notes-storage-status" role="status"></p>
          <button type="button" data-listen="notes-retry" hidden>再存一次</button>
          <button type="button" data-listen="notes-reload" hidden>用另一版</button>
        </aside>
        </div>
      </section>`;

    const workbench = root.querySelector(".lp-listening");
    // 练习记录收进「⋯」
    workbench.querySelector('[data-listen="history-slot"]').replaceWith(workbench.querySelector(".lp-listening-history"));
    const more = workbench.querySelector(".lp-more");
    more.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && more.open) { ev.stopPropagation(); more.open = false; more.querySelector("summary").focus(); } });
    document.addEventListener("pointerdown", (ev) => { if (more.open && !more.contains(ev.target)) more.open = false; });
    const setup = workbench.querySelector(".lp-listening-setup");
    const progress = workbench.querySelector("progress");
    const steps = workbench.querySelector(".lp-listening-steps");
    const status = workbench.querySelector(".lp-listening-status");
    const player = workbench.querySelector(".lp-listening-player");
    const audio = player.querySelector("audio");
    const quiz = workbench.querySelector(".lp-listening-questions");
    const review = workbench.querySelector(".lp-listening-review");
    const notes = workbench.querySelector("#lp-listening-notes");
    const SPEEDS = [0.75, 1, 1.25];
    let speed = 1;
    const field = (name) => workbench.querySelector(`[data-listen="${name}"]`);
    const storage = window.LP.studyStorage;
    function storageMessage(kind, state, text) {
      field(kind + "-storage-status").dataset.state = state;
      field(kind + "-storage-status").textContent = text;
      field(kind + "-retry").hidden = state !== "error";
      field(kind + "-reload").hidden = state !== "conflict";
    }
    // One revision-aware queue per database record; browser storage is not a second owner.
    function record(read, write, apply, notify) {
      let value, revision, version = 0, savedVersion = 0, timer, inFlight, loading;
      let state = "loading";
      const report = (next, text) => { state = next; notify(next, text); };
      async function load(discard = false) {
        if (loading) return loading;
        const started = version;
        report("loading", "");
        loading = (async () => {
          try {
            if (!storage) throw new Error();
            await storage.ready();
            const result = await read();
            revision = result.revision;
            if (version === started && (discard || version === savedVersion)) {
              value = result.value;
              if (discard) savedVersion = version;
              apply(value);
            }
            report("ready", "");
          } catch { report("error", "没连上"); }
          finally { loading = null; }
        })();
        await loading;
        if (revision !== undefined && version !== savedVersion) schedule();
      }
      function schedule() {
        if (timer || state === "conflict" || state === "error") return;
        timer = setTimeout(() => { timer = null; void flush(); }, 700);
      }
      async function flush(retry = false) {
        clearTimeout(timer); timer = null;
        if (loading) await loading;
        if (inFlight) return inFlight;
        if ((state === "error" && !retry) || state === "conflict") return;
        if (revision === undefined) { await load(); if (revision === undefined) return; }
        if (version === savedVersion) return;
        const sent = version, payload = structuredClone(value);
        report("saving", "");
        inFlight = (async () => {
          try {
            const response = await write(payload, revision);
            revision = response.revision;
            savedVersion = sent;
            report("ready", "");            // 存上了不说话，只在没存上时说
          } catch (error) {
            report(error.status === 409 ? "conflict" : "error", error.status === 409 ? "别处改过了" : "没存上");
          } finally { inFlight = null; }
        })();
        await inFlight;
        if (version !== savedVersion) schedule();
      }
      return {
        load, flush,
        get value() { return value; },
        get dirty() { return version !== savedVersion; },
        get state() { return state; },
        set(next) {
          if (JSON.stringify(next) === JSON.stringify(value)) return;
          value = next; version += 1;
          if (state !== "error" && state !== "conflict") report("dirty", "");
          schedule();
        },
      };
    }
    const migrationStatus = element("p");
    migrationStatus.setAttribute("role", "status");
    workbench.querySelector(".lp-listening-history").append(migrationStatus);
    const showStorageStatus = () => {
      const current = storage?.getStatus();
      migrationStatus.textContent = current && ["warning", "unavailable"].includes(current.state) ? current.message : "";
      migrationStatus.hidden = !migrationStatus.textContent;
    };
    globalThis.addEventListener("lp:study-storage", showStorageStatus);
    showStorageStatus();
    const notesRecord = record(
      async () => { const result = await storage.getListeningNotes(); return { value: result.text, revision: result.revision }; },
      (text, revision) => storage.saveListeningNotes({ text, revision }),
      text => { notes.value = text || ""; },
      (state, text) => storageMessage("notes", state, text),
    );
    notes.addEventListener("input", () => notesRecord.set(notes.value));
    field("notes-retry").addEventListener("click", () => void notesRecord.flush(true));
    // 「用另一版」：把别处存的那一版拿过来，这里没存上的会被换掉
    const takeOther = () => window.LP.util.confirm({ title: "用另一版？", text: "这里没存上的会被换掉。", ok: "用另一版" });
    field("notes-reload").addEventListener("click", async () => { if (await takeOther()) void notesRecord.load(true); });
    void notesRecord.load();
    const language = field("language");
    const format = field("format");
    const difficulty = field("difficulty");
    const difficultyHelp = workbench.querySelector("#lp-listening-difficulty-help");
    const start = setup.querySelector('button[type="submit"]');
    let settings;
    let active;
    let busy = false;
    window.LP.scene?.provide('listening', () => ({ language: language.value }));
    let operation;
    let phase = 0;
    let clipEnd = null;
    let clipFrame;
    let historyVersion = 0;
    let historyCount = 0;
    let choosing = false;
    const draftRecords = new Map();
    let pendingSeek = null;
    let lastPositionSave = 0;
    let closeBox = null;          // { id, ready: Promise<精听那一块> }
    function draftRecord(id) {
      if (!draftRecords.has(id)) {
        draftRecords.set(id, record(
          async () => { const result = await storage.getListeningDraft(id); return { value: result.draft, revision: result.revision }; },
          (draft, revision) => storage.saveListeningDraft({ id, draft, revision }),
          () => {},
          (state, text) => { if (active?.id === id) storageMessage("draft", state, text); },
        ));
      }
      return draftRecords.get(id);
    }
    function saveDraft() {
      if (!active) return;
      const answers = [...quiz.querySelectorAll('input:checked')].map(input => [input.name, input.value]);
      draftRecord(active.id).set({ phase, answers, time: Math.floor(pendingSeek ?? audio.currentTime) });
    }
    field("draft-retry").addEventListener("click", () => { if (active) void draftRecord(active.id).flush(true); });
    field("draft-reload").addEventListener("click", async () => {
      if (!active || busy) return;
      const id = active.id, saved = draftRecord(id);
      if (!await takeOther() || active?.id !== id) return;
      await saved.load(true);
      if (active?.id !== id || saved.state !== "ready") return;
      const draft = saved.value;
      pendingSeek = Number.isFinite(draft?.time) ? draft.time : 0;
      audio.currentTime = pendingSeek;
      pendingSeek = null;
      if (phase === 3) {
        for (const input of quiz.querySelectorAll("input")) input.checked = Array.isArray(draft?.answers)
          && draft.answers.some(pair => Array.isArray(pair) && pair[0] === input.name && pair[1] === input.value);
      }
    });
    // 本地时间：今天只写时刻，今年写月/日
    function practiceTime(value) { return window.LP.util.shortDate(value) || "—"; }
    function sessionsSupported() { return settings?.capabilities?.listening_sessions === true; }
    async function refreshHistory() {
      const version = ++historyVersion;
      if (!sessionsSupported()) {
        field("history-status").textContent = "";
        return;
      }
      field("history-status").textContent = "";
      try {
        const response = await request("/practices?lang=" + encodeURIComponent(language.value) + "&limit=20");
        if (version !== historyVersion) return;
        const all = response.items || [];
        const items = all.filter(item => item.status !== "unreadable");
        historyCount = all.length;
        paintManage(all);
        workbench.querySelector('.lp-listening-history').hidden = phase !== 0 || !historyCount;
        unfinished = items.filter(item => item.status !== "graded");
        paintStart();
        field("history-status").textContent = '';
      } catch (error) {
        if (version === historyVersion) field("history-status").textContent = "没读出来";
      }
    }
    // 没听完的练习里，有和现在选的题型一样的（选「自动」时任何一段都算）：主按钮是「接着听」，接的就是那一段
    let unfinished = [];
    function pendingFor() {
      const name = format.selectedOptions[0]?.textContent;
      return unfinished.find(item => format.value === "auto" || item.format === name) || null;
    }
    function paintStart() {
      const pending = pendingFor();
      start.textContent = pending ? "接着听" : "开始听";
      field("fresh").hidden = !pending;
    }
    let recentKey = "";
    const LANG_TAG = { ja: "日", en: "EN", de: "DE", fr: "FR", zh: "中", ko: "韩" };
    function paintRecent(items) {
      const list = field("recent-list");
      // 内容没变就不重画（列表会被频繁刷新，别让行一直换新节点）
      const key = JSON.stringify(items.map((i) => [i.id, i.status, i.marks, i.count, i.format]));
      if (key === recentKey && list.childElementCount) return;
      recentKey = key;
      list.replaceChildren(...items.map((item) => {
        const li = element("li");
        const open = element("button", "", "lp-recent-row" + (item.status === "graded" ? "" : " pending"));
        open.type = "button";
        open.dataset.id = item.id;
        const dots = element("span", "", "lp-dots");
        const marks = Array.isArray(item.marks) ? item.marks : null;
        const total = marks ? marks.length : Math.max(0, Number(item.count) || 0);
        for (let i = 0; i < total; i += 1) dots.append(element("i", "", marks ? (marks[i] ? "ok" : "bad") : "open"));
        dots.setAttribute("aria-label", marks ? marks.filter(Boolean).length + " / " + marks.length : "没听完");
        const tag = element("span", LANG_TAG[item.language] || String(item.language || "").slice(0, 2).toUpperCase(), "lp-lang-tag");
        open.append(tag, element("strong", item.format || ""), dots, element("time", practiceTime(item.created_at)), element("span", item.status !== "graded" ? "▶" : "", "lp-recent-go"));
        if (item.preview) { const p = element("span", item.preview, "lp-recent-preview"); p.lang = item.language || ""; open.append(p); }
        open.addEventListener("click", () => {
          void resume(item.id);
        });
        li.append(open);
        return li;
      }));
      field("recent-list").closest(".lp-recent").hidden = !items.length;
    }
    // 这个月 + 卡上的两个小标：只画后端给了的项
    let homeTicket = 0;
    let practicesAll = [];
    // 题型格子：第一格「自动」，后面是当前语言的题型。格子=名字、说话人数（小人）、题数（空心方块）；
    // 练过的在右上角画累计 对/总。点格子=选中并保存安排（savePlan，和表单里「保存安排」同一个），开始仍按主按钮
    function paintFormats() {
      const box = field("formats");
      const options = [...format.options];
      if (!options.length) { box.replaceChildren(); return; }
      const meta = new Map((settings?.formats || []).filter((f) => f.language === language.value).map((f) => [f.id, f]));
      const tally = new Map();
      for (const p of practicesAll) {
        if (p.language !== language.value || !Array.isArray(p.marks)) continue;
        const t = tally.get(p.format) || { ok: 0, n: 0 };
        t.ok += p.marks.filter(Boolean).length; t.n += p.marks.length;
        tally.set(p.format, t);
      }
      box.replaceChildren(...options.map((option) => {
        const info = meta.get(option.value);
        const tile = element("button", "", "lp-format-tile" + (option.value === "auto" ? " auto" : ""));
        tile.type = "button";
        tile.dataset.format = option.value;
        tile.setAttribute("role", "radio");
        tile.setAttribute("aria-checked", String(option.value === format.value));
        tile.append(element("strong", option.textContent, "lp-format-name"));
        const marks = element("span", "", "lp-format-marks");
        if (info?.speakers) {
          const people = element("span", "", "lp-speakers");
          people.setAttribute("aria-label", info.speakers + " 人");
          for (let i = 0; i < info.speakers; i += 1) people.append(element("i"));
          marks.append(people);
        }
        if (info?.questions) {
          const q = element("span", "", "lp-dots");
          q.setAttribute("aria-label", info.questions + " 题");
          for (let i = 0; i < info.questions; i += 1) q.append(element("i", "", "open"));
          marks.append(q);
        }
        if (option.value === "auto") marks.append(element("span", "✦", "lp-auto-mark"));
        tile.append(marks);
        const t = tally.get(option.textContent);
        if (t?.n) {
          const stat = element("span", "", "lp-format-stat");
          const track = element("span", "", "lp-bar-track"), fill = element("span", "", "lp-bar-fill");
          fill.style.width = Math.round((t.ok / t.n) * 100) + "%";
          track.append(fill);
          stat.append(track, element("b", t.ok + "/" + t.n));
          tile.append(stat);
        }
        tile.addEventListener("click", () => {
          if (busy || format.value === option.value) return;
          format.value = option.value;
          readiness();
          box.querySelectorAll(".lp-format-tile").forEach((x) => x.setAttribute("aria-checked", String(x === tile)));
          void savePlan();
        });
        return tile;
      }));
      field("home").classList.toggle("no-recent", field("recent-list").closest(".lp-recent").hidden);
    }
    async function paintHome() {
      const mine = ++homeTicket;
      const lang = language.value;
      if (!lang) return;
      const get = (path) => fetch(path, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const [stats, advice, meta, all] = await Promise.all([
        get("/api/learning/stats?language=" + encodeURIComponent(lang) + "&days=30"),
        get("/api/learning/advice?language=" + encodeURIComponent(lang)),
        window.LP.util.loadTypes ? window.LP.util.loadTypes().then(() => get("/api/learning/settings")) : get("/api/learning/settings"),
        get(base + "/practices?limit=50"),
      ]);
      if (mine !== homeTicket) return;
      practicesAll = (all?.items || []).filter((i) => i.status !== "unreadable");
      paintRecent(practicesAll.slice(0, 8));
      paintFormats();
      const s = stats?.listening || {};
      const typeName = (key, t) => t?.label || window.LP.util.typeLabel?.("listening", key) || key;
      // 小标：最弱题型（难度建议在「今天」页，点开有依据、能采纳）
      const tags = field("tags");
      tags.replaceChildren();
      const weakAdvice = (advice?.weak_types || []).find((w) => w.skill === "listening");
      const typed = Object.entries(s.types || {}).filter(([, t]) => t && t.n > 0);
      const weakest = weakAdvice ? [weakAdvice.type, weakAdvice] : typed.length > 1 ? typed.reduce((a, b) => (b[1].accuracy < a[1].accuracy ? b : a)) : null;
      if (weakest && (weakest[1].accuracy ?? 1) < 1) tags.append(element("span", typeName(weakest[0], weakest[1]) + "最弱", "lp-tag weak"));
      // 这个月
      const body = field("month-body");
      const blocks = [];
      const pct = (v) => Math.round(v * 100) + "%";
      if (s.accuracy == null && !s.count) {
        const big = element("div", "", "lp-big-number");
        big.append(element("strong", "0"), element("span", "组"));
        blocks.push(big);
      }
      if (s.accuracy != null) {
        const big = element("div", "", "lp-big-number");
        big.append(element("strong", pct(s.accuracy)), element("span", "正确率"));
        if (s.count) big.append(element("small", s.count + " 组"));
        blocks.push(big);
      }
      if (s.dictation != null) {
        const big = element("div", "", "lp-big-number");
        big.append(element("strong", pct(s.dictation)), element("span", "听写"));
        blocks.push(big);
      }
      if (s.replays != null) {
        const big = element("div", "", "lp-big-number");
        big.append(element("strong", String(s.replays)), element("span", "回听"));
        blocks.push(big);
      }
      // 30 天：一天一格，练过就实心（越多越深，三档），今天描边
      const perDay = new Map();
      const dayKey = (d) => d.getFullYear() + "-" + (d.getMonth() + 1) + "-" + d.getDate();
      for (const p of practicesAll) { const d = window.LP.util.time?.(p.created_at); if (d) perDay.set(dayKey(d), (perDay.get(dayKey(d)) || 0) + 1); }
      let activity = null;
      {
        activity = element("div", "", "lp-activity");
        activity.setAttribute("aria-label", "30 天");
        const today = new Date();
        for (let i = 29; i >= 0; i -= 1) {
          const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
          const n = perDay.get(dayKey(d)) || 0;
          const cell = element("i", "", "l" + Math.min(3, n) + (i === 0 ? " today" : ""));
          cell.title = (d.getMonth() + 1) + "/" + d.getDate() + (n ? " · " + n : "");
          activity.append(cell);
        }
      }
      const bars = (title, rows, cls) => {
        if (!rows.length) return null;
        const box = element("div", "", "lp-bars " + cls);
        box.append(element("h4", title));
        for (const r of rows) {
          const line = element("div", "", "lp-bar");
          const track = element("span", "", "lp-bar-track");
          const fill = element("span", "", "lp-bar-fill");
          fill.style.width = r.value == null ? "0%" : Math.round(Math.max(0, Math.min(1, r.value)) * 100) + "%";
          track.append(fill);
          line.append(element("span", r.label, "lp-bar-label"), track, element("b", r.text || ""));
          if (r.value == null) line.classList.add("empty");
          box.append(line);
        }
        return box;
      };
      const numbers = element("div", "", "lp-month-numbers");
      numbers.append(...blocks);
      // 没数据时也列出这门语言的听力技能类型和三类错因，条是空的
      const allTypes = Object.entries(meta?.types?.listening || {}).filter(([key]) => (lang === "ja") === key.startsWith("jlpt_"));
      const typeRows = typed.length
        ? typed.sort((a, b) => a[1].accuracy - b[1].accuracy).map(([key, t]) => ({ label: typeName(key, t), value: t.accuracy, text: t.correct + "/" + t.n }))
        : allTypes.map(([key, label]) => ({ label, value: null }));
      const typeBars = bars("题型", typeRows, "types");
      const causeNames = meta?.causes || { not_heard: "没听清", not_understood: "没听懂", misjudged: "听懂了答错" };
      const causes = Object.entries(s.causes || {}).filter(([, n]) => n > 0);
      const causeTotal = causes.reduce((a, [, n]) => a + n, 0);
      const causeRows = causes.length
        ? causes.sort((a, b) => b[1] - a[1]).map(([key, n]) => ({ label: causeNames[key] || key, value: n / causeTotal, text: String(n) }))
        : Object.entries(causeNames).map(([, label]) => ({ label, value: null }));
      const causeBars = bars("错在哪", causeRows, "causes");
      body.replaceChildren(...[blocks.length ? numbers : null, activity, typeBars, causeBars].filter(Boolean));
      field("month").hidden = false;
      field("home").classList.toggle("no-recent", field("recent-list").closest(".lp-recent").hidden);
    }
    function size(bytes) {
      if (!Number.isFinite(bytes)) return "";
      return bytes >= 1048576 ? (bytes / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
    }
    // 练习记录管理：每条一个删除（删练习和它的答题草稿；错题本里的错题留着）
    function paintManage(items) {
      field("manage-summary").textContent = "练习记录 · " + items.length;
      field("manage-list").replaceChildren(...items.map(item => {
        const row = element("div");
        row.className = "listen-manage-row" + (item.status === "unreadable" ? " unreadable" : "");
        const name = element("strong", item.status === "unreadable" ? "坏了" : item.format || item.id);
        const meta = element("span", [item.status === "graded" ? "做完" : item.status === "unreadable" ? "" : "没做完", practiceTime(item.created_at), size(item.size_bytes)].filter(Boolean).join(" · "));
        const remove = window.LP.util.button("删除", async () => {
          const ok = await window.LP.util.confirm({ title: "删除这组练习？", text: "音频和答题进度一起删，错题本里的留着。", ok: "删除" });
          if (!ok) return;
          remove.disabled = true;
          try {
            const response = await fetch(base + "/practice/" + encodeURIComponent(item.id), { method: "DELETE" });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "没删掉");
            void LP.studyStorage.deleteListeningDraft(item.id).catch(() => {});
            draftRecords.delete(item.id);
            paintManage(items.filter(other => other !== item));
            void refreshHistory();
          } catch (error) { remove.disabled = false; field("history-status").textContent = error.message; }
        }, "row-delete");
        remove.setAttribute("aria-label", "删除 " + (item.format || "这组练习"));
        row.append(name, meta, remove);
        return row;
      }));
    }
    // ---- 进度：句子块带（/shape）；没有时间轴时退化成一条像素进度条 ----
    const track = field("track");
    let segments = [], shapeDuration = 0;
    function updateVoiceMute() {
      if (segments.some((seg) => seg.female === false && audio.currentTime >= seg.start && audio.currentTime < seg.end)) {
        audio.dataset.voiceMute = "1";
      } else delete audio.dataset.voiceMute;
    }
    let voiceFrame;
    function trackVoiceMute() {
      cancelAnimationFrame(voiceFrame);
      updateVoiceMute();
      if (!audio.paused && !audio.ended) voiceFrame = requestAnimationFrame(trackVoiceMute);
    }
    for (const event of ["play", "pause", "ended", "seeking", "seeked", "timeupdate", "emptied"]) {
      audio.addEventListener(event, trackVoiceMute);
    }
    const duration = () => (Number.isFinite(audio.duration) && audio.duration > 0 ? audio.duration : shapeDuration);
    function paintTrack() {
      const total = duration();
      const parts = segments.length ? segments : [{ start: 0, end: total || 1, speaker: "" }];
      track.classList.toggle("plain", !segments.length);
      track.replaceChildren(...parts.map((seg) => {
        const block = element("span", "", "lp-seg" + (seg.speaker === "B" ? " b" : ""));
        block.style.flexGrow = String(Math.max(0.05, (seg.end - seg.start) || 0.05));
        block.dataset.start = seg.start; block.dataset.end = seg.end;
        block.append(element("i"));
        return block;
      }));
      paintProgress();
    }
    function paintProgress() {
      const t = audio.currentTime || 0;
      for (const block of track.children) {
        const start = Number(block.dataset.start), end = Number(block.dataset.end) || duration() || 1;
        const f = Math.max(0, Math.min(1, (t - start) / Math.max(0.01, end - start)));
        block.firstChild.style.width = Math.round(f * 100) + "%";
        block.classList.toggle("now", t >= start && t < end && !audio.paused);
      }
      track.setAttribute("aria-valuemax", String(Math.round(duration())));
      track.setAttribute("aria-valuenow", String(Math.round(t)));
    }
    async function loadShape(id) {
      segments = []; shapeDuration = 0; updateVoiceMute(); paintTrack();
      try {
        const shape = await request("/practice/" + encodeURIComponent(id) + "/shape");
        if (active?.id !== id) return;
        segments = Array.isArray(shape.segments) ? shape.segments.filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start) : [];
        shapeDuration = Number(shape.duration) || 0;
        updateVoiceMute();
        if (shapeDuration && !(audio.duration > 0)) field("total").textContent = " / " + clockOf(shapeDuration);
      } catch { /* 老练习：普通进度条 */ }
      paintTrack();
    }
    function seekTo(time) {
      clipEnd = null;
      const total = duration();
      audio.currentTime = Math.max(0, total ? Math.min(time, total - 0.05) : time);
      paintProgress();
    }
    function timeAt(clientX) {
      const r = track.getBoundingClientRect();
      return Math.max(0, Math.min(1, (clientX - r.left) / Math.max(1, r.width))) * duration();
    }
    let dragging = false;
    track.addEventListener("pointerdown", (ev) => {
      dragging = true; track.setPointerCapture?.(ev.pointerId);
      const block = ev.target.closest(".lp-seg");
      // 点块 = 跳到那句开头；没有时间轴 = 点哪到哪
      seekTo(block && segments.length ? Number(block.dataset.start) : timeAt(ev.clientX));
    });
    track.addEventListener("pointermove", (ev) => { if (dragging) seekTo(timeAt(ev.clientX)); });
    track.addEventListener("pointerup", () => { dragging = false; });
    track.addEventListener("pointercancel", () => { dragging = false; });
    player.addEventListener("keydown", (ev) => {
      if (ev.target.closest("input, textarea, select")) return;
      if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); seekTo((audio.currentTime || 0) + (ev.key === "ArrowLeft" ? -5 : 5)); }
      if (ev.key === " " && ev.target === track) { ev.preventDefault(); bigPlay.click(); }
    });
    audio.addEventListener("timeupdate", paintProgress);
    audio.addEventListener("durationchange", () => { if (!segments.length) paintTrack(); else paintProgress(); });
    audio.addEventListener("play", paintProgress);
    audio.addEventListener("pause", paintProgress);
    // 这组几道题：空心小方块（和首页点阵同一种画法）
    function paintQuestionDots(count) {
      field("qdots").replaceChildren(...Array.from({ length: Math.max(0, Math.min(20, Number(count) || 0)) }, () => element("i", "", "open")));
    }
    // 语速：一个按钮循环三档；整段和逐句共用
    field("speed").addEventListener("click", () => {
      speed = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length];
      field("speed").textContent = speed + "×"; field("speed").setAttribute("aria-label", "语速 " + speed + "×");
      workbench.querySelectorAll("audio").forEach((a) => { a.playbackRate = speed; });
    });

    // 大播放键：播 / 停；从头放的每一遍记一次（POST /practice/{id}/play）
    const bigPlay = field("big-play");
    // 同一时间只响一个：放整段就停掉精听里的逐句
    const quietLines = (except) => workbench.querySelectorAll("audio").forEach((a) => { if (a !== except) a.pause(); });
    bigPlay.addEventListener("click", () => { if (audio.paused) { quietLines(audio); void audio.play().catch(() => notice("放不出来")); } else audio.pause(); });
    audio.addEventListener("play", () => {
      bigPlay.textContent = "❚❚"; bigPlay.setAttribute("aria-label", "暂停");
      if (active && clipEnd === null && audio.currentTime < 0.5) void request("/practice/" + encodeURIComponent(active.id) + "/play", {}).then((r) => paintPlays(r?.plays)).catch(() => {});
    });
    audio.addEventListener("pause", () => { bigPlay.textContent = "▶"; bigPlay.setAttribute("aria-label", "播放"); });

    // 交卷后先标错因（只给答错的题），点完才看对错和依据（docs/LEARNING.md 4.4）
    const CAUSES = [["not_heard", "≋", "没听清"], ["not_understood", "?", "没听懂"], ["misjudged", "✗", "听懂了答错"]];
    function askCauses(response, only = null) {
      const wrong = only || response.results.map((r, i) => (r.correct ? -1 : i)).filter((i) => i >= 0);
      if (!wrong.length) { showReview(response); return; }
      const picked = new Map();
      const box = element("section");
      box.className = "lp-causes";
      box.append(element("h2", response.score + " / " + response.count));
      for (const index of wrong) {
        const row = element("div");
        row.className = "lp-cause-row";
        row.append(element("strong", "第 " + (index + 1) + " 题"));
        const group = element("div");
        group.className = "lp-cause-choices";
        group.setAttribute("role", "radiogroup");
        for (const [id, glyph, label] of CAUSES) {
          const b = element("button");
          b.type = "button";
          b.className = "lp-cause";
          b.dataset.cause = id;
          b.setAttribute("role", "radio");
          b.setAttribute("aria-checked", "false");
          b.append(element("span", glyph), element("small", label));
          b.addEventListener("click", async () => {
            picked.set(index, id);
            group.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
            if (picked.size < wrong.length) return;
            box.querySelectorAll("button").forEach((x) => { x.disabled = true; });
            try {
              const result = await request("/practice/" + encodeURIComponent(active.id) + "/causes", { items: [...picked].map(([i, cause]) => ({ index: i, cause })) });
              // 后端合并保存并返回全部错题的当前状态；旧服务只回这次标的
              const merged = new Map((response.causes || []).map((c) => [c.index, c]));
              for (const c of result.items || []) if (c.cause) merged.set(c.index, c);
              response.causes = [...merged.values()];
            } catch (error) { notice(error.message); }
            showReview(response);
          });
          group.append(b);
        }
        row.append(group);
        box.append(row);
      }
      review.replaceChildren(box);
      review.hidden = false;
      quiz.hidden = true;
      move(4);
      box.querySelector("button")?.focus();
    }

    // 精听：逐句播放、点一句显示一句；系统挑的几句做听写（语速和整段共用）
    async function closeListening(id, language) {
      const box = element("section");
      box.className = "lp-close";
      const head = element("div");
      head.className = "lp-close-head";
      head.append(element("h3", "精听"));
      box.append(head);
      let data;
      try { data = await request("/practice/" + encodeURIComponent(id) + "/lines"); }
      catch (error) { box.append(element("p", error.message)); return box; }
      // 推荐听写：后端按句挑 {line, sentence}；旧服务只给段号
      const picks = new Set((data.dictation || []).map((p) => typeof p === "object" ? p.line + ":" + (p.sentence ?? "") : p + ":"));
      const list = element("ol");
      list.className = "lp-lines";
      const clipUrl = (line, sentence) => base + "/practice/" + encodeURIComponent(id) + "/lines/" + line + "/audio" + (sentence ? "?sentence=" + sentence : "");
      // 一个听写框，跟着「当前句」走：点哪句的播放键，哪句就是当前句
      const form = element("form", "", "lp-dictation");
      const input = element("input");
      input.lang = language; input.autocomplete = "off"; input.spellcheck = false;
      input.setAttribute("aria-label", "听写这一句");
      const check = element("button", "对一下");
      check.type = "submit";
      form.append(input, check);
      let current = null;
      function setCurrent(li) {
        if (current === li) return;
        current?.classList.remove("current");
        current = li;
        li.classList.add("current");
        li.append(form);
        input.value = li.dataset.typed || "";
      }
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!current || !input.value.trim()) { input.focus(); return; }
        const li = current, k = li.dataset.sentence ? Number(li.dataset.sentence) : null;
        li.dataset.typed = input.value.trim();
        check.disabled = true;
        try {
          const r = await request("/practice/" + encodeURIComponent(id) + "/dictation", { line: Number(li.dataset.line), ...(k ? { sentence: k } : {}), text: input.value.trim() });
          const marks = element("div", "", "lp-dictation-words");
          marks.append(...(r.words || []).map((w) => {
            const word = element("span", w.text);
            word.className = "lp-word " + w.status;
            word.lang = language;
            if (w.typed) word.title = w.typed;
            return word;
          }), element("b", r.correct + "/" + r.total));
          li.querySelector(".lp-dictation-words")?.remove();
          li.append(marks);
          const text = li.querySelector(".lp-line-text");
          if (r.reference) text.textContent = r.reference;
          text.classList.add("shown");
        } catch (error) { notice(error.message); }
        finally { check.disabled = false; }
      });
      let firstPick = null, firstRow = null;
      for (const line of data.lines || []) {
        const turn = element("li");
        turn.className = "lp-turn";
        if (line.speaker) turn.append(element("span", line.speaker, "lp-turn-speaker"));
        const parts = line.sentences?.length ? line.sentences : [{ sentence: null, text: line.text }];
        const rows = element("ol");
        rows.className = "lp-sentences";
        for (const part of parts) {
          const k = part.sentence ?? null;
          const picked = picks.has(line.line + ":" + (k ?? "")) || (parts.length === 1 && picks.has(line.line + ":"));
          const li = element("li");
          li.className = "lp-line" + (picked ? " dictation" : "");
          li.dataset.line = line.line;
          if (k) li.dataset.sentence = k;
          const audio = element("audio");
          if (line.female === false) audio.dataset.voiceMute = "1";
          audio.preload = "none";
          audio.src = clipUrl(line.line, k);
          const play = element("button", "▶");
          play.type = "button";
          play.className = "lp-line-play";
          play.setAttribute("aria-label", "播放");
          play.addEventListener("click", () => { setCurrent(li); quietLines(audio); audio.playbackRate = speed; audio.currentTime = 0; void audio.play().catch(() => notice("放不出来")); });
          const text = element("button", part.text || "");
          text.type = "button";
          text.className = "lp-line-text";
          text.lang = language;
          text.addEventListener("click", () => text.classList.toggle("shown"));
          li.append(play, audio, text);
          if (picked && !firstPick) firstPick = li;
          if (!firstRow) firstRow = li;
          rows.append(li);
        }
        turn.append(rows);
        list.append(turn);
      }
      if (firstPick || firstRow) setCurrent(firstPick || firstRow);
      box.append(list, window.LP.util.nextActions("listening"));
      return box;
    }

    function renderQuestions(response, draft) {
      quiz.replaceChildren(...response.questions.map((item, index) => questionMarkup(item, index, active.language)));
      for (const input of quiz.querySelectorAll("input")) {
        input.checked = Array.isArray(draft?.answers) && draft.answers.some(pair => Array.isArray(pair) && pair[0] === input.name && pair[1] === input.value);
      }
      const submit = element("button", "批改");
      submit.type = "submit";
      quiz.append(submit);
      quiz.hidden = false;
      move(3);
    }
    function activate(item, draft) {
      reset();
      operation = new AbortController();
      active = item;
      const saved = draftRecord(item.id);
      storageMessage("draft", saved.state, saved.state === "error" ? "没存上" : "");
      player.querySelector("h2").textContent = item.format + (item.difficulty_label ? ` · ${item.difficulty_label}练习` : "");
      pendingSeek = Number.isFinite(draft?.time) ? Math.max(0, draft.time) : null;
      audio.src = base + "/practice/" + encodeURIComponent(item.id) + "/audio";
      audio.playbackRate = speed;
      paintQuestionDots(item.count);
      void loadShape(item.id);
      player.hidden = false;
      move(draft?.phase >= 2 ? 2 : 1);
    }
    async function resume(id) {
      if (busy || !sessionsSupported() || !id) return;
      saveDraft();
      busy = true;
      readiness();
      const controller = new AbortController();
      operation?.abort();
      operation = controller;
      notice("");
      try {
        const item = await request("/practice/" + encodeURIComponent(id), undefined, controller.signal);
        const saved = draftRecord(id);
        if (!saved.dirty) await saved.load();
        const draft = saved.value;
        const questions = !item.receipt && draft?.phase >= 3
          ? await request("/practice/" + encodeURIComponent(id) + "/questions", undefined, controller.signal) : null;
        if (operation !== controller) return;
        activate(item, draft);
        if (item.receipt) {
          const receipt = { ...item.receipt };
          const marks = Array.isArray(item.causes?.items) ? item.causes.items : Array.isArray(item.causes) ? item.causes : null;
          if (marks) {
            receipt.causes = marks.filter((c) => c.cause);
            const unmarked = marks.filter((c) => c.cause == null).map((c) => c.index);
            if (unmarked.length) askCauses(receipt, unmarked); else showReview(receipt);
          } else showReview(receipt);
        }
        else if (questions) renderQuestions(questions, draft);
        notice("");
      } catch (error) { if (operation === controller) notice("没打开"); }
      finally { busy = false; readiness(); }
    }

    function renderLanguages(preferred = language.value) {
      const items = window.LP.languages?.list();
      if (!items?.length) return;
      language.replaceChildren(...items.map(({ tag, label }) => new Option(label, tag)));
      language.value = items.some(item => item.tag === preferred) ? preferred : items[0].tag;
    }
    renderLanguages(window.LP.preferences?.get("listeningLanguage"));

    stages.forEach((name) => steps.append(element("li", name)));

    function move(index) {
      phase = index;
      choosing = false;
      workbench.classList.remove('listening-choosing');
      setup.hidden = index > 0;
      field("new-practice").hidden = index === 0;
      workbench.querySelector('.lp-listening-stage').hidden = index === 0;
      workbench.querySelector('.lp-listening-history').hidden = index > 0 || !historyCount;
      field("home").hidden = index > 0;
      workbench.classList.toggle("in-practice", index > 0);
      if (index === 0) void paintHome();
      progress.value = index;
      progress.setAttribute("aria-valuetext", stages[index]);
      player.classList.toggle("blind", index === 1 || index === 2);
      field("questions").hidden = index !== 2;
      field("replay").hidden = index < 2;
      [...steps.children].forEach((step, offset) => {
        step.classList.toggle("done", offset < index);
        if (offset === index) step.setAttribute("aria-current", "step");
        else step.removeAttribute("aria-current");
      });
    }

    function notice(text) {
      status.textContent = text;
    }

    function readiness() {
      language.disabled = busy;
      const available = settings?.synthesis?.[language.value] === true;
      start.disabled = busy || !available;
      difficulty.disabled = busy || !supportsDifficulty();
      format.disabled = busy;
      field("topic").disabled = busy;
      field("reload").hidden = busy || available;
      field('configure').hidden = !settings || available;
      paintDial();
      paintStart();
      // 只写选定了的：题型、难度都是自动时，这一行是空的
      const levelLabel = difficulty.value === 'default' ? '' : difficulty.selectedOptions[0]?.textContent;
      field('plan-detail').textContent = [format.selectedOptions[0]?.textContent, levelLabel, field('topic').value]
        .filter((text) => text && text !== '自动').join(' · ');
    }

    // 语言拨片：和主聊天的拨片同一种画法；拨一下 = 换语言
    function paintDial() {
      const dial = field("dial");
      // 只列能出声的语言（配了音色的）；当前选中的那门即使没配也留着，免得拨片上没有选中项
      const voiced = settings?.synthesis;
      const items = [...language.options].filter((option) => !voiced || voiced[option.value] === true || option.value === language.value);
      dial.replaceChildren(...items.map((option) => {
        const b = element("button", option.textContent, "lp-dial-opt");
        b.type = "button"; b.lang = option.value;
        b.setAttribute("role", "radio");
        b.setAttribute("aria-checked", String(option.value === language.value));
        b.disabled = busy;
        b.addEventListener("click", () => {
          if (option.value === language.value) return;
          language.value = option.value;
          language.dispatchEvent(new Event("change"));
        });
        return b;
      }));
    }
    function pickFormats() {
      const auto = element("option", "自动");
      auto.value = "auto";
      format.replaceChildren(auto);
      for (const item of settings?.formats || []) {
        if (item.language !== language.value) continue;
        const option = element("option", item.label);
        option.value = item.id;
        format.append(option);
      }
      const saved = settings?.plans?.[language.value]?.format;
      if ([...format.options].some(item => item.value === saved)) format.value = saved;
      field('topic').value = settings?.plans?.[language.value]?.topic || '';
      paintFormats();
    }

    function supportsDifficulty() {
      return settings?.capabilities?.practice_difficulty === true
        && Array.isArray(settings.difficulties) && settings.difficulties.some(item => item.id === "default");
    }

    function pickDifficulty() {
      const supported = supportsDifficulty();
      const items = supported ? settings.difficulties : [{ id: "default", label: "自动" }];
      // 「default」一律叫「自动」（旧服务叫它「跟随课程」；听力页是自由练习，不跟课）
      difficulty.replaceChildren(...items.map(item => new Option(item.id === "default" ? "自动" : item.label, item.id)));
      let saved;
      try { saved = localStorage.getItem(difficultyKey + language.value); } catch { /* Optional preference. */ }
      saved = settings?.plans?.[language.value]?.difficulty || saved;
      difficulty.value = supported && items.some(item => item.id === saved) ? saved : "default";
      difficultyHelp.textContent = "";
      difficulty.disabled = busy || !supported;
    }

    async function reload() {
      field("reload").disabled = true;
      notice("…");
      try {
        settings = await request("/options");
        notice("");
        pickFormats();
        pickDifficulty();
      } catch (error) {
        settings = undefined;
        pickDifficulty();
        notice(error.message);
      } finally {
        field("reload").disabled = false;
        readiness();
        void refreshHistory();
      }
    }
    document.addEventListener('lp:languages', () => {
      renderLanguages();
      void reload();
    });
    globalThis.addEventListener('lp:listening-settings', () => void reload());

    function reset() {
      saveDraft();
      pendingSeek = null;
      operation?.abort();
      operation = undefined;
      active = undefined;
      closeBox = null;
      busy = false;
      clipEnd = null;
      quietLines(null);
      segments = [];
      delete audio.dataset.voiceMute;
      audio.removeAttribute("src");
      audio.load();
      field("questions").hidden = true;
      player.hidden = true;
      quiz.hidden = true;
      quiz.replaceChildren();
      review.hidden = true;
      review.replaceChildren();
      move(0);
    }

    async function prepare(event) {
      event.preventDefault();
      if (busy || start.disabled) return;
      const pending = event.fresh ? null : pendingFor();
      if (pending) { await resume(pending.id); return; }
      saveDraft();
      const controller = new AbortController();
      operation?.abort();
      operation = controller;
      busy = true;
      readiness();
      notice("…");
      try {
        const item = await request("/practice", {
          language: language.value,
          format: format.value,
          topic: field("topic").value.trim(),
          ...(supportsDifficulty() ? { difficulty: difficulty.value } : {}),
        }, controller.signal);
        if (operation !== controller) return;
        await draftRecord(item.id).load();
        if (operation !== controller) return;
        activate(item);
        notice("");
        saveDraft();
        void refreshHistory();
        busy = false;
        readiness();
        audio.focus();
      } catch (error) {
        if (operation === controller) { notice(error.message); if (phase > 0) chooseNew(false); }
      } finally {
        if (operation === controller) {
          busy = false;
          readiness();
        }
      }
    }

    function questionMarkup(item, index, lang) {
      const question = element("fieldset");
      question.lang = lang;
      question.append(element("legend", `${index + 1}. ${item.prompt}`));
      item.choices.forEach((choice, choiceIndex) => {
        const label = element("label");
        const radio = element("input");
        radio.type = "radio";
        radio.name = `question-${index}`;
        radio.value = choiceIndex;
        radio.required = true;
        label.append(radio, element("span", choice));
        question.append(label);
      });
      return question;
    }

    async function revealQuestions() {
      if (!active || busy || phase !== 2) return;
      busy = true;
      field("questions").disabled = true;
      readiness();
      const controller = operation;
      try {
        const response = await request("/practice/" + encodeURIComponent(active.id) + "/questions", undefined, controller.signal);
        if (operation !== controller) return;
        renderQuestions(response, draftRecord(active.id).value);
        saveDraft();
        notice("");
        quiz.querySelector("input")?.focus();
      } catch (error) {
        if (operation === controller) notice(error.message);
      } finally {
        if (operation === controller) {
          busy = false;
          readiness();
          field("questions").disabled = false;
        }
      }
    }

    function showReview(response) {
      void window.LP.util.loadTypes?.().then(() => review.querySelectorAll(".lp-type-tag").forEach((tag) => { tag.textContent = window.LP.util.typeLabel("listening", tag.dataset.skill); }));
      const score = element("h2", `${response.score} / ${response.count} · ${response.title}`);
      const saved = [];
      if (response.saved_errors) {
        const row = element("div", "", "lp-saved-row");
        row.append(element("p", `${response.saved_errors} 题进了错题本`));
        if (window.LP.appShell) {
          const open = element("button", "查看错题");
          open.type = "button";
          open.addEventListener("click", () => window.LP.appShell.openMistakes("listening", active.language));
          row.append(open);
        }
        saved.push(row);
      }
      const results = response.results.map((item, index) => {
        const result = element("article");
        const heading = element("h3", `${index + 1}. ${item.correct ? "✓" : "✗"}`);
        if (item.skill) { const tag = element("span", window.LP.util.typeLabel("listening", item.skill), "lp-type-tag"); tag.dataset.skill = item.skill; heading.append(tag); }
        const question = element("p", item.prompt);
        question.lang = active.language;
        const answer = element("p", "✓ " + item.choices[item.answer], "lp-answer");
        answer.lang = active.language;
        result.append(heading, question, answer, element("p", item.explanation));
        for (const line of item.evidence) {
          const quote = element("blockquote", `${line.speaker} · ${line.text}`);
          quote.lang = active.language;
          const playback = clipButton(response.clips?.[line.line - 1]);
          if (playback) quote.append(playback);
          result.append(quote);
        }
        return result;
      });
      const transcript = element("details");
      transcript.append(element("summary", "原文"));
      for (const [index, line] of response.script.entries()) {
        const paragraph = element("p", `${line.speaker} · ${line.text}`);
        paragraph.lang = active.language;
        const playback = clipButton(response.clips?.[index]);
        if (playback) paragraph.append(playback);
        transcript.append(paragraph);
      }
      const causeLabel = Object.fromEntries(CAUSES.map(([id, glyph, label]) => [id, glyph + " " + label]));
      for (const c of response.causes || []) {
        const target = results[c.index];
        if (target && c.cause) {
          const tag = element("button", causeLabel[c.cause] || c.cause);
          tag.type = "button"; tag.className = "lp-cause-tag " + c.cause; tag.title = "改错因";
          tag.addEventListener("click", () => askCauses(response, [c.index]));
          target.querySelector("h3")?.append(tag);
        }
      }
      review.replaceChildren(score, ...saved, ...results, transcript);
      // 精听做过的听写留着：同一段练习只建一次，改错因重画复盘时把原来那块放回去
      if (active) {
        const id = active.id;
        if (closeBox?.id !== id) closeBox = { id, ready: closeListening(id, active.language) };
        void closeBox.ready.then((box) => { if (review.contains(score) && active?.id === id) (saved.at(-1) || score).after(box); });
      }
      review.hidden = false;
      quiz.hidden = true;
      move(4);
      saveDraft();
      score.tabIndex = -1;
      score.focus();
    }

    function clipButton(clip) {
      if (!clip || !Number.isFinite(clip.start) || !Number.isFinite(clip.end) || clip.end <= clip.start) return null;
      const button = element("button", "▶ 听这一句");
      button.type = "button";
      button.className = "lp-listening-secondary lp-listening-clip";
      button.addEventListener("click", () => {
        cancelAnimationFrame(clipFrame);
        quietLines(audio);
        audio.currentTime = clip.start;
        clipEnd = clip.end;
        audio.play().then(trackClip).catch(() => {
          clipEnd = null;
          notice("放不出来");
        });
      });
      return button;
    }

    function trackClip() {
      if (clipEnd === null || audio.paused) return;
      if (audio.currentTime >= clipEnd) {
        clipEnd = null;
        audio.pause();
      } else clipFrame = requestAnimationFrame(trackClip);
    }

    async function grade(event) {
      event.preventDefault();
      if (!active || busy || phase !== 3) return;
      const answers = new FormData(quiz);
      const selections = Array.from({ length: active.count }, (_, index) => answers.get(`question-${index}`));
      if (selections.some((answer) => answer === null)) return;
      const controller = operation;
      const submit = quiz.querySelector("button");
      submit.disabled = true;
      busy = true;
      readiness();
      try {
        const response = await request("/practice/" + encodeURIComponent(active.id) + "/grade", {
          selections: selections.map(Number),
        }, controller.signal);
        if (operation !== controller) return;
        window.LP.jine?.refreshPending?.();
        askCauses(response);
        notice("");
        void refreshHistory();
      } catch (error) {
        if (operation === controller) notice(error.message);
      } finally {
        if (operation === controller) {
          submit.disabled = false;
          busy = false;
          readiness();
        }
      }
    }

    language.addEventListener("change", () => {
      saveDraft();
      void refreshHistory();
      pickFormats();
      pickDifficulty();
      notice("");
      readiness();
      void paintHome();
    });
    setup.addEventListener("submit", prepare);
    format.addEventListener("change", () => { readiness(); paintFormats(); });
    field("fresh").addEventListener("click", () => { more.open = false; void prepare({ preventDefault() {}, fresh: true }); });
    start.textContent = "开始听";
    field('edit-plan').onclick = () => { more.open = false; field('plan-fields').hidden = !field('plan-fields').hidden; };
    field('ask-plan').onclick = () => window.LP.workspaceAgent.prefill('帮我调整' + (language.selectedOptions[0]?.textContent || '') + '的听力安排。当前是' + field('plan-detail').textContent + '。');
    // 保存安排：表单里的按钮、点题型格子、聊天里的开练都走这里
    async function savePlan() {
      const button = field('save-plan'); button.disabled = true;
      try {
        const plan = await request('/plans/' + encodeURIComponent(language.value), {format: format.value, difficulty: difficulty.value, topic: field('topic').value.trim()});
        settings ||= {};
        settings.plans ||= {}; settings.plans[language.value] = plan;
        field('plan-fields').hidden = true; notice(''); readiness(); paintFormats();
      } catch (error) { notice(error.message); } finally { button.disabled = false; }
    }
    field('save-plan').onclick = () => void savePlan();
    function chooseNew(value) {
      choosing = value; workbench.classList.toggle('listening-choosing', value);
      setup.hidden = phase > 0 && !value;
      field("home").hidden = phase > 0 && !value;
      if (value) void paintHome();
      field('new-practice').textContent = value ? '返回练习' : '换一段';
    }
    field('new-practice').onclick = () => { saveDraft(); audio.pause(); chooseNew(!choosing); notice(''); };
    field('configure').onclick = () => window.LP.settings.open('listen');
    field('notes-toggle').onclick = () => { const panel = workbench.querySelector('.lp-listening-notes'); panel.hidden = !panel.hidden; field('notes-toggle').setAttribute('aria-pressed', String(!panel.hidden)); };
    quiz.addEventListener("change", saveDraft);
    const flushStorage = () => {
      saveDraft();
      void notesRecord.flush();
      for (const saved of draftRecords.values()) void saved.flush();
    };
    globalThis.addEventListener("pagehide", flushStorage);
    globalThis.addEventListener("beforeunload", event => {
      saveDraft();
      if (notesRecord.dirty || [...draftRecords.values()].some(saved => saved.dirty)) {
        event.preventDefault(); event.returnValue = "";
      }
    });
    const clockOf = (t) => (Number.isFinite(t) ? Math.floor(t / 60) + ":" + String(Math.floor(t % 60)).padStart(2, "0") : "");
    function paintPlays(n) {
      const box = field("plays");
      box.replaceChildren(...Array.from({ length: Math.max(0, Math.min(12, Number(n) || 0)) }, () => element("i", "")));
    }
    audio.addEventListener("timeupdate", () => { field("time").textContent = clockOf(audio.currentTime); });
    audio.addEventListener("durationchange", () => { field("total").textContent = Number.isFinite(audio.duration) ? " / " + clockOf(audio.duration) : ""; });
    audio.addEventListener("emptied", () => { field("time").textContent = "0:00"; field("total").textContent = ""; paintPlays(0); });
    audio.addEventListener("timeupdate", () => {
      if (Date.now() - lastPositionSave >= 5000) { lastPositionSave = Date.now(); saveDraft(); }
    });
    audio.addEventListener("loadedmetadata", () => {
      if (pendingSeek !== null) {
        audio.currentTime = Number.isFinite(audio.duration) ? Math.min(pendingSeek, audio.duration) : pendingSeek;
        pendingSeek = null;
      }
    });
    difficulty.addEventListener("change", () => {
      if (!supportsDifficulty() || busy) return;
      try { localStorage.setItem(difficultyKey + language.value, difficulty.value); } catch { /* Keep selection for this visit. */ }
      saveDraft();
      notice("");
      readiness();
    });
    field("reload").addEventListener("click", reload);
    field("questions").addEventListener("click", revealQuestions);
    field("back").addEventListener("click", () => {
      clipEnd = null;
      audio.currentTime = Math.max(0, audio.currentTime - 5);
    });
    field("replay").addEventListener("click", () => {
      clipEnd = null;
      audio.currentTime = 0;
      audio.play().catch(() => notice("放不出来"));
    });
    quiz.addEventListener("submit", grade);
    audio.addEventListener("ended", () => {
      clipEnd = null;
      if (phase === 1) move(2);
      saveDraft();
    });
    audio.addEventListener("pause", () => { clipEnd = null; saveDraft(); if (active) void draftRecord(active.id).flush(); });
    audio.addEventListener("error", () => {
      if (!player.hidden && audio.hasAttribute("src")) notice("放不出来");
    });
    // 离开这一页、窗口藏起来：整段和逐句都停
    const stopHidden = () => { if (document.hidden || !root.getClientRects().length) quietLines(null); };
    document.addEventListener("visibilitychange", stopHidden);
    new MutationObserver(stopHidden).observe(root, { attributes: true, attributeFilter: ["class", "hidden"] });
    move(0);
    const initialSettings = reload();
    startFromAction = async ({ format: requestedFormat } = {}) => {
      await initialSettings;
      const profile = settings?.formats?.find(item => item.id === requestedFormat);
      const label = profile?.label;
      if (busy) return { ok: false, label };
      // 正在练的就是要的题型（或没指定题型）：不打断；要的是别的题型：换成那一种
      if (active && (!requestedFormat || active.format === label)) return { ok: true, label: active.format };
      if (requestedFormat) {
        if (!profile) return { ok: false, label };
        if (language.value !== profile.language) {
          language.value = profile.language;
          language.dispatchEvent(new Event('change'));
        }
        if (![...format.options].some(option => option.value === requestedFormat)) return { ok: false, label };
        if (format.value !== requestedFormat) {
          format.value = requestedFormat;
          readiness(); paintFormats();
          await savePlan();
        }
      }
      if (start.disabled) return { ok: false, label };
      await prepare({ preventDefault() {} });     // 有同一题型没听完的，接着那一段
      return { ok: Boolean(active) && (!label || active.format === label), label: active?.format || label };
    };
  }

  window.LP ||= {};
  window.LP.listening = { mount, start: (options) => startFromAction ? startFromAction(options) : Promise.resolve({ ok: false }) };
})();
