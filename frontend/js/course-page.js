/* course-page.js — 「学习 › 课程」。三层：
   目录：整门课所有的课排成一张表，想上哪节点哪节；每种题型旁边有它的练习。
   课：点进去是一整节课，从头读到尾，最后是本课小测。
   练习：按题型一直练；上面是「这种题怎么做」和对应的课，交卷后告诉你错的题该回去看哪一课。
   限时写作练习在聊天页里写，从目录点过去。 */
(function (global) {
  'use strict';
  const { LP } = global;
  const h = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text != null) node.textContent = text; return node; };
  const STATUS = { new: '', learning: '学习中', known: '已掌握' };
  const LEARNED = ['known'];
  const recall = () => { try { return localStorage.getItem('lp.course.language'); } catch (e) { return null; } };
  const keep = (tag) => { try { localStorage.setItem('lp.course.language', tag); } catch (e) { /* 只是记住上次看的是哪门 */ } };

  function mount(root) {
    root.classList.add('course-page');
    const catalog = h('div', 'cp-catalog'), lesson = h('div', 'cp-lesson');
    lesson.hidden = true;
    root.replaceChildren(catalog, lesson);
    let language = recall(), ticket = 0, course = null, bundle = null;
    let open = null;              // { kind: 'lesson' | 'practice', id, part }
    const cards = new Map();

    const unit = (id) => course.units.find((item) => item.id === id);
    const status = (id) => bundle.progress?.units?.find((item) => item.id === id)?.status || 'new';
    const title = (id) => unit(id)?.title || course.titles?.[id] || id;
    const practiceLessons = () => new Set(course.sections.flatMap((part) => (part.parts || []).map((group) => group.practice?.lesson).filter(Boolean)));

    // 三样都在页面最上面选：语言、这门语言的哪门课、哪一部分
    let choices = [];             // 每门有分项课的语言：{ tag, options: [课], bundle, active: 正在用的那门 }
    const sectionKey = () => 'lp.course.section.' + (course?.id || '');

    async function load() {
      const current = ++ticket;
      const all = await LP.api.getTeachingPresets().then((result) => result.items);
      const tags = LP.languages.list().map((item) => item.tag);
      const bundles = await Promise.all(tags.map((tag) => LP.api.getCourse(tag).catch(() => null)));
      if (current !== ticket) return false;
      choices = tags.map((tag, n) => {
        const options = all.filter((item) => item.language === tag);
        const teaching = bundles[n]?.teaching;
        return { tag, options, bundle: bundles[n], active: teaching?.mode === 'ambient' ? options.find((item) => item.id === teaching.preset_id) || null : null };
      }).filter((item) => item.options.length);
      const mine = choices.find((item) => item.tag === language) || choices.find((item) => item.active) || choices[0] || null;
      language = mine?.tag || language; course = mine?.active || null; bundle = mine?.bundle || null;
      return mine;
    }

    async function choose(id) {
      try { await LP.api.saveCourse(language, { mode: 'ambient', preset: id }); document.dispatchEvent(new Event('lp:teaching-settings')); }
      catch (error) { LP.toast?.(/^请求失败/.test(error.message) ? '没存上' : error.message); void paintCatalog(); }
    }

    async function paintCatalog() {
      let mine;
      try { mine = await load(); } catch (error) { catalog.replaceChildren(h('p', 'cp-empty', '没连上')); return; }
      if (mine === false) return;
      catalog.replaceChildren();
      if (!mine) {
        const empty = h('div', 'cp-empty'), ask = h('button', 'cp-primary', '让管家做一门课');
        ask.type = 'button'; ask.onclick = () => LP.workspaceAgent.prefill('帮我做一门备考课。我要考的是：');
        empty.append(h('p', '', '还没有课程'), ask);
        catalog.append(empty);
        return;
      }
      const head = h('header', 'cp-head'), langs = h('div', 'cp-languages');
      for (const item of choices) {
        const button = h('button', '', LP.languages.label(item.tag));
        button.type = 'button'; button.setAttribute('aria-pressed', String(item.tag === language));
        button.onclick = () => { language = item.tag; keep(language); void paintCatalog(); };
        langs.append(button);
      }
      head.append(langs);
      if (course) {
        const pick = h('select', 'cp-course');
        pick.setAttribute('aria-label', '课程');
        for (const option of mine.options) pick.append(new Option(option.title, option.id, false, option.id === course.id));
        pick.onchange = () => { pick.disabled = true; void choose(pick.value); };
        head.append(pick);
      }
      catalog.append(head);
      if (!course) {                                   // 这门语言有分项课，但还没选用哪一门
        const list = h('ol', 'cp-list cp-courses');
        for (const option of mine.options) {
          const row = h('li', ''), go = h('button', 'cp-row', '');
          go.type = 'button';
          go.append(h('span', 'cp-title', option.title), h('span', 'cp-status', option.units.length + ' 课'));
          go.onclick = () => { go.disabled = true; void choose(option.id); };
          row.append(go); list.append(row);
        }
        catalog.append(list);
        return;
      }
      const hidden = practiceLessons();
      const listed = (part) => (part.parts || [{ title: '', lessons: part.lessons }]).flatMap((group) => group.lessons).filter((id) => !hidden.has(id) && (unit(id) || course.titles?.[id]));
      const sections = course.sections.filter((part) => listed(part).length);
      let wanted = null;
      try { wanted = localStorage.getItem(sectionKey()); } catch (e) { wanted = null; }
      const section = sections.find((part) => part.id === wanted) || sections[0];
      const tabs = h('nav', 'cp-sections');
      for (const part of sections) {
        const ids = listed(part), tab = h('button', '', '');
        tab.type = 'button'; tab.setAttribute('aria-pressed', String(part === section));
        tab.append(h('span', '', part.title), h('small', '', ids.filter((id) => unit(id) && LEARNED.includes(status(id))).length + ' / ' + ids.length));
        tab.onclick = () => { try { localStorage.setItem(sectionKey(), part.id); } catch (e) { /* 只是记住上次看的是哪一部分 */ } void paintCatalog(); };
        tabs.append(tab);
      }
      catalog.append(tabs);
      let number = 0;
      for (const group of section.parts || [{ title: '', lessons: section.lessons }]) {
        const ids = group.lessons.filter((id) => !hidden.has(id) && (unit(id) || course.titles?.[id]));
        if (!ids.length) continue;
        if (group.title) {
          const bar = h('div', 'cp-part');
          bar.append(h('h3', '', group.title));
          if (group.practice) {
            const practise = h('button', 'cp-practise', '练习　' + group.practice.title);
            practise.type = 'button'; practise.onclick = () => enter({ kind: 'practice', id: group.practice.lesson, part: group }, practise);
            bar.append(practise);
          }
          catalog.append(bar);
        }
        const list = h('ol', 'cp-list');
        for (const id of ids) {
          const row = h('li', ''), there = Boolean(unit(id));
          const go = h('button', 'cp-row', '');
          go.type = 'button'; go.disabled = !there;
          const mark = h('span', 'cp-status', there ? STATUS[status(id)] : '未完成');
          mark.dataset.status = there ? status(id) : 'none';
          go.append(h('span', 'cp-number', String(++number).padStart(2, '0')), h('span', 'cp-title', title(id)), mark);
          go.onclick = () => enter({ kind: 'lesson', id, part: group }, go);
          row.append(go);
          list.append(row);
        }
        catalog.append(list);
      }
    }

    // 进一节课或一种练习。练习可能要现出题，按钮上显示在等
    async function enter(target, button) {
      const label = button?.textContent;
      if (button) { button.disabled = true; if (target.kind === 'practice') button.textContent = '出题中…'; }
      try {
        if (target.kind === 'practice' && target.part.practice.open) {
          const practice = target.part.practice;
          const lessons = [...new Set(Object.values(practice.points || {}))].map((id) => ({ id, title: title(id), ready: Boolean(unit(id)) }));
          LP.appShell.switchTab('coach');
          await LP.appShell.ready('coach');
          LP.coach.practise(practice.open, { brief: practice.brief, lessons, language });
        } else if (target.kind === 'practice' && target.part.practice.venue === 'chat') await LP.lesson.write(language, target.id);   // 限时写作在聊天页里写
        else { open = target; await LP.lesson[target.kind === 'practice' ? 'practice' : 'start'](language, target.id); }
      } catch (error) { open = null; if (target.kind !== 'lesson') LP.toast?.(error.message); }   // 开课出错 LP.lesson.start 自己已经提示过
      finally { if (button) { button.disabled = false; if (label) button.textContent = label; } }
    }

    function nextLesson(id) {
      const hidden = practiceLessons();
      const order = course.sections.flatMap((section) => section.lessons).filter((item) => !hidden.has(item) && unit(item));
      return order[order.indexOf(id) + 1] || null;
    }

    // 课不是从这一页点开的（聊天页的「上课」、今天页、重开软件之后还开着的课）：接过来
    let adopting = false;
    async function adopt(view) {
      if (adopting) return;
      adopting = true;
      try {
        if (view.language !== language || course?.id !== view.course_id) { language = view.language; keep(language); await paintCatalog(); }
        if (!course || course.id !== view.course_id || LP.lesson.current()?.id !== view.id) return;
        const held = view.practice && course.sections.flatMap((section) => section.parts || []).find((group) => group.practice?.lesson === view.lesson_id);
        open = held ? { kind: 'practice', id: view.lesson_id, part: held } : { kind: 'lesson', id: view.lesson_id, part: partOf(view.lesson_id) || { title: '', lessons: [] } };
      } finally { adopting = false; }
      if (open?.id === view.lesson_id) paintLesson();
    }

    function paintLesson() {
      const view = LP.lesson.current();
      if (view && view.venue === 'page' && (!open || open.id !== view.lesson_id || course?.id !== view.course_id)) {
        if (!adopting) void adopt(view);
        return;
      }
      const mine = Boolean(view && view.venue === 'page' && open && view.lesson_id === open.id && view.course_id === course?.id);
      catalog.hidden = mine; lesson.hidden = !mine;
      if (!mine) { LP.lessonCards.clear(lesson, cards); if (open) { open = null; void paintCatalog(); } return; }
      const practice = open.kind === 'practice' ? open.part.practice : null;
      let top = lesson.querySelector('.cp-top'), body = lesson.querySelector('.cp-body'), foot = lesson.querySelector('.cp-foot');
      if (!top || lesson.dataset.run !== String(view.id)) {
        LP.lessonCards.clear(lesson, cards);
        lesson.dataset.run = String(view.id);
        top = h('header', 'cp-top'); body = h('div', 'cp-body'); foot = h('footer', 'cp-foot');
        const back = h('button', 'cp-back', '← 目录');
        back.type = 'button'; back.onclick = () => {
          const current = LP.lesson.current();
          if (current?.id !== view.id) return;
          back.disabled = true; LP.lesson.stop(current).catch((error) => LP.toast?.(error.message));
        };
        top.append(back, h('span', 'cp-crumb', open.part.title || ''));
        const intro = h('div', 'cp-intro');
        if (practice) {
          intro.append(h('h1', '', (open.part.title || '').split('　')[0] + ' · 练习'));
          if (view.practice) intro.append(LP.lessonCards.brief(view.practice, (item) => lessonLink(item.id)));
        } else {
          intro.append(h('h1', '', view.title), h('p', 'cp-goal', unit(view.lesson_id)?.can_do || ''));
        }
        lesson.replaceChildren(top, intro, body, foot);
        lesson.classList.toggle('cp-practice', Boolean(practice));
        root.scrollTop = 0;
      }
      LP.lessonCards.sync(body, cards, view);
      foot.replaceChildren();
      if (view.ended) {
        if (practice && view.result) {
          const missed = new Map();
          view.set.groups.forEach((group, g) => {
            const marks = view.result.groups[g] || [], gaps = (group.tags || []).length;
            (group.tags || []).forEach((tag, k) => { if (!marks[k]) missed.set(tag, (missed.get(tag) || 0) + 1); });
            (group.items || []).forEach((item, k) => { if (!marks[gaps + k]) missed.set(item.point, (missed.get(item.point) || 0) + 1); });
          });
          const back = [...missed].filter(([point]) => practice.points?.[point]);
          if (back.length) {
            const box = h('section', 'cp-missed');
            box.append(h('h2', '', '错题对应的课程'));
            for (const [point, count] of back) { const line = h('p', ''); line.append(lessonLink(practice.points[point]), h('span', 'cp-miss-count', '错 ' + count + ' 题')); box.append(line); }
            foot.append(box);
          }
        }
        if (!practice) {
          const following = nextLesson(view.lesson_id);
          if (following) {
            const go = h('button', 'cp-primary', '下一课　' + title(following));
            go.type = 'button'; go.onclick = () => enter({ kind: 'lesson', id: following, part: partOf(following) }, go);
            foot.append(go);
          }
          const part = open.part;
          if (part.practice) {
            const practise = h('button', '', '练习　' + part.practice.title);
            practise.type = 'button'; practise.onclick = () => enter({ kind: 'practice', id: part.practice.lesson, part }, practise);
            foot.append(practise);
          }
        }
      }
    }

    const partOf = (id) => course.sections.flatMap((section) => section.parts || [{ title: '', lessons: section.lessons }]).find((group) => group.lessons.includes(id));
    function lessonLink(id) {
      const link = h('button', 'cp-link', title(id));
      link.type = 'button'; link.disabled = !unit(id);
      link.onclick = () => { void LP.lesson.start(language, id).catch(() => {}); };
      return link;
    }

    // 切到别的页、窗口藏起来：课上的录音停下
    const quiet = () => { if (document.hidden || !root.classList.contains('active')) root.querySelectorAll('audio').forEach((audio) => audio.pause()); };
    new MutationObserver(quiet).observe(root, { attributes: true, attributeFilter: ['class'] });
    document.addEventListener('visibilitychange', quiet);
    document.addEventListener('lp:lesson', paintLesson);
    document.addEventListener('lp:teaching-settings', () => { if (!open) void paintCatalog(); });
    void paintCatalog().then(paintLesson);
    return { refresh: () => { if (!open) void paintCatalog(); } };
  }

  LP.coursePage = { mount };
})(window);
