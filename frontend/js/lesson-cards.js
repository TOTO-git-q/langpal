/* 分项课的卡片：一张卡 → 一个 DOM 节点（docs/COURSE-KERNEL.md 7.1、7.6）。只管画和卡片内的输入，不管课怎么走。
   LP.lessonCards.render(card, ctx)
   ctx: { current, ended, answers, task, sheet, essay, set, result, runId,
          onNext(), onAnswer(item, text) -> {ok, fix, why}, onSubmit(text, seconds), onQuiz(answers, seconds) } */
(function (global) {
  'use strict';
  const LP = global.LP = global.LP || {};

  function h(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  const en = (node) => { node.lang = 'en'; return node; };
  const list = (tag, items, make) => { const box = h(tag); for (const item of items) box.append(make(item)); return box; };
  const words = (text) => (text.trim().match(/\S+/g) || []).length;
  const clock = (seconds) => Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
  const score = (value) => h('span', 'lc-score s' + value, String(value));

  // 作文、范文：一段英文，批注的引用处描底色、标序号
  function letter(text, notes) {
    const box = en(h('div', 'lc-letter'));
    const marks = (notes || []).map((note, n) => ({ at: text.indexOf(note.quote), note, n: n + 1 })).filter((m) => m.at >= 0).sort((a, b) => a.at - b.at);
    let cursor = 0;
    for (const mark of marks) {
      if (mark.at < cursor) continue;
      box.append(document.createTextNode(text.slice(cursor, mark.at)));
      const hit = h('mark', mark.note.kind, mark.note.quote);
      hit.append(h('sup', '', String(mark.n)));
      box.append(hit);
      cursor = mark.at + mark.note.quote.length;
    }
    box.append(document.createTextNode(text.slice(cursor)));
    return box;
  }

  function taskBox(task) {
    const box = en(h('div', 'lc-task'));
    box.append(h('p', '', task.setting), h('p', '', task.lead), list('ul', task.bullets, (b) => h('li', '', b)));
    if (task.posts) {                      // 讨论题：教授和同学的帖子
      for (const post of task.posts) { const item = h('div', 'lc-post'); item.append(h('b', '', post.who), h('p', '', post.text)); box.append(item); }
      return box;
    }
    box.append(h('p', '', 'Write as much as you can and in complete sentences.'));
    const head = h('p', 'lc-task-head');
    head.append('To: ' + task.to, h('br'), 'Subject: ' + task.subject);
    box.append(head);
    return box;
  }

  function compare(item) {
    const box = h('div', 'lc-compare');
    box.append(en(h('p', 'thin', item.thin || item.from)), en(h('p', 'full', item.full || item.to)), h('p', 'why', item.why));
    return box;
  }

  function fold(summary, ...children) {
    const box = h('details', 'lc-fold');
    box.append(h('summary', '', summary), ...children);
    return box;
  }

  // 批改单：五项，固定顺序
  function sheetBox(sheet, task) {
    const box = h('div', 'lc-sheet');
    const table = (rows) => { const t = h('table', 'lc-mark'); const body = h('tbody'); body.append(...rows); t.append(body); return t; };
    const row = (...cells) => { const tr = h('tr'); tr.append(...cells); return tr; };
    box.append(h('h4', '', '一、题目的要求'), table(sheet.coverage.map((item, n) => {
      const what = h('td');
      if (item.quote) what.append(en(h('q', '', item.quote)), h('br'));
      what.append(item.note);
      const verdict = { done: '做到了', thin: '做了但太薄', missing: '没做' }[item.verdict] || item.verdict;
      return row(en(h('td', '', task?.bullets?.[n] || '')), h('td', 'lc-verdict ' + item.verdict, verdict), what);
    })));
    const level = h('p');
    level.append(score(sheet.score), ' ' + sheet.reason);
    box.append(h('h4', '', '二、分数档'), level);
    box.append(h('h4', '', '三、必改的地方'), sheet.fixes.length
      ? table(sheet.fixes.map((fix) => row(en(h('td', 'from', fix.from)), en(h('td', 'to', fix.to)), h('td', '', fix.rule))))
      : h('p', '', '—'));
    if (sheet.upgrade) box.append(h('h4', '', '四、升一档'), compare(sheet.upgrade));
    return box;
  }

  const readers = {
    facts(card) {
      const box = h('div', 'lc-facts');
      for (const item of card.rows) {
        const line = h('div', 'lc-row'), value = h('div', '', item.v);
        value.append(h('small', '', item.src));
        line.append(h('b', '', item.k), value);
        box.append(line);
      }
      return [box];
    },
    rubric(card) {
      const out = [];
      for (const level of card.levels) {
        const line = h('div', 'lc-level'), body = h('div');
        body.append(h('b', '', level.name), '　' + level.summary);
        if (level.signs.length) body.append(list('ul', level.signs, (s) => h('li', '', s)));
        line.append(score(level.score), body);
        out.push(line);
      }
      for (const item of card.takeaways || []) { const box = h('div', 'lc-take'); box.append(h('b', '', item.t), h('p', '', item.d)); out.push(box); }
      return out;
    },
    steps(card) { return [list('ol', card.steps, (s) => { const li = h('li'); li.append(h('b', '', s.t), h('p', '', s.d)); return li; })].map((n) => { n.className = 'lc-steps'; return n; }); },
    skeleton(card) {
      const box = h('div', 'lc-skeleton');
      for (const part of card.parts) {
        const line = h('div', 'lc-bone'), body = h('div');
        body.append(h('p', '', part.what));
        if (part.en) body.append(en(h('p', 'eg', part.en)));
        line.append(h('b', '', part.name), body);
        box.append(line);
      }
      return [box];
    },
    text(card) {
      return card.body.map((block) => {
        if (block.p) return h('p', '', block.p);
        if (block.list) return list('ul', block.list, (i) => h('li', '', i));
        if (block.box) { const box = en(h('div', 'lc-task')); box.textContent = block.box; return box; }
        return compare(block.compare);
      });
    },
    table(card) {
      const wrap = h('div', 'lc-tablewrap'), table = h('table'), head = h('tr'), body = h('tbody');
      for (const col of card.cols) head.append(h('th', '', col));
      for (const cells of card.rows) { const tr = h('tr'); for (const cell of cells) tr.append(h('td', '', cell)); body.append(tr); }
      const thead = h('thead'); thead.append(head); table.append(thead, body); wrap.append(table);
      return [wrap];
    },
    model(card) {
      const out = [taskBox(card.task)];
      for (const response of card.responses) {
        const box = h('div', 'lc-response'), head = h('div', 'lc-rhead');
        head.append(score(response.score), h('b', '', response.score + ' 分的写法'));
        box.append(head, letter(response.text, response.notes), list('ol', response.notes, (n) => h('li', n.kind, n.note)), h('p', 'lc-comment', response.comment));
        box.querySelector('ol').className = 'lc-notes';
        out.push(box);
      }
      return out;
    },
    marking(card) {
      const steps = list('ol', card.format, (s) => { const li = h('li'); li.append(h('b', '', s.t), h('p', '', s.d)); return li; });
      steps.className = 'lc-steps';
      const example = card.example, box = h('div', 'lc-example');
      box.append(h('p', 'lc-about', example.about), sheetBox({ coverage: example.coverage, score: example.score, reason: example.reason, fixes: example.fixes, upgrade: example.upgrade },
        { bullets: example.coverage.map((c) => c.bullet) }));
      if (example.next) box.append(h('h4', '', '五、回去看'), h('p', '', example.next));
      return [steps, h('p', 'lc-criteria', card.rules), box];
    },
  };

  function drill(card, ctx) {
    const out = [h('p', 'lc-prompt', card.prompt)];
    if (card.material) { const material = en(h('div', 'lc-task')); material.textContent = card.material; out.push(material); }
    if (card.criteria) out.push(h('p', 'lc-criteria', card.criteria));
    const items = h('ol', 'lc-items');
    card.items.forEach((item, index) => {
      const li = h('li'), result = h('div', 'lc-check');
      const input = h('textarea'); input.rows = 2; input.spellcheck = false; input.setAttribute('aria-label', '你的回答');
      const go = h('button', 'lc-go', '对答案'); go.type = 'button';
      const paint = (check) => {
        result.replaceChildren();
        if (!check) return;
        const line = h('p', check.ok ? 'ok' : 'no');
        line.append(h('b', '', check.ok ? '✓' : '✗'), ' ' + check.why);
        result.append(line);
        if (!check.ok && check.fix) result.append(h('p', 'fix', check.fix));
        result.append(fold('参考答案', h('p', '', item.a)));
      };
      const saved = ctx.answers?.[String(index)];
      if (saved) { input.value = saved.text; paint(saved); }
      go.onclick = async () => {
        const text = input.value.trim();
        if (!text) { input.focus(); return; }
        go.disabled = true; go.textContent = '…';
        try { paint(await ctx.onAnswer(index, text)); }
        catch (error) { result.replaceChildren(h('p', 'no', error.message)); }
        finally { go.disabled = false; go.textContent = '对答案'; }
      };
      if (!ctx.current) { input.readOnly = true; go.hidden = true; }
      li.append(h('p', 'lc-q', item.q), input, go, result);
      items.append(li);
    });
    out.push(items);
    return out;
  }

  // 这节课结束之后，在批改单（成绩）下面：再来一道。写死的题用完了由模型出新的，要等几秒到一分钟。
  function again(card, ctx, label) {
    if (!card.more || !ctx.ended || !ctx.onMore) return [];
    const row = h('div', 'lc-again'), go = h('button', 'lc-go', label), notice = h('span', 'lc-notice');
    go.type = 'button';
    go.onclick = async () => {
      go.disabled = true; go.textContent = '出题中…'; notice.textContent = '';
      try { await ctx.onMore(); }
      catch (error) { notice.textContent = error.message; go.disabled = false; go.textContent = label; }
    };
    row.append(notice, go);
    return [row];
  }

  // 限时写作：点「开始」才出题、才走表；时间到自动交卷；交卷后原地显示批改单
  function write(card, ctx) {
    const task = ctx.task, out = [];
    if (!task) return out;
    const key = 'lp.lesson.draft.' + ctx.runId;
    const load = () => { try { return JSON.parse(localStorage.getItem(key)) || null; } catch (e) { return null; } };
    const save = (value) => { try { value ? localStorage.setItem(key, JSON.stringify(value)) : localStorage.removeItem(key); } catch (e) { /* 草稿只是方便 */ } };
    const head = h('div', 'lc-rhead'), timer = h('span', 'lc-timer', clock(card.minutes * 60));
    head.append(timer, h('b', '', task.purpose));
    out.push(head);
    if (ctx.sheet) {
      timer.hidden = true;
      out.push(taskBox(task), letter(ctx.essay || ''), sheetBox(ctx.sheet, task));
      if (ctx.review) {
        const back = h('button', 'cp-link', ctx.review.title); back.type = 'button';
        back.onclick = () => { void LP.lesson.start(ctx.language, ctx.review.id).catch(() => {}); };
        const line = h('p'); line.append(back);
        out.push(h('h4', '', '五、回去看'), line);
      }
      if (task.must) out.push(fold('得分要点', list('ol', task.must, (m) => h('li', '', m))));
      if (task.model) out.push(fold('5 分范文', letter(task.model)));
      out.push(...again(card, ctx, '再写一道'));
      return out;
    }
    const begin = h('button', 'lc-go lc-begin', '开始'); begin.type = 'button';
    const stage = h('div', 'lc-writing'); stage.hidden = true;
    const box = h('textarea', 'lc-essay'); box.rows = 12; box.spellcheck = false; box.autocapitalize = 'off'; box.setAttribute('autocorrect', 'off'); box.setAttribute('aria-label', '作文');
    const foot = h('div', 'lc-writing-foot'), count = h('span', 'lc-count', '0 词'), send = h('button', 'lc-go', '交卷'), notice = h('span', 'lc-notice');
    send.type = 'button';
    foot.append(count, notice, send);
    stage.append(taskBox(task), box, foot);
    let startedAt = 0, tick = null, sending = false;
    const total = card.minutes * 60;
    const left = () => Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000));
    // 太短不交（和后端同一条线：10 个词，中日韩文 20 个字）。没交成：框是开着的，可以接着写、再交；时间到了也一样，不会卡死。
    async function submit() {
      if (sending) return;
      const cjk = (box.value.match(/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/g) || []).length;
      if (words(box.value) < 10 && cjk < 20) { notice.textContent = '写得太少，没法批改'; return; }
      sending = true; send.disabled = true; box.readOnly = true; send.textContent = '批改中…'; notice.textContent = '';
      clearInterval(tick);
      try { await ctx.onSubmit(box.value, Math.min(total, Math.floor((Date.now() - startedAt) / 1000))); save(null); }
      catch (error) { notice.textContent = error.message; sending = false; send.disabled = false; box.readOnly = false; send.textContent = '交卷'; }
    }
    function run() {
      begin.hidden = true; stage.hidden = false;
      const paint = () => {
        const remaining = left();
        timer.textContent = clock(remaining);
        timer.classList.toggle('low', remaining <= 60);
        if (remaining === 0) { clearInterval(tick); void submit(); }
      };
      paint();
      tick = setInterval(paint, 500);
      ctx.onCleanup(() => clearInterval(tick));
      if (left() > 0) box.focus();
    }
    box.oninput = () => { count.textContent = words(box.value) + ' 词'; save({ text: box.value, startedAt }); };
    begin.onclick = () => { startedAt = Date.now(); save({ text: '', startedAt }); run(); };
    send.onclick = () => void submit();
    const draft = load();
    if (draft?.startedAt) { startedAt = draft.startedAt; box.value = draft.text || ''; count.textContent = words(box.value) + ' 词'; run(); }
    out.push(begin, stage);
    return out;
  }

  // ---------- 客观题：题组 = 材料 + 补字母的空 + 单选题 ----------
  // 一段录音：练习卡里可以重听，限时卡里只放一遍（once）
  function player(cardId, index, once, onCleanup) {
    const box = h('div', 'lc-audio'), play = h('button', 'lc-go lc-play', '▶ 播放'), state = h('span', 'lc-notice');
    play.type = 'button';
    let audio = null;
    onCleanup?.(() => { if (audio) { audio.onended = null; audio.onerror = null; audio.onpause = null; audio.pause(); audio.remove(); audio = null; } });   // 下课、翻走：别接着响
    const failed = () => { state.textContent = '没放出来，再点一次'; play.disabled = false; play.textContent = '▶ 播放'; audio?.remove(); audio = null; };
    play.onclick = async () => {
      play.disabled = true; play.textContent = '…'; state.textContent = '';
      // 放到一半被停（切到别的页）：从停下的地方接着放，限时卡也不算第二遍
      if (audio && audio.paused && !audio.ended && audio.currentTime > 0) {
        try { await audio.play(); play.textContent = '播放中'; } catch (error) { failed(); }
        return;
      }
      try {
        audio?.remove();
        audio = new Audio('/api/teaching/lesson/audio?card=' + encodeURIComponent(cardId) + '&group=' + index);
        audio.dataset.voiceMute = '1';
        box.append(audio);         // 放在页面里（不显示），页面藏起来时能找到它、停掉它
        audio.onended = () => { play.textContent = once ? '放完了' : '▶ 再听一遍'; play.disabled = Boolean(once); };
        const media = audio;
        media.onpause = () => { if (media === audio && !media.ended) { play.textContent = '▶ 接着放'; play.disabled = false; } };
        audio.onerror = failed;
        await audio.play();
        play.textContent = '播放中';
      } catch (error) { failed(); }
    };
    box.append(play, state);
    return box;
  }

  function script(audio) {
    const lines = list('div', audio.lines, (line) => { const p = en(h('p')); if (audio.lines.some((l) => l.who !== audio.lines[0].who)) p.append(h('b', '', line.who + '  ')); p.append(line.text); return p; });
    lines.className = 'lc-script';
    return fold('听力原文', lines);
  }

  function stimulus(group, where) {
    const out = [];
    // 录音前那句 Listen to …（声音会念）和 Read the passage. 之类的提示不显示：材料摆在那里就够了
    if (group.audio) out.push(player(where.card, where.index, where.once, where.onCleanup));
    if (!group.text) return out;
    const box = en(h('div', 'lc-stim ' + (group.look || 'passage')));
    const blocks = group.text.split('\n\n');
    blocks.forEach((block, n) => {
      const p = h('p', n === 0 && blocks.length > 1 && block.length < 90 ? 'head' : '');
      block.split('\n').forEach((line, i) => {
        if (i) p.append(h('br'));
        const said = group.look === 'messages' && line.match(/^([A-Z][\w.]*): (.*)$/);
        if (said) p.append(h('b', '', said[1]), '  ' + said[2]); else p.append(line);
      });
      box.append(p);
    });
    out.push(box);
    return out;
  }

  // fill：`We mi{ght} think`（带答案）或 `We mi{3} think`（交卷前，只有字母个数）
  function fillBox(group) {
    const box = en(h('p', 'lc-fill')), inputs = [], answers = [];
    group.fill.split(/\{([a-z]+|\d+)\}/).forEach((part, n) => {
      if (n % 2 === 0) { box.append(part); return; }
      const hidden = /^\d+$/.test(part), size = hidden ? Number(part) : part.length;
      const input = h('input', 'lc-gap');
      input.type = 'text'; input.maxLength = size; input.spellcheck = false; input.autocapitalize = 'off';
      input.setAttribute('autocomplete', 'off'); input.setAttribute('aria-label', '缺 ' + size + ' 个字母');
      input.style.width = (size + 0.9) + 'ch';
      input.addEventListener('input', () => { if (input.value.length >= size) inputs[inputs.indexOf(input) + 1]?.focus(); });
      inputs.push(input); answers.push(hidden ? null : part);
      box.append(input);
    });
    // marks[k] = 对不对；rights[k] = 正确的字母
    function mark(marks, rights) {
      inputs.forEach((input, k) => {
        input.readOnly = true;
        input.classList.add(marks[k] ? 'ok' : 'no');
        if (!marks[k] && rights[k]) input.after(h('b', 'lc-right', rights[k]));
      });
    }
    return { box, inputs, answers, mark };
  }

  function gapNotes(group, marks) {
    if (!group.notes) return null;
    const notes = list('ol', group.notes, (n) => h('li', '', n));
    notes.className = 'lc-gapnotes';
    [...notes.children].forEach((li, k) => li.classList.add(marks[k] ? 'ok' : 'no'));
    const box = fold('每个空的说明', notes);
    box.open = marks.includes(false);
    return box;
  }

  function mcItem(item, number) {
    const box = h('div', 'lc-mc'), options = h('div', 'lc-options'), after = h('p', 'lc-why');
    const buttons = item.options.map((text, n) => {
      const button = en(h('button', 'lc-option', String.fromCharCode(65 + n) + '.  ' + text));
      button.type = 'button'; button.setAttribute('aria-pressed', 'false');
      options.append(button);
      return button;
    });
    box.append(en(h('p', 'lc-stem', number + '. ' + item.stem)), options, after);
    let chosen = null;
    const pick = (n) => { chosen = n; buttons.forEach((b, i) => b.setAttribute('aria-pressed', String(i === n))); };
    const reveal = (answer, why) => {
      buttons.forEach((b, i) => { b.disabled = true; b.classList.toggle('right', i === answer); b.classList.toggle('wrong', i === chosen && chosen !== answer); });
      after.textContent = why || '';
    };
    return { box, buttons, pick, reveal, chosen: () => chosen };
  }

  // 自己填的空：没有选项。判法和后端一样：去掉首尾空白、连着的空白压成一个、不分大小写，和 accept 里任何一个相同就对
  const plainAnswer = (value) => String(value ?? '').trim().replace(/\s+/g, ' ').toLowerCase();
  function blankItem(item, number) {
    const box = h('div', 'lc-mc lc-blank'), row = h('div', 'lc-blank-row'), after = h('p', 'lc-why');
    const input = en(h('input', 'lc-answer'));
    input.type = 'text'; input.spellcheck = false; input.autocapitalize = 'off';
    input.setAttribute('autocomplete', 'off'); input.setAttribute('aria-label', '第 ' + number + ' 题的答案');
    row.append(input);
    box.append(en(h('p', 'lc-stem', number + '. ' + item.stem)), row, after);
    const pick = (value) => { input.value = value ?? ''; };
    // ok 不给就在这里判（练习卡）；限时卡用后端判好的
    const reveal = (accept, why, ok) => {
      const right = ok ?? accept.some((one) => plainAnswer(one) === plainAnswer(input.value));
      input.readOnly = true;
      input.classList.add(right ? 'ok' : 'no');
      if (!right) row.append(en(h('b', 'lc-right', accept[0])));
      after.textContent = why || '';
    };
    return { box, buttons: [], pick, reveal, chosen: () => input.value, blank: true };
  }
  // 一组题共用同一组选项（选词填空、段落匹配、七选五）：选项只列一次，每题用下拉框选
  const banked = (group) => {
    const items = group.items || [], first = items[0]?.options;
    return items.length > 1 && first?.length > 4 && items.every((item) => item.options && item.options.length === first.length && item.options.every((text, n) => text === first[n]));
  };
  function bankBox(options) {
    const list = h('ol', 'lc-bank');
    options.forEach((text) => list.append(en(h('li', '', text))));
    return list;
  }
  function selectItem(item, number) {
    const box = h('div', 'lc-mc lc-pick'), row = h('div', 'lc-blank-row'), after = h('p', 'lc-why');
    const letter = (n) => String.fromCharCode(65 + n);
    const select = en(h('select', 'lc-select'));
    select.setAttribute('aria-label', '第 ' + number + ' 题');
    select.append(new Option('—', ''));
    item.options.forEach((text, n) => select.append(new Option(letter(n) + '.  ' + (text.length > 48 ? text.slice(0, 46) + '…' : text), String(n))));
    row.append(en(h('span', 'lc-stem', number + '. ' + item.stem)), select);
    box.append(row, after);
    const chosen = () => (select.value === '' ? null : Number(select.value));
    const pick = (n) => { select.value = n == null ? '' : String(n); };
    const reveal = (answer, why) => {
      const right = chosen() === answer;
      select.disabled = true;
      select.classList.add(right ? 'ok' : 'no');
      if (!right) row.append(en(h('b', 'lc-right', letter(answer))));
      after.textContent = why || '';
    };
    return { box, buttons: [], pick, reveal, chosen, select };
  }
  // 连词成句：点下面的词块，按顺序排进句子里；点句子里的词块可以拿回去。交卷前只有打乱的 pool，没有答案
  function orderItem(item, number) {
    const box = h('div', 'lc-mc lc-order'), line = en(h('div', 'lc-order-line')), tray = en(h('div', 'lc-order-pool')), after = h('p', 'lc-why');
    const slots = item.slots ?? item.chunks.length;
    const pool = item.pool || [...item.chunks, ...(item.extra || [])].map((text) => [Math.random(), text]).sort((a, b) => a[0] - b[0]).map((pair) => pair[1]);
    const placed = [];          // 下标：pool 里的第几块
    let locked = false;
    const spot = h('span', 'lc-order-spot');
    if (item.lead) line.append(h('span', 'lc-order-fixed', item.lead));
    line.append(spot);
    if (item.tail) line.append(h('span', 'lc-order-fixed', item.tail));
    const chips = pool.map((text, k) => {
      const chip = h('button', 'lc-chip', text);
      chip.type = 'button';
      chip.onclick = () => { if (!locked && placed.length < slots) { placed.push(k); paint(); } };
      tray.append(chip);
      return chip;
    });
    function paint() {
      spot.replaceChildren();
      placed.forEach((k, at) => {
        const chip = h('button', 'lc-chip on', pool[k]);
        chip.type = 'button'; chip.disabled = locked;
        chip.onclick = () => { placed.splice(at, 1); paint(); };
        spot.append(chip);
      });
      for (let n = placed.length; n < slots; n++) spot.append(h('span', 'lc-order-gap'));
      chips.forEach((chip, k) => { chip.hidden = placed.includes(k); chip.disabled = locked; });
    }
    paint();
    box.append(en(h('p', 'lc-stem', number + '. ' + item.stem)), line, tray, after);
    const chosen = () => placed.map((k) => pool[k]);
    // 交卷后的题没有 pool：把他排的那几块直接摆上去
    const pick = (given) => { if (!Array.isArray(given)) return; placed.length = 0; given.forEach((text) => { let k = pool.findIndex((one, n) => one === text && !placed.includes(n)); if (k < 0) k = pool.push(text) - 1; placed.push(k); }); paint(); };
    const reveal = (chunks, why, ok) => {
      const right = ok ?? (chunks.length === placed.length && chunks.every((text, n) => text === pool[placed[n]]));
      locked = true; paint(); tray.hidden = true;
      line.classList.add(right ? 'ok' : 'no');
      if (!right) {
        const tail = item.tail || '', sentence = [item.lead, ...chunks].filter(Boolean).join(' ') + (/^[.,!?;:]/.test(tail) || !tail ? tail : ' ' + tail);
        box.insertBefore(en(h('p', 'lc-order-right', sentence)), after);
      }
      after.textContent = why || '';
    };
    return { box, buttons: [], pick, reveal, chosen, order: true, tray };
  }
  const questionItem = (item, number, bank) => (item.options ? (bank ? selectItem(item, number) : mcItem(item, number))
    : (item.pool || item.chunks) ? orderItem(item, number) : blankItem(item, number));

  // 练习：选完一题当场看对错和说明；补字母的一组点「对答案」
  function check(card, ctx) {
    const out = [];
    let number = 0;
    card.groups.forEach((group, index) => {
      const box = h('div', 'lc-group');
      box.append(...stimulus(group, { card: card.id, index, once: false, onCleanup: ctx.onCleanup }));
      let shown = false;
      const reveal = () => { if (!shown && group.audio) { shown = true; box.append(script(group.audio)); } };
      if (group.fill) {
        const fill = fillBox(group), go = h('button', 'lc-go', '对答案');
        go.type = 'button';
        go.onclick = () => {
          const marks = fill.inputs.map((input, k) => input.value.trim().toLowerCase() === fill.answers[k]);
          fill.mark(marks, fill.answers);
          go.hidden = true;
          const notes = gapNotes(group, marks);
          if (notes) box.append(notes);
        };
        box.append(fill.box, go);
      }
      const bank = banked(group);
      if (bank) box.append(bankBox(group.items[0].options));
      for (const item of group.items || []) {
        const mc = questionItem(item, ++number, bank);
        mc.buttons.forEach((button, n) => { button.onclick = () => { mc.pick(n); mc.reveal(item.answer, item.why); reveal(); }; });
        if (mc.select) mc.select.onchange = () => { if (mc.chosen() != null) { mc.reveal(item.answer, item.why); reveal(); } };
        if (mc.blank) {
          const go = h('button', 'lc-go', '对答案');
          go.type = 'button';
          go.onclick = () => { go.hidden = true; mc.reveal(item.accept, item.why); reveal(); };
          mc.box.querySelector('.lc-blank-row').append(go);
        }
        if (mc.order) {
          const go = h('button', 'lc-go', '对答案');
          go.type = 'button';
          go.onclick = () => { go.hidden = true; mc.reveal(item.chunks, item.why); reveal(); };
          mc.tray.after(go);
        }
        box.append(mc.box);
      }
      out.push(box);
    });
    return out;
  }

  // 限时客观题：点「开始」才出题、才走表；时间到自动交卷；交卷后原地显示对错和说明
  function quiz(card, ctx) {
    const set = ctx.set, result = ctx.result, out = [];
    if (!set) return out;
    const head = h('div', 'lc-rhead'), timer = h('span', 'lc-timer', clock(card.minutes * 60));
    out.push(head);
    const stage = h('div', 'lc-quiz'), parts = [];
    let number = 0;
    set.groups.forEach((group, g) => {
      const box = h('div', 'lc-group'), part = { fill: null, items: [] };
      box.append(...stimulus(group, { card: card.id, index: g, once: true, onCleanup: ctx.onCleanup }));
      if (group.fill) { part.fill = fillBox(group); box.append(part.fill.box); }
      const bank = banked(group);
      if (bank) box.append(bankBox(group.items[0].options));
      for (const item of group.items || []) { const mc = questionItem(item, ++number, bank); part.items.push(mc); box.append(mc.box); }
      if (result) {
        const marks = result.groups[g], given = result.answers[g] || [], gaps = part.fill ? part.fill.inputs.length : 0;
        if (part.fill) {
          part.fill.inputs.forEach((input, k) => { input.value = given[k] || ''; });
          part.fill.mark(marks.slice(0, gaps), part.fill.answers);
          const notes = gapNotes(group, marks.slice(0, gaps));
          if (notes) box.append(notes);
        }
        part.items.forEach((mc, k) => {
          const item = group.items[k];
          if (given[gaps + k] != null) mc.pick(given[gaps + k]);
          if (mc.blank) mc.reveal(item.accept, item.why, marks[gaps + k]);
          else if (mc.order) mc.reveal(item.chunks, item.why, marks[gaps + k]);
          else mc.reveal(item.answer, item.why);
        });
        if (group.audio?.lines) box.append(script(group.audio));
      } else {
        part.items.forEach((mc) => mc.buttons.forEach((button, n) => { button.onclick = () => mc.pick(n); }));
      }
      parts.push(part);
      stage.append(box);
    });
    if (result) {
      head.append(h('b', '', result.total + ' 题对了 ' + result.score + ' 题'), h('span', 'lc-pass ' + (result.passed ? 'yes' : 'no'), result.passed ? '过了' : '没过'));
      out.push(stage, ...again(card, ctx, '再来一套'));
      return out;
    }
    const amount = set.groups.reduce((sum, group) => sum + (group.fill ? (group.fill.match(/\{\d+\}/g) || []).length : 0) + (group.items || []).length, 0);
    head.append(timer, h('b', '', amount + ' 题'));
    const key = 'lp.lesson.quiz.' + ctx.runId, total = card.minutes * 60;
    const begin = h('button', 'lc-go lc-begin', '开始'), send = h('button', 'lc-go', '交卷'), notice = h('span', 'lc-notice'), foot = h('div', 'lc-writing-foot');
    begin.type = 'button'; send.type = 'button';
    foot.append(notice, send);
    stage.append(foot);
    stage.hidden = true;
    let startedAt = 0, tick = null, sending = false;
    const left = () => Math.max(0, total - Math.floor((Date.now() - startedAt) / 1000));
    async function submit() {
      if (sending) return;
      sending = true; send.disabled = true; send.textContent = '…'; notice.textContent = '';
      clearInterval(tick);
      const answers = parts.map((part) => [...(part.fill ? part.fill.inputs.map((input) => input.value) : []), ...part.items.map((mc) => mc.chosen())]);
      try { await ctx.onQuiz(answers, Math.min(total, Math.floor((Date.now() - startedAt) / 1000))); try { localStorage.removeItem(key); } catch (e) { /* 只是计时的记号 */ } }
      catch (error) { notice.textContent = error.message; sending = false; send.disabled = false; send.textContent = '交卷'; }
    }
    function run() {
      begin.hidden = true; stage.hidden = false;
      const paint = () => {
        const remaining = left();
        timer.textContent = clock(remaining);
        timer.classList.toggle('low', remaining <= 60);
        if (remaining === 0) { clearInterval(tick); void submit(); }
      };
      paint();
      tick = setInterval(paint, 500);
      ctx.onCleanup(() => clearInterval(tick));
    }
    begin.onclick = () => { startedAt = Date.now(); try { localStorage.setItem(key, String(startedAt)); } catch (e) { /* 同上 */ } run(); };
    send.onclick = () => void submit();
    let saved = 0;
    try { saved = Number(localStorage.getItem(key)) || 0; } catch (e) { saved = 0; }
    if (saved) { startedAt = saved; run(); }
    out.push(begin, stage);
    return out;
  }

  function render(card, given) {
    const cleanups = [];
    const ctx = { ...given, onCleanup: (fn) => { cleanups.push(fn); } };
    const box = h('details', 'jm-card lc-' + card.type);
    // 这张卡被换掉、拿走的时候调：停计时、停录音
    box.dispose = () => { while (cleanups.length) { try { cleanups.pop()(); } catch (e) { /* 收尾不该再出错 */ } } };
    box.dataset.card = card.id;
    box.open = Boolean(ctx.current);
    box.append(h('summary', '', card.title));
    const body = h('div', 'lc-body');
    if (card.intro) body.append(h('p', 'lc-intro', card.intro));
    const special = { drill, write, quiz, check };
    body.append(...(special[card.type] ? special[card.type](card, ctx) : readers[card.type](card)));
    for (const key of ['note', 'src']) if (card[key]) body.append(h('p', 'lc-foot', card[key]));
    box.append(body);
    return box;
  }

  // 把一节课的卡片画进 container（课程页和聊天页共用）。store 是调用方留着的 Map，记着哪张卡画过。
  // 返回当前那张卡的节点。按钮只对「现在还开着的这一节课」起作用：卡片要是过时了，点了也不会交到别的课上。
  function sync(container, store, view) {
    const live = (fn) => (...args) => (LP.lesson.current()?.id === view.id ? fn(view.id, ...args) : Promise.resolve(null));
    const ids = new Set();
    for (const card of view.cards) {
      ids.add(card.id);
      const current = true, done = (card.type === 'write' && Boolean(view.sheet)) || (card.type === 'quiz' && Boolean(view.result));
      let entry = store.get(card.id);
      if (entry && entry.current === current && entry.done === done) continue;
      const node = render(card, {
        current, ended: view.ended, answers: view.answers?.[card.id] || {},
        task: view.task, sheet: view.sheet, essay: view.essay, set: view.set, result: view.result, runId: view.id,
        review: view.review, language: view.language,
        onAnswer: live((runId, item, text) => LP.lesson.answer(runId, card.id, item, text)), onSubmit: live(LP.lesson.submit), onQuiz: live(LP.lesson.quiz),
        onMore: () => LP.lesson.more(view.language, view.lesson_id),
      });
      if (entry) { entry.node.dispose(); entry.node.replaceWith(node); } else container.append(node);
      store.set(card.id, { node, current, done });
    }
    for (const [id, entry] of store) if (!ids.has(id)) { entry.node.dispose(); entry.node.remove(); store.delete(id); }
    return store.get(view.cards[0]?.id)?.node || null;
  }
  function clear(container, store) {
    for (const entry of store.values()) entry.node.dispose();
    store.clear();
    container.replaceChildren();
  }

  // 练习上面那一块：这种题的解题要点，和讲它的课。link(课) 返回一个能点过去的节点。
  function brief(practice, link) {
    const box = h('section', 'cp-brief'), list = h('ul', '');
    for (const line of practice.brief) list.append(h('li', '', line));
    box.append(h('h2', '', '解题要点'), list);
    if (practice.lessons.length) {
      const links = h('p', 'cp-links');
      links.append(h('span', '', '相关课程'), ...practice.lessons.map(link));
      box.append(links);
    }
    return box;
  }

  LP.lessonCards = { render, sync, clear, brief };
})(window);
