// stage.js — 主窗口这一半：把聊天里发生的事广播给角色窗口（stage.html），并负责开关那扇窗。
//   LP.stage.reactsTo(persona)   这个人设有没有对应的角色（现在只有糖糖；清单见 assets/live2d/characters.json）
//   LP.stage.emit(name, data)    事件：typing / read / mood / bubble / idle / interrupted / user_typing / sent / other / tab / voice
//   LP.stage.voice(audio)        这段声音要她对口型（页面上的 <audio> 播放时会自动接，不用调）
//   LP.stage.sync(persona)       主聊天对象变了：有角色且上次没被关掉 → 打开她的窗口
//   LP.stage.toggle()            标题栏上那个头像按钮
// 角色窗口是独立的：切到阅读、听力、口语时她还在。桌面壳里是一扇跟着主窗口的小窗，浏览器里是弹出窗口。
(function (global) {
  'use strict';
  const LP = global.LP = global.LP || {};
  const desktop = global.langpalDesktop && global.langpalDesktop.stage;
  const channel = 'BroadcastChannel' in global ? new BroadcastChannel('langpal-stage') : null;
  const PREF = 'lp.stage.open';
  let characters = {}, current = null, open = false, popup = null, lastTab = 'talk';

  const pref = () => { try { return localStorage.getItem(PREF) !== '0'; } catch (e) { return true; } };
  const remember = (on) => { try { localStorage.setItem(PREF, on ? '1' : '0'); } catch (e) { /* 不能存就算了 */ } };
  const voiceOn = () => { try { return localStorage.getItem('lp.stage.voice') !== '0'; } catch { return true; } };
  let speechWarmed = false, speechGeneration = 0, speaking = null;
  const speechQueue = [];

  function stopSpeech() {
    ++speechGeneration;
    speechQueue.length = 0;
    const job = speaking;
    speaking = null;
    job?.stop?.();
  }

  function speak(messageId) {
    speechQueue.push({ messageId, generation: speechGeneration });
    void nextSpeech();
  }

  async function nextSpeech() {
    if (speaking || !speechQueue.length) return;
    const job = speaking = speechQueue.shift();
    let audio, url, started = false, finished = false;
    const finish = (state) => {
      if (finished) return;
      finished = true;
      if (state) emit('speech', { message_id: job.messageId, state });
      if (audio) { audio.onplaying = audio.onended = audio.onerror = null; audio.pause(); audio.removeAttribute('src'); audio.load(); }
      if (url) URL.revokeObjectURL(url);
      if (speaking === job) speaking = null;
      void nextSpeech();
    };
    job.stop = () => finish(started ? 'end' : null);
    try {
      const blob = await LP.api.messageSpeech(job.messageId);
      if (job.generation !== speechGeneration || finished) return;
      url = URL.createObjectURL(blob);
      audio = new Audio(url);
      audio.onplaying = () => { if (!started) { started = true; emit('speech', { message_id: job.messageId, state: 'start' }); } };
      audio.onended = () => finish('end');
      audio.onerror = () => finish('error');
      LP.jine?.stopSpeech?.();   // 聊天里手动点的「朗读」先停，两段声音不叠在一起
      voice(audio);
      await audio.play();
    } catch (error) {
      if (!finished && job.generation === speechGeneration) finish('error');
    }
  }

  function characterFor(persona) {
    if (!persona || !persona.name) return null;
    for (const id of Object.keys(characters)) {
      if ((characters[id].match || []).some((prefix) => persona.name.startsWith(prefix))) return id;
    }
    return null;
  }
  const reactsTo = (persona) => Boolean(current && characterFor(persona) === current);

  function post(type, data) { if (channel && (current || type === 'fail')) channel.postMessage({ from: 'app', character: current, type, data: data || null }); }
  function emit(type, data) { if (open) post(type, data); }

  function setOpen(on) {
    open = on;
    const btn = document.getElementById('app-btn-stage');
    if (btn) btn.setAttribute('aria-pressed', String(on));
  }
  function show() {
    if (!current) return;
    if (desktop) desktop.open(current);
    else if (!popup || popup.closed) popup = global.open('stage.html?c=' + encodeURIComponent(current), 'langpal-stage', 'popup,width=340,height=620');
    else popup.focus();
    setOpen(true);
  }
  function hide() {
    if (desktop) desktop.close(); else if (popup && !popup.closed) popup.close();
    setOpen(false);
  }
  function toggle() { if (open) { remember(false); hide(); } else { remember(true); show(); } }

  // 主聊天对象变了。浏览器里弹窗必须由点击触发，所以只有桌面壳会自己打开
  function sync(persona) {
    const next = characterFor(persona);
    const btn = document.getElementById('app-btn-stage');
    if (btn) {
      btn.hidden = !next;
      if (next && characters[next].icon) btn.querySelector('img').src = characters[next].icon;
      if (next) btn.setAttribute('aria-label', characters[next].name || next);   // 名字跟着角色走，不写死
    }
    if (next === current) return;
    if (open) hide();
    current = next;
    if (current && desktop && pref()) show();
  }

  if (channel) {
    channel.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.from !== 'stage') return;
      if (m.type === 'hello') {
        setOpen(true); post('tab', { tab: lastTab });
        const language = LP.state?.chatMain?.language;
        if (voiceOn() && !speechWarmed && language) {
          speechWarmed = true;
          void Promise.resolve().then(() => LP.api.warmSpeech(language)).catch(() => {});
        }
      }
      else if (m.type === 'say') {
        const text = typeof m.data?.text === 'string' ? m.data.text.trim() : '';
        if (!text || text.length > 500) return;
        if (!LP.jine?.say(text, { via: 'stage' })) post('fail', { text });
      }
      else if (m.type === 'dismissed') { remember(false); setOpen(false); }
      else if (m.type === 'closed') setOpen(false);
    };
  }

  function mountButton() {
    const host = document.getElementById('app-winbtns');
    if (!host || document.getElementById('app-btn-stage')) return;
    const btn = document.createElement('button');
    btn.type = 'button'; btn.id = 'app-btn-stage'; btn.className = 'stage-btn'; btn.hidden = true;
    btn.setAttribute('aria-pressed', 'false');
    const img = document.createElement('img'); img.alt = ''; img.src = 'assets/avatars/ame-head.png';
    btn.appendChild(img);
    btn.addEventListener('click', toggle);
    host.parentNode.insertBefore(btn, host);            // 放在三个窗口键左边；浏览器里窗口键整组隐藏，她的开关还在
  }
  // 现在在哪一页：她据此决定发呆时看哪边
  function watchTabs() {
    const page = document.getElementById('app-page');
    if (!page) return;
    new MutationObserver(() => {
      const active = page.querySelector('.page-panel.active');
      const tab = active ? active.id.replace(/^page-/, '') : 'talk';
      if (tab !== lastTab) { lastTab = tab; emit('tab', { tab }); }
    }).observe(page, { subtree: true, attributes: true, attributeFilter: ['class'] });
  }

  // ---------- 对口型：主窗口里放出来的声音，量响度广播给角色窗口 ----------
  // 页面上的 <audio>（听力、复习里的片段）开始播放时自动接上；不在页面上的（聊天朗读）调 LP.stage.voice(audio)。
  // audio.dataset.voice = 'off' 的不接（别的角色的朗读）。跨域又没开 CORS 的音频接上会变静音，所以只接同源和 blob:。
  // 口语页的实时语音在独立服务的 iframe 里，那边用 postMessage 发 {type:'langpal:voice', level, tone} 过来。
  let actx = null, meterTimer = 0;
  const taps = new WeakMap(), live = new Set();
  function tappable(audio) {
    if (!audio || audio.dataset.voice === 'off') return false;
    try { const u = new URL(audio.currentSrc || audio.src, global.location.href); return u.protocol === 'blob:' || u.origin === global.location.origin; } catch (e) { return false; }
  }
  function voice(audio) {
    if (!open || !current || !tappable(audio)) return;
    try {
      actx = actx || new (global.AudioContext || global.webkitAudioContext)();
      if (actx.state === 'suspended') void actx.resume();
      if (!taps.has(audio)) {
        const source = actx.createMediaElementSource(audio);
        const analyser = actx.createAnalyser();
        analyser.fftSize = 1024; analyser.smoothingTimeConstant = 0.2;
        source.connect(analyser); analyser.connect(actx.destination);
        taps.set(audio, { analyser, wave: new Float32Array(analyser.fftSize), spec: new Uint8Array(analyser.frequencyBinCount) });
        const stop = () => { live.delete(audio); if (!live.size) quiet(); };
        audio.addEventListener('pause', stop); audio.addEventListener('ended', stop); audio.addEventListener('emptied', stop);
        audio.addEventListener('play', () => { if (actx.state === 'suspended') void actx.resume(); });
      }
      live.add(audio);
      if (!meterTimer) meterTimer = setInterval(meter, 33);
    } catch (e) { /* 量不了就不对口型，声音照放 */ }
  }
  function quiet() { clearInterval(meterTimer); meterTimer = 0; emit('voice', { level: 0, tone: 0.5 }); }
  function meter() {
    if (!live.size) { quiet(); return; }
    let level = 0, tone = 0.5;
    for (const audio of live) {
      const tap = taps.get(audio);
      if (!tap || audio.paused || audio.dataset.voiceMute === '1') continue;
      tap.analyser.getFloatTimeDomainData(tap.wave);
      let sum = 0;
      for (let i = 0; i < tap.wave.length; i++) sum += tap.wave[i] * tap.wave[i];
      // 响度刻度同 airi：(dBFS + 60) / 60，0.45 ≈ -33 dBFS
      const l = Math.max(0, Math.min(1, (20 * Math.log10(Math.sqrt(sum / tap.wave.length) + 1e-6) + 60) / 60));
      if (l <= level) continue;
      level = l;
      // 频谱重心定嘴形：i/e 高、o/u 低（0→1 对应 0→3 kHz）
      tap.analyser.getByteFrequencyData(tap.spec);
      let w = 0, m = 0;
      for (let i = 2; i < tap.spec.length; i++) { w += tap.spec[i]; m += tap.spec[i] * i; }
      tone = w ? Math.min(1, (m / w) * actx.sampleRate / tap.analyser.fftSize / 3000) : 0.5;
    }
    emit('voice', { level, tone });
  }
  document.addEventListener('play', (ev) => { if (ev.target instanceof HTMLMediaElement) voice(ev.target); }, true);
  global.addEventListener('message', (ev) => {
    const d = ev.data;
    if (!d || d.type !== 'langpal:voice') return;
    const frame = document.querySelector('iframe.coach-frame');
    if (!frame || frame.contentWindow !== ev.source) return;   // 只认口语页那个 iframe
    emit('voice', { level: Math.max(0, Math.min(1, +d.level || 0)), tone: Math.max(0, Math.min(1, +(d.tone ?? 0.5) || 0)) });
  });

  const ready = fetch('assets/live2d/characters.json', { cache: 'no-cache' })
    .then((r) => (r.ok ? r.json() : {})).then((j) => { characters = j || {}; }).catch(() => { characters = {}; });
  function init() { mountButton(); watchTabs(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();

  global.addEventListener('storage', (ev) => { if (ev.key === 'lp.stage.voice' && !voiceOn()) stopSpeech(); });
  LP.stage = { emit, reactsTo, voice, voiceOn, speak, stopSpeech, sync: (p) => ready.then(() => sync(p)), toggle, get open() { return open; }, get character() { return current; } };
})(window);
