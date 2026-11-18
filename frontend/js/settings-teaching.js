/* Courses belong to learning languages. All screens edit the same records. */
(function (global) {
  'use strict';
  const {LP} = global;
  let controller, preferredLanguage, presetRequest;
  const { el: node, button: action } = LP.util;
  const presets = () => presetRequest ||= LP.api.getTeachingPresets().then(result => result.items).catch(error => { presetRequest = null; throw error; });
  const name = tag => LP.languages.label(tag);
  const changed = () => document.dispatchEvent(new Event('lp:teaching-settings'));
  document.addEventListener('lp:course-build', () => { presetRequest = null; });   // 管家开始做一门新课：下次打开课程页重新读目录
  const ask = text => LP.workspaceAgent.prefill(text);
  function bodyOf(bundle) {
    const value = bundle.teaching || {};
    return {mode: value.mode || 'off', ...(value.preset_id ? {preset: value.preset_id} : {})};
  }
  const outlineOf = (bundle, all) => all.find(item => item.id === bundle.teaching?.preset_id);
  const markup = `<div class="course-preview">
    <nav class="course-preview-tabs" aria-label="课程与世界书"><button type="button" data-course-tab="course" aria-pressed="true">课程</button><button type="button" data-course-tab="world" aria-pressed="false">世界书</button></nav>
    <section data-course-panel="course">
      <div class="course-language-tabs" aria-label="课程语言"></div>
      <div class="course-preview-toolbar"><span data-course="state"></span><div><button type="button" data-course="choose">更换课程</button></div></div>
      <div data-course="empty" class="course-empty" hidden><h2>选择一门课程</h2></div>
      <div data-course="choices" class="course-choices" hidden></div><article class="course-paper" data-course="paper"></article>
    </section>
    <section data-course-panel="world" hidden><div data-lore-root></div></section><p class="course-preview-status" data-course="notice" role="status"></p>
  </div>`;

  function pointStatus(state) {
    const labels={new:'',learning:'学习中',known:'已掌握'};
    const status=node('div','','course-point-status');
    const value=state?.status||'new';
    if(labels[value]){const chip=node('span',labels[value]);chip.dataset.status=value;status.append(chip);}
    return status;
  }

  function wire(root) {
    const get = key => root.querySelector('[data-course="' + key + '"]');
    let language = preferredLanguage || LP.currentPersona?.()?.language || LP.languages.list()[0]?.tag;
    let all = [], bundle, draft, outline, ticket = 0, saving = false;
    const notice = text => { get('notice').textContent = text; };
    function paintLanguages() {
      root.querySelector('.course-language-tabs').replaceChildren(...LP.languages.list().map(({tag, label}) => {
        const button = action(label, () => selectLanguage(tag)); button.setAttribute('aria-pressed', String(tag === language)); return button;
      }));
    }
    function paintChoices() {
      const target = get('choices'); target.replaceChildren();
      for (const item of all.filter(item => item.language === language)) {
        const button = action('', () => {
          draft = {mode: 'ambient', preset: item.id}; outline = item; target.hidden = true; paintCourse();
        }, 'course-choice');
        button.append(node('strong', item.title), node('span', item.units.length + ' 节课'));
        button.setAttribute('aria-pressed', String(draft?.preset === item.id)); target.append(button);
      }
      target.append(action('让管家做一门备考课', () => ask('帮我做一门' + name(language) + '的备考课。我要考的是：'), 'course-choice-create'));
    }
    // 管家做出来的课（id 以 my- 开头）：没做完的课排在下面，能接着做、重做、删掉。做的时候每 5 秒看一次进度。
    let builds = [], buildTimer = 0;
    const BUILD_STATE = { building: '在做', waiting: '还没轮到', failed: '没做成' };
    async function refreshBuild() {
      const current = ticket;
      if (!root.offsetParent) return;   // 页面不在眼前就不轮询；回到这页时 refresh() 会重新开始
      try {
        presetRequest = null;
        const [catalog, result, made] = await Promise.all([presets(), LP.api.getCourse(language), LP.api.getBuilds()]);
        if (current !== ticket || saving) return;
        all = catalog; bundle = result; builds = made.builds || [];
        const kept = all.find(item => item.id === outline?.id);
        if (kept) outline = kept;
        paintCourse();
      } catch (error) { if (current === ticket) notice(LP.util.message(error)); }
    }
    function paintBuild(paper) {
      clearTimeout(buildTimer);
      const build = builds.find(item => item.course_id === outline.id);
      if (!build) return;
      const left = (build.lessons || []).filter(row => row.status !== 'done');
      const box = node('section', '', 'course-build'), head = node('div', '', 'course-build-head');
      const run = async (work) => { try { await work(); await refreshBuild(); } catch (error) { notice(LP.util.message(error)); } };
      if (build.status === 'running') {
        head.append(node('strong', left.length ? '管家正在做这门课' : '正在排课表'), action('先停下', () => run(() => LP.api.stopBuild(outline.id))));
        buildTimer = setTimeout(refreshBuild, 5000);
      } else if (left.length) {
        head.append(node('strong', build.status === 'stopped' ? '做到一半停了' : left.length + ' 课没做成'),
          action(build.status === 'stopped' ? '接着做' : '重做这几课', () => run(() => LP.api.resumeBuild(outline.id)), 'course-primary'));
      }
      const remove = action('删掉这门课', async () => {
        if (!await LP.util.confirm({ title: '删掉「' + outline.title + '」？', ok: '删掉' })) return;
        run(async () => { await LP.api.deleteBuild(outline.id); outline = null; draft = {mode: 'off'}; changed(); });
      }, 'course-build-remove');
      head.append(remove);
      box.append(head);
      if (left.length) {
        const list = node('ol', '', 'course-build-list');
        for (const row of left) {
          const item = node('li'), state = node('span', BUILD_STATE[row.status] + (row.status === 'building' && row.steps ? ' ' + row.step + ' / ' + row.steps : ''), 'course-build-state');
          state.dataset.status = row.status;
          item.append(node('span', row.title), state);
          list.append(item);
        }
        box.append(list);
      }
      for (const skipped of build.skipped || []) box.append(node('p', '没做：' + skipped.item + '（' + skipped.why + '）', 'course-build-skipped'));
      paper.append(box);
    }
    function paintCourse() {
      const paper = get('paper'); paper.replaceChildren();
      const current = outlineOf(bundle, all), same = JSON.stringify(bodyOf(bundle)) === JSON.stringify(draft);
      get('state').textContent = same && current ? (draft.mode === 'ambient' ? '使用中' : '已暂停') : '';
      get('empty').hidden = Boolean(outline);
      if (!outline) {
        get('choices').hidden = false; paintChoices(); return;
      }
      paper.append(node('h2', outline.title, 'course-title'));
      const meta = node('div', '', 'course-paper-meta'); meta.append(node('span', name(language)), node('span', outline.units.length + ' 节课'));
      if (same && bundle.progress?.counts?.points > 0) {
        const {known,points}=bundle.progress.counts;
        const bar=node('span','','course-bar');bar.setAttribute('role','img');bar.setAttribute('aria-label','课程进度');
        const learned=node('i','','known');
        learned.style.width=known/points*100+'%';bar.append(learned);
        meta.append(bar,node('span','已掌握 '+known+' / '+points));
      }
      paper.append(meta);
      const {lesson,next}=bundle.progress||{};
      const goLesson=unitId=>LP.lesson.start(language,unitId).catch(()=>{});   // 出错时 lesson.js 自己弹提示
      if(same&&draft.mode==='ambient'&&(lesson||next)){
        const go=action('',()=>lesson?LP.appShell.switchTab(LP.lesson.current()?.venue === 'chat' ? 'talk' : 'course'):goLesson(next.unit_id),'course-next course-primary');
        go.append(node('b',lesson?'回到课上':'上第 '+(outline.units.findIndex(unit=>unit.id===next.unit_id)+1)+' 课'),node('span',(lesson||next).title));
        paper.append(go);
      }
      const activate = action(same && draft.mode === 'ambient' ? '暂停课程' : '设为默认课程', async () => {
        draft.mode = same && draft.mode === 'ambient' ? 'off' : 'ambient'; await save();
      }, same && draft.mode === 'ambient' ? 'course-active-switch' : 'course-primary');
      activate.disabled = saving; paper.append(activate);
      const groupLists = new Map();
      let units = node('ol', '', 'course-unit-list');
      {
        for (const group of outline.sections) {
          const existing = group.lessons.map(id => outline.units.find(unit => unit.id === id)).filter(Boolean);
          if (!existing.length) continue;
          const list = node('ol', '', 'course-unit-list');
          paper.append(node('h3', group.title, 'course-section'), list);
          groupLists.set(group.id, list);
        }
      }
      for (const [index, unit] of outline.units.entries()) {
        {
          const group = outline.sections.find(group => group.lessons.includes(unit.id));
          units = groupLists.get(group?.id);
          if (!units) continue;
        }
        const item = node('li'), section = node('details', '', 'course-unit'), summary = node('summary');
        const unitState=bundle.progress?.units?.find(value=>value.id===unit.id);
        summary.append(node('span', String(index + 1).padStart(2, '0'), 'course-unit-number'), node('strong', unit.title), node('span', unit.can_do || unit.goal, 'course-unit-goal')); section.append(summary);
        const unitStatus=same?unitState?.status||'new':'new';
        const marker=node('span','','course-unit-state');marker.dataset.status=unitStatus;marker.setAttribute('role','img');marker.setAttribute('aria-label',({new:'',learning:'学习中',known:'已掌握'})[unitStatus]);summary.append(marker);
        const content = node('div', '', 'course-unit-content');
        {
          content.classList.add('course-lesson-content');
          const actions = node('div', '', 'course-unit-actions');
          actions.append(action('上这一课', () => goLesson(unit.id), 'course-primary'));
          content.append(actions);
          for (const point of unitState?.points || []) {
            const row = node('section', '', 'course-knowledge');
            row.append(node('h4', point.label), pointStatus(same ? point : null));
            content.append(row);
          }
        }
        section.append(content); section.ontoggle = () => { if (section.open) section.closest('.course-unit-list').querySelectorAll('details[open]').forEach(other => { if (other !== section) other.open = false; }); };
        item.append(section); units.append(item);
      }
      if (outline.id.startsWith('my-')) paintBuild(paper);
    }
    async function save() {
      if (saving || !draft || !outline) return;
      saving = true; notice('');
      get('paper').querySelectorAll('input, textarea, button').forEach(el => { el.disabled = true; });
      try {
        const result = await LP.api.saveCourse(language, draft); bundle = result; draft = bodyOf(result); outline = outlineOf(result, all);
        paintCourse(); notice('已保存'); changed();
      } catch (error) { notice(LP.util.message(error)); } finally { saving = false; paintCourse(); }
    }
    async function selectLanguage(tag) {
      if (saving) return;   // 正在存：存完再换语言
      language = tag; preferredLanguage = tag; paintLanguages(); const current = ++ticket; notice('');
      get('paper').inert = true;
      try {
        clearTimeout(buildTimer);
        const [catalog, result, made] = await Promise.all([presets(), LP.api.getCourse(tag), LP.api.getBuilds().catch(() => ({builds: []}))]); if (current !== ticket) return;
        all = catalog; bundle = result; builds = made.builds || []; draft = bodyOf(result); outline = outlineOf(result, all); get('choices').hidden = true; paintCourse(); notice('');
      } catch (error) { if (current === ticket) notice(LP.util.message(error)); }
      finally { if (current === ticket) get('paper').inert = false; }
    }
    get('choose').onclick = () => { paintChoices(); get('choices').hidden = !get('choices').hidden; };

    for (const tab of root.querySelectorAll('[data-course-tab]')) tab.onclick = () => {
      root.querySelectorAll('[data-course-tab]').forEach(item => item.setAttribute('aria-pressed', String(item === tab)));
      root.querySelectorAll('[data-course-panel]').forEach(panel => { panel.hidden = panel.dataset.coursePanel !== tab.dataset.courseTab; });
      if (tab.dataset.courseTab === 'world') LP.settingsLore.show(root.querySelector('[data-lore-root]')); else refresh(); notice('');
    };
    const refresh = () => { if (!saving) void selectLanguage(preferredLanguage || language); };
    document.addEventListener('lp:teaching-settings', () => { if (!root.closest('[hidden]') && !root.querySelector('[data-course-panel="course"]').hidden) refresh(); });
    document.addEventListener('lp:languages', paintLanguages);
    controller = {refresh, selectLanguage, showWorld() { root.querySelector('[data-course-tab="world"]').click(); }};
    paintLanguages(); refresh(); return controller;
  }

  async function openPicker(language) {
    document.getElementById('jine-course-picker')?.remove();
    const dialog = node('dialog', '', 'course-picker'); dialog.id = 'jine-course-picker'; dialog.setAttribute('aria-label', '选择课程');
    const header = node('header'); header.append(node('h2', name(language) + '课程'), action('×', () => dialog.close()));
    const list = node('div', '', 'course-picker-list'), status = node('p', '', 'course-muted'); status.setAttribute('role', 'status');
    dialog.append(header, status, list, action('编辑课程', () => { dialog.close(); LP.settings.open('library'); LP.settingsTeaching.setLanguage(language); }, 'course-text-action'));
    document.body.append(dialog); dialog.showModal(); dialog.addEventListener('close', () => dialog.remove(), {once: true});
    try {
      const [all, bundle] = await Promise.all([presets(), LP.api.getCourse(language)]); if (!dialog.open) return;
      status.textContent = '';
      const current = outlineOf(bundle, all), choices = all.filter(item => item.language === language);
      for (const item of choices) {
        const selected = current === item || bundle.teaching?.preset_id === item.id;
        const button = action('', async () => {
          list.querySelectorAll('button').forEach(el => { el.disabled = true; });
          try { await LP.api.saveCourse(language, {mode: 'ambient', preset: item.id}); changed(); dialog.close(); }
          catch (error) { status.textContent = LP.util.message(error); list.querySelectorAll('button').forEach(el => { el.disabled = false; }); }
        }, 'course-picker-choice');
        button.append(node('strong', item.title), node('span', selected && bundle.teaching.mode === 'ambient' ? '使用中' : item.units.length + ' 节课')); list.append(button);
      }
      if (current && bundle.teaching.mode === 'ambient') list.append(action('暂停课程', async () => {
        try { await LP.api.saveCourse(language, {...bodyOf(bundle), mode: 'off'}); changed(); dialog.close(); } catch (error) { status.textContent = LP.util.message(error); }
      }, 'course-text-action'));
      if (!choices.length) list.append(action('让管家做一门课', () => { dialog.close(); ask('帮我做一门' + name(language) + '的课。'); }, 'course-primary'));
    } catch (error) { status.textContent = LP.util.message(error); }
  }
  // 聊天「⋯」里的课程项：点了在聊天里弹出选课框（openPicker）
  async function paintChatButton(button, language) {
    const ticket = button.dataset.language = language; button.textContent = '选择课程'; button.onclick = () => openPicker(language);
    try {
      const [all, bundle] = await Promise.all([presets(), LP.api.getCourse(language)]); if (button.dataset.language !== ticket) return;
      const outline = outlineOf(bundle, all);
      button.textContent = outline ? (bundle.teaching.mode === 'ambient' ? '课程 · ' : '已暂停 · ') + outline.title : '选择课程';
      button.dataset.active = String(Boolean(outline && bundle.teaching.mode === 'ambient'));
    } catch { if (button.dataset.language === ticket) button.textContent = '选择课程'; }
  }
  document.addEventListener('lp:teaching-settings', () => { presetRequest = null; });
  LP.settingsTeaching = {markup, wire, openPicker, paintChatButton, setLanguage(tag) { preferredLanguage = tag; return controller?.selectLanguage(tag); }, showWorld() { controller?.showWorld(); }};
})(window);
