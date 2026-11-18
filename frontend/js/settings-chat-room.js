/* settings-chat-room.js — 设置 › 角色 › 聊天安排（docs/MAIN-CHAT.md 1.1）。
   主人设一个；副人设各自的出现时机（总在 / 时段 / 关键词）和插话概率；趣味模式的语言池。
   改了就存：PUT /api/chat/main 只带改动的字段。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const TIMING = [['always', '总在'], ['time', '时段'], ['keyword', '关键词']];

  function avatar(p, cls = '') {
    const box = el('span', '', 'room-ava ' + cls);
    if (p?.avatar_url) { const img = el('img'); img.src = p.avatar_url; img.alt = ''; box.append(img); }
    else if (p?.name?.startsWith('糖糖')) { const img = el('img'); img.src = 'assets/avatars/ame-head.png'; img.alt = ''; box.append(img); }
    else { box.classList.add('lang-' + (p?.language || 'x')); box.textContent = Array.from(p?.name || '?')[0]; }
    return box;
  }

  function mount(root) {
    let main = null;
    let saveTimer = null;
    let queued = {};
    let selfRefresh = false;

    root.classList.add('settings-block', 'room');
    root.innerHTML = `
      <h2 class="settings-block-title">聊天安排</h2>
      <div class="room-line"><label class="room-label" for="room-user-name">她怎么叫你</label><input id="room-user-name" type="text" placeholder="ピ" maxlength="24"></div>
      <div class="room-line"><span class="room-label">主角色</span><div class="room-primary" role="radiogroup" aria-label="主角色"></div></div>
      <details class="room-more" data-room-more><summary>其他角色与趣味模式</summary>
      <div class="room-line room-line-chime"><span class="room-label">主角色插话</span><label class="room-chime room-primary-chime"><input type="range" min="0" max="100" step="5" aria-label="主角色插话概率"><output></output></label></div>
      <div class="room-line room-line-top"><span class="room-label">其他角色</span><div class="room-guests"></div></div>
      <div class="room-line"><span class="room-label">趣味模式</span><div class="room-pool" role="group" aria-label="趣味模式的语言"></div></div>
      </details>
      <p class="room-notice" role="status"></p>`;
    const $ = (sel) => root.querySelector(sel);
    const notice = (text, tone = '') => { const p = $('.room-notice'); p.textContent = text || ''; p.dataset.tone = tone; };

    const userName = $('#room-user-name');
    let storedName = '';
    async function saveName() {
      const value = userName.value.trim();
      userName.value = value;
      if (value === storedName) return;
      try {
        const settings = await LP.api.putSettings({ user_name: value });
        storedName = settings.user_name || '';
        userName.value = storedName;
        notice('');
      } catch (error) { notice(LP.util.message(error), 'bad'); }
    }
    userName.onblur = saveName;
    userName.onkeydown = (event) => {
      if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); userName.blur(); }
    };

    function save(patch, { soon = false } = {}) {
      Object.assign(main, patch);
      Object.assign(queued, patch);
      clearTimeout(saveTimer);
      saveTimer = setTimeout(flush, soon ? 500 : 0);
    }
    async function flush() {
      const patch = queued; queued = {};
      if (!Object.keys(patch).length) return;
      try {
        const next = await LP.api.putMainChat(patch);
        if (next && 'primary_id' in next) main = { ...main, ...next };
        notice('');
        LP.util.tick($('.settings-block-title'), true);
        selfRefresh = true;   // 主聊天重读完会发 lp:chat-main（顶栏跟着重画）；这一次是自己改的，不用重画这一块
        try { await LP.jine?.refreshMain?.(); } finally { selfRefresh = false; }
      } catch (error) { notice(LP.util.message(error), 'bad'); await load(); }
    }

    function paint() {
      const personas = LP.state.personas;
      // 主人设：头像一排，点哪个就是谁
      $('.room-primary').replaceChildren(...personas.map((p) => {
        const b = button('', () => { if (p.id !== main.primary_id) { save({ primary_id: p.id, guests: main.guests.filter((g) => g.persona_id !== p.id) }); paint(); } }, 'room-pick');
        b.append(avatar(p), el('span', p.name));
        b.setAttribute('role', 'radio');
        b.setAttribute('aria-checked', String(p.id === main.primary_id));
        return b;
      }));
      const pc = root.querySelector('.room-primary-chime input'), pco = root.querySelector('.room-primary-chime output');
      pc.value = main.primary_chime ?? 25; pco.textContent = pc.value + '%';
      pc.oninput = () => { pco.textContent = pc.value + '%'; };
      pc.onchange = () => save({ primary_chime: Number(pc.value) }, { soon: true });
      // 副人设：除主人设外每个人一行
      const others = personas.filter((p) => p.id !== main.primary_id);
      $('.room-guests').replaceChildren(...(others.length ? others.map(guestRow) : [el('span', '—', 'room-empty')]));
      // 语言池：点亮的语言会被骰子抽到
      const pool = new Set(main.fun_languages || []);
      $('.room-pool').replaceChildren(...LP.languages.list().map((l) => {
        const b = button(l.label, () => {
          const next = new Set(pool);
          if (next.has(l.tag)) { if (next.size === 1) return; next.delete(l.tag); } else next.add(l.tag);
          save({ fun_languages: [...next] }); paint();
        }, 'room-chip');
        b.lang = l.tag;
        b.setAttribute('aria-pressed', String(pool.has(l.tag)));
        return b;
      }), el('span', '', 'room-dice' + (main.fun ? ' on' : '')));
    }

    function guestRow(p) {
      const guest = main.guests.find((g) => g.persona_id === p.id);
      const g = guest || { persona_id: p.id, enabled: false, rule: { type: 'always' }, chime: 25 };
      const commit = (soon) => {
        const list = main.guests.filter((x) => x.persona_id !== p.id);
        save({ guests: [...list, g] }, { soon });
      };
      const row = el('div', '', 'room-guest' + (g.enabled ? '' : ' off'));
      const head = el('div', '', 'room-guest-head');
      const toggle = el('input');
      toggle.type = 'checkbox'; toggle.setAttribute('role', 'switch');
      toggle.checked = Boolean(g.enabled);
      toggle.setAttribute('aria-label', p.name + ' 出现在主聊天');
      toggle.onchange = () => { g.enabled = toggle.checked; row.classList.toggle('off', !g.enabled); commit(); };
      head.append(avatar(p, 'sm'), el('strong', p.name), toggle);
      row.append(head);

      const body = el('div', '', 'room-guest-body');
      // 出现时机：分段开关 + 对应的小输入
      const seg = el('div', '', 'room-seg');
      seg.setAttribute('role', 'radiogroup');
      seg.setAttribute('aria-label', p.name + ' 什么时候在');
      const extra = el('div', '', 'room-rule');
      const paintRule = () => {
        seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.type === g.rule.type)));
        extra.replaceChildren();
        if (g.rule.type === 'time') {
          const from = el('input'); from.type = 'time'; from.value = g.rule.start || '22:00'; from.setAttribute('aria-label', '从');
          const to = el('input'); to.type = 'time'; to.value = g.rule.end || '02:00'; to.setAttribute('aria-label', '到');
          const update = () => { g.rule = { type: 'time', start: from.value, end: to.value }; commit(true); };
          from.onchange = to.onchange = update;
          extra.append(from, el('span', '→', 'room-arrow'), to);
        } else if (g.rule.type === 'keyword') {
          const box = el('div', '', 'lore-tags');
          const input = el('input', '', 'lore-tag-input');
          input.placeholder = '回车添加';
          input.setAttribute('aria-label', p.name + ' 的关键词');
          const words = [...(g.rule.keywords || [])];
          const paintWords = () => box.replaceChildren(...words.map((w, i) => {
            const chip = el('span', '', 'tag-chip');
            chip.append(el('span', w), button('×', () => {
              words.splice(i, 1);
              // 删光了：退回「总在」并存上（不然界面空着、后端还留着旧词）
              if (!words.length) { g.rule = { type: 'always' }; commit(); paintRule(); return; }
              g.rule = { type: 'keyword', keywords: [...words] }; commit(); paintWords();
            }, 'rm'));
            return chip;
          }), input);
          // 刚切到「关键词」一个词都没写就走开：退回原来的规则（关键词规则要写了第一个词才存）
          input.addEventListener('blur', () => { if (!words.length && keywordFrom) { g.rule = keywordFrom; keywordFrom = null; paintRule(); } });
          input.addEventListener('keydown', (ev) => {
            if (ev.key !== 'Enter' || ev.isComposing) return;
            ev.preventDefault();
            const parts = input.value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);
            if (!parts.length) return;
            for (const w of parts) if (!words.includes(w)) words.push(w);
            input.value = '';
            g.rule = { type: 'keyword', keywords: [...words] };
            keywordFrom = null;
            commit(); paintWords(); input.focus();
          });
          paintWords();
          extra.append(box);
        }
      };
      let keywordFrom = null;   // 切到「关键词」之前的规则（还没写词时退回用）
      for (const [type, label] of TIMING) {
        const b = button(label, () => {
          if (g.rule.type === type) return;
          keywordFrom = type === 'keyword' ? g.rule : null;
          g.rule = type === 'time' ? { type, start: '22:00', end: '02:00' } : type === 'keyword' ? { type, keywords: [] } : { type };
          paintRule();
          // 关键词规则等写了第一个词再存
          if (type === 'keyword') extra.querySelector('input')?.focus(); else commit();
        }, 'room-seg-opt');
        b.dataset.type = type;
        b.setAttribute('role', 'radio');
        seg.append(b);
      }
      paintRule();
      // 插话概率：滑块 + 数字
      const chime = el('label', '', 'room-chime');
      const range = el('input');
      range.type = 'range'; range.min = 0; range.max = 100; range.step = 5;
      range.value = g.chime ?? 25;
      range.setAttribute('aria-label', p.name + ' 插话概率');
      const value = el('output', (g.chime ?? 25) + '%');
      range.oninput = () => { value.textContent = range.value + '%'; };
      range.onchange = () => { g.chime = Number(range.value); commit(true); };
      chime.append(el('span', '插话', 'room-chime-label'), range, value);
      body.append(seg, extra, chime);
      row.append(body);
      return row;
    }

    async function load() {
      try {
        const [chat, settings] = await Promise.all([LP.api.getMainChat(), LP.api.getSettings()]);
        main = chat;
        storedName = settings.user_name || '';
        userName.value = storedName;
        main.guests ||= [];
        paint();
      } catch (error) { root.querySelector('.room-primary').replaceChildren(el('span', LP.util.message(error, '读不到'), 'room-empty')); }
    }
    document.addEventListener('lp:chat-main', (event) => { if (event.detail && main && !selfRefresh && !Object.keys(queued).length) { main = { ...main, ...event.detail }; paint(); } });
    document.addEventListener('lp:languages', () => { if (main) paint(); });
    return { refresh: load };
  }

  global.LP = global.LP || {};
  global.LP.settingsChatRoom = { mount };
})(window);
