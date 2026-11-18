/* settings-hooks.js — 设置 › 事件。接口见 docs/LORE-AND-HOOKS.md 第二节：
   顶部总开关和节流（/api/settings 的 hooks_enabled / hooks_say_daily_cap / hooks_say_min_gap_minutes），
   规则列表 + 规则编辑（事件、联系人、条件、概率、冷却、once_per、动作）、变量小表、最近触发记录。
   事件、条件字段、动作、宏的可选项全部来自 GET /api/hooks/meta。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const ONCE_FALLBACK = [{ value: 'none', label: '不限' }, { value: 'session', label: '每次启动应用一次' }, { value: 'day', label: '每天一次' }];
  const LIMIT_FALLBACK = { rules: 200, conditions: 12, actions: 10, text: 2000 };
  const truthy = (v) => v === true || v === 1 || v === '1' || v === 'true';
  // 日志里没做成的原因（后端 skipped_reason）
  const SKIP_LABELS = {
    probability: '没抽中概率', say_daily_cap: '今天主动消息够数了', say_min_gap: '离上一条主动消息太近',
    no_due_vocab: '没有到期的生词', no_persona: '这门语言没有角色', duplicate_memory: '这条记忆已经有了',
    empty: '内容是空的', unknown_action: '认不出的动作', nothing_done: '一个动作都没做成',
  };

  function wire(root) {
    let meta = { events: [], condition_fields: [], actions: [], macros: [], once_per: ONCE_FALLBACK, limits: LIMIT_FALLBACK };
    const bookEntries = new Map(); // book_id -> Promise<[{uid,title}]>
    let rules = [];
    let books = [];
    let editing = null;      // 正在编辑的规则（副本）
    let readTicket = 0;

    root.innerHTML = `
      <div class="hooks-master">
        <label class="settings-check hooks-switch"><input type="checkbox" role="switch" data-hooks="enabled">事件总开关</label>
        <label class="hooks-limit">每天最多 <input type="number" min="0" max="50" data-hooks="cap" aria-label="每天最多几条主动消息"> 条主动消息</label>
        <label class="hooks-limit">两条之间至少隔 <input type="number" min="0" max="1440" data-hooks="gap" aria-label="主动消息最少间隔分钟"> 分钟</label>
      </div>
      <p class="hooks-notice" role="status"></p>
      <div class="settings-block"><h2 class="settings-block-title">规则</h2><div class="hooks-rules"></div><div class="hooks-editor"></div></div>
      <div class="settings-block"><h2 class="settings-block-title">变量</h2><div class="hooks-vars"></div></div>
      <div class="settings-block"><h2 class="settings-block-title">最近触发</h2><div class="hooks-log"></div></div>`;
    const $ = (sel) => root.querySelector(sel);
    const notice = (text, tone) => { const p = $('.hooks-notice'); p.textContent = text || ''; p.dataset.tone = tone || ''; };
    const eventDef = (id) => meta.events.find((e) => e.id === id);
    const eventLabel = (id) => eventDef(id)?.label || id;
    const actionDef = (type) => meta.actions.find((a) => a.type === type);
    const personaName = (id) => LP.getPersona(id)?.name || ('角色 ' + id);

    // ---------- 总开关和节流 ----------
    async function loadMaster() {
      try {
        const s = await LP.api.getSettings();
        $('[data-hooks="enabled"]').checked = s.hooks_enabled == null ? true : truthy(s.hooks_enabled);
        $('[data-hooks="cap"]').value = s.hooks_say_daily_cap ?? 4;
        $('[data-hooks="gap"]').value = s.hooks_say_min_gap_minutes ?? 30;
        root.classList.toggle('hooks-off', !$('[data-hooks="enabled"]').checked);
      } catch (error) { notice(LP.util.message(error), 'bad'); }
    }
    // 改了就存：控件旁边打勾
    async function saveMaster(patch, field) {
      try { await LP.api.putSettings(patch); LP.util.tick(field, true); }
      catch (error) { notice(LP.util.message(error), 'bad'); await loadMaster(); }
    }
    $('[data-hooks="enabled"]').onchange = (event) => {
      root.classList.toggle('hooks-off', !event.target.checked);
      void saveMaster({ hooks_enabled: event.target.checked }, event.target.parentElement);
    };
    const clampInt = (input) => { const n = Math.round(Number(input.value) || 0); const v = Math.min(Number(input.max), Math.max(0, n)); input.value = v; return v; };
    $('[data-hooks="cap"]').onchange = (event) => void saveMaster({ hooks_say_daily_cap: clampInt(event.target) }, event.target);
    $('[data-hooks="gap"]').onchange = (event) => void saveMaster({ hooks_say_min_gap_minutes: clampInt(event.target) }, event.target);

    // ---------- 规则列表 ----------
    function summary(rule) {
      const parts = [eventLabel(rule.event)];
      const fields = [...meta.condition_fields, ...eventFields(rule.event)];
      const cond = LP.conditions.summarize(rule.conditions, fields);
      if (cond) parts.push(cond);
      const acts = (rule.actions || []).map((a) => actionDef(a.type)?.label || a.type).join('、');
      return parts.join('，') + (acts ? ' → ' + acts : '');
    }
    function paintRules() {
      const list = $('.hooks-rules');
      list.replaceChildren(...rules.map((rule) => {
        const row = el('div', '', 'hooks-rule' + (rule.enabled ? '' : ' off') + (editing?.id === rule.id ? ' active' : ''));
        const pick = button('', () => edit(rule), 'hooks-rule-pick');
        const name = el('strong', rule.name || '未命名');
        if (rule.builtin) name.append(el('span', '自带', 'lore-badge'));
        pick.append(name, el('span', summary(rule)));
        const toggle = el('input');
        toggle.type = 'checkbox';
        toggle.setAttribute('role', 'switch');
        toggle.checked = Boolean(rule.enabled);
        toggle.setAttribute('aria-label', (rule.name || '规则') + ' 启用');
        toggle.onchange = async () => {
          try { await LP.api.updateHookRule(rule.id, { enabled: toggle.checked }); rule.enabled = toggle.checked; paintRules(); }
          catch (error) { toggle.checked = !toggle.checked; notice(LP.util.message(error), 'bad'); }
        };
        row.append(pick, toggle);
        return row;
      }));
      const add = button('+ 新规则', () => edit(null), 'hooks-rule-add');
      add.disabled = rules.length >= meta.limits.rules;
      list.append(add);
    }

    function eventFields(id) {
      return (eventDef(id)?.fields || []).map((f) => ({ ...f, key: 'event.' + f.key, label: '事件 · ' + (f.label || f.key) }));
    }

    // ---------- 规则编辑 ----------
    // 编辑到一半换别的规则、离开设置：先问（和设置页别处一样的「有改动没保存」）
    let editingStart = '';
    const editDirty = () => Boolean(editing) && JSON.stringify(editing) !== editingStart;
    async function edit(rule) {
      if (editDirty() && !(await LP.util.confirm({ title: '有改动没保存', text: '离开就丢了', ok: '不保存', cancel: '留下' }))) return;
      editing = rule ? structuredClone(rule) : {
        name: '新规则', enabled: true, persona_ids: null, event: meta.events[0]?.id || 'chat.open',
        conditions: [], probability: 100, cooldown_minutes: 0, cooldown_turns: 0, once_per: 'none', actions: [],
      };
      paintRules();
      paintEditor();
      editingStart = JSON.stringify(editing);   // 画完再记（下拉框会给没填的字段补上默认值）
      $('.hooks-editor').scrollIntoView({ block: 'nearest' });
    }

    function macroMenu(target) {
      const wrap = el('details', '', 'hooks-macros');
      wrap.append(el('summary', '插入'));
      const list = el('div', '', 'hooks-macro-list');
      list.append(...meta.macros.map((m) => {
        const token = m.name.startsWith('{{') ? m.name : '{{' + m.name + '}}';
        const pick = button('', () => {
          const start = target.selectionStart ?? target.value.length, end = target.selectionEnd ?? start;
          target.value = target.value.slice(0, start) + token + target.value.slice(end);
          target.dispatchEvent(new Event('input', { bubbles: true }));
          target.focus();
          target.selectionStart = target.selectionEnd = start + token.length;
          wrap.open = false;
        }, 'hooks-macro');
        pick.append(el('code', token), el('span', m.label || ''));
        return pick;
      }));
      wrap.append(list);
      return wrap;
    }

    // 动作的默认值：meta 字段的 default；select 没给 default 用第一个选项
    function freshAction(type) {
      const action = { type };
      for (const field of actionDef(type)?.fields || []) {
        if (field.default !== undefined) action[field.key] = field.default;
        else if (field.type === 'select' && field.options?.length) action[field.key] = field.options[0].value ?? field.options[0];
      }
      return action;
    }
    function entriesOf(bookId) {
      if (!bookEntries.has(bookId)) {
        bookEntries.set(bookId, LP.api.getLoreBook(bookId)
          .then((data) => (data.book?.entries || []).map((e) => ({ uid: e.uid, title: e.title || (e.content || '').slice(0, 24) || '条目 ' + e.uid })))
          .catch((error) => { bookEntries.delete(bookId); throw error; }));
      }
      return bookEntries.get(bookId);
    }

    function actionCard(action, index) {
      const card = el('div', '', 'hooks-action');
      const head = el('div', '', 'hooks-action-head');
      const type = el('select');
      type.setAttribute('aria-label', '动作');
      type.append(...meta.actions.map((a) => new Option(a.label || a.type, a.type)));
      if (!actionDef(action.type)) type.append(new Option(action.type, action.type));
      type.value = action.type;
      type.onchange = () => { editing.actions[index] = freshAction(type.value); paintEditor(); };
      head.append(el('strong', '动作 ' + (index + 1)), type, button('×', () => { editing.actions.splice(index, 1); paintEditor(); }, 'cond-remove'));
      card.append(head);
      const grid = el('div', '', 'lore-grid');
      const entrySelects = [];
      for (const def of actionDef(action.type)?.fields || []) {
        const key = def.key;
        const long = def.type === 'textarea';
        const wrap = el('label', '', 'lore-field' + (long ? ' lore-wide' : ''));
        const caption = el('span', def.label || key);
        let control;
        if (def.type === 'book') {
          control = el('select');
          control.append(new Option('选一本书', ''), ...books.map((b) => new Option(b.name, b.id)));
          if (action[key] != null && !books.some((b) => b.id === action[key])) control.append(new Option('书 ' + action[key] + '（已不在）', action[key]));
        } else if (def.type === 'entry') {
          control = el('select');
          entrySelects.push(control);
        } else if (def.type === 'select') {
          control = el('select');
          control.append(...(def.options || []).map((o) => (typeof o === 'object' ? new Option(o.label ?? o.value, o.value) : new Option(o, o))));
        } else if (long) {
          control = el('textarea');
          control.rows = 3;
          control.maxLength = meta.limits.text;
        } else {
          control = el('input');
          control.type = def.type === 'number' ? 'number' : 'text';
          if (def.type === 'number') { if (def.min != null) control.min = def.min; if (def.max != null) control.max = def.max; }
          else control.maxLength = meta.limits.text;
        }
        control.required = Boolean(def.required);
        control.dataset.label = def.label || key;
        control.dataset.field = key;
        if (def.type !== 'entry') {
          if (action[key] != null) control.value = String(action[key]);
          else if (def.type === 'select') action[key] = control.value;
        }
        const numeric = def.type === 'number' || def.type === 'book' || def.type === 'entry';
        control.oninput = control.onchange = () => {
          action[key] = numeric ? (control.value === '' ? null : Number(control.value)) : control.value;
          if (def.type === 'book') { action.uid = null; void fillEntries(); }
        };
        if (long && meta.macros.length) caption.append(macroMenu(control));
        wrap.append(caption, control);
        grid.append(wrap);
      }
      // 条目下拉跟着同一动作里选的书走；显示标题，存 uid
      async function fillEntries() {
        for (const control of entrySelects) {
          const key = control.dataset.field;
          control.replaceChildren(new Option(action.book_id ? '读取条目…' : '先选书', ''));
          if (!action.book_id) continue;
          try {
            const entries = await entriesOf(action.book_id);
            control.replaceChildren(new Option('选一条', ''), ...entries.map((e) => new Option(e.title, e.uid)));
            if (action[key] != null && !entries.some((e) => e.uid === action[key])) control.append(new Option('条目 ' + action[key] + '（已不在）', action[key]));
            if (action[key] != null) control.value = String(action[key]);
          } catch (error) { control.replaceChildren(new Option(LP.util.message(error, '读不到条目'), '')); }
        }
      }
      if (entrySelects.length) void fillEntries();
      card.append(grid);
      return card;
    }

    // 保存前：必填项不能空
    function missingRequired(form) {
      return [...form.querySelectorAll('.hooks-action [required]')].find((control) => !String(control.value).trim());
    }

    function paintEditor() {
      const box = $('.hooks-editor');
      if (!editing) { box.replaceChildren(); return; }
      const r = editing;
      const form = el('section', '', 'hooks-form');
      form.append(el('h3', r.id ? '编辑规则' : '新规则'));
      const top = el('div', '', 'lore-grid');
      const name = el('label', '', 'lore-field');
      const nameInput = el('input');
      nameInput.value = r.name || '';
      nameInput.maxLength = 80;
      nameInput.oninput = () => { r.name = nameInput.value; };
      name.append(el('span', '名字'), nameInput);
      const ev = el('label', '', 'lore-field');
      const evSelect = el('select');
      evSelect.append(...meta.events.map((e) => new Option(e.label || e.id, e.id)));
      if (!meta.events.some((e) => e.id === r.event)) evSelect.append(new Option(r.event, r.event));
      evSelect.value = r.event;
      ev.append(el('span', '事件'), evSelect);
      top.append(name, ev);

      // 适用联系人
      const who = el('div', '', 'lore-field lore-wide hooks-who');
      const all = el('label', '', 'settings-check');
      const allBox = el('input');
      allBox.type = 'checkbox';
      allBox.checked = r.persona_ids == null;
      all.append(allBox, document.createTextNode('所有角色'));
      const picks = el('div', '', 'hooks-personas');
      picks.hidden = allBox.checked;
      picks.append(...LP.state.personas.map((p) => {
        const label = el('label', '', 'settings-check');
        const box = el('input');
        box.type = 'checkbox';
        box.value = p.id;
        box.checked = (r.persona_ids || []).includes(p.id);
        box.onchange = () => { r.persona_ids = [...picks.querySelectorAll('input:checked')].map((x) => Number(x.value)); };
        label.append(box, document.createTextNode(p.name));
        return label;
      }));
      allBox.onchange = () => {
        picks.hidden = allBox.checked;
        r.persona_ids = allBox.checked ? null : [...picks.querySelectorAll('input:checked')].map((x) => Number(x.value));
      };
      who.append(el('span', '适用角色'), all, picks);

      // 条件：通用字段 + 这个事件带的 event.*
      const condWrap = el('div', '', 'lore-field lore-wide');
      const conditions = LP.conditions.create({ fields: [...meta.condition_fields, ...eventFields(r.event)], value: r.conditions, max: meta.limits.conditions, onChange: (v) => { r.conditions = v; } });
      condWrap.append(el('span', '条件（全部满足才做）'), conditions.element);
      evSelect.onchange = () => { r.event = evSelect.value; r.conditions = conditions.read(); conditions.setFields([...meta.condition_fields, ...eventFields(r.event)]); };

      const limits = el('div', '', 'lore-grid lore-wide');
      const num = (label, key, max) => {
        const wrap = el('label', '', 'lore-field');
        const input = el('input');
        input.type = 'number'; input.min = 0; input.max = max;
        input.value = r[key] ?? 0;
        input.oninput = () => { r[key] = Number(input.value) || 0; };
        wrap.append(el('span', label), input);
        return wrap;
      };
      const once = el('label', '', 'lore-field');
      const onceSelect = el('select');
      onceSelect.append(...(meta.once_per || ONCE_FALLBACK).map((o) => new Option(o.label, o.value)));
      onceSelect.value = r.once_per || 'none';
      onceSelect.onchange = () => { r.once_per = onceSelect.value; };
      once.append(el('span', '次数'), onceSelect);
      limits.append(num('概率 %', 'probability', 100), num('冷却（分钟）', 'cooldown_minutes', 10080), num('冷却（轮）', 'cooldown_turns', 1000), once);

      const actions = el('div', '', 'lore-wide hooks-actions');
      const addAction = button('+ 动作', () => { r.actions.push(freshAction(meta.actions[0]?.type || 'say')); paintEditor(); }, 'cond-add');
      addAction.disabled = r.actions.length >= meta.limits.actions;
      actions.append(el('span', '做什么', 'hooks-caption'), ...r.actions.map(actionCard), addAction);

      const bar = el('div', '', 'hooks-form-actions');
      const save = button('保存规则', async () => {
        const missing = missingRequired(form);
        if (missing) { missing.focus(); notice('「' + missing.dataset.label + '」要填', 'bad'); return; }
        save.disabled = true;
        try {
          r.conditions = conditions.read();
          const body = { ...r };
          delete body.id; delete body.builtin;
          const saved = r.id ? await LP.api.updateHookRule(r.id, body) : await LP.api.createHookRule(body);
          editing = null;
          await loadRules();
          notice('已保存「' + (saved?.name || r.name) + '」', 'ok');
        } catch (error) { notice(LP.util.message(error), 'bad'); }
        finally { save.disabled = false; }
      }, 'primary');
      bar.append(save, button('取消', () => { editing = null; paintRules(); paintEditor(); }, ''));
      if (r.id && !r.builtin) bar.append(button('删除', async () => {
        const ok = await LP.util.confirm({ title: '删掉「' + r.name + '」？', ok: '删除' });
        if (!ok) return;
        try { await LP.api.deleteHookRule(r.id); editing = null; await loadRules(); notice('已删除', 'ok'); }
        catch (error) { notice(LP.util.message(error), 'bad'); }
      }, 'row-delete'));

      top.append(who, condWrap, limits, actions);
      form.append(top, bar);
      box.replaceChildren(form);
    }

    // ---------- 变量 ----------
    async function loadVars() {
      const box = $('.hooks-vars');
      try {
        const { items = [] } = await LP.api.getHookVars();
        const table = el('div', '', 'hooks-table');
        const row = (item) => {
          const line = el('div', '', 'hooks-var');
          const value = el('input');
          value.value = item.value == null ? '' : String(item.value);
          value.setAttribute('aria-label', item.name + ' 的值');
          const put = async (next) => {
            try {
              await LP.api.putHookVar({ name: item.name, value: next, scope: item.scope, persona_id: item.persona_id ?? undefined });
              await loadVars();
            } catch (error) { notice(LP.util.message(error), 'bad'); }
          };
          line.append(el('code', item.name), el('span', item.scope === 'global' ? '全局' : personaName(item.persona_id), 'hooks-scope'), value,
            button('保存', () => void put(/^-?\d+(\.\d+)?$/.test(value.value.trim()) ? Number(value.value) : value.value), 'btn-sm'),
            button('删除', () => void put(null), 'btn-sm row-delete'));
          return line;
        };
        table.append(...items.map(row));
        if (!items.length) table.append(el('p', '还没有变量', 'lore-empty'));
        // 新建一个
        const add = el('div', '', 'hooks-var hooks-var-new');
        const name = el('input'); name.placeholder = '名字'; name.setAttribute('aria-label', '新变量名字'); name.maxLength = 60;
        const scope = el('select'); scope.setAttribute('aria-label', '作用范围');
        scope.append(new Option('全局', 'global'), ...LP.state.personas.map((p) => new Option(p.name, 'p:' + p.id)));
        const value = el('input'); value.placeholder = '值'; value.setAttribute('aria-label', '新变量的值');
        add.append(name, scope, value, button('添加', async () => {
          if (!name.value.trim()) { name.focus(); return; }
          const personaId = scope.value.startsWith('p:') ? Number(scope.value.slice(2)) : undefined;
          try {
            await LP.api.putHookVar({ name: name.value.trim(), value: /^-?\d+(\.\d+)?$/.test(value.value.trim()) ? Number(value.value) : value.value, scope: personaId ? 'persona' : 'global', persona_id: personaId });
            await loadVars();
          } catch (error) { notice(LP.util.message(error), 'bad'); }
        }, 'btn-sm'));
        table.append(add);
        box.replaceChildren(table);
      } catch (error) { box.replaceChildren(el('p', LP.util.message(error, '读不到'), 'lore-empty')); }
    }

    // ---------- 最近触发 ----------
    function when(at) {
      const d = new Date(typeof at === 'number' ? at * 1000 : at);
      if (!Number.isFinite(d.getTime())) return '';
      const pad = (n) => String(n).padStart(2, '0');
      return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
    function did(entry) {
      if (entry.skipped_reason) {
        const reason = String(entry.skipped_reason);
        return '没做成：' + (SKIP_LABELS[reason] || (reason.startsWith('error') ? '出错了' : reason));
      }
      // 后端记的是 "say"、"inject"、"set_var:名字" 这样的字符串
      const acts = (entry.actions || []).map((a) => {
        const [type, detail] = String(typeof a === 'string' ? a : a.type).split(':');
        return (actionDef(type)?.label || type) + (detail ? ' ' + detail : '');
      });
      return acts.length ? acts.join('、') : '—';
    }
    async function loadLog() {
      const box = $('.hooks-log');
      try {
        const { items = [] } = await LP.api.getHookLog(50);
        box.replaceChildren(...(items.length ? items.map((entry) => {
          const line = el('div', '', 'hooks-log-row' + (entry.skipped_reason ? ' skipped' : ''));
          line.append(el('time', when(entry.at)), el('strong', entry.rule_name || ('规则 ' + entry.rule_id)),
            el('span', eventLabel(entry.event) + (entry.persona_id ? ' · ' + personaName(entry.persona_id) : ''), 'hooks-scope'),
            el('span', did(entry), 'hooks-did'));
          return line;
        }) : [el('p', '还没有触发过', 'lore-empty')]));
      } catch (error) { box.replaceChildren(el('p', LP.util.message(error, '读不到'), 'lore-empty')); }
    }

    async function loadRules() {
      const { items = [] } = await LP.api.getHookRules();
      rules = items;
      paintRules();
      paintEditor();
    }

    async function refresh() {
      const ticket = ++readTicket;
      try {
        const [m, b] = await Promise.all([LP.conditions.meta(), LP.api.getLoreBooks().catch(() => ({ items: [] }))]);
        if (ticket !== readTicket) return;
        meta = { events: [], condition_fields: [], actions: [], macros: [], once_per: ONCE_FALLBACK, ...m, limits: { ...LIMIT_FALLBACK, ...(m.limits || {}) } };
        books = b.items || [];
        bookEntries.clear();
        await Promise.all([loadMaster(), loadRules(), loadVars(), loadLog()]);
      } catch (error) { notice(LP.util.message(error), 'bad'); }
    }
    return { refresh, isDirty: editDirty, discard: () => { editing = null; paintRules(); paintEditor(); } };
  }

  global.LP = global.LP || {};
  global.LP.settingsHooks = { wire };
})(window);
