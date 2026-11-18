// stage-chat.js — 角色窗口里的直播间（docs/STAGE.md「直播间」）：
//   底下一条弹幕框：打一句、回车，交给主窗口发进主聊天（这里不发后端请求）；
//   你发的话从左下往上冒，几秒后淡掉；她的回答在头顶冒气泡，开着声音时主窗口把它念出来、她对口型。
// 和主窗口只靠 BroadcastChannel('langpal-stage') 说话：
//   这边发：say {text}
//   那边发：typing / idle / bubble {text, message_id, show, speak, sticker} / speech {message_id, state} / acted {label, ok} / fail {text}
// 声音开关存在 localStorage['lp.stage.voice']（'1' 开、'0' 关，没有就是开），两扇窗共用。
(function (global) {
  'use strict';
  const params = new URLSearchParams(global.location.search);
  const charId = params.get('c') || 'ame';
  const channel = 'BroadcastChannel' in global ? new BroadcastChannel('langpal-stage') : null;
  const VOICE_KEY = 'lp.stage.voice';
  const KEEP = 4;                 // 屏幕上最多留几条弹幕
  const COMMENT_MS = 7000;        // 一条弹幕留多久
  const SPEECH_WAIT_MS = 45000;   // 等声音出来最多等多久（本机声音模型冷启动慢）
  const view = document.getElementById('sw-view');
  const form = document.getElementById('sw-chat');
  if (!view || !form) return;
  const input = form.querySelector('input');
  const voiceBtn = form.querySelector('.sw-voice');
  const sendBtn = form.querySelector('.sw-send');

  const comments = document.createElement('div');
  comments.className = 'sw-comments';
  const bubble = document.createElement('div');
  bubble.className = 'sw-bubble';
  bubble.setAttribute('aria-live', 'polite');
  const clip = document.createElement('div');
  clip.className = 'sw-bubble-clip';
  const text = document.createElement('div');
  text.className = 'sw-bubble-text';
  clip.appendChild(text);
  bubble.appendChild(clip);
  view.append(comments, bubble);

  // ---------- 声音开关 ----------
  const voiceOn = () => { try { return localStorage.getItem(VOICE_KEY) !== '0'; } catch (e) { return true; } };
  function paintVoice() { voiceBtn.setAttribute('aria-pressed', String(voiceOn())); }
  voiceBtn.addEventListener('click', () => {
    try { localStorage.setItem(VOICE_KEY, voiceOn() ? '0' : '1'); } catch (e) { /* 存不了就只管这一次 */ }
    paintVoice();
  });
  global.addEventListener('storage', (ev) => { if (ev.key === VOICE_KEY) paintVoice(); });
  paintVoice();

  // ---------- 弹幕 ----------
  let lastMine = null;
  function comment(content, cls) {
    const node = document.createElement('div');
    node.className = 'sw-comment' + (cls ? ' ' + cls : '');
    node.textContent = content;
    comments.appendChild(node);
    while (comments.children.length > KEEP) comments.firstElementChild.remove();
    setTimeout(() => { node.classList.add('leaving'); setTimeout(() => node.remove(), 650); }, COMMENT_MS);
    return node;
  }

  // ---------- 她的气泡 ----------
  const queue = [];
  let current = null;       // {id, speak, timer, scroller, started}
  let awaiting = false;     // 我在这儿发了一句，还没等到她的第一条
  const lineHeight = () => parseFloat(getComputedStyle(bubble).lineHeight) || 21;

  function hideBubble() {
    bubble.classList.remove('on', 'thinking');
    if (current) { clearTimeout(current.timer); clearInterval(current.scroller); clearInterval(current.typer); }
    current = null;
  }
  function think() {
    if (current) return;
    text.replaceChildren(document.createElement('i'), document.createElement('i'), document.createElement('i'));
    text.style.transform = '';
    bubble.classList.add('on', 'thinking');
  }
  function next() {
    hideBubble();
    const item = queue.shift();
    if (!item) { if (awaiting) think(); return; }
    awaiting = false;
    bubble.classList.remove('thinking');
    text.textContent = '';
    text.style.transform = '';
    if (item.language) bubble.lang = item.language;
    bubble.classList.add('on');
    const state = current = { id: item.id, speak: item.speak, started: false, timer: 0, scroller: 0, typer: 0 };
    // 一个字一个字出来
    const chars = Array.from(item.text);
    let shown = 0;
    state.typer = setInterval(() => {
      shown = Math.min(chars.length, shown + 2);
      text.textContent = chars.slice(0, shown).join('');
      follow();
      if (shown >= chars.length) { clearInterval(state.typer); settle(); }
    }, 45);
    // 超过三行：跟着最新一行
    function follow() {
      const over = text.scrollHeight - clip.clientHeight;
      text.style.transform = over > 0 ? `translateY(${-over}px)` : '';
    }
    // 字出完以后：没声音就按字数留一会儿；有声音就等它念完
    function settle() {
      if (current !== state) return;
      const lines = Math.max(1, Math.round(text.scrollHeight / lineHeight()));
      if (lines > 3) {                      // 长的：回到开头，再一行一行往上卷，让人读得完
        text.style.transform = '';
        let at = 0;
        const step = state.speak ? 2400 : 1900;
        state.scroller = setInterval(() => {
          at = Math.min(lines - 3, at + 1);
          text.style.transform = `translateY(${-at * lineHeight()}px)`;
          if (at >= lines - 3) clearInterval(state.scroller);
        }, step);
      }
      if (state.speak) state.timer = setTimeout(next, state.started ? 60000 : SPEECH_WAIT_MS);   // 声音一直没来 / 没报完：别卡住
      else state.timer = setTimeout(next, Math.min(11000, Math.max(2400, chars.length * 120) + Math.max(0, lines - 3) * 1900));
    }
  }
  function onBubble(d) {
    if (!d || !d.show || !d.text) return;
    queue.push({ id: d.message_id, text: String(d.text), speak: Boolean(d.speak), language: d.language || '' });
    if (!current || bubble.classList.contains('thinking')) next();
  }
  function onSpeech(d) {
    if (!d || !current || current.id !== d.message_id) return;
    if (d.state === 'start') { current.started = true; clearTimeout(current.timer); current.timer = setTimeout(next, 60000); }
    else { clearTimeout(current.timer); current.timer = setTimeout(next, d.state === 'end' ? 700 : 2200); }
  }

  // ---------- 发一句 ----------
  function send() {
    const value = input.value.trim().slice(0, 500);
    if (!value || !channel) return;
    input.value = '';
    sendBtn.disabled = true;
    queue.length = 0;
    hideBubble();
    lastMine = comment(value);
    awaiting = true;
    channel.postMessage({ from: 'stage', character: charId, type: 'say', data: { text: value } });
  }
  form.addEventListener('submit', (ev) => { ev.preventDefault(); send(); });
  input.addEventListener('input', () => { sendBtn.disabled = !input.value.trim(); });
  input.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') input.blur(); });
  sendBtn.disabled = true;

  if (channel) {
    channel.addEventListener('message', (ev) => {
      const m = ev.data || {};
      if (m.from !== 'app' || (m.character && m.character !== charId)) return;
      const d = m.data || {};
      if (m.type === 'typing') { if (awaiting) think(); }
      else if (m.type === 'bubble') onBubble(d);
      else if (m.type === 'speech') onSpeech(d);
      else if (m.type === 'idle' || m.type === 'interrupted') { awaiting = false; if (bubble.classList.contains('thinking')) hideBubble(); }
      else if (m.type === 'acted') comment(String(d.label || ''), 'sys' + (d.ok === false ? ' bad' : ''));
      else if (m.type === 'fail') { awaiting = false; if (bubble.classList.contains('thinking')) hideBubble(); if (lastMine) lastMine.classList.add('failed'); }
    });
  }

  // 测试用：不经主窗口直接喂事件、看状态
  global.stageChat = {
    feed: (type, data) => channel && channel.dispatchEvent(new MessageEvent('message', { data: { from: 'app', character: charId, type, data } })),
    state: () => ({ bubble: bubble.classList.contains('on'), thinking: bubble.classList.contains('thinking'), text: text.textContent,
      queued: queue.length, comments: [...comments.children].map((n) => n.textContent), voice: voiceOn() }),
  };
})(window);
