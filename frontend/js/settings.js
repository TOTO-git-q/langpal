/* settings.js — 设置页框架 + 角色页（人设卡、记忆、挂接世界书）+ 听力/口语/复习的小选项。
   其他分类各有自己的模块：settings-models.js（模型与账号）、settings-teaching.js + settings-lore.js（课程与世界书）、
   settings-hooks.js（事件）、settings-reading.js（阅读）、settings-providers.js（声音）。 */
(function (global) {
  'use strict';

  const MEM_CAT_LABEL = { fact: '事实', preference: '偏好', event: '事件', promise: '约定' };
  const PAGES = [
    ['chat', '角色', 'jine.png'], ['library', '课程与世界书', 'notebook.png'], ['hooks', '事件', 'agent.svg'], ['reader', '阅读', 'reading.svg'],
    ['listen', '听力', 'listening.svg'], ['speak', '口语', 'lesson.png'],
    ['review', '复习', 'review.png'], ['voice', '音声', 'listening.svg'], ['models', '模型与账号', 'settings.png'],
  ];

  const sState = { selectedPersonaId: null, interests: [], keigo: '平辈' };
  let els = {};
  let listeningRead = 0;
  let bookChoices = [];
  let bookChoicesReady = false;
  let bookRead = 0;
  let roleDirty = false;
  // 角色表单改了没存：表单上挂 .dirty（保存按钮这时才出现），离开设置时也认它
  function setRoleDirty(value) { roleDirty = value; els.form?.classList.toggle('dirty', value); }
  let roleSaving = false;
  const escapeHtml = (s) => global.LP.util.escapeHtml(s);
  function personaInitial(p) { return Array.from(p.name || '?')[0]; }

  // 头像小方块：有自定义头像就用图，否则语言色底 + 名字首字母（和 jine.js 的口径一致）
  function avatarBoxHtml(p, cls) {
    if (p && p.avatar_url) {
      return `<div class="avatar ${cls || ''}"><img src="${escapeHtml(p.avatar_url)}" alt=""></div>`;
    }
    return `<div class="avatar ${cls || ''} lang-${escapeHtml(p.language)}">${escapeHtml(personaInitial(p))}</div>`;
  }

  // ================= 区块一：人设 =================

  function renderPersonaList() {
    els.personaList.innerHTML = '';
    LP.state.personas.forEach((p) => {
      const card = document.createElement('button');
      card.type = 'button';
      card.className = 'p-card' + (p.id === sState.selectedPersonaId ? ' active' : '');
      card.innerHTML = `${avatarBoxHtml(p, 'sm')}
        <div><div class="jn-name">${escapeHtml(p.name)}</div><div class="jn-lang">${escapeHtml(LP.languages.label(p.language))}</div></div>`;
      card.addEventListener('click', () => selectPersona(p.id));
      els.personaList.appendChild(card);
    });
    const addBtn = document.createElement('button');
    addBtn.type = 'button';
    addBtn.className = 'p-add';
    addBtn.textContent = '+ 新建角色';
    addBtn.addEventListener('click', () => selectPersona(null));
    els.personaList.appendChild(addBtn);
  }

  // 换一个角色：这张表改了没存就先问
  async function selectPersona(personaId) {
    if (roleDirty && !(await confirmLeave())) return false;
    setRoleDirty(false);
    sState.selectedPersonaId = personaId;
    if (els.addMemory) els.addMemory.disabled = personaId == null;
    renderPersonaList();
    if (personaId == null) {
      loadForm(null);
      els.memoryList.innerHTML = '';
    } else {
      loadForm(LP.getPersona(personaId));
      loadMemory(personaId);
    }
    return true;
  }
  const confirmLeave = () => LP.util.confirm({ title: '有改动没保存', text: '离开就丢了', ok: '不保存', cancel: '留下' });

  function renderInterests() {
    els.interests.innerHTML = '';
    sState.interests.forEach((tag, idx) => {
      const chip = document.createElement('div');
      chip.className = 'tag-chip';
      chip.innerHTML = `<span>${escapeHtml(tag)}</span><span class="rm">×</span>`;
      chip.querySelector('.rm').addEventListener('click', () => { sState.interests.splice(idx, 1); setRoleDirty(true); renderInterests(); });
      els.interests.appendChild(chip);
    });
    const addBtn = document.createElement('div');
    addBtn.className = 'tag-add';
    addBtn.textContent = '添加';
    addBtn.addEventListener('click', () => {
      const input = document.createElement('input');
      input.className = 'tag-add-input';
      input.placeholder = '回车确认';
      addBtn.replaceWith(input);
      input.focus();
      let committed = false;
      const commit = () => { if (committed) return; committed = true; const v = input.value.trim(); if (v) { sState.interests.push(v); setRoleDirty(true); } renderInterests(); };
      input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); commit(); } });
      input.addEventListener('blur', commit);
    });
    els.interests.appendChild(addBtn);
  }

  function updateKeigoVisibility() { els.keigoWrap.style.display = els.language.value === 'ja' ? '' : 'none'; }

  // 人设语言跟随 LP.languages；人设自己的语言不在表里时也补上，免得下拉框选不中。
  function renderPersonaLanguages(keep) {
    const items = LP.languages.list();
    const options = items.map(({ tag, label }) => new Option(label, tag));
    if (keep && !items.some((item) => item.tag === keep)) options.push(new Option(LP.languages.label(keep), keep));
    els.language.replaceChildren(...options);
  }

  function loadForm(persona) {
    renderPersonaLanguages(persona?.language);
    if (!persona) {
      els.name.value = ''; els.language.value = 'ja'; els.relation.value = ''; els.tone.value = '';
      sState.keigo = '平辈'; sState.interests = []; els.freeText.value = '';
    } else {
      const profile = persona.profile || {};
      els.name.value = persona.name || '';
      els.language.value = persona.language || 'ja';
      els.relation.value = profile.relation || '';
      els.tone.value = profile.tone || '';
      sState.keigo = profile.keigo || '平辈';
      sState.interests = Array.isArray(profile.interests) ? profile.interests.slice() : [];
      els.freeText.value = profile.free_text || '';
    }
    els.keigo.querySelectorAll('.seg-opt').forEach((o) => o.classList.toggle('active', o.dataset.val === sState.keigo));
    renderInterests();
    updateKeigoVisibility();
    renderAvatarEditor(persona);
    els.dangerZone.classList.toggle('hidden', !persona);
    renderBookHooks(persona?.profile?.world_book_ids || []);
    const samples = persona?.profile?.voice_samples;
    sState.voice = {};
    if (samples && typeof samples === 'object') for (const [tag, lines] of Object.entries(samples)) if (Array.isArray(lines)) sState.voice[tag] = lines.map(String);
    sState.voiceLang = sState.voice[persona?.language]?.length || !Object.keys(sState.voice).length ? (persona?.language || els.language.value) : Object.keys(sState.voice)[0];
    renderVoice();
  }

  // ---------- 口吻样本：按语言分的多行文本，一行一句 ----------
  const VOICE_MAX = 600;
  const voiceLines = (text) => text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  function renderVoice() {
    const tags = [...new Set([...LP.languages.list().map((l) => l.tag), ...Object.keys(sState.voice)])];
    if (!tags.includes(sState.voiceLang)) sState.voiceLang = tags[0];
    els.voiceTabs.replaceChildren(...tags.map((tag) => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(tag === sState.voiceLang));
      const n = sState.voice[tag]?.length || 0;
      tab.innerHTML = escapeHtml(LP.languages.label(tag)) + (n ? ` <b>${n}</b>` : '');
      tab.onclick = () => { sState.voiceLang = tag; renderVoice(); };
      return tab;
    }));
    els.voice.value = (sState.voice[sState.voiceLang] || []).join('\n');
    els.voice.lang = sState.voiceLang;
    paintVoiceCount();
  }
  function paintVoiceCount() {
    const n = sState.voice[sState.voiceLang]?.length || 0;
    els.voiceCount.textContent = n + ' / ' + VOICE_MAX;
    els.voiceCount.classList.toggle('over', n > VOICE_MAX);
    const total = Object.values(sState.voice).reduce((sum, lines) => sum + lines.length, 0);
    els.voiceTotal.textContent = total ? total + ' 句' : '';
    const tab = els.voiceTabs.querySelector('[aria-selected="true"]');
    if (tab) tab.innerHTML = escapeHtml(LP.languages.label(sState.voiceLang)) + (n ? ` <b>${n}</b>` : '');
  }
  function cleanVoice() {
    const out = {};
    for (const [tag, lines] of Object.entries(sState.voice)) {
      const kept = [...new Set(lines.map((line) => line.trim()).filter(Boolean))];
      if (kept.length) out[tag] = kept;
    }
    return out;
  }

  function selectedBooks() {
    return [...els.bookHooks.querySelectorAll('input:checked:not(:disabled)')].map(input => Number(input.value));
  }

  // 全局的书对所有人都生效：照样列出来，但勾着、不能取消
  function renderBookHooks(ids) {
    els.bookHooks.replaceChildren();
    for (const book of bookChoices) {
      const label = document.createElement('label');
      label.className = 'settings-check';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.value = book.id;
      const global = book.scope === 'global';
      check.checked = global || ids.includes(book.id);
      check.disabled = global;
      label.append(check, book.name + (global ? '（全局）' : ''));
      els.bookHooks.append(label);
    }
    els.bookEmpty.hidden = bookChoices.length > 0;
  }

  async function refreshBookHooks() {
    const ticket = ++bookRead;
    try {
      const data = await LP.api.getLoreBooks();
      const items = Array.isArray(data?.items) ? data.items : [];
      if (ticket !== bookRead || roleSaving) return;
      const selected = bookChoicesReady && roleDirty ? selectedBooks() : LP.getPersona(sState.selectedPersonaId)?.profile?.world_book_ids || [];
      bookChoices = items;
      bookChoicesReady = true;
      renderBookHooks(selected);
    } catch { /* Keep the currently loaded attachments available. */ }
  }

  // ---------- 头像 ----------
  const AVATAR_MAX_BYTES = 3 * 1024 * 1024;

  function renderAvatarEditor(persona) {
    // 新建状态下还没有 persona_id，没法把文件挂到谁名下 —— 先存人设再传头像
    els.avatarPreview.innerHTML = persona
      ? avatarBoxHtml(persona, 'lg')
      : '<div class="avatar lg lang-ja">?</div>';
    els.avatarPick.hidden = !persona;   // 新建的还没存：没法挂头像，不给按钮
    els.avatarClear.classList.toggle('hidden', !(persona && persona.avatar_url));
    els.avatarHint.textContent = '';
  }

  async function afterAvatarChanged(personaId) {
    await LP.appShell.reloadPersonas();
    renderPersonaList();
    renderAvatarEditor(LP.getPersona(personaId));
    // 聊天里已经画出来的气泡头像：reloadPersonas → jine.personasChanged 会重读消息（她正在回时等这一轮说完）
  }

  function wireAvatarEditor() {
    els.avatarPick.addEventListener('click', () => els.avatarFile.click());
    els.avatarFile.addEventListener('change', async () => {
      const file = els.avatarFile.files && els.avatarFile.files[0];
      els.avatarFile.value = '';  // 清掉，下次选同一个文件也能触发 change
      const personaId = sState.selectedPersonaId;
      if (!file || personaId == null) return;
      if (file.size > AVATAR_MAX_BYTES) { els.avatarHint.textContent = '图片太大，3MB 以内'; return; }
      els.avatarPick.disabled = true;
      try {
        await LP.api.uploadPersonaAvatar(personaId, file);
        await afterAvatarChanged(personaId);
      } catch (e) {
        els.avatarHint.textContent = LP.util.message(e, '头像没传上去，再试一次');
      } finally {
        els.avatarPick.disabled = false;
      }
    });
    els.avatarClear.addEventListener('click', async () => {
      const personaId = sState.selectedPersonaId;
      if (personaId == null) return;
      try {
        await LP.api.deletePersonaAvatar(personaId);
        await afterAvatarChanged(personaId);
      } catch (e) {
        els.avatarHint.textContent = LP.util.message(e, '没恢复成，再试一次');
      }
    });
  }

  async function loadMemory(personaId) {
    if (els.addMemory) els.addMemory.disabled = personaId == null;
    els.memoryList.innerHTML = '<div class="row-card skeleton-row" aria-hidden="true"></div><div class="row-card skeleton-row" aria-hidden="true"></div>';
    try {
      const res = await LP.api.getMemory(personaId);
      if (personaId !== sState.selectedPersonaId) return;
      els.memoryList.innerHTML = '';
      if (!res.items || res.items.length === 0) { els.memoryList.innerHTML = '<div class="row-card muted">还没有</div>'; return; }
      res.items.forEach((item) => els.memoryList.appendChild(memoryRow(item)));
    } catch (e) {
      if (personaId === sState.selectedPersonaId) els.memoryList.innerHTML = `<div class="row-card muted">${escapeHtml(LP.util.message(e, '没读到'))}</div>`;
    }
  }

  function memoryRow(item) {
    const row = document.createElement('div');
    row.className = 'row-card';
    const cat = item.category in MEM_CAT_LABEL ? item.category : 'fact';
    row.innerHTML = `
      <div class="mem-cat">${MEM_CAT_LABEL[cat]}</div>
      <div class="mem-content ${item.active ? '' : 'inactive'}">${escapeHtml(item.content)}</div>
      <div class="memory-actions">
      <button type="button" class="mem-edit" aria-label="编辑记忆"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20l4.5-1L20 7.5l-3.5-3.5L5 15.5 4 20z"/></svg></button>
      <button type="button" class="mem-del" aria-label="删除记忆"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16M10 7V5h4v2M6 7l1 13h10l1-13"/></svg></button>
      <button type="button" class="toggle ${item.active ? '' : 'off'}" role="switch" aria-label="启用记忆" aria-checked="${item.active}"><span class="knob"></span></button></div>`;
    row.classList.add('memory-record');
    const contentEl = row.querySelector('.mem-content');
    const toggleEl = row.querySelector('.toggle');

    row.querySelector('.mem-edit').addEventListener('click', () => {
      if (contentEl.getAttribute('contenteditable') === 'true') { commitEdit(); return; }
      contentEl.setAttribute('contenteditable', 'true');
      contentEl.focus();
      const range = document.createRange(); range.selectNodeContents(contentEl);
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    });
    async function commitEdit() {
      contentEl.removeAttribute('contenteditable');
      const newContent = contentEl.textContent.trim();
      if (newContent && newContent !== item.content) {
        try { await LP.api.patchMemory(item.id, { content: newContent }); item.content = newContent; }
        catch (e) { contentEl.textContent = item.content; LP.toast?.(LP.util.message(e, '没改成，再试一次')); }
      } else { contentEl.textContent = item.content; }
    }
    contentEl.addEventListener('blur', () => { if (contentEl.getAttribute('contenteditable') === 'true') commitEdit(); });
    contentEl.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); contentEl.blur(); } });

    // 删除：先拿掉，5 秒内能撤销（和单词本、错题本一样）
    row.querySelector('.mem-del').addEventListener('click', () => {
      const parent = row.parentElement, next = row.nextSibling;
      const undoable = LP.appShell?.undoable || ((message, step) => { step.remove(); void step.commit(); });
      undoable('已删除', {
        remove: () => row.remove(),
        restore: () => parent?.insertBefore(row, next),
        commit: async () => {
          try { await LP.api.deleteMemory(item.id); }
          catch (e) { parent?.insertBefore(row, next); LP.toast?.(LP.util.message(e, '没删掉，再试一次')); }
        },
      });
    });
    toggleEl.addEventListener('click', async () => {
      const nextActive = toggleEl.classList.contains('off');
      toggleEl.classList.toggle('off', !nextActive);
      contentEl.classList.toggle('inactive', !nextActive);
      toggleEl.setAttribute('aria-checked', String(nextActive));
      try { await LP.api.patchMemory(item.id, { active: nextActive }); item.active = nextActive; }
      catch (e) { toggleEl.classList.toggle('off', !item.active); contentEl.classList.toggle('inactive', !item.active); LP.util.tick(toggleEl, false, LP.util.message(e, '没存上')); }
      toggleEl.setAttribute('aria-checked', String(item.active));
    });
    return row;
  }

  // ---------- 危险操作：移除人设 ----------
  async function deletePersona() {
    const persona = LP.getPersona(sState.selectedPersonaId);
    if (!persona) return;
    const ok = await LP.util.confirm({ title: `移除「${persona.name}」？`, ok: '移除' });
    if (!ok) return;
    try {
      await LP.api.deletePersona(persona.id);
      await LP.appShell.reloadPersonas();
      await els.chatRoom.refresh();
      setRoleDirty(false);
      await selectPersona(LP.state.personas[0]?.id ?? null);
    } catch (e) {
      LP.toast?.(LP.util.message(e, '没移除成，再试一次'));
    }
  }

  // ---------- 听力出题、口语互通（也存在 /api/settings）：改了就存，控件旁边打勾 ----------
  async function saveSetting(patch, field) {
    try {
      await LP.api.putSettings(patch);
      LP.util.tick(field, true);
      return true;
    } catch (e) {
      LP.util.tick(field, false, LP.util.message(e, '没存上'));
      return false;
    }
  }

  async function loadListening() {
    const ticket = ++listeningRead;
    els.listeningSubscription.disabled = true;
    try {
      const response = await fetch('/api/listening/options');
      if (!response.ok) throw new Error();
      const { subscription } = await response.json();
      if (ticket !== listeningRead) return;
      els.listeningSubscription.value = [...els.listeningSubscription.options].some(option => option.value === (subscription ?? '')) ? (subscription ?? '') : '';
      els.listeningSubscription.disabled = false;
    } catch {
      // 读不到：下拉保持灰着，旁边一个叉
      if (ticket === listeningRead) { els.listeningSubscription.disabled = true; LP.util.tick(els.listeningSubscription, false, '读不到'); }
    }
  }

  async function loadCoachBridge() {
    try { els.coachBridge.value = (await LP.api.getSettings()).coach_bridge === false ? '0' : '1'; }
    catch { LP.util.tick(els.coachBridge, false, '读不到'); }
  }

  function wireSmallSettings() {
    els.coachBridge.addEventListener('change', () => saveSetting({ coach_bridge: els.coachBridge.value === '1' }, els.coachBridge));
    els.listeningSubscription.addEventListener('change', async () => {
      els.listeningSubscription.disabled = true;
      await saveSetting({ listening_subscription: els.listeningSubscription.value }, els.listeningSubscription);
      await loadListening();
    });
  }

  function mount(root) {
    const sectionTitle = key => {
      const [, label, icon] = PAGES.find(page => page[0] === key);
      return `<h1><img src="/assets/icons/${icon}" alt=""><span>${label}</span></h1>`;
    };
    const preference = (key, label, choices) => `
      <div class="field settings-choice-field">
        <span id="pref-${key}">${label}</span>
        <div class="settings-choices" role="group" aria-labelledby="pref-${key}" data-preference="${key}">
          ${choices.map(([value, text]) => `<button type="button" data-value="${value}">${text}</button>`).join('')}
        </div>
      </div>`;
    const languagePreference = (key, label, all = false) => `
      <div class="field"><label for="pref-${key}">${label}</label>
        <select id="pref-${key}" data-language-default="${key}" data-all="${all}"></select>
      </div>`;
    root.innerHTML = `
      <section class="settings-layout" aria-label="设置">
        <nav class="settings-nav" aria-label="设置分类">
          ${PAGES.map(([key, label, icon]) => `<button type="button" data-settings-tab="${key}" aria-controls="settings-${key === 'voice' ? 'character-voice' : key}"${['reader', 'models'].includes(key) ? ' class="group-start"' : ''}><img src="/assets/icons/${icon}" alt="">${label}</button>`).join('')}
        </nav>
        <div class="settings-form-area">
          <section id="settings-chat" data-settings-page="chat">
          ${sectionTitle('chat')}
          <div id="settings-chat-room"></div>
          <div class="settings-personas" id="settings-persona-list" aria-label="角色"></div>
          <form id="persona-form">
            <div class="field"><label>头像</label>
              <div class="avatar-editor">
                <div id="f-avatar-preview"></div>
                <div class="avatar-editor-side">
                  <input type="file" id="f-avatar-file" class="hidden"
                         accept="image/png,image/jpeg,image/gif,image/webp">
                  <div class="key-row">
                    <button type="button" class="btn-sm primary" id="btn-avatar-pick">上传图片</button>
                    <button type="button" class="btn-sm hidden" id="btn-avatar-clear">恢复默认</button>
                  </div>
                  <div class="settings-note" id="f-avatar-hint"></div>
                </div>
              </div>
            </div>
            <div class="settings-fields">
              <div class="field"><label for="f-name">名字</label><input type="text" id="f-name"></div>
              <div class="field"><label for="f-language">语言</label>
                <select id="f-language"></select>
              </div>
              <div class="field"><label for="f-relation">和我的关系</label><input type="text" id="f-relation"></div>
              <div class="field"><label for="f-tone">语气</label><input type="text" id="f-tone"></div>
            </div>
            <div class="field" id="f-keigo-wrap"><label>敬语档位</label>
              <div class="seg" id="f-keigo">
                <div class="seg-opt" data-val="敬语">敬语</div>
                <div class="seg-opt active" data-val="平辈">平辈</div>
                <div class="seg-opt" data-val="亲昵">亲昵</div>
              </div>
            </div>
            <div class="field"><label>兴趣标签</label><div id="f-interests"></div></div>
            <div class="field"><label for="f-free-text">自由描述</label><textarea id="f-free-text"></textarea></div>
            <details class="settings-fold" id="settings-voice">
              <summary>口吻样本 <span class="voice-total"></span></summary>
              <div class="voice-tabs" role="tablist" aria-label="样本语言"></div>
              <textarea id="f-voice" rows="8" aria-label="口吻样本" placeholder="一行一句"></textarea>
              <div class="voice-bar"><span class="voice-count" aria-live="polite"></span>
                <button type="button" class="btn-sm" id="btn-voice-import">导入 .txt</button>
                <input type="file" id="f-voice-file" accept=".txt,text/plain" class="hidden"></div>
            </details>
            <details class="settings-fold" id="settings-role-books">
              <summary>挂接世界书</summary>
              <div id="settings-book-hooks" class="settings-book-hooks"></div>
              <p id="settings-book-empty" class="settings-note">暂无世界书</p>
            </details>
            <button type="submit" class="save-btn">保存角色</button>
            <span class="save-flash" id="save-flash">已保存 ✓</span>
          </form>

          <details class="settings-fold" id="settings-memory">
            <summary>记忆</summary>
            <div class="memory-toolbar"><button type="button" class="btn-sm" id="btn-add-memory" disabled>＋ 添加记忆</button></div>
            <div id="memory-list"></div>
          </details>
          <dialog id="memory-new-dialog" class="settings-memory-dialog" aria-labelledby="memory-new-title">
            <form id="memory-new-form"><header><h2 id="memory-new-title">添加记忆</h2><button type="button" data-memory-close aria-label="关闭">×</button></header>
              <label>类型<select name="category" aria-label="记忆类型"><option value="fact">事实</option><option value="preference">偏好</option><option value="event">事件</option><option value="promise">约定</option></select></label>
              <textarea name="content" aria-label="记忆内容" rows="5" maxlength="4000" placeholder="记住这件事……" required></textarea>
              <p role="status"></p><footer><button type="button" data-memory-close>取消</button><button type="submit" class="save-btn">添加</button></footer>
            </form>
          </dialog>

          <details class="settings-fold danger-zone hidden" id="danger-zone">
            <summary>移除角色</summary>
            <button type="button" class="danger-btn" id="btn-delete-persona">移除此角色</button>
          </details>
          </section>

          <section id="settings-library" data-settings-page="library" hidden>
          ${sectionTitle('library')}
          ${LP.settingsTeaching.markup}
          </section>

          <section id="settings-hooks" data-settings-page="hooks" hidden>
          ${sectionTitle('hooks')}
          <div data-settings-hooks></div>
          </section>

          <section id="settings-character-voice" data-settings-page="voice" hidden>
          ${sectionTitle('voice')}
          ${LP.settingsVoice?.markup || ''}
          </section>

          <section id="settings-models" data-settings-page="models" hidden>
          ${sectionTitle('models')}
          ${LP.settingsModels.markup}
          </section>
          <section id="settings-reader" data-settings-page="reader" hidden>
          ${sectionTitle('reader')}
          ${LP.readingPreferences.markup}
          <div data-settings-reading></div>
          </section>
          <section id="settings-listen" data-settings-page="listen" hidden>
          ${sectionTitle('listen')}
          <div class="settings-block">
            <div class="settings-fields">
              ${languagePreference('listeningLanguage', '默认语言')}
              <div class="field"><label for="f-listening-subscription">出题用哪个</label><select id="f-listening-subscription" disabled>
                <option value="">跟聊天一样</option><option value="claude">Claude</option><option value="chatgpt">ChatGPT</option><option value="deepseek">DeepSeek</option><option value="custom">自定义接口</option>
              </select></div>
            </div>
          </div>
          ${LP.settingsProviders.listeningMarkup}
          </section>
          <section id="settings-speak" data-settings-page="speak" hidden>
          ${sectionTitle('speak')}
          ${LP.settingsProviders.speakingMarkup}
          <div class="settings-block">
            <div class="field">
              <label for="f-coach-bridge">和聊天同步练习反馈</label>
              <select id="f-coach-bridge">
                <option value="1">开启</option>
                <option value="0">关闭</option>
              </select>
            </div>
          </div>
          </section>
          <section id="settings-review" data-settings-page="review" hidden>
          ${sectionTitle('review')}
          <div class="settings-block" data-review-plan>
            <h2 class="settings-block-title">复习</h2>
            <div class="settings-fields">
              <div class="field"><label for="f-review-retention">想记住几成</label>
                <div class="review-retention"><input type="range" id="f-review-retention" min="80" max="95" step="1"><output></output><span class="review-arrow" aria-hidden="true"></span></div></div>
              <div class="field"><label for="f-review-new">每天新卡</label><input type="number" id="f-review-new" min="0" max="50"></div>
            </div>
            <label class="settings-check"><input type="checkbox" role="switch" id="f-review-mix">各种卡混在一起</label>
            <label class="settings-check"><input type="checkbox" role="switch" id="f-reading-first">阅读先看题再读</label>
          </div>
          <div class="settings-block">
            <h2 class="settings-block-title">错题本</h2>
            <div class="settings-fields">
              ${preference('reviewKind', '默认题型', [['all', '全部'], ['reading', '阅读'], ['listening', '听力']])}
              ${languagePreference('reviewLanguage', '错题语言', true)}
            </div>
          </div>
          <div class="settings-block">
            <h2 class="settings-block-title">单词本与句型</h2>
            ${languagePreference('notebookLanguage', '收藏语言', true)}
          </div>
          </section>
        </div>
      </section>`;

    els = {
      personaList: root.querySelector('#settings-persona-list'),
      form: root.querySelector('#persona-form'),
      bookHooks: root.querySelector('#settings-book-hooks'),
      bookEmpty: root.querySelector('#settings-book-empty'),
      name: root.querySelector('#f-name'),
      language: root.querySelector('#f-language'),
      relation: root.querySelector('#f-relation'),
      tone: root.querySelector('#f-tone'),
      keigoWrap: root.querySelector('#f-keigo-wrap'),
      keigo: root.querySelector('#f-keigo'),
      interests: root.querySelector('#f-interests'),
      freeText: root.querySelector('#f-free-text'),
      saveFlash: root.querySelector('#save-flash'),
      memoryList: root.querySelector('#memory-list'),
      voice: root.querySelector('#f-voice'),
      voiceTabs: root.querySelector('.voice-tabs'),
      voiceCount: root.querySelector('.voice-count'),
      voiceTotal: root.querySelector('.voice-total'),
      voiceImport: root.querySelector('#btn-voice-import'),
      voiceFile: root.querySelector('#f-voice-file'),
      addMemory: root.querySelector('#btn-add-memory'),

      avatarPreview: root.querySelector('#f-avatar-preview'),
      avatarFile: root.querySelector('#f-avatar-file'),
      avatarPick: root.querySelector('#btn-avatar-pick'),
      avatarClear: root.querySelector('#btn-avatar-clear'),
      avatarHint: root.querySelector('#f-avatar-hint'),

      dangerZone: root.querySelector('#danger-zone'),
      deletePersonaBtn: root.querySelector('#btn-delete-persona'),
      coachBridge: root.querySelector('#f-coach-bridge'),
      listeningSubscription: root.querySelector('#f-listening-subscription'),
    };

    const memoryDialog = root.querySelector('#memory-new-dialog');
    const memoryForm = root.querySelector('#memory-new-form');
    let memoryTarget = null;
    let memoryRevision = 0;
    els.addMemory.onclick = () => {
      ++memoryRevision;
      memoryTarget = sState.selectedPersonaId;
      if (memoryTarget == null) return;
      memoryForm.reset(); memoryForm.querySelector('[role=status]').textContent = '';
      memoryForm.querySelector('[type=submit]').disabled = false;
      memoryDialog.showModal(); memoryForm.elements.content.focus();
    };
    memoryForm.querySelectorAll('[data-memory-close]').forEach(button => { button.onclick = () => memoryDialog.close(); });
    memoryDialog.addEventListener('close', () => { ++memoryRevision; });
    memoryDialog.addEventListener('cancel', () => { ++memoryRevision; });
    memoryForm.onsubmit = async event => {
      event.preventDefault(); const content = memoryForm.elements.content.value.trim();
      if (!content || memoryTarget == null) return;
      const button = memoryForm.querySelector('[type=submit]'); button.disabled = true;
      const current = memoryRevision, target = memoryTarget;
      try {
        await LP.api.createMemory({persona_id: target, category: memoryForm.elements.category.value, content, active:true});
        if (current === memoryRevision) memoryDialog.close();
        if (target === sState.selectedPersonaId) await loadMemory(target);
      } catch (error) { if (current === memoryRevision) memoryForm.querySelector('[role=status]').textContent = LP.util.message(error, '没加上，再试一次'); }
      finally { if (current === memoryRevision) button.disabled = false; }
    };

    els.keigo.querySelectorAll('.seg-opt').forEach((opt) => {
      opt.addEventListener('click', () => {
        els.keigo.querySelectorAll('.seg-opt').forEach((o) => o.classList.remove('active'));
        opt.classList.add('active');
        if (sState.keigo !== opt.dataset.val) setRoleDirty(true);
        sState.keigo = opt.dataset.val;
      });
    });
    els.library = LP.settingsTeaching.wire(root.querySelector('#settings-library'));
    document.addEventListener('lp:lore-books', event => {
      ++bookRead;
      const ids = bookChoicesReady && roleDirty ? selectedBooks() : LP.getPersona(sState.selectedPersonaId)?.profile?.world_book_ids || [];
      bookChoices = Array.isArray(event.detail) ? event.detail : [];
      bookChoicesReady = true;
      if (!roleSaving) renderBookHooks(ids);
    });
    document.addEventListener('lp:teaching-settings', () => {
      if (!root.classList.contains('active')) return;
      void refreshBookHooks();
    });
    els.form.addEventListener('input', () => { setRoleDirty(true); });
    els.voice.addEventListener('input', () => { sState.voice[sState.voiceLang] = voiceLines(els.voice.value); paintVoiceCount(); });
    els.voiceImport.addEventListener('click', () => els.voiceFile.click());
    els.voiceFile.addEventListener('change', async () => {
      const file = els.voiceFile.files?.[0];
      els.voiceFile.value = '';
      if (!file) return;
      const added = voiceLines(await file.text());
      const merged = [...new Set([...(sState.voice[sState.voiceLang] || []), ...added])];
      sState.voice[sState.voiceLang] = merged;
      setRoleDirty(true);
      renderVoice();   // 条数在下面的计数里
    });
    els.chatRoom = LP.settingsChatRoom.mount(root.querySelector('#settings-chat-room'));
    els.language.addEventListener('change', updateKeigoVisibility);

    els.form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const id = sState.selectedPersonaId;
      const name = els.name.value.trim();
      if (!name) { els.name.focus(); LP.util.tick(els.name, false, '要填名字'); return; }
      const submit = els.form.querySelector('[type="submit"]');
      if (submit.disabled) return;
      try {
        const profile = { ...LP.getPersona(id)?.profile, relation: els.relation.value.trim(),
          tone: els.tone.value.trim(), interests: sState.interests, free_text: els.freeText.value.trim(), voice_samples: cleanVoice(),
          ...(bookChoicesReady ? {world_book_ids: selectedBooks()} : {}) };
        if (els.language.value === 'ja') profile.keigo = sState.keigo;
        else delete profile.keigo;
        const body = { name, language: els.language.value, profile };
        submit.disabled = true;
        roleSaving = true;
        const saved = id == null ? await LP.api.createPersona(body) : await LP.api.updatePersona(id, body);
        await LP.appShell.reloadPersonas();
        await els.chatRoom.refresh();
        if (sState.selectedPersonaId !== id) { renderPersonaList(); return; }
        sState.selectedPersonaId = saved.id;
        setRoleDirty(false);
        renderPersonaList();
        renderBookHooks(saved.profile?.world_book_ids || profile.world_book_ids || []);
        loadMemory(saved.id);
        els.dangerZone.classList.remove('hidden');
        els.saveFlash.classList.add('show');
        setTimeout(() => els.saveFlash.classList.remove('show'), 1600);
      } catch (e) { LP.toast?.(LP.util.message(e, '没存上，再试一次')); }
      finally { roleSaving = false; submit.disabled = false; }
    });

    els.deletePersonaBtn.addEventListener('click', deletePersona);

    const pages = [...root.querySelectorAll('[data-settings-page]')];
    const tabs = [...root.querySelectorAll('[data-settings-tab]')];
    els.providerSettings = LP.settingsProviders.wire(root);
    els.characterVoice = LP.settingsVoice?.wire(root.querySelector('#settings-character-voice'));
    els.models = LP.settingsModels.wire(root.querySelector('#settings-models'));
    els.hooks = LP.settingsHooks.wire(root.querySelector('[data-settings-hooks]'));
    function showPage(key) {
      pages.forEach(page => { page.hidden = page.dataset.settingsPage !== key; });
      tabs.forEach(tab => tab.setAttribute('aria-pressed', tab.dataset.settingsTab === key));
      root.querySelector('.settings-form-area').scrollTop = 0;
      if (key === 'models') void els.models.refresh();
      if (key === 'voice') void els.characterVoice?.refresh();
      else els.characterVoice?.stop();
      if (key === 'hooks') void els.hooks.refresh();
      if (key === 'speak') void loadCoachBridge();
      if (key === 'listen') {
        void loadListening();
        void els.providerSettings.loadListening();
      }
      if (key === 'speak') void els.providerSettings.loadSpeaking();
      if (key === 'library') els.library.refresh();
    }
    // 改了没存：离开前拦一下。三处来源，isDirty 取或：
    //   角色表单 → roleDirty（文字、下拉、勾选、敬语、兴趣、口吻样本导入都算；存成功才清）；
    //   别的「按保存才存」的表单（声音、阅读排版、阅读默认安排、题型对话框…）→ 表单里任何控件改了都算；
    //   世界书、事件规则 → 各自模块的 isDirty。改了就存的控件（开关、聊天安排、模型）不在这里。
    const dirtyForms = new Set();
    const area = root.querySelector('.settings-form-area');
    const markForm = (form) => { dirtyForms.add(form); form.classList.add('dirty'); };
    const cleanForm = (form) => { dirtyForms.delete(form); form.classList.remove('dirty'); };
    const trackedForm = (target) => {
      const form = target.closest('form');
      return form && form !== els.form && form.querySelector('[type="submit"]') ? form : null;
    };
    area.addEventListener('input', (ev) => { const form = trackedForm(ev.target); if (form) markForm(form); });
    area.addEventListener('change', (ev) => { const form = trackedForm(ev.target); if (form) markForm(form); });
    area.addEventListener('submit', (ev) => cleanForm(ev.target), true);
    area.addEventListener('lp:form-saved', (ev) => cleanForm(ev.target));   // 不经 submit 存的（比如「保存并试听」）
    // 对话框关掉（取消 / Esc）：里面填了一半的不算
    area.addEventListener('close', (ev) => { if (ev.target.matches?.('dialog')) ev.target.querySelectorAll('form').forEach(cleanForm); }, true);
    const formsDirty = () => [...dirtyForms].some((form) => form.isConnected && !form.closest('[hidden]') && !form.closest('dialog:not([open])'));
    els.isDirty = () => roleDirty || formsDirty() || Boolean(LP.settingsLore?.isDirty?.()) || Boolean(els.hooks?.isDirty?.()) || Boolean(els.characterVoice?.isDirty());
    els.clearDirty = () => {
      dirtyForms.forEach((form) => form.classList.remove('dirty')); dirtyForms.clear();
      if (roleDirty) { setRoleDirty(false); loadForm(LP.getPersona(sState.selectedPersonaId)); }
      LP.settingsLore?.discard?.();
      els.hooks?.discard?.();
      els.characterVoice?.discard();
    };
    global.addEventListener('beforeunload', (ev) => { if (els.isDirty?.()) { ev.preventDefault(); ev.returnValue = ''; } });
    async function leaveOk() {
      if (!els.isDirty()) return true;
      const ok = await confirmLeave();
      if (ok) els.clearDirty();
      return ok;
    }
    els.leaveOk = leaveOk;
    for (const tab of tabs) tab.addEventListener('click', async () => { if (tab.getAttribute('aria-pressed') === 'true' || await leaveOk()) showPage(tab.dataset.settingsTab); });
    els.showPage = showPage;
    showPage('chat');
    for (const field of root.querySelectorAll('[data-preference]')) {
      const key = field.dataset.preference;
      const save = value => {
        const saved = LP.preferences.set(key, value);
        LP.util.tick(field, Boolean(saved));
      };
      if (field.tagName === 'SELECT') {
        field.value = LP.preferences.get(key);
        field.addEventListener('change', () => save(field.value));
      } else if (field.type === 'checkbox') {
        field.checked = LP.preferences.get(key);
        field.addEventListener('change', () => { save(field.checked); field.checked = LP.preferences.get(key); });
      } else {
        const options = [...field.querySelectorAll('button')];
        const update = () => options.forEach(option => option.setAttribute('aria-pressed', String(option.dataset.value === LP.preferences.get(key))));
        update();
        options.forEach(option => option.addEventListener('click', () => { save(option.dataset.value); update(); }));
      }
    }
    const defaults = [...root.querySelectorAll('[data-language-default]')];
    function renderLanguageDefaults() {
      for (const field of defaults) {
        const tags = LP.languages.list().map(({tag, label}) => new Option(label, tag));
        if (field.dataset.all === 'true') tags.unshift(new Option('全部语言', ''));
        field.replaceChildren(...tags);
        field.value = LP.preferences.get(field.dataset.languageDefault);
        if (field.selectedIndex === -1 && tags.length) field.selectedIndex = 0;
      }
    }
    for (const field of defaults) field.onchange = () => {
      LP.util.tick(field, Boolean(LP.preferences.set(field.dataset.languageDefault, field.value)));
    };
    renderLanguageDefaults();
    document.addEventListener('lp:languages', renderLanguageDefaults);
    document.addEventListener('lp:languages', () => {
      const value = els.language.value;
      renderPersonaLanguages(value);
      els.language.value = value;
    });
    wireSmallSettings();
    wireReviewPlan();
    wireAvatarEditor();
    LP.settingsReading?.mount(root.querySelector('[data-settings-reading]'));

    refresh();
  }

  // 复习：GET /api/learning/settings 读，PUT /api/settings 写；保持率越高间隔越短（箭头示意）
  function wireReviewPlan() {
    const box = document.querySelector('[data-review-plan]');
    if (!box) return;
    const range = box.querySelector('#f-review-retention'), out = box.querySelector('.review-retention output'), arrow = box.querySelector('.review-arrow');
    const fresh = box.querySelector('#f-review-new'), mix = box.querySelector('#f-review-mix'), first = box.querySelector('#f-reading-first');
    let base = 90;
    const paint = () => {
      out.textContent = range.value + '%';
      const d = Number(range.value) - base;
      arrow.textContent = d > 0 ? '↓' : d < 0 ? '↑' : '';
      arrow.className = 'review-arrow' + (d > 0 ? ' short' : d < 0 ? ' long' : '');
    };
    // 改了就存：控件旁边打勾 / 打叉
    const put = async (patch, field) => {
      try { await LP.api.putSettings(patch); LP.util.tick(field, true); global.dispatchEvent(new CustomEvent('lp:learning-settings', { detail: { ...current, ...patch } })); Object.assign(current, patch); }
      catch (error) { LP.util.tick(field, false, LP.util.message(error, '没存上')); await load(); }
    };
    let current = {};
    async function load() {
      try {
        const response = await fetch('/api/learning/settings', { cache: 'no-store' });
        if (!response.ok) throw new Error();   // 出错时的返回体不能当成设置读进来
        current = await response.json();
        base = Math.round((current.review_target_retention ?? 0.9) * 100);
        range.value = base; fresh.value = current.review_new_per_day ?? 12;
        mix.checked = current.review_mix !== false; first.checked = Boolean(current.reading_questions_first);
        paint();
      } catch { LP.util.tick(range, false, '读不到'); }
    }
    range.oninput = paint;
    range.onchange = () => { void put({ review_target_retention: Number(range.value) / 100 }, range).then(() => { base = Number(range.value); paint(); }); };
    fresh.onchange = () => { const v = Math.max(0, Math.min(50, Math.round(Number(fresh.value) || 0))); fresh.value = v; void put({ review_new_per_day: v }, fresh); };
    mix.onchange = () => void put({ review_mix: mix.checked }, mix.parentElement);
    first.onchange = () => void put({ reading_questions_first: first.checked }, first.parentElement);
    void load();
  }

  function refresh() {
    if (!els.personaList) return;
    if (!roleDirty && sState.selectedPersonaId == null && LP.state.personas.length) sState.selectedPersonaId = LP.state.currentPersonaId || LP.state.personas[0].id;
    renderPersonaList();
    void els.chatRoom?.refresh();
    const p = LP.getPersona(sState.selectedPersonaId);
    if (!roleDirty && !roleSaving) loadForm(p);
    if (p) loadMemory(p.id);
    void refreshBookHooks();
    if (!document.getElementById('settings-library').hidden) els.library.refresh();
    if (!document.getElementById('settings-models').hidden) void els.models.refresh();
    if (!document.getElementById('settings-hooks').hidden) void els.hooks.refresh();
  }

  function renderUsage(u) { els.models?.renderUsage(u); }

  global.LP = global.LP || {};
  global.LP.settings = { mount, refresh, renderUsage, isDirty: () => Boolean(els.isDirty?.()),
    leaveOk: () => (els.leaveOk ? els.leaveOk() : Promise.resolve(true)),
    leave: () => els.characterVoice?.stop(), open(page = 'chat') {
    LP.appShell.switchTab('settings');
    const go = () => els.showPage?.(PAGES.some(([key]) => key === page) ? page : 'chat');
    if (els.showPage) go(); else void LP.appShell.ready?.('settings').then(go);
  }, newPersona() {
    this.open('chat');
    void selectPersona(null).then((ok) => { if (ok) els.name?.focus(); });
  } };
})(window);
