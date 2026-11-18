/* The workspace harness plans changes. The app commits the reviewed proposal. */
(function (global) {
  'use strict';
  const examples = [
    ['选一门课程', '帮我选择日语默认课程。'],
    ['调整听力', '帮我调整听力练习安排。'],
    ['整理世界书', '帮我整理角色的世界书。'],
  ];
  const reviewKeys = ['reviewKind', 'reviewLanguage'];
  const fieldLabels = { title:'标题', mode:'学习方式', preset:'课程目标', book:'世界书', world_book_ids:'关联世界书', relation:'关系', tone:'语气', interests:'兴趣', free_text:'角色描述', theme: '底色', font_size: '字号', line_height: '行距', max_width: '行宽', enabled: '启用', language: '语言', name: '名称' };
  const valueLabels = { lilac: '淡紫', paper: '纸色', night: '夜间' };
  let composer, returnToChat;
  // 设置 › 课程与世界书（课程管家页右上的「课程」、做课后的「去看」）
  function openLibrary(section) {
    global.LP.settings.open('library');
    if (section === 'world') global.LP.settingsTeaching.showWorld();
  }
  let pendingPrefill = null;   // 页面还没挂好时先记下要填的话，挂好再填
  const make = (tag, label, css) => global.LP.util.el(tag, label, css);
  const button = (label, handler) => global.LP.util.button(label, handler);

  async function request(path, body, method) {
    const response = await fetch('/api/workspace-agent/' + path, method ? { method } : body ? {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    } : { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : '管家现在连不上'); error.status = response.status; throw error; }
    return data;
  }
  const say = (error) => global.LP.util.message(error, '管家现在连不上');

  function preferences() {
    return Object.fromEntries(reviewKeys.flatMap(key => {
      const value = global.LP.preferences?.get(key);
      return typeof value === 'string' ? [[key, value]] : [];
    }));
  }

  // 管家改完之后让各页面重读：和聊天里她动手用的是同一份（actions.js）
  const refreshApp = (result) => global.LP.actions.refreshApp(result);

  function displayValue(value) {
    if (value == null) return '—';
    if (typeof value === 'boolean') return value ? '开启' : '关闭';
    if (Array.isArray(value)) return value.length + ' 项';
    if (typeof value === 'object') return String(value.title || value.name || Object.keys(value).length + ' 项');
    return value === '' ? '全部' : (Object.hasOwn(valueLabels, value) ? valueLabels[value] : String(value));
  }

  function comparison(before, after) {
    const grid = make('div', '', 'workspace-agent-comparison');
    for (const [value, label] of [[before, '现在'], [after, '改成']]) {
      const group = make('div');
      group.append(make('small', label), make('p', displayValue(value)));
      grid.append(group);
    }
    return grid;
  }

  function proposalCard(proposal, onCommit, historical = false) {
    const card = make('section', '', 'workspace-agent-proposal');
    const heading = make('h3', '这样安排可以吗？');
    const list = make('div', '', 'workspace-agent-changes');
    for (const change of proposal.changes) {
      if (change.tool === 'course.set') {
        const next = change.after || {}, preview = make('div', '', 'concierge-course-change');
        const title = make('strong', next.preset || '课程');
        if (next.preset) global.LP.api.getTeachingPresets().then(result => { title.textContent = result.items.find(item => item.id === next.preset)?.title || next.preset; }).catch(() => {});
        preview.append(title, make('span', next.mode === 'ambient' ? '使用' : '暂停'));
        list.append(preview); continue;
      }
      const row = make('details', '', 'workspace-agent-change');
      row.open = false;
      row.append(make('summary', change.label));
      const isRecord = value => value && typeof value === 'object' && !Array.isArray(value);
      if (isRecord(change.before) || isRecord(change.after)) {
        const before = change.before || {};
        const after = change.after || {};
        const fields = new Set([...Object.keys(before), ...Object.keys(after)]);
        for (const key of fields) {
          const label = Object.hasOwn(fieldLabels, key) ? fieldLabels[key] : key;
          row.append(make('p', label, 'workspace-agent-field'), comparison(before[key], after[key]));
        }
      } else {
        row.append(comparison(change.before, change.after));
      }
      list.append(row);
    }
    const actions = make('div', '', 'workspace-agent-actions');
    const status = make('span');
    status.setAttribute('role', 'status');
    let pending = false; let deadline = Number(proposal.expires_at) > 0 ? Number(proposal.expires_at) * 1000 : Date.now() + (proposal.expires_in ?? 1800) * 1000;
    let applied = proposal.status === 'applied';
    const EXPIRED = '过期了，再说一遍';
    async function commit(undo) {
      if (pending || historical || Date.now() >= deadline) return;
      pending = true; apply.disabled = undoButton.disabled = true;
      status.textContent = '';
      try {
        const result = await request(undo ? 'undo' : 'apply', { id: proposal.id, preferences: preferences() });
        deadline = Number(result.proposal?.expires_at) > 0 ? Number(result.proposal.expires_at) * 1000 : Date.now() + 1800000;
        await refreshApp(result);
        if (onCommit) await onCommit(undo, proposal);
        const coachActive = result.tools?.includes('coach.preferences') && global.LP.coach?.serviceChanged();
        status.textContent = (undo ? '已撤销' : '已应用') + (coachActive ? ' · 下次口语课起生效' : '');
        applied = !undo;
        apply.hidden = true; undoButton.hidden = undo;
        heading.textContent = '改了什么';
      } catch (error) {
        if ([404,409,410].includes(error.status)) { apply.hidden = undoButton.hidden = true; status.textContent = EXPIRED; }
        else status.textContent = say(error);
      }
      finally { apply.disabled = undoButton.disabled = false; pending = false; }
    }
    const apply = button('使用此安排', () => void commit(false));
    apply.className = 'workspace-agent-primary';
    const undoButton = button('撤销', () => void commit(true));
    undoButton.hidden = true;
    if (applied) { apply.hidden = true; undoButton.hidden = false; heading.textContent = '改了什么'; }
    if (['undone','expired'].includes(proposal.status)) historical = true;
    // 到期：没用的方案收起按钮、说一声过期；已经用上的只收起「撤销」，状态不改口
    if (!historical) { const check = () => { if (Date.now() >= deadline) { apply.hidden = undoButton.hidden = true; if (!applied) status.textContent = EXPIRED; } else setTimeout(check, Math.min(30000, deadline - Date.now())); }; setTimeout(check, Math.min(30000, deadline - Date.now())); }
    if (historical) { apply.hidden = undoButton.hidden = true; heading.textContent = '改了什么'; status.textContent = proposal.status === 'undone' ? '已撤销' : proposal.status === 'applied' ? '已应用' : EXPIRED; }
    actions.append(apply, undoButton, status);
    card.append(heading, list, actions);
    return card;
  }

  function mount(root) {
    if (!root || root.dataset.mounted) return;
    root.dataset.mounted = 'true';
    root.innerHTML = `
      <section class="workspace-agent" aria-busy="true" aria-labelledby="workspace-agent-title">
        <header class="workspace-agent-head">
          <div class="workspace-agent-title"><img src="assets/icons/agent.svg" alt=""><h1 id="workspace-agent-title">课程管家</h1></div>
        </header>
        <div class="workspace-agent-body">
          <aside class="workspace-agent-conversations" aria-label="对话记录"><button type="button" class="workspace-agent-new" disabled>＋ 新对话</button><div class="workspace-agent-conversation-list"></div></aside><div class="workspace-agent-main">
            <div class="workspace-agent-thread" aria-label="课程管家对话" role="log" aria-live="polite">
              <div class="workspace-agent-empty">
                <img src="assets/icons/agent.svg" alt="">
                <h2>今天学点啥？</h2>
                <div class="workspace-agent-examples"></div>
              </div>
            </div>
            <form class="workspace-agent-form">
              
              <textarea aria-label="发送消息" id="workspace-agent-input" rows="2" maxlength="2000" placeholder="想怎么学，直接说"></textarea>
              <div class="workspace-agent-attachments" aria-live="polite"></div><input class="workspace-agent-file" type="file" accept=".txt,.md,.csv,.json,.pdf,.png,.jpg,.jpeg,.webp" multiple hidden><div class="workspace-agent-formbar"><button type="button" class="workspace-agent-attach" disabled aria-label="添加附件" title="添加附件">＋</button>
                <button class="workspace-agent-primary workspace-agent-send" type="submit" aria-label="发送" title="发送（Ctrl+Enter）">
                  <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M10 16V4m-5 5 5-5 5 5"/></svg>
                </button>
              </div>
              <p class="workspace-agent-status" role="status"></p>
            </form>
          </div>
          <aside class="workspace-agent-inspector" aria-label="改了什么" hidden>
            <div class="workspace-agent-inspector-head"><span>改了什么</span><button type="button" aria-label="收起">×</button></div>
            <div class="workspace-agent-inspector-content"></div>
          </aside>
        </div>
      </section>`;
    const input = root.querySelector('textarea');
    composer = input;
    const form = root.querySelector('form');
    const submit = form.querySelector('.workspace-agent-send');
    const status = root.querySelector('.workspace-agent-status');
    const thread = root.querySelector('.workspace-agent-thread');
    const empty = root.querySelector('.workspace-agent-empty');
    const inspector = root.querySelector('.workspace-agent-inspector');
    const inspectorContent = root.querySelector('.workspace-agent-inspector-content');
    const history = []; // Legacy server only; never persist raw attachments in browser storage.
    // 建议小签最多 4 个，最近用过的排前；输入框自动聚焦
    const usedOrder = LP.appShell?.store?.get('agentExamples') || [];
    const ranked = [...examples].sort((a, b) => {
      const ia = usedOrder.indexOf(a[0]), ib = usedOrder.indexOf(b[0]);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    }).slice(0, 4);
    root.querySelector('.workspace-agent-examples').append(...ranked.map(([label, example]) => {
      const action = button(label, () => {
        LP.appShell?.store?.set('agentExamples', [label, ...usedOrder.filter((x) => x !== label)].slice(0, 8));
        input.value = example; input.dispatchEvent(new Event('input')); input.focus();
      });
      return action;
    }));
    requestAnimationFrame(() => { if (root.classList.contains('active') || root.offsetParent) input.focus({ preventScroll: true }); });
    inspector.querySelector('button').onclick = () => {
      inspector.hidden = true;
      input.focus();
    };

    function showInspector(content, title = '改了什么') {
      inspectorContent.replaceChildren(content);
      inspector.querySelector('.workspace-agent-inspector-head span').textContent = title;
      inspector.hidden = false;
    }
    returnToChat = () => { inspector.hidden = true; thread.hidden = false; };
    const preview = button('课程', () => openLibrary());
    const recent = button('对话记录', () => {
      const rail = root.querySelector('.workspace-agent-conversations');
      rail.hidden = !rail.hidden; recent.setAttribute('aria-expanded', String(!rail.hidden));
    });
    recent.setAttribute('aria-expanded', 'false');
    root.querySelector('.workspace-agent-conversations').hidden = true;
    root.querySelector('.workspace-agent-head').append(recent, preview);

    const fileInput = form.querySelector('.workspace-agent-file');
    const attachButton = form.querySelector('.workspace-agent-attach');
    const attachmentList = form.querySelector('.workspace-agent-attachments');
    const conversationList = root.querySelector('.workspace-agent-conversation-list');
    const newButton = root.querySelector('.workspace-agent-new');
    let mic = null;   // 语音按钮（下面才建；sync() 可能先跑）
    let capable = false, imagesCapable = false, proposalsCapable = false, booting = true, bootFailed = false, conversationId = null, switching = false, sending = false, files = [], conversations = [];
    let creating = null;
    const drafts = new Map(); // In-memory drafts only. Canonical files/history live in SQLite.
    function requestKey() {
      if (global.crypto.randomUUID) return global.crypto.randomUUID();
      const bytes = global.crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
      const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
      return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
    }
    const savedFiles = new Map();
    function attachmentURL(id, file) {
      return /^image\/(png|jpeg|webp)$/.test(file.mime || '') ? '/api/workspace-agent/conversations/' + encodeURIComponent(id) + '/attachments/' + encodeURIComponent(file.id) + '/content' : undefined;
    }
    const reuse = make('details', '', 'workspace-agent-reuse');
    const reuseList = make('div', '', 'workspace-agent-actions');
    reuse.append(make('summary', '附件'), reuseList);
    form.before(reuse); reuse.hidden = true;
    form.after(status);
    input.before(attachmentList);
    // 用哪家：默认跟设置里聊天用的那家，输入框下面一个小下拉，一步就能换（Claude / DeepSeek / ChatGPT）。
    // 选中的那家不可用、或这轮带图而它看不了图时，在输入框上方说一句；连不上时给「重试」，没配好时给「去设置」。
    let caps = null, modelRevision = 0;
    const PROVIDER_KEY = 'jine.agent.provider';
    let choice = (() => { try { return localStorage.getItem(PROVIDER_KEY) || 'main'; } catch { return 'main'; } })();
    const providerHint = make('small', '', 'workspace-agent-provider'); providerHint.setAttribute('role', 'status');
    const providerText = make('span');
    const providerFix = button('', () => { if (providerFix.dataset.fix === 'retry') void boot(); else global.LP.settings?.open('models'); });
    providerHint.append(providerText, providerFix);
    form.before(providerHint);
    const picker = make('select', '', 'workspace-agent-model');
    picker.setAttribute('aria-label', '模型');
    form.querySelector('.workspace-agent-formbar').insertBefore(picker, attachButton.nextSibling);
    picker.onchange = () => { choice = picker.value; picker.classList.toggle('custom', choice !== 'main'); try { localStorage.setItem(PROVIDER_KEY, choice); } catch { /* 只记本次 */ } sync(); };
    const providers = () => caps?.providers || [];
    function chosen() {
      if (choice === 'main') return providers().find(p => p.id === caps?.default_provider) || null;
      return providers().find(p => p.id === choice) || null;
    }
    function paintPicker() {
      const main = providers().find(p => p.id === caps?.default_provider);
      const options = [new Option(main ? '默认 · ' + main.label : '默认', 'main'),
        ...providers().map(p => { const o = new Option(p.label, p.id); o.className = p.configured ? '' : 'off'; return o; })];
      picker.replaceChildren(...options);
      if (!options.some(o => o.value === choice)) choice = 'main';
      picker.value = choice;
      picker.classList.toggle('custom', choice !== 'main');
    }
    function updateProviderHint() {
      let issue = '', fix = '';
      const p = chosen();
      if (booting) issue = '';
      else if (!caps || bootFailed) { issue = '管家现在连不上'; fix = 'retry'; }
      else if (!p) { issue = '默认的模型用不了，换一个'; fix = 'settings'; }
      else if (!p.configured) { issue = p.label + ' 用不了'; fix = 'settings'; }
      else if (files.some(file => /^image\//.test(file.mime || file.source?.type || '')) && !p.vision) issue = p.label + ' 看不了图';
      providerText.textContent = issue;
      providerFix.hidden = !fix;
      providerFix.dataset.fix = fix;
      providerFix.textContent = fix === 'retry' ? '重试' : '去设置';
      providerHint.hidden = !issue;
      picker.dataset.state = issue ? 'bad' : 'ok';
      return issue;
    }
    async function refreshModels() {
      const revision = ++modelRevision;
      try {
        const capabilities = await request('capabilities');
        if (revision !== modelRevision) return;
        caps = capabilities; paintPicker(); sync();
      } catch {
        if (revision !== modelRevision) return;
        caps = null; paintPicker(); sync();
      }
    }
    global.addEventListener('lp:models-changed', () => void refreshModels());

    const objectURLs = new Set();
    function releasePreview(file) {
      if (file.previewURL && objectURLs.has(file.previewURL)) {
        URL.revokeObjectURL(file.previewURL); objectURLs.delete(file.previewURL); delete file.previewURL;
      }
    }
    global.addEventListener('pagehide', () => { for (const url of objectURLs) URL.revokeObjectURL(url); objectURLs.clear(); });
    function drawSavedFiles() {
      const saved = savedFiles.get(conversationId) || [];
      reuse.hidden = !saved.length;
      reuseList.replaceChildren(...saved.map(file => {
        const selected = files.some(item => item.id === file.id);
        const action = button((selected ? '已选 · ' : '选用 · ') + file.name, () => {
          if (files.length >= 4 || sending || switching) return;
          files.push({...file, pending:false, progress:''}); chips();
        });
        action.disabled = selected || sending || switching || files.length >= 4;
        return action;
      }));
    }
    function sync() {
      drawSavedFiles();
      const providerIssue = updateProviderHint();
      const uploading = files.some(file => file.pending);
      submit.disabled = Boolean(providerIssue) || (!input.value.trim() && !files.length) || booting || sending || switching || uploading || files.some(file => file.error);
      attachButton.disabled = !capable || sending || switching || uploading || files.length >= 4;
      newButton.disabled = !capable || sending || switching || uploading;
      conversationList.querySelectorAll('button').forEach(item => { item.disabled = sending || switching || uploading; });
      input.readOnly = sending || switching;
      if (mic) mic.disabled = !Recognition || sending || switching;
    }
    const Recognition = global.SpeechRecognition || global.webkitSpeechRecognition;
    let recognition = null, dictationAccepted = false, dictationBase = '', dictationFinal = '';
    mic = button('', async () => {
      if (recognition) { stopDictation(); return; }
      if (!Recognition || sending || switching) return;
      if (!dictationAccepted) {
        // 浏览器的语音识别会把声音发给浏览器厂商：第一次用之前问一句
        if (!await LP.util.confirm({ title: '用浏览器识别语音？', ok: '用' })) return;
        dictationAccepted = true;
      }
      const current = new Recognition(); recognition = current;
      current.lang = document.documentElement.lang || 'zh-CN';
      current.continuous = true; current.interimResults = true;
      dictationBase = input.value; dictationFinal = '';
      mic.setAttribute('aria-pressed','true'); mic.setAttribute('aria-label','停止语音输入'); mic.title = '停止语音输入';
      status.textContent = '';
      current.onresult = event => {
        if (recognition !== current) return;
        let interim = '';
        for (let index = event.resultIndex; index < event.results.length; index++) {
          const text = event.results[index][0]?.transcript || '';
          if (event.results[index].isFinal) dictationFinal += text;
          else interim += text;
        }
        input.value = (dictationBase + (dictationBase && (dictationFinal || interim) ? ' ' : '') + dictationFinal + interim).slice(0,input.maxLength);
        sync();
      };
      current.onerror = event => {
        if (recognition !== current) return;
        const messages = {'not-allowed':'麦克风没允许','no-speech':'没听到声音','aborted':''};
        status.textContent = event.error in messages ? messages[event.error] : '麦克风用不了';
        stopDictation(false);
      };
      current.onend = () => { if (recognition === current) { recognition = null; resetMic(); } };
      try { current.start(); } catch { status.textContent = '麦克风用不了'; stopDictation(false); }
    });
    mic.className = 'workspace-agent-mic';
    mic.innerHTML = '<svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M6 11v1a6 6 0 0 0 12 0v-1M12 18v3m-3 0h6"/></svg>';
    mic.disabled = !Recognition;
    function resetMic() {
      mic.setAttribute('aria-pressed','false'); mic.setAttribute('aria-label','语音输入');
      mic.title = Recognition ? '语音输入' : '这个浏览器不支持语音输入';
    }
    resetMic(); submit.before(mic);
    function stopDictation(clearStatus = true) {
      const current = recognition; recognition = null;
      if (current) { try { current.stop(); } catch {} }
      resetMic();
      if (clearStatus && current) status.textContent = '';
    }
    document.addEventListener('visibilitychange', () => { if (document.hidden) stopDictation(); });
    global.addEventListener('pagehide', () => stopDictation());
    const visibilityObserver = new MutationObserver(() => {
      if (recognition && (!root.isConnected || !root.getClientRects().length)) stopDictation();
    });
    visibilityObserver.observe(document.body, {attributes:true, subtree:true, attributeFilter:['class','hidden','style']});

    input.addEventListener('input', sync);
    function chips() {
      attachmentList.replaceChildren();
      for (const file of files) {
        const row = make('div', '', 'workspace-agent-file-chip');
        const imageFile = /^image\/(png|jpeg|webp)$/.test(file.mime || file.source?.type || '');
        if (imageFile && (file.previewURL || file.content_url)) {
          row.classList.add('image');
          const preview = make('img'); preview.alt = file.name;
          preview.src = file.previewURL || file.content_url;
          row.append(preview);
        } else {
          const icon = make('span', '▤', 'workspace-agent-file-icon'); icon.setAttribute('aria-hidden','true');
          row.append(icon, make('span', file.name, 'workspace-agent-file-name'));
        }
        row.title = file.name;
        const state = make('small', file.error || (file.pending ? file.progress : file.truncated ? '只读了前一部分' : ''), 'workspace-agent-file-state');
        if (file.error || file.pending || file.truncated) row.append(state);
        if (!file.pending) {
          const remove = button('×', () => { releasePreview(file); files = files.filter(item => item !== file); chips(); });
          remove.disabled = sending;
          remove.setAttribute('aria-label', '移除 ' + file.name); row.append(remove);
        }
        row.dataset.state = file.error ? 'error' : file.pending ? 'pending' : 'ready';
        if (file.error) row.classList.add('error');
        attachmentList.append(row);
      }
      drawSavedFiles(); sync();
    }
    function drawConversations() {
      conversationList.replaceChildren(...conversations.map(row => {
        const action = button(row.title || '新对话', () => void selectConversation(row.id));
        action.setAttribute('aria-current', String(row.id === conversationId));
        action.title = row.title || '新对话';
        const remove = button('×', async () => {
          if (!await LP.util.confirm({ title: '删掉这段对话？' })) return;
          try {
            await request('conversations/' + encodeURIComponent(row.id), null, 'DELETE');
            drafts.delete(row.id); savedFiles.delete(row.id);
            if (conversationId === row.id) { newButton.click(); drafts.delete(row.id); }
            conversations = conversations.filter(item => item.id !== row.id); drawConversations();
          } catch (error) { status.textContent = say(error); }
        });
        remove.setAttribute('aria-label', '删除');
        const group = make('div', '', 'workspace-agent-actions'); group.append(action, remove); return group;
      })); sync();
    }
    async function listConversations() {
      const data = await request('conversations'); conversations = data.conversations || []; drawConversations();
    }
    async function ensureConversation() {
      if (conversationId) return conversationId;
      if (!creating) creating = request('conversations', {title:'新对话'}).then(row => {
        conversationId = row.id; conversations.unshift(row); drawConversations(); return row.id;
      }).finally(() => { creating = null; });
      return creating;
    }
    function messageAttachment(file, id = conversationId) {
      const row = make('div', '', 'workspace-agent-message-file');
      const url = attachmentURL(id, file);
      if (url) { const picture = make('img'); picture.src = url; picture.alt = file.name; picture.loading = 'lazy'; row.append(picture); }
      row.append(make('small', file.name)); return row;
    }
    async function showHistoricalProposal(snapshot) {
      if (!proposalsCapable) { showInspector(proposalCard(snapshot, null, true)); return; }
      const loading = make('p','…'); showInspector(loading);
      try {
        const latest = await request('proposals/' + encodeURIComponent(snapshot.id));
        if (!loading.isConnected) return;
        const active = ['pending','applied'].includes(latest.status) && Number(latest.expires_at) * 1000 > Date.now();
        showInspector(proposalCard(latest, null, !active));
      } catch {
        if (!loading.isConnected) return;
        showInspector(proposalCard(snapshot, null, true));
      }
    }
    async function showChangeHistory() {
      if (!proposalsCapable) return;
      const panel = make('section','','workspace-agent-change-history');
      panel.append(make('p','…')); showInspector(panel, '改过什么');
      try {
        const data = await request('proposals'); if (!panel.isConnected) return;
        panel.replaceChildren();
        const labels = {pending:'待确认',applied:'已应用',undone:'已撤销',expired:'已过期'};
        if (!data.proposals?.length) panel.append(make('p','还没改过'));
        for (const proposal of data.proposals || []) {
          const row = make('article');
          row.append(make('strong', proposal.changes?.map(change=>change.label).join('、') || '设置'));
          const date = Number(proposal.created_at) > 0 ? new Date(proposal.created_at * 1000).toLocaleString() : '';
          row.append(make('small', [labels[proposal.status], date].filter(Boolean).join(' · ')));
          row.append(button('看看', () => void showHistoricalProposal(proposal))); panel.append(row);
        }
      } catch (error) { if (panel.isConnected) panel.replaceChildren(make('p',say(error)),button('重试',()=>void showChangeHistory())); }
    }

    // 以前的对话里的方案只给一个「改了什么」按钮（点了再去问它现在的状态）；刚回来的直接放卡片
    function showResult(turn, result, historical = false) {
      if (!result.proposal) return;
      if (historical) turn.append(button('改了什么', () => void showHistoricalProposal(result.proposal)));
      else turn.append(proposalCard(result.proposal, null));
    }
    function saveDraft() { drafts.set(conversationId, {text:input.value, files}); }
    function restoreDraft() { const draft = drafts.get(conversationId); input.value = draft?.text || ''; files = draft?.files || []; chips(); }
    async function selectConversation(id) {
      if (sending || switching || files.some(file => file.pending)) return;
      stopDictation(); saveDraft(); switching = true; sync(); status.textContent = '';
      try {
        const data = await request('conversations/' + encodeURIComponent(id));
        conversationId = id; inspector.hidden = true; returnToChat?.(); thread.replaceChildren(empty);
        savedFiles.set(id, (data.attachments || []).map(file => ({...file, content_url:attachmentURL(id,file)})));
        empty.hidden = Boolean(data.messages?.length);
        for (const message of data.messages || []) {
          const turn = make('article', '', 'workspace-agent-turn');
          if (message.content) turn.append(make('p', message.content, message.role === 'user' ? 'workspace-agent-request' : 'workspace-agent-reply'));
          for (const attachmentId of message.attachment_ids || []) {
            const file = data.attachments?.find(row => row.id === attachmentId);
            if (file) turn.append(messageAttachment(file,id));
          }
          if (message.status === 'failed') turn.append(make('small', '没做完', 'workspace-agent-status'));
          if (message.result) showResult(turn, message.result, true);
          thread.append(turn);
        }
        restoreDraft(); drawConversations(); status.textContent = ''; thread.scrollTop = thread.scrollHeight;
      } catch (error) { status.textContent = say(error); }
      finally { switching = false; sync(); }
    }
    newButton.onclick = () => {
      if (newButton.disabled) return;
      stopDictation(); saveDraft(); conversationId = null; restoreDraft(); inspector.hidden = true; returnToChat?.();
      thread.replaceChildren(empty); empty.hidden = false; drawConversations(); input.focus();
    };
    const refresh = button('刷新记录', () => { if (!capable || sending || switching || files.some(file => file.pending)) return; if (conversationId) void selectConversation(conversationId); else void listConversations().catch(error => { status.textContent = say(error); }); });
    const changeHistory = button('改过什么', () => void showChangeHistory());
    changeHistory.disabled = true;
    root.querySelector('.workspace-agent-conversations').append(refresh, changeHistory);
    attachButton.onclick = () => fileInput.click();
    const NOT_SENT = '没传上去，再试一次', UNREADABLE = '这个文件读不了';
    function upload(id, body, file) {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/workspace-agent/conversations/' + encodeURIComponent(id) + '/attachments');
        xhr.timeout = 120000;
        xhr.upload.onprogress = event => {
          file.progress = event.lengthComputable ? '正在上传 ' + Math.round(event.loaded / event.total * 100) + '%' : '正在上传…'; chips();
        };
        xhr.onload = () => {
          let data; try { data = JSON.parse(xhr.responseText); } catch { reject(new Error(NOT_SENT)); return; }
          if (xhr.status >= 200 && xhr.status < 300) resolve(data);
          else reject(new Error(typeof data.detail === 'string' ? data.detail : NOT_SENT));
        };
        xhr.onerror = xhr.ontimeout = () => reject(new Error(NOT_SENT));
        xhr.send(body);
      });
    }
    fileInput.onchange = async () => {
      const selected = [...fileInput.files]; fileInput.value = '';
      if (!capable || sending || switching) return;
      if (files.length + selected.length > 4) { status.textContent = '最多 4 个文件'; return; }
      // Reserve all slots before awaiting: navigation/send stay locked throughout this batch.
      const additions = selected.map(source => {
        const file = {name:source.name, pending:true, progress:'正在读取…', source};
        if (/^image\/(png|jpeg|webp)$/.test(source.type)) { file.previewURL = URL.createObjectURL(source); objectURLs.add(file.previewURL); }
        return file;
      });
      files.push(...additions); chips();
      for (const file of additions) {
        try {
          const source = file.source;
          const ext = source.name.split('.').pop().toLowerCase();
          const imageFile = ['png','jpg','jpeg','webp'].includes(ext);
          if (imageFile && !imagesCapable) throw new Error('图片发不了');
          if (!['txt','md','csv','json','pdf','png','jpg','jpeg','webp'].includes(ext)) throw new Error(UNREADABLE);
          const limit = ext === 'pdf' || imageFile ? 8 * 1024 * 1024 : 1024 * 1024;
          if (source.size > limit) throw new Error(ext === 'pdf' || imageFile ? '文件太大，8MB 以内' : '文件太大，1MB 以内');
          if (!source.size) throw new Error('这个文件是空的');
          const body = new FormData(); body.append('file', source);
          if (ext === 'pdf') {
            file.progress = '正在提取 PDF 正文…'; chips();
            const pdf = await import('./reading-pdf.mjs');
            const task = await pdf.openPDF(source);
            let doc;
            try {
              doc = await task.promise;
              let text = '', pages = Math.min(doc.numPages, 20);
              for (let index = 1; index <= pages && text.length < 60000; index++) {
                file.progress = '正在读取 PDF ' + index + ' / ' + pages + ' 页'; chips();
                text += (text ? '\n\n' : '') + await pdf.pageText(doc, index);
              }
              if (!text.trim()) throw new Error(UNREADABLE);
              const truncated = doc.numPages > 20 || text.length > 60000;
              body.append('extracted_text', text.slice(0,60000)); body.append('extraction_truncated', String(truncated));
              file.truncated = truncated;
            } finally { if (doc) await doc.destroy(); else await task.destroy(); }
          } else if (!imageFile) {
            let text = '';
            try { text = new TextDecoder('utf-8', {fatal:true}).decode(await source.arrayBuffer()); } catch { throw new Error(UNREADABLE); }
            if (!text.trim() || text.includes('\u0000')) throw new Error(UNREADABLE);
          }
          const id = await ensureConversation();
          file.progress = '正在上传…'; chips();
          const saved = await upload(id, body, file);
          Object.assign(file, saved.attachment || saved);
          file.content_url = attachmentURL(id, file);
          if (!file.id) throw new Error(NOT_SENT);
          const savedList = savedFiles.get(id) || [];
          if (!savedList.some(item => item.id === file.id)) savedList.push({...file, source:undefined, previewURL:undefined});
          savedFiles.set(id, savedList);
          file.progress = '';
        } catch (error) { file.error = global.LP.util.message(error, NOT_SENT); }
        finally { delete file.source; file.pending = false; chips(); }
      }
    };
    async function send(message, attached, retryId, existingTurn) {
      if (sending || switching) return;
      if (updateProviderHint()) return;
      stopDictation(); sending = true; sync(); chips(); empty.hidden = true; status.textContent = ''; returnToChat?.();
      const turn = existingTurn || make('article', '', 'workspace-agent-turn');
      turn.replaceChildren(); if (message) turn.append(make('p', message, 'workspace-agent-request'));
      for (const file of attached) turn.append(messageAttachment(file));
      const reply = make('p', '在想…', 'workspace-agent-reply pending');
      turn.append(reply); if (!existingTurn) thread.append(turn); thread.scrollTop = thread.scrollHeight;
      const requestId = retryId || requestKey();
      try {
        const payload = {message, preferences:preferences()};
        if (choice !== 'main') payload.provider = choice;
        if (capable) Object.assign(payload, {conversation_id:await ensureConversation(), request_id:requestId, attachment_ids:attached.map(file => file.id)});
        else payload.previous = history.slice(-3);
        const result = await request('plan', payload);
        // 重发拿回来的方案也照常能用（以前当成历史记录，只能看不能用）
        reply.textContent = result.reply; reply.classList.remove('pending'); showResult(turn, result);
        // 管家刚存了一个阅读来源：顺手给一个「试一下」，抓回几条就显示条数
        if (result.test_source?.id) {
          const probe = button('试一下 ' + (result.test_source.name || '这个来源'), async () => {
            probe.disabled = true;
            try { const r = await request('test-source', { id: result.test_source.id }); probe.textContent = (r.ok === false ? '× ' : '✓ ') + (r.count ?? 0) + ' 条'; }
            catch (error) { probe.textContent = '× ' + say(error); }
          });
          probe.className = 'workspace-agent-test-source';
          turn.append(probe);
        }
        // 管家提出做一门备考课：点了才开始，做的进度在「课程」页里看
        if (result.build?.exam) {
          const go = button('开始做这门课', async () => {
            go.disabled = true;
            try {
              await LP.api.startBuild(result.build); go.textContent = '开始做了'; document.dispatchEvent(new CustomEvent('lp:course-build'));
              const look = button('去看', () => openLibrary());   // 做课的进度在 设置 › 课程与世界书
              look.className = 'workspace-agent-test-source';
              go.after(look);
            }
            catch (error) { go.disabled = false; go.textContent = say(error); }
          });
          go.className = 'workspace-agent-test-source';
          turn.append(go);
        }
        if (input.value.trim() === message) input.value = '';
        for (const file of attached) releasePreview(file);
        files = files.filter(file => !attached.includes(file)); drafts.delete(conversationId); chips();
        history.push({request:message, reply:result.reply}); if (history.length > 3) history.shift();
        if (capable) await listConversations().catch(() => {});
      } catch (error) {
        reply.classList.remove('pending'); reply.textContent = say(error);
        // 网断了（没有状态码）：不知道后端做没做完，重发带同一个编号，后端认得出来不会做两遍
        const uncertain = !error.status;
        const retry = button('重发', () => {
          if (sending) return;
          void send(message, attached, uncertain ? requestId : null, turn);
        });
        turn.append(retry);
      } finally { sending = false; chips(); sync(); thread.scrollTop = thread.scrollHeight; }
    }
    form.addEventListener('submit', event => {
      event.preventDefault(); const message = input.value.trim();
      if (submit.disabled || (!message && !files.length)) return;
      void send(message, [...files]);
    });
    sync();
    // 启动：读能力、读对话记录。连不上时输入框上方说「管家现在连不上」并给「重试」
    async function boot() {
      booting = true; bootFailed = false; sync();
      try {
        let capabilities;
        try { capabilities = await request('capabilities'); }
        catch (error) { bootFailed = true; throw error; }
        proposalsCapable = capabilities.proposals === true;
        imagesCapable = capabilities.images === true;
        caps = capabilities; paintPicker();
        capable = capabilities.version >= 1 && capabilities.conversations === true && capabilities.attachments === true;
        if (!imagesCapable) fileInput.accept = '.txt,.md,.csv,.json,.pdf';
        if (!capable) return;
        await listConversations();
        if (conversations.length) await selectConversation(conversations[0].id);
      } catch (error) {
        if (!bootFailed) status.textContent = say(error);
      } finally { booting = false; changeHistory.disabled = !proposalsCapable; root.querySelector('.workspace-agent').setAttribute('aria-busy','false'); refresh.disabled = !capable; sync(); }
    }
    void boot();
    // 别处「问管家」时这页还没挂好：现在把那句话填进去
    if (pendingPrefill != null) { const text = pendingPrefill; pendingPrefill = null; fill(text); }

    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
  }

  function fill(text) {
    composer.value = text.trim().slice(0, composer.maxLength);
    composer.dispatchEvent(new Event('input', {bubbles:true}));
    composer.focus();
  }

  global.LP ||= {};
  global.LP.workspaceAgent = { mount, openLibrary, prefill(text) {
    if (typeof text !== 'string') return;
    global.LP.appShell.switchTab('workspace-agent'); returnToChat?.();
    if (!composer) { pendingPrefill = text; return; }   // 第一次来：页面挂好时再填（mount 末尾）
    fill(text);
  } };
})(window);
