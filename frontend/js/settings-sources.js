/* settings-sources.js — 设置 › 阅读 › 来源 和 Zotero。
   来源：GET/POST/PATCH/DELETE /api/reader/sources、PUT /sources/order、POST /sources/test。
   加一个来源先只问地址：点「试一下」就抓回前三条给你看；RSS / JSON 和字段对应关系自动去猜，猜对了直接存；
   猜不对或要密钥时，高级项在「更多」里。内置来源只能开关。密钥只显示掩码。
   Zotero：GET/PUT /api/reader/zotero/connection、POST /connection/test。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const base = '/api/reader';
  const FIELDS = [['items', '结果列表'], ['title', '标题'], ['url', '原文网址'], ['text', '正文 / 摘要'], ['date', '日期'], ['authors', '作者列表'], ['author_name', '作者名'], ['image', '配图'], ['doi', 'DOI']];
  // JSON 接口常见的写法：先猜结果列表在哪，再猜标题、网址、正文叫什么
  // 只试最常见的几种；猜不中就把「更多」打开让人填，不去连发一串注定失败的请求
  const GUESS_ITEMS = ['items', 'results', 'data', 'articles'];
  const GUESS_TITLE = ['title', 'name', 'headline'];
  const GUESS_URL = ['url', 'link'];
  const GUESS_TEXT = ['summary', 'description', 'abstract', 'content', 'text', 'body', 'excerpt'];
  const languageLabel = (tag) => LP.languages.label(tag);
  const NOT_RECOGNISED = '没认出来，在「更多」里填';

  async function request(path, method = 'GET', payload) {
    const options = { method, cache: 'no-store' };
    if (payload !== undefined) { options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(payload); }
    const response = await fetch(base + path, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = body.detail;
      const error = new Error(Array.isArray(detail) ? detail.map((d) => d.msg?.replace(/^Value error, /, '')).filter(Boolean).join('。') : detail || '没连上，再试一次');
      error.status = response.status;
      throw error;
    }
    return body;
  }
  // 试连失败：后端可能回 422，也可能回 200 {ok:false, message}，两种都当成失败的原因
  async function test(source, query) {
    const r = await request('/sources/test', 'POST', { source, ...(query ? { query } : {}) });
    if (r.ok === false) throw new Error(r.message || '没抓到内容');
    return r;
  }

  function hostName(url) {
    try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; }
  }
  const looksLikeFeed = (url) => /(rss|atom|feed|\.xml)(\b|$)/i.test(url);

  function mount(panel, { onChange } = {}) {
    let sources = [];
    let editing = null;   // {id?, draft, builtin}
    panel.innerHTML = `
      <div class="src-list" data-src="list"></div>
      <p class="src-notice" role="status" data-src="notice"></p>`;
    const list = panel.querySelector('[data-src="list"]');
    const notice = (text, tone = '') => { const p = panel.querySelector('[data-src="notice"]'); p.textContent = text || ''; p.dataset.tone = tone; };

    async function load() {
      try { sources = (await request('/sources')).items || []; paint(); }
      catch (error) { notice(LP.util.message(error), 'bad'); }
    }
    async function changed() { await load(); onChange?.(); }

    function paint() {
      list.replaceChildren();
      for (const [kind, label] of [['article', '文章'], ['paper', '论文']]) {
        const group = sources.filter((s) => s.kind === kind);
        list.append(el('h5', label + ' · ' + group.length, 'src-group'));
        for (const item of group) {
          list.append(row(item, group));
          if (editing?.id === item.id) list.append(editor());
        }
        if (editing && !editing.id && editing.draft.kind === kind) list.append(editor());
        const add = button('＋ 添加' + label + '来源', () => startNew({ kind }), 'src-add');
        if (!(editing && !editing.id)) list.append(add);
      }
    }

    function row(item, group) {
      const line = el('article', '', 'src-row' + (item.enabled ? '' : ' off'));
      const main = el('div', '', 'src-main');
      const name = el('strong', item.name);
      const tags = el('span', '', 'src-tags');
      if (item.lang) tags.append(el('span', languageLabel(item.lang), 'src-tag'));
      tags.append(el('span', item.format === 'rss' ? 'RSS' : 'JSON', 'src-tag'));
      if (item.builtin) tags.append(el('span', '内置', 'src-tag muted'));
      if (item.auth?.configured) tags.append(el('span', '密钥 ' + (item.auth.key_mask || ''), 'src-tag'));
      main.append(name, tags);
      if (!item.builtin) main.append(el('small', hostName(item.url), 'src-host'));
      const result = el('span', '', 'src-result');
      const actions = el('div', '', 'src-actions');
      const index = group.indexOf(item);
      const up = button('↑', () => void move(item, -1), 'src-move'); up.disabled = index === 0; up.setAttribute('aria-label', '上移');
      const down = button('↓', () => void move(item, 1), 'src-move'); down.disabled = index === group.length - 1; down.setAttribute('aria-label', '下移');
      const probe = button('试一下', async () => {
        probe.disabled = true; result.textContent = '…'; result.dataset.tone = '';
        try {
          const r = await request('/sources/' + encodeURIComponent(item.id) + '/test', 'POST', item.kind === 'paper' ? { query: 'language learning' } : {});
          result.textContent = r.ok === false ? (r.message || '没抓到') : '✓ ' + (r.count ?? r.items?.length ?? 0);
          result.dataset.tone = r.ok === false ? 'bad' : 'ok';
        } catch (error) { result.textContent = LP.util.message(error); result.dataset.tone = 'bad'; }
        finally { probe.disabled = false; }
      }, 'btn-sm');
      actions.append(result, probe, up, down);
      if (!item.builtin) {
        actions.append(button('编辑', () => { editing = { id: item.id, draft: structuredClone(item) }; paint(); }, 'btn-sm'));
        actions.append(button('删除', async () => {
          const ok = await LP.util.confirm({ title: '删掉「' + item.name + '」？', ok: '删除' });
          if (!ok) return;
          try { await request('/sources/' + encodeURIComponent(item.id), 'DELETE'); await changed(); }
          catch (error) { notice(LP.util.message(error), 'bad'); }
        }, 'btn-sm row-delete'));
      }
      const toggle = el('input');
      toggle.type = 'checkbox'; toggle.setAttribute('role', 'switch'); toggle.checked = Boolean(item.enabled);
      toggle.setAttribute('aria-label', item.name + ' 启用');
      toggle.onchange = async () => {
        try { await request('/sources/' + encodeURIComponent(item.id), 'PATCH', { enabled: toggle.checked }); item.enabled = toggle.checked; line.classList.toggle('off', !toggle.checked); onChange?.(); }
        catch (error) { toggle.checked = !toggle.checked; notice(LP.util.message(error), 'bad'); }
      };
      actions.append(toggle);
      line.append(main, actions);
      return line;
    }

    async function move(item, step) {
      const ids = sources.map((s) => s.id);
      const group = sources.filter((s) => s.kind === item.kind).map((s) => s.id);
      const neighbor = group[group.indexOf(item.id) + step];
      if (!neighbor) return;
      const a = ids.indexOf(item.id), b = ids.indexOf(neighbor);
      [ids[a], ids[b]] = [ids[b], ids[a]];
      try { await request('/sources/order', 'PUT', { ids }); await changed(); }
      catch (error) { notice(LP.util.message(error), 'bad'); }
    }

    function startNew({ kind = 'article', lang } = {}) {
      editing = { draft: { name: '', kind, lang: lang || (kind === 'article' ? (LP.preferences?.get('readerLanguage') || LP.languages.list()[0]?.tag) : null),
        format: 'rss', url: '', query_param: kind === 'paper' ? 'q' : '', params: {}, fields: {}, auth: { mode: 'none', name: '', prefix: '' }, allow_private: false, enabled: true } };
      paint();
      panel.querySelector('.src-url')?.focus();
    }

    // ---------- 编辑卡片：地址 → 试一下 → 存 ----------
    function editor() {
      const d = editing.draft;
      let preview = editing.preview || null;
      const card = el('section', '', 'src-editor');
      const head = el('div', '', 'src-url-row');
      const url = el('input', '', 'src-url');
      url.type = 'url'; url.value = d.url || ''; url.placeholder = 'https://…'; url.setAttribute('aria-label', '来源地址');
      url.oninput = () => { d.url = url.value.trim(); };   // 换「文章/论文」、改「更多」会重画这张卡：刚粘的地址要留着
      const go = button('试一下', () => void probe(), 'primary');
      head.append(url, go);
      url.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); void probe(); } });

      const meta = el('div', '', 'src-meta');
      const seg = el('div', '', 'src-seg');
      for (const [kind, label] of [['article', '文章'], ['paper', '论文']]) {
        const b = button(label, () => { d.kind = kind; if (kind === 'paper' && !d.query_param) d.query_param = 'q'; if (kind === 'article' && !d.lang) d.lang = LP.languages.list()[0]?.tag; paint(); }, 'src-seg-opt');
        b.setAttribute('aria-pressed', String(d.kind === kind));
        seg.append(b);
      }
      meta.append(seg);
      if (d.kind === 'article') {
        const lang = el('select', '', 'src-lang');
        lang.setAttribute('aria-label', '文章语言');
        lang.append(...LP.languages.list().map((l) => new Option(l.label, l.tag)));
        lang.value = d.lang || '';
        lang.onchange = () => { d.lang = lang.value; };
        meta.append(lang);
      }
      const name = el('input', '', 'src-name');
      name.value = d.name || ''; name.placeholder = hostName(d.url) || '名字'; name.maxLength = 80; name.setAttribute('aria-label', '来源名字');
      name.oninput = () => { d.name = name.value; };
      meta.append(name);

      const out = el('div', '', 'src-preview');
      const paintPreview = () => {
        out.replaceChildren();
        if (!preview) return;
        if (preview.error) { out.append(el('p', preview.error, 'src-error')); return; }
        const items = (preview.items || []).slice(0, 3);
        out.append(el('p', '✓ ' + (preview.count ?? items.length) + ' · ' + (d.format === 'rss' ? 'RSS' : 'JSON'), 'src-ok'));
        out.append(...items.map((it) => {
          const c = el('article', '', 'src-sample');
          c.append(el('strong', it.title || '—'), el('p', (it.text || '').replace(/\s+/g, ' ').slice(0, 140)));
          if (it.date) c.append(el('small', it.date));
          return c;
        }));
      };
      paintPreview();

      // 更多：格式、字段对应、搜索参数、密钥、内网
      const more = el('details', '', 'src-more');
      more.open = Boolean(editing.moreOpen);
      more.ontoggle = () => { editing.moreOpen = more.open; };
      more.append(el('summary', '更多'));
      const grid = el('div', '', 'lore-grid');
      const field = (label, input, wide) => { const w = el('label', '', 'lore-field' + (wide ? ' lore-wide' : '')); w.append(el('span', label), input); return w; };
      const format = el('select'); format.append(new Option('RSS / Atom', 'rss'), new Option('JSON', 'json')); format.value = d.format;
      format.onchange = () => { d.format = format.value; paint(); };
      grid.append(field('格式', format));
      if (d.kind === 'paper') {
        const q = el('input'); q.value = d.query_param || ''; q.maxLength = 80; q.oninput = () => { d.query_param = q.value.trim(); };
        grid.append(field('搜索参数', q));
      }
      if (d.format === 'json') {
        for (const [key, label] of FIELDS) {
          const input = el('input'); input.value = d.fields?.[key] || ''; input.maxLength = 160; input.spellcheck = false;
          input.oninput = () => { d.fields = { ...d.fields, [key]: input.value.trim() }; };
          grid.append(field(label, input));
        }
      }
      const mode = el('select'); mode.append(new Option('不用密钥', 'none'), new Option('放在请求头', 'header'), new Option('放在网址参数', 'query'));
      mode.value = d.auth?.mode || 'none';
      mode.onchange = () => { d.auth = { ...d.auth, mode: mode.value }; paint(); };
      grid.append(field('密钥', mode));
      if (mode.value !== 'none') {
        const keyName = el('input'); keyName.value = d.auth?.name || ''; keyName.placeholder = mode.value === 'header' ? 'Authorization' : 'api_key';
        keyName.oninput = () => { d.auth = { ...d.auth, name: keyName.value.trim() }; };
        const prefix = el('input'); prefix.value = d.auth?.prefix || ''; prefix.placeholder = mode.value === 'header' ? 'Bearer ' : '';
        prefix.oninput = () => { d.auth = { ...d.auth, prefix: prefix.value }; };
        const key = el('input'); key.type = 'password'; key.autocomplete = 'new-password'; key.placeholder = d.auth?.key_mask || '';
        key.oninput = () => { d.auth = { ...d.auth, key: key.value }; };
        grid.append(field('名字', keyName), field('前缀', prefix), field('值', key));
      }
      const priv = el('label', '', 'settings-check lore-wide');
      const privBox = el('input'); privBox.type = 'checkbox'; privBox.checked = Boolean(d.allow_private);
      privBox.onchange = () => { d.allow_private = privBox.checked; };
      priv.append(privBox, document.createTextNode('允许本机 / 内网地址'));
      grid.append(priv);
      more.append(grid);

      const bar = el('div', '', 'src-bar');
      const save = button('保存', () => void store(), 'primary');
      save.disabled = !preview || Boolean(preview.error);
      if (editing.id) save.disabled = false;
      bar.append(save, button('取消', () => { editing = null; paint(); }, ''));
      card.append(head, meta, out, more, bar);

      async function probe() {
        d.url = url.value.trim();
        if (!d.url) { url.focus(); return; }
        go.disabled = true; save.disabled = true;
        out.replaceChildren(el('p', '…', 'src-wait'));
        try {
          preview = await guess(d);
          if (!d.name) d.name = preview.title || hostName(d.url);
        } catch (error) { preview = { error: LP.util.message(error) }; editing.moreOpen = true; }
        editing.preview = preview;
        go.disabled = false;
        paint();
      }
      async function store() {
        const payload = clean(d);
        save.disabled = true;
        try {
          if (editing.id) await request('/sources/' + encodeURIComponent(editing.id), 'PATCH', payload);
          else await request('/sources', 'POST', payload);
          editing = null;
          await changed();
          notice('已保存', 'ok');
        } catch (error) { notice(LP.util.message(error), 'bad'); save.disabled = false; }
      }
      return card;
    }

    // 猜：地址像订阅源先试 RSS，否则先试 JSON；JSON 依次猜结果列表、标题/网址、正文
    async function guess(d) {
      const query = d.kind === 'paper' ? 'language learning' : undefined;
      const draft = (patch) => clean({ ...d, name: d.name || hostName(d.url) || 'source', ...patch });
      // 订阅源先试 RSS；看着像 JSON 接口的先试 JSON；都不像的先试 RSS（一次就能判断）
      const tries = looksLikeFeed(d.url) ? ['rss', 'json'] : /\.json(\?|$)|\/api\/|\/v\d+\//i.test(d.url) ? ['json', 'rss'] : ['rss', 'json'];
      let lastError = null;
      for (const format of tries) {
        try {
          if (format === 'rss') {
            const r = await test(draft({ format: 'rss', fields: {} }), query);
            if (r.ok !== false && (r.count || r.items?.length)) { d.format = 'rss'; d.fields = {}; return r; }
            lastError = r.message || lastError;
            continue;
          }
          // JSON：用户在「更多」里填过的优先
          if (d.format === 'json' && d.fields?.items && d.fields?.title) {
            const r = await test(draft({ format: 'json' }), query);
            if (r.ok !== false) return r;
          }
          for (const items of GUESS_ITEMS) {
            let r = null;
            let found = { items, title: 'title', url: 'url' };
            try { r = await test(draft({ format: 'json', fields: { ...found, text: 'summary' } }), query); }
            catch (error) {
              if (/没有指向数组|格式与配置不符/.test(error.message)) continue;
              if (!/没有读到标题/.test(error.message)) throw error;
            }
            // 列表找到了，但标题或网址不叫 title / url：挨个试
            for (const title of r ? [] : GUESS_TITLE) {
              for (const link of GUESS_URL) {
                try { r = await test(draft({ format: 'json', fields: { items, title, url: link } }), query); found = { items, title, url: link }; break; }
                catch { r = null; }
              }
              if (r) break;
            }
            if (!r) throw new Error(NOT_RECOGNISED);
            d.fields = found;
            // 正文：挑一个抓得到字的
            for (const text of GUESS_TEXT) {
              try {
                const t = await test(draft({ format: 'json', fields: { ...d.fields, text } }), query);
                if ((t.items || []).some((it) => it.text)) { d.fields.text = text; r = t; break; }
              } catch { /* 下一个 */ }
            }
            d.format = 'json';
            return r;
          }
          lastError = NOT_RECOGNISED;
        } catch (error) { lastError = error.message; }
      }
      throw new Error(lastError || '没抓到内容');
    }

    function clean(d) {
      const out = { name: (d.name || hostName(d.url) || '来源').slice(0, 80), kind: d.kind, lang: d.kind === 'article' ? d.lang : (d.lang || null), format: d.format,
        url: d.url, query_param: d.kind === 'paper' ? (d.query_param || 'q') : (d.query_param || ''), params: d.params || {},
        fields: Object.fromEntries(Object.entries(d.fields || {}).filter(([, v]) => v)), allow_private: Boolean(d.allow_private), enabled: d.enabled !== false };
      const auth = d.auth || { mode: 'none' };
      out.auth = auth.mode === 'none' ? { mode: 'none' } : { mode: auth.mode, name: auth.name || '', prefix: auth.prefix || '', ...(auth.key ? { key: auth.key } : {}) };
      return out;
    }

    load();
    return { refresh: load, addSource: (opts) => startNew(opts) };
  }

  // ---------- Zotero ----------
  function mountZotero(panel) {
    panel.innerHTML = `
      <div class="zot">
        <img class="zot-logo" src="assets/icons/notebook.png" alt="">
        <div class="zot-fields">
          <label class="lore-field"><span>端口</span><input type="number" min="1024" max="65535" data-zot="port"></label>
          <label class="lore-field"><span>书库</span><span class="zot-lib"><select data-zot="kind"><option value="users">我的书库</option><option value="groups">群组</option></select>
            <input type="number" min="1" data-zot="group" aria-label="群组编号" placeholder="群组编号" hidden></span></label>
        </div>
        <div class="zot-actions"><span class="zot-state" data-zot="state" role="status"></span>
          <button type="button" class="btn-sm" data-zot="test">试一下</button><button type="button" class="btn-sm primary" data-zot="save">保存</button></div>
      </div>`;
    const $ = (k) => panel.querySelector(`[data-zot="${k}"]`);
    const state = (text, tone) => { $('state').textContent = text; $('state').dataset.tone = tone || ''; };
    const value = () => ({ port: Number($('port').value) || 23119, library: $('kind').value === 'users' ? 'users/0' : 'groups/' + (Number($('group').value) || 0) });
    $('kind').onchange = () => { $('group').hidden = $('kind').value !== 'groups'; };
    async function load() {
      try {
        const c = await request('/zotero/connection');
        $('port').value = c.port || 23119;
        const [kind, id] = String(c.library || 'users/0').split('/');
        $('kind').value = kind === 'groups' ? 'groups' : 'users';
        $('group').value = kind === 'groups' ? id : '';
        $('group').hidden = kind !== 'groups';
      } catch (error) { state(LP.util.message(error), 'bad'); }
    }
    $('test').onclick = async () => {
      state('…');
      try { await request('/zotero/connection/test', 'POST', value()); state('✓ 连上了', 'ok'); }
      catch (error) { state(LP.util.message(error), 'bad'); }
    };
    $('save').onclick = async () => {
      try { await request('/zotero/connection', 'PUT', value()); state('已保存', 'ok'); }
      catch (error) { state(LP.util.message(error), 'bad'); }
    };
    load();
    return { refresh: load };
  }

  global.LP = global.LP || {};
  global.LP.settingsSources = { mount, mountZotero };
})(window);
