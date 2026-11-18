/* settings-lore.js — 设置 › 课程与世界书 › 世界书。接口见 docs/LORE-AND-HOOKS.md 第一节：
   书的列表（启用、作用域、条目数）→ 选中一本：名字/作用域/导出/删除、书的设置、条目列表 + 条目编辑、试触发。
   条目常用字段放明面，其余收进「更多」；条件触发用 conditions.js 的编辑器。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const POSITIONS = [['before_persona', '角色设定前'], ['after_persona', '角色设定后'], ['turn', '本轮背景']];
  const LOGIC = [['and_any', '任一命中'], ['and_all', '全部命中'], ['not_any', '一个都不能有'], ['not_all', '不能全有']];
  const positionLabel = (id) => (POSITIONS.find(([key]) => key === id) || [, id])[1];
  const ENTRY_DEFAULTS = {
    title: '', content: '', enabled: true, constant: false, keys: [], secondary_keys: [], logic: 'and_any',
    case_sensitive: false, whole_words: false, lemma: null, semantic: false, semantic_threshold: 0.84,
    position: 'turn', order: 100, probability: 100, scan_depth: null, sticky: 0, cooldown: 0, delay: 0,
    group: '', group_weight: 100, group_override: false, exclude_recursion: false, prevent_recursion: false,
    delay_until_recursion: false, conditions: [], automation_id: '', extensions: {},
  };
  const SETTINGS_DEFAULTS = { scan_depth: 4, budget_chars: 1600, recursion: true, max_recursion: 3, lemma_match: true };
  // 试触发：为什么生效（reason）、为什么被挡下（why），见 docs/LORE-AND-HOOKS.md 1.6
  const WHY = {
    disabled: '停用了', suppressed: '被事件压住', delay: '对话还不够长', cooldown: '冷却中', no_match: '没命中关键词',
    secondary_logic: '次要关键词不满足', semantic_unavailable: '语义模型没准备好', conditions: '条件不满足',
    probability: '没抽中概率', group: '同组留了别的', recursion_only: '只在递归时触发', budget: '超出字数预算',
    no_due_vocab: '没有到期的生词',
  };
  function reasonText(reason) {
    const text = String(reason || '');
    const [head, ...rest] = text.split(':');
    const tail = rest.join(':');
    return ({
      constant: () => '常驻', conditions: () => '条件满足', key: () => '关键词「' + tail + '」', lemma: () => '原形「' + tail + '」',
      regex: () => '正则 ' + tail, semantic: () => '意思相近 ' + tail, sticky: () => '粘性中', forced: () => '被事件强制',
      recursion: () => '被别的条目带出' + (tail ? '（' + tail + '）' : ''),
    })[head]?.() || text;
  }
  // injected：system = 进系统提示词；turn = 进这一轮的背景块；null = 激活中但这轮不重复注入
  const INJECTED = { system: ['进系统提示词', 'system'], turn: ['进本轮背景', 'turn'] };

  let root = null;
  let books = [];
  let selectedId = null;
  let draft = null;        // {id, name, scope, enabled, book}
  let dirty = false;
  let openEntry = null;     // 展开的条目（按对象认：新条目还没有 uid，由后端编号）
  let conditionFields = [];
  let listRead = 0;

  const persona = (id) => LP.getPersona(id);
  const notice = (text, tone) => {
    const line = root?.querySelector('.lore-notice');
    if (!line) return;
    line.textContent = text || '';
    line.dataset.tone = tone || '';
  };

  // ---------- 小控件 ----------
  function check(label, value, onChange, cls = 'settings-check') {
    const wrap = el('label', '', cls);
    const input = el('input');
    input.type = 'checkbox';
    input.checked = Boolean(value);
    input.onchange = () => onChange(input.checked);
    wrap.append(input, document.createTextNode(label));
    return wrap;
  }
  function numberField(label, value, onChange, { min, max, step = 1, placeholder } = {}) {
    const wrap = el('label', '', 'lore-field');
    const input = el('input');
    input.type = 'number';
    if (min != null) input.min = min;
    if (max != null) input.max = max;
    input.step = step;
    if (placeholder) input.placeholder = placeholder;
    input.value = value == null ? '' : String(value);
    input.oninput = () => onChange(input.value === '' ? null : Number(input.value));
    wrap.append(el('span', label), input);
    return wrap;
  }
  function textField(label, value, onChange, { multiline = false, rows = 4, max } = {}) {
    const wrap = el('label', '', 'lore-field' + (multiline ? ' lore-wide' : ''));
    const input = el(multiline ? 'textarea' : 'input');
    if (multiline) input.rows = rows;
    if (max) input.maxLength = max;
    input.value = value || '';
    input.oninput = () => onChange(input.value);
    wrap.append(el('span', label), input);
    return wrap;
  }
  function selectField(label, value, choices, onChange) {
    const wrap = el('label', '', 'lore-field');
    const select = el('select');
    select.append(...choices.map(([id, text]) => new Option(text, id)));
    select.value = value;
    select.onchange = () => onChange(select.value);
    wrap.append(el('span', label), select);
    return wrap;
  }
  // 关键词：标签式输入，回车或逗号加一个，× 删一个
  function tagInput(label, values, onChange) {
    const wrap = el('div', '', 'lore-field lore-wide');
    const box = el('div', '', 'lore-tags');
    const input = el('input', '', 'lore-tag-input');
    input.placeholder = '回车添加';
    input.setAttribute('aria-label', label);
    let tags = [...(values || [])];
    function paint() {
      box.replaceChildren(...tags.map((tag, index) => {
        const chip = el('span', '', 'tag-chip');
        chip.append(el('span', tag), button('×', () => { tags.splice(index, 1); onChange([...tags]); paint(); }, 'rm'));
        return chip;
      }), input);
    }
    function commit() {
      const parts = input.value.split(/[,，、]/).map((x) => x.trim()).filter(Boolean);
      if (!parts.length) return;
      tags = [...new Set([...tags, ...parts])];
      input.value = '';
      onChange([...tags]);
      paint();
      input.focus();
    }
    input.addEventListener('keydown', (event) => {
      if ((event.key === 'Enter' || event.key === ',' || event.key === '，') && !event.isComposing) { event.preventDefault(); commit(); }
      if (event.key === 'Backspace' && !input.value && tags.length) { tags.pop(); onChange([...tags]); paint(); input.focus(); }
    });
    input.addEventListener('blur', commit);
    paint();
    wrap.append(el('span', label), box);
    return wrap;
  }

  function markDirty() {
    dirty = true;
    const bar = root.querySelector('.lore-savebar');
    if (bar) bar.hidden = false;
    syncTester();
  }

  // ---------- 书的列表 ----------
  function scopeText(book) {
    if (book.scope === 'global') return '全局';
    const names = (book.attached_persona_ids || []).map((id) => persona(id)?.name).filter(Boolean);
    return names.length ? '挂在 ' + names.join('、') : '还没挂到角色';
  }

  function paintList() {
    const list = root.querySelector('.lore-books');
    list.replaceChildren(...books.map((book) => {
      const card = el('div', '', 'lore-book' + (book.id === selectedId ? ' active' : '') + (book.enabled ? '' : ' off'));
      const pick = button('', () => void select(book.id), 'lore-book-pick');
      pick.append(el('strong', book.name || '未命名'), el('span', book.entry_count + ' 条 · ' + scopeText(book)));
      pick.setAttribute('aria-pressed', String(book.id === selectedId));
      const toggle = el('input');
      toggle.type = 'checkbox';
      toggle.setAttribute('role', 'switch');
      toggle.checked = Boolean(book.enabled);
      toggle.setAttribute('aria-label', (book.name || '这本书') + ' 启用');
      toggle.onchange = async () => {
        try {
          await LP.api.updateLoreBook(book.id, { enabled: toggle.checked });
          book.enabled = toggle.checked;
          if (draft?.id === book.id) draft.enabled = toggle.checked;
          paintList();
        } catch (error) { toggle.checked = !toggle.checked; notice(LP.util.message(error), 'bad'); }
      };
      card.append(pick, toggle);
      return card;
    }), button('+ 新建世界书', () => void createBook(), 'lore-book-add'));
  }

  async function loadList() {
    const ticket = ++listRead;
    try {
      const data = await LP.api.getLoreBooks();
      if (ticket !== listRead) return;
      books = data.items || [];
      document.dispatchEvent(new CustomEvent('lp:lore-books', { detail: books }));
      paintList();
      if (!books.some((b) => b.id === selectedId)) {
        selectedId = null; draft = null;
        if (books[0]) await select(books[0].id); else paintEditor();
      }
    } catch (error) { if (ticket === listRead) notice(LP.util.message(error), 'bad'); }
  }

  async function select(id) {
    if (dirty && draft && draft.id !== id) {
      const ok = await LP.util.confirm({ title: '有改动没保存', text: '离开就丢了', ok: '不保存', cancel: '留下' });
      if (!ok) return;
    }
    try {
      const data = await LP.api.getLoreBook(id);
      draft = { id: data.id, name: data.name, scope: data.scope, enabled: data.enabled, book: normalize(data.book) };
      selectedId = id; dirty = false; openEntry = null;
      paintList(); paintEditor();
    } catch (error) { notice(LP.util.message(error), 'bad'); }
  }

  function normalize(book) {
    const value = structuredClone(book || {});
    value.version = 2;
    value.settings = { ...SETTINGS_DEFAULTS, ...(value.settings || {}) };
    value.entries = (value.entries || []).map((entry) => ({ ...ENTRY_DEFAULTS, ...entry }));
    return value;
  }

  async function createBook() {
    try {
      const made = await LP.api.createLoreBook({ name: '新的世界书', scope: 'attached', book: normalize({}) });
      await loadList();
      await select(made.id);
      root.querySelector('.lore-name')?.select();
    } catch (error) { notice(LP.util.message(error), 'bad'); }
  }

  async function importFile(file) {
    notice('正在导入…');
    try {
      const result = await LP.api.importLore(file);
      const warnings = result.warnings || [];
      await loadList();
      await select(result.id);
      const box = root.querySelector('.lore-warnings');
      box.replaceChildren();
      box.hidden = !warnings.length;
      if (warnings.length) {
        box.append(el('strong', '导入了「' + result.name + '」' + result.entry_count + ' 条，有 ' + warnings.length + ' 处要留意'));
        const list = el('ul');
        list.append(...warnings.map((w) => el('li', typeof w === 'string' ? w : (w.message || JSON.stringify(w)))));
        box.append(list, button('知道了', () => { box.hidden = true; }, 'btn-sm'));
      }
      notice('已导入「' + result.name + '」· ' + result.entry_count + ' 条', 'ok');
    } catch (error) { notice(LP.util.message(error), 'bad'); }
  }

  async function saveBook() {
    if (!draft) return false;
    const save = root.querySelector('.lore-save');
    if (save) save.disabled = true;
    try {
      const openIndex = openEntry ? draft.book.entries.indexOf(openEntry) : -1;
      await LP.api.updateLoreBook(draft.id, { name: draft.name.trim() || '未命名', scope: draft.scope, enabled: draft.enabled, book: draft.book });
      dirty = false;
      // 重读一遍：新条目由后端编了 uid，下次保存要带回去
      await select(draft.id);
      if (openIndex >= 0) { openEntry = draft.book.entries[openIndex] || null; paintEditor(); }
      notice('已保存', 'ok');
      await loadList();
      return true;
    } catch (error) { notice(LP.util.message(error), 'bad'); return false; }
    finally { if (save) save.disabled = false; }
  }

  async function deleteBook() {
    if (!draft) return;
    const ok = await LP.util.confirm({ title: '删掉「' + draft.name + '」？', ok: '删除' });
    if (!ok) return;
    try {
      await LP.api.deleteLoreBook(draft.id);
      draft = null; selectedId = null; dirty = false;
      await loadList();
      notice('已删除', 'ok');
    } catch (error) { notice(LP.util.message(error), 'bad'); }
  }

  // ---------- 选中的书 ----------
  function paintEditor() {
    const box = root.querySelector('.lore-editor');
    if (!draft) { box.replaceChildren(el('p', books.length ? '选一本书' : '还没有世界书', 'lore-empty')); return; }
    const head = el('div', '', 'lore-head');
    const name = el('input', '', 'lore-name');
    name.value = draft.name;
    name.maxLength = 80;
    name.setAttribute('aria-label', '书名');
    name.oninput = () => { draft.name = name.value; markDirty(); };
    const scope = el('select', '', 'lore-scope');
    scope.setAttribute('aria-label', '作用域');
    scope.append(new Option('只给挂了它的角色', 'attached'), new Option('所有角色', 'global'));
    scope.value = draft.scope || 'attached';
    scope.onchange = () => { draft.scope = scope.value; markDirty(); };
    const exportLink = el('a', '导出', 'lore-export');
    exportLink.href = LP.api.loreExportUrl(draft.id);
    exportLink.download = (draft.name || 'worldbook') + '.json';
    head.append(name, scope, exportLink, button('删除', () => void deleteBook(), 'row-delete'));

    // 书的设置
    const s = draft.book.settings;
    const settings = el('details', '', 'settings-fold lore-settings');
    settings.append(el('summary', '书的设置'));
    const grid = el('div', '', 'lore-grid');
    grid.append(
      numberField('往回看几条', s.scan_depth, (v) => { s.scan_depth = v ?? 0; markDirty(); }, { min: 0, max: 50 }),
      numberField('每轮字数预算', s.budget_chars, (v) => { s.budget_chars = v ?? 0; markDirty(); }, { min: 0, max: 20000, step: 100 }),
      check('递归触发', s.recursion, (v) => { s.recursion = v; markDirty(); }),
      numberField('最多几层', s.max_recursion, (v) => { s.max_recursion = v ?? 0; markDirty(); }, { min: 0, max: 10 }),
      check('按原形匹配', s.lemma_match, (v) => { s.lemma_match = v; markDirty(); }),
    );
    settings.append(grid);

    // 条目
    const entries = el('div', '', 'lore-entries');
    const entriesHead = el('div', '', 'lore-entries-head');
    entriesHead.append(el('h3', '条目 · ' + draft.book.entries.length));
    entries.append(entriesHead);
    for (const entry of draft.book.entries) entries.append(entryRow(entry));
    entries.append(button('+ 新条目', () => {
      const entry = structuredClone(ENTRY_DEFAULTS); // 不带 uid，保存时后端编号
      draft.book.entries.push(entry);
      openEntry = entry; markDirty(); paintEditor();
      root.querySelector('.lore-entry.open input')?.focus();
    }, 'lore-entry-add'));

    const savebar = el('div', '', 'lore-savebar course-preview-save');
    savebar.hidden = !dirty;
    const save = button('保存这本书', () => void saveBook(), 'lore-save primary');
    savebar.append(el('span', '有改动没保存'), button('不要了', () => void discard(), ''), save);

    box.replaceChildren(head, settings, entries, savebar, tester());
  }

  function entryRow(entry) {
    const open = entry === openEntry;
    const item = el('div', '', 'lore-entry' + (open ? ' open' : '') + (entry.enabled ? '' : ' off'));
    const summary = el('div', '', 'lore-entry-row');
    const pick = button('', () => { openEntry = open ? null : entry; paintEditor(); }, 'lore-entry-pick');
    pick.setAttribute('aria-expanded', String(open));
    const keys = entry.constant ? '常驻' : (entry.keys || []).join('、') || (entry.conditions?.length ? '按条件' : entry.semantic ? '按意思' : '没有关键词');
    pick.append(el('strong', entry.title || (entry.content || '').slice(0, 24) || '（无标题）'), el('span', keys));
    const badges = el('span', '', 'lore-badges');
    badges.append(el('span', positionLabel(entry.position), 'lore-badge'));
    if (entry.conditions?.length) badges.append(el('span', '条件 ' + entry.conditions.length, 'lore-badge'));
    if (entry.semantic) badges.append(el('span', '语义', 'lore-badge'));
    if (entry.group) badges.append(el('span', '组 ' + entry.group, 'lore-badge'));
    if (entry.sticky) badges.append(el('span', '粘 ' + entry.sticky + ' 轮', 'lore-badge'));
    const toggle = el('input');
    toggle.type = 'checkbox';
    toggle.setAttribute('role', 'switch');
    toggle.checked = entry.enabled;
    toggle.setAttribute('aria-label', '启用这条');
    toggle.onchange = () => { entry.enabled = toggle.checked; item.classList.toggle('off', !toggle.checked); markDirty(); };
    summary.append(pick, badges, toggle);
    item.append(summary);
    if (open) item.append(entryEditor(entry));
    return item;
  }

  function entryEditor(entry) {
    const form = el('div', '', 'lore-entry-editor');
    const set = (key) => (value) => { entry[key] = value; markDirty(); };
    const main = el('div', '', 'lore-grid');
    main.append(
      textField('标题', entry.title, set('title'), { max: 120 }),
      selectField('位置', entry.position, POSITIONS, set('position')),
      textField('正文', entry.content, set('content'), { multiline: true, rows: 5 }),
      tagInput('主关键词', entry.keys, set('keys')),
    );
    const switches = el('div', '', 'lore-switches');
    switches.append(check('常驻（不看关键词）', entry.constant, set('constant')), check('启用', entry.enabled, set('enabled')));
    // 条件触发
    const conditions = el('div', '', 'lore-field lore-wide');
    const editor = LP.conditions.create({ fields: conditionFields, value: entry.conditions, onChange: (value) => { entry.conditions = value; markDirty(); } });
    conditions.append(el('span', '条件（全部满足才触发）'), editor.element);

    // 更多
    const more = el('details', '', 'lore-more');
    more.append(el('summary', '更多'));
    const g = el('div', '', 'lore-grid');
    g.append(
      tagInput('次要关键词', entry.secondary_keys, set('secondary_keys')),
      selectField('次要关键词怎么算', entry.logic, LOGIC, set('logic')),
      selectField('按原形匹配', entry.lemma == null ? 'book' : entry.lemma ? 'yes' : 'no', [['book', '跟书的设置'], ['yes', '是'], ['no', '否']],
        (v) => { entry.lemma = v === 'book' ? null : v === 'yes'; markDirty(); }),
      numberField('语义阈值', entry.semantic_threshold, set('semantic_threshold'), { min: 0, max: 1, step: 0.01 }),
      numberField('顺序', entry.order, set('order'), { min: 0, max: 10000 }),
      numberField('概率 %', entry.probability, set('probability'), { min: 0, max: 100 }),
      numberField('往回看几条', entry.scan_depth, set('scan_depth'), { min: 0, max: 50, placeholder: '跟书' }),
      numberField('粘性（轮）', entry.sticky, set('sticky'), { min: 0, max: 100 }),
      numberField('冷却（轮）', entry.cooldown, set('cooldown'), { min: 0, max: 100 }),
      numberField('延迟（条消息后）', entry.delay, set('delay'), { min: 0, max: 1000 }),
      textField('分组', entry.group, set('group'), { max: 60 }),
      numberField('组内权重', entry.group_weight, set('group_weight'), { min: 0, max: 1000 }),
      textField('事件编号', entry.automation_id, set('automation_id'), { max: 80 }),
    );
    const flags = el('div', '', 'lore-switches lore-wide');
    flags.append(
      check('语义触发', entry.semantic, set('semantic')),
      check('区分大小写', entry.case_sensitive, set('case_sensitive')),
      check('整词', entry.whole_words, set('whole_words')),
      check('组内优先（不抽签）', entry.group_override, set('group_override')),
      check('不被别的条目触发', entry.exclude_recursion, set('exclude_recursion')),
      check('不去触发别的条目', entry.prevent_recursion, set('prevent_recursion')),
      check('只在递归时触发', entry.delay_until_recursion, set('delay_until_recursion')),
    );
    g.append(flags);
    more.append(g);

    const actions = el('div', '', 'lore-entry-actions');
    actions.append(button('删除这条', async () => {
      const ok = await LP.util.confirm({ title: '删掉「' + (entry.title || '（无标题）') + '」？', ok: '删除' });
      if (!ok) return;
      draft.book.entries = draft.book.entries.filter((e) => e !== entry);
      openEntry = null; markDirty(); paintEditor();
    }, 'row-delete'));
    form.append(main, switches, conditions, more, actions);
    return form;
  }

  // ---------- 试触发 ----------
  // 只建一次：展开/收起条目、加新条目会重画编辑区，试触发框里打好的句子和上次结果都留着。
  // 有没保存的修改时按钮写「保存并试一下」（试的是存好的书）
  let testBox = null;
  function syncTester() {
    if (!testBox) return;
    testBox.querySelector('.lore-test-bar button').textContent = dirty ? '保存并试一下' : '试一下';
    const who = testBox.querySelector('select');
    const keep = who.value;
    who.replaceChildren(...LP.state.personas.map((p) => new Option(p.name, p.id)));
    who.value = keep || String(LP.state.currentPersonaId || '');
    if (who.selectedIndex < 0 && who.options.length) who.selectedIndex = 0;
  }
  function tester() {
    if (testBox) { syncTester(); return testBox; }
    const box = el('section', '', 'lore-test');
    box.append(el('h3', '试触发'));
    const bar = el('div', '', 'lore-test-bar');
    const who = el('select');
    who.setAttribute('aria-label', '角色');
    const text = el('input');
    text.placeholder = '她会听到的一句话';
    text.setAttribute('aria-label', '试触发的消息');
    text.maxLength = 2000;
    const run = button('试一下', () => void go(), 'primary');
    bar.append(who, text, run);
    const out = el('div', '', 'lore-test-out');
    box.append(bar, out);
    text.addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); void go(); } });

    async function go() {
      if (!text.value.trim() || !who.value) { text.focus(); return; }
      run.disabled = true;
      try {
        const ask = { persona_id: Number(who.value), text: text.value.trim() };
        if (dirty && !(await saveBook())) return;
        paintResult(out, await LP.api.testLore(ask));
      } catch (error) {
        out.replaceChildren(el('p', LP.util.message(error, '没试成，再试一次'), 'lore-test-error'));
      } finally { run.disabled = false; }
    }
    testBox = box;
    syncTester();
    return box;
  }

  // 不要这次的修改：重新读回存着的那本
  async function discard() {
    dirty = false;
    if (draft) await select(draft.id);
  }

  function paintResult(out, result) {
    const activated = result.activated || [];
    const skipped = result.skipped || [];
    const on = el('div', '', 'lore-test-col');
    on.append(el('h4', '会生效 · ' + activated.length));
    on.append(...(activated.length ? activated.map((row) => {
      const [label, tone] = INJECTED[row.injected] || ['已在生效', 'held'];
      const line = el('div', '', 'lore-hit' + (tone === 'held' ? ' held' : ''));
      const badge = el('span', label, 'lore-badge lore-injected');
      badge.dataset.injected = tone;
      line.append(el('strong', row.title || '条目 ' + row.uid), badge, el('small', (row.book_name ? row.book_name + ' · ' : '') + reasonText(row.reason)));
      return line;
    }) : [el('p', '一条都没触发', 'lore-empty')]));
    const off = el('div', '', 'lore-test-col');
    off.append(el('h4', '被挡下 · ' + skipped.length));
    const missList = el('div', '', 'lore-miss-list');
    missList.append(...(skipped.length ? skipped.map((row) => {
      const line = el('div', '', 'lore-miss');
      const book = books.find((b) => b.id === row.book_id)?.name;
      line.append(el('strong', row.title || '条目 ' + row.uid), el('small', (book ? book + ' · ' : '') + (WHY[row.why] || row.why || '')));
      return line;
    }) : [el('p', '没有', 'lore-empty')]));
    off.append(missList);
    const cols = el('div', '', 'lore-test-cols');
    cols.append(on, off);
    const previews = el('div', '', 'lore-previews');
    for (const [label, value] of [['这一轮的背景块', result.turn_preview], ['系统提示词里的世界书', result.system_preview]]) {
      const block = el('details', '', 'lore-preview');
      block.open = Boolean(value);
      block.append(el('summary', label + (value ? ' · ' + value.length + ' 字' : ' · 空')), el('pre', value || '（空）'));
      previews.append(block);
    }
    out.replaceChildren(cols, previews);
  }

  // ---------- 入口 ----------
  async function show(container) {
    if (root !== container || !container.firstChild) {
      root = container;
      testBox = null;
      const fileInput = el('input');
      fileInput.type = 'file';
      fileInput.accept = '.json,.png,application/json,image/png';
      fileInput.hidden = true;
      fileInput.onchange = () => { const file = fileInput.files[0]; fileInput.value = ''; if (file) void importFile(file); };
      const toolbar = el('div', '', 'lore-toolbar');
      toolbar.append(button('导入…', () => fileInput.click(), ''), fileInput, el('p', '', 'lore-notice'));
      toolbar.querySelector('.lore-notice').setAttribute('role', 'status');
      const warnings = el('div', '', 'lore-warnings');
      warnings.hidden = true;
      root.replaceChildren(toolbar, warnings, el('div', '', 'lore-books'), el('div', '', 'lore-editor'));
      paintEditor();
    }
    try { conditionFields = ((await LP.conditions.meta()).condition_fields || []).filter((f) => !f.key.startsWith('event.')); }
    catch { conditionFields = []; }
    if (!dirty) await loadList();
    if (draft && !dirty) paintEditor();
  }

  global.LP = global.LP || {};
  // 设置页的「有改动没保存」也认这本书：isDirty 看有没有改，discard 是离开时选了「不保存」
  global.LP.settingsLore = { show, isDirty: () => dirty && Boolean(root?.isConnected), discard: () => { if (dirty) void discard(); } };
})(window);
