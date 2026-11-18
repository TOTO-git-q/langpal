/* settings-models.js — 设置 › 模型与账号。四个引擎：Claude / ChatGPT / DeepSeek / 自定义端点（docs/model-capabilities.md）。
   上面一块是聊天用哪个：主引擎、讲解与出题、出错换备用，外加「现在实际在用」和降级状态；
   下面「账号与密钥」四张卡并排：每张卡的模型 = 连上接口后读到什么显示什么，思考档位 = 这个模型声明的档位
   （接口没声明时是默认列表，档位框画成虚线）。ChatGPT 登录走桌面壳 IPC，没有就开浏览器，链接始终能复制。
   读写：GET/PUT /api/settings、GET /api/engines/status、GET /api/engines/{e}/models、POST /api/engines/{e}/reasoning、
   /api/workspace-agent/siwc/*、GET /api/usage。 */
(function (global) {
  'use strict';

  const { el, button } = global.LP.util;
  const ENGINES = ['claude', 'chatgpt', 'deepseek', 'custom'];
  const NAMES = { claude: 'Claude', chatgpt: 'ChatGPT', deepseek: 'DeepSeek', custom: '自定义接口' };
  const engineName = (id) => NAMES[id] || id || '未知';
  const masked = (value) => typeof value === 'string' && value.startsWith('····');
  const SIWC = '/api/workspace-agent/siwc';

  async function call(path, method = 'GET', body) {
    const options = { method, cache: 'no-store' };
    if (body !== undefined) { options.headers = { 'Content-Type': 'application/json' }; options.body = JSON.stringify(body); }
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      const error = new Error(typeof detail === 'string' ? detail : detail?.message || (Array.isArray(detail) ? detail.map((d) => d.msg).join('；') : '请求失败（' + response.status + '）'));
      error.status = response.status;
      throw error;
    }
    return data;
  }

  const engineOptions = (extra = '') => extra + ENGINES.map((id) => `<option value="${id}">${NAMES[id]}</option>`).join('');
  const modelRow = (engine) => `
    <div class="settings-fields engine-model-row">
      <div class="field"><label for="f-model-${engine}">模型</label>
        <div class="key-row"><select id="f-model-${engine}" data-model="${engine}"></select>
          <button type="button" class="btn-sm engine-reload" data-read-models="${engine}" aria-label="重新读取模型" title="重新读取模型">↻</button></div>
        <p class="settings-note engine-models-note" data-models-status="${engine}" role="status"></p></div>
      <div class="field"><label for="f-reasoning-${engine}">思考档位</label>
        <select id="f-reasoning-${engine}" data-reasoning="${engine}"></select></div>
    </div>`;
  const keyField = (engine) => `
    <div class="field"><label for="f-${engine}-key">API 密钥</label>
      <div class="key-row"><input type="password" id="f-${engine}-key" autocomplete="new-password" placeholder="未设置">
        <button type="button" class="btn-sm primary" data-save-key="${engine}">保存</button>
        <button type="button" class="btn-sm" data-clear-key="${engine}">清除</button></div>
    </div>`;

  const markup = `
    <div class="engine-now" data-engine-now role="status"></div>
    <div class="settings-block">
      <h2 class="settings-block-title">聊天</h2>
      <div class="settings-fields">
        <div class="field"><label for="f-chat-engine">聊天用</label><select id="f-chat-engine">${engineOptions()}</select></div>
        <div class="field"><label for="f-utility-engine">讲解与出题</label><select id="f-utility-engine">${engineOptions('<option value="auto">自动</option>')}</select></div>
      </div>
      <label class="settings-check"><input type="checkbox" role="switch" id="f-chat-fallback">出错时换一家</label>
    </div>
    <div class="settings-block">
      <h2 class="settings-block-title">账号与密钥</h2>
      <div class="engine-cards">
        <section class="engine-card" data-engine-block="claude">
          <h3><span class="engine-dot"></span>Claude <span class="engine-state" data-engine-state="claude"></span></h3>
          <p class="engine-hint" data-claude-login hidden>没登录：在终端里运行 <code>claude login</code></p>
          ${modelRow('claude')}
          <div class="field"><label for="f-vision-engine">聊天里的图片</label>
            <select id="f-vision-engine"><option value="claude">交给 Claude 看</option><option value="none">不看图</option></select></div>
          <div class="usage-panel" data-usage-panel></div>
        </section>
        <section class="engine-card" data-engine-block="chatgpt">
          <h3><span class="engine-dot"></span>ChatGPT <span class="engine-state" data-engine-state="chatgpt"></span></h3>
          <div class="gpt-account" data-gpt="account"></div>
          <div class="gpt-login" data-gpt="login" hidden>
            <div class="key-row"><input type="text" readonly data-gpt="link" aria-label="登录链接"><button type="button" class="btn-sm" data-gpt="copy">复制</button></div>
          </div>
          <div class="engine-model-wrap" data-gpt="models">${modelRow('chatgpt')}</div>
        </section>
        <section class="engine-card" data-engine-block="deepseek">
          <h3><span class="engine-dot"></span>DeepSeek <span class="engine-state" data-engine-state="deepseek"></span></h3>
          ${keyField('deepseek')}
          ${modelRow('deepseek')}
        </section>
        <section class="engine-card" data-engine-block="custom">
          <h3><span class="engine-dot"></span>自定义接口 <span class="engine-state" data-engine-state="custom"></span></h3>
          <div class="field"><label for="f-custom-base-url">地址</label>
            <div class="key-row"><input type="text" id="f-custom-base-url" placeholder="https://…/v1"><button type="button" class="btn-sm primary" data-save-custom>保存</button></div></div>
          ${keyField('custom')}
          ${modelRow('custom')}
        </section>
      </div>
    </div>`;

  function wire(root) {
    const $ = (sel) => root.querySelector(sel);
    const f = {
      engine: $('#f-chat-engine'), utility: $('#f-utility-engine'), fallback: $('#f-chat-fallback'), vision: $('#f-vision-engine'),
      deepseekKey: $('#f-deepseek-key'), customUrl: $('#f-custom-base-url'), customKey: $('#f-custom-key'),
      now: $('[data-engine-now]'), usage: $('[data-usage-panel]'), login: $('[data-claude-login]'),
    };
    let status = null;
    let settings = {};
    const catalogs = {};       // engine -> [{id,label,reasoning}]
    const catalogReads = {};

    // 改了就存：控件旁边打个勾（失败打叉，原因放在叉的悬停提示里）
    async function save(patch, field) {
      try {
        settings = { ...settings, ...(await LP.api.putSettings(patch) || {}) };
        global.dispatchEvent(new Event('lp:models-changed'));
        void refreshStatus();
        LP.util.tick(field, true);
        return true;
      } catch (error) {
        LP.util.tick(field, false, LP.util.message(error, '没存上'));
        await loadSettings();
        return false;
      }
    }

    async function loadSettings() {
      try { settings = await LP.api.getSettings(); } catch { return; }
      f.engine.value = NAMES[settings.chat_engine] ? settings.chat_engine : 'claude';
      f.utility.value = settings.utility_engine || 'auto';
      f.fallback.checked = (settings.chat_fallback || 'enabled') !== 'none';
      f.vision.value = settings.vision_engine === 'none' ? 'none' : 'claude';
      f.customUrl.value = settings.custom_base_url || '';
      // 密钥：只在 placeholder 上显示掩码，绝不把掩码放进 value
      for (const [input, value] of [[f.deepseekKey, settings.deepseek_api_key], [f.customKey, settings.custom_api_key]]) {
        input.value = '';
        input.placeholder = masked(value) ? value : '未设置';
      }
    }

    // 现在实际在用哪家；出错换了一家时整条变红，写上原来那家用不了
    function renderNow(st) {
      f.now.replaceChildren();
      f.now.classList.toggle('degraded', Boolean(st?.degraded));
      if (!st) { f.now.append(el('span', '读不到')); return; }
      const current = st.current_engine || st.chat_engine;
      const model = st[current]?.model;
      f.now.append(el('strong', '现在用'), el('span', engineName(current) + (model ? ' · ' + model : '')));
      if (st.degraded) f.now.append(el('span', engineName(st.chat_engine) + ' 用不了', 'engine-now-sub bad'));
      const utility = st.utility_effective || st.utility_engine;
      f.now.append(el('span', '讲解与出题：' + (utility === 'none' ? '没有能用的' : engineName(utility)), 'engine-now-sub'));
    }

    const ready = (engine, st = status) => engine === 'claude' ? Boolean(st?.claude?.available)
      : engine === 'chatgpt' ? Boolean(st?.chatgpt?.authorized ?? st?.chatgpt?.configured) : Boolean(st?.[engine]?.configured);

    function setState(engine, ok, text) {
      const tag = $(`[data-engine-state="${engine}"]`);
      tag.textContent = text;
      tag.classList.toggle('ok', ok);
      const card = tag.closest('.engine-card');
      card.classList.toggle('ready', ok);
      card.classList.toggle('in-use', (status?.current_engine || status?.chat_engine) === engine);
    }

    async function refreshStatus() {
      try { status = await LP.api.getEnginesStatus(); } catch { status = null; }
      renderNow(status);
      setState('claude', ready('claude'), ready('claude') ? '已登录' : '未登录');
      f.login.hidden = ready('claude') || !status;
      const gptState = status?.chatgpt || {};
      setState('chatgpt', ready('chatgpt'), ready('chatgpt') ? '已登录' : gptState.authorization_state === 'pending' ? '登录中' : '未登录');
      setState('deepseek', ready('deepseek'), ready('deepseek') ? '已配置' : '未配置');
      setState('custom', ready('custom'), ready('custom') ? '已配置' : '未配置');
      f.usage.hidden = !ready('claude');
      $('[data-gpt="models"]').hidden = !ready('chatgpt');
      return status;
    }

    // ---------- 模型和档位：读到什么显示什么 ----------
    function savedModel(engine) {
      if (engine === 'claude') return settings.chat_model_claude || status?.claude?.model;
      if (engine === 'deepseek') return settings.deepseek_model || status?.deepseek?.model;
      if (engine === 'custom') return settings.custom_model || status?.custom?.model;
      return status?.chatgpt?.model;
    }
    async function loadCatalog(engine) {
      const note = $(`[data-models-status="${engine}"]`);
      const control = $(`[data-read-models="${engine}"]`);
      const select = $(`[data-model="${engine}"]`);
      if (!ready(engine)) {
        catalogs[engine] = null;
        select.replaceChildren(...(savedModel(engine) ? [new Option(savedModel(engine), savedModel(engine))] : []));
        select.disabled = true; control.disabled = true;
        note.textContent = '';
        paintReasoning(engine);
        return;
      }
      const ticket = catalogReads[engine] = (catalogReads[engine] || 0) + 1;
      control.disabled = true; control.classList.add('spin');
      try {
        const data = await call('/api/engines/' + engine + '/models');
        if (ticket !== catalogReads[engine]) return;
        catalogs[engine] = Array.isArray(data) ? data : data.models || [];
        note.textContent = '';
        note.dataset.tone = '';
      } catch (error) {
        if (ticket !== catalogReads[engine]) return;
        catalogs[engine] = null;
        note.textContent = LP.util.message(error, '读不到模型');
        note.dataset.tone = 'bad';
      } finally {
        if (ticket === catalogReads[engine]) { control.disabled = false; control.classList.remove('spin'); }
      }
      paintModels(engine);
    }
    function paintModels(engine) {
      const select = $(`[data-model="${engine}"]`);
      const list = catalogs[engine] || [];
      const current = savedModel(engine);
      const options = list.map((m) => new Option(m.label || m.id, m.id));
      // 存着的模型不在这次读到的表里：照样列出来（样式标灰），不偷偷换掉
      if (current && !list.some((m) => m.id === current)) { const o = new Option(current, current); o.className = 'stale'; options.unshift(o); }
      select.replaceChildren(...options);
      select.disabled = !options.length;
      if (current) select.value = current;
      else if (list[0]) select.value = list[0].id;
      paintReasoning(engine);
    }
    function paintReasoning(engine) {
      const select = $(`[data-reasoning="${engine}"]`);
      const model = (catalogs[engine] || []).find((m) => m.id === $(`[data-model="${engine}"]`).value);
      const r = model?.reasoning;
      const levels = [...(r?.levels || [])];
      if (engine === 'claude' && !levels.some((l) => l.id === 'off')) levels.unshift({ id: 'off', label: '关闭' });
      const NICE = { off: '关闭', none: '不思考', minimal: '最少', low: '低', medium: '中', high: '高', xhigh: '很高', max: '最高' };
      select.replaceChildren(...levels.map((l) => new Option(!l.label || l.label === l.id ? NICE[l.id] || l.id : l.label, l.id)));
      if (engine !== 'claude') select.prepend(new Option('默认', ''));
      const fallback = engine === 'claude' ? (settings.chat_reasoning_claude || 'off') : '';
      select.value = r?.selected ?? fallback;
      if (select.selectedIndex < 0) select.selectedIndex = 0;
      select.disabled = !model;
      // 接口没声明档位：给的是默认列表，框画成虚线
      select.classList.toggle('guessed', r?.source === 'default');
    }
    async function chooseModel(engine) {
      const field = $(`[data-model="${engine}"]`);
      const model = field.value;
      paintReasoning(engine);
      const effort = $(`[data-reasoning="${engine}"]`).value || null;
      if (engine === 'claude') { await save({ chat_model_claude: model }, field); return; }
      if (engine === 'deepseek') { await save({ deepseek_model: model }, field); return; }
      if (engine === 'custom') { await save({ custom_model: model }, field); return; }
      await chooseReasoning(engine, model, effort);
    }
    async function chooseReasoning(engine, model = $(`[data-model="${engine}"]`).value, effort = $(`[data-reasoning="${engine}"]`).value || null) {
      const field = $(`[data-reasoning="${engine}"]`);
      try {
        await call('/api/engines/' + engine + '/reasoning', 'POST', { model, effort });
        const entry = (catalogs[engine] || []).find((m) => m.id === model);
        if (entry?.reasoning) entry.reasoning.selected = effort;
        if (engine === 'claude') settings.chat_reasoning_claude = effort || 'off';
        global.dispatchEvent(new Event('lp:models-changed'));
        void refreshStatus();
        LP.util.tick(field, true);
      } catch (error) {
        LP.util.tick(field, false, LP.util.message(error, '没存上'));
        paintReasoning(engine);
      }
    }
    for (const engine of ENGINES) {
      $(`[data-model="${engine}"]`).onchange = () => void chooseModel(engine);
      $(`[data-reasoning="${engine}"]`).onchange = () => void chooseReasoning(engine);
      $(`[data-read-models="${engine}"]`).onclick = () => void loadCatalog(engine);
    }

    // ---------- 修改即保存 ----------
    f.engine.onchange = () => save({ chat_engine: f.engine.value }, f.engine);
    f.utility.onchange = () => save({ utility_engine: f.utility.value }, f.utility);
    f.fallback.onchange = () => save({ chat_fallback: f.fallback.checked ? 'enabled' : 'none' }, f.fallback);
    f.vision.onchange = () => save({ vision_engine: f.vision.value }, f.vision);
    const afterKey = async (engine) => { await loadSettings(); await refreshStatus(); void loadCatalog(engine); };
    $('[data-save-key="deepseek"]').onclick = async () => {
      const value = f.deepseekKey.value.trim();
      if (!value) { f.deepseekKey.focus(); return; }
      if (await save({ deepseek_api_key: value }, $('[data-clear-key="deepseek"]'))) await afterKey('deepseek');
    };
    $('[data-clear-key="deepseek"]').onclick = async () => { if (await save({ deepseek_api_key: '' }, $('[data-clear-key="deepseek"]'))) await afterKey('deepseek'); };
    $('[data-save-custom]').onclick = async () => {
      if (await save({ custom_base_url: f.customUrl.value.trim() }, $('[data-save-custom]'))) await afterKey('custom');
    };
    // 存密钥：地址框空着时不会把已存的地址抹掉（地址填了新的才一起存）
    $('[data-save-key="custom"]').onclick = async () => {
      const value = f.customKey.value.trim(), url = f.customUrl.value.trim();
      if (!value) { f.customKey.focus(); return; }
      const patch = { custom_api_key: value };
      if (url && url !== (settings.custom_base_url || '')) patch.custom_base_url = url;
      if (await save(patch, $('[data-clear-key="custom"]'))) await afterKey('custom');
    };
    $('[data-clear-key="custom"]').onclick = async () => { if (await save({ custom_api_key: '' }, $('[data-clear-key="custom"]'))) await afterKey('custom'); };

    // ---------- ChatGPT 账号 ----------
    let gpt = null;          // GET siwc/status
    let polling = null;
    const account = $('[data-gpt="account"]');
    const loginBox = $('[data-gpt="login"]');
    const link = $('[data-gpt="link"]');
    function paintAccount() {
      account.replaceChildren();
      const state = gpt?.authorization_state;
      if (state === 'authorized' || gpt?.configured) {
        account.append(el('span', gpt.account_label || 'ChatGPT', 'gpt-who'),
          button('试一下', async (event) => {
            const b = event.currentTarget; b.disabled = true;
            try { await call(SIWC + '/test', 'POST'); LP.util.tick(b, true); }
            catch (error) { LP.util.tick(b, false, LP.util.message(error, '没连上')); }
            finally { b.disabled = false; }
          }, 'btn-sm'),
          button('退出', async () => {
            const ok = await LP.util.confirm({ title: '退出 ChatGPT？', text: gpt.account_label || '', ok: '退出' });
            if (!ok) return;
            try { await call(SIWC + '/logout', 'POST'); } catch (error) { LP.toast?.(LP.util.message(error, '没退出，再试一次')); }
            await refreshAccount();
          }, 'btn-sm'));
        loginBox.hidden = true;
      } else if (state === 'pending' || polling) {
        account.append(el('span', '等你在浏览器里登录…', 'gpt-wait'), button('取消', async () => {
          stopPolling();
          try { await call(SIWC + '/cancel', 'POST'); } catch { /* 已经结束 */ }
          link.value = '';
          await refreshAccount();
        }, 'btn-sm'));
        loginBox.hidden = !link.value;
      } else {
        account.append(button('登录 ChatGPT', () => void login(), 'btn-sm primary gpt-login-btn'));
        loginBox.hidden = !link.value;
      }
    }
    async function refreshAccount() {
      try { gpt = await call(SIWC + '/status'); paintAccount(); }
      catch (error) { gpt = null; account.replaceChildren(el('span', LP.util.message(error, '读不到'), 'gpt-error')); }
      await refreshStatus();
      if (ready('chatgpt')) void loadCatalog('chatgpt');
    }
    async function login() {
      const b = account.querySelector('.gpt-login-btn');
      if (b) b.disabled = true;
      let result;
      try { result = await call(SIWC + '/login', 'POST', { approved: true }); }
      catch (error) { LP.toast?.(LP.util.message(error, '没打开登录页，再试一次')); if (b) b.disabled = false; return; }
      link.value = result.browser_url || '';
      // 有桌面壳走壳的 IPC（系统浏览器）；没有就新开窗口。哪条路都把链接摆出来能复制（没打开时链接框标红）
      let opened = false;
      try {
        if (global.langpalDesktop?.openChatGPTLogin) opened = Boolean((await global.langpalDesktop.openChatGPTLogin(link.value))?.opened);
        else opened = Boolean(global.open(link.value, '_blank'));
      } catch (error) { console.warn(error); }
      loginBox.dataset.opened = String(opened);
      startPolling((Number(result.expires_in) || 300) * 1000);
      paintAccount();
    }
    function startPolling(ms) {
      stopPolling();
      const until = Date.now() + ms;
      polling = setInterval(async () => {
        if (Date.now() > until || !root.isConnected) { stopPolling(); paintAccount(); return; }
        try {
          const next = await call(SIWC + '/status');
          gpt = next;
          if (next.authorization_state === 'authorized' || next.configured) { stopPolling(); link.value = ''; await refreshAccount(); }
        } catch { /* 下一轮再看 */ }
      }, 2000);
    }
    function stopPolling() { clearInterval(polling); polling = null; }
    $('[data-gpt="copy"]').onclick = async () => {
      link.select();
      try { await navigator.clipboard.writeText(link.value); } catch { document.execCommand?.('copy'); }
      LP.util.tick($('[data-gpt="copy"]'), true);
    };

    // ---------- Claude 周额度（剩余） ----------
    function fmtReset(iso) {
      const d = new Date(iso);
      if (!iso || !Number.isFinite(d.getTime())) return '';
      return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }
    function renderUsage(u) {
      const rows = [];
      if (u?.available && u.five_hour_pct != null) rows.push({ label: '5 小时剩余', left: 100 - u.five_hour_pct, resets: u.five_hour_resets });
      if (u?.available && u.seven_day_pct != null) rows.push({ label: '本周剩余', left: 100 - u.seven_day_pct, resets: u.seven_day_resets });
      f.usage.replaceChildren(...(rows.length ? rows.map((r) => {
        const row = el('div', '', 'usage-row' + (r.left <= 20 ? ' hot' : ''));
        const bar = el('span', '', 'usage-bar');
        bar.style.setProperty('--left', Math.max(0, Math.min(100, r.left)) + '%');
        row.append(el('span', r.label, 'usage-label'), bar, el('b', Math.round(r.left) + '%', 'usage-pct'));
        if (r.resets) row.append(el('span', fmtReset(r.resets) + ' 重置', 'usage-reset'));
        return row;
      }) : [el('div', '读不到额度', 'row-card muted')]));
    }

    async function refresh() {
      await loadSettings();
      await refreshStatus();
      try { renderUsage(await LP.api.getUsage()); } catch { renderUsage(null); }
      try { gpt = await call(SIWC + '/status'); paintAccount(); } catch (error) { account.replaceChildren(el('span', LP.util.message(error, '读不到'), 'gpt-error')); }
      await Promise.all(ENGINES.map(loadCatalog));
    }
    return { refresh, refreshStatus, renderUsage, status: () => status };
  }

  global.LP = global.LP || {};
  global.LP.settingsModels = { markup, wire, engineName, NAMES };
})(window);
