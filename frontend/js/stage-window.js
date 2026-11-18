// stage-window.js — 角色窗口（stage.html）里跑的那一半：加载 Live2D 模型，按主窗口广播来的聊天事件做反应。
// 不发任何后端请求。角色是哪一个、怎么取景、十种心情各是什么表情、有哪些手部姿势，全在
// assets/live2d/characters.json 里（见 docs/STAGE.md），这里只是按清单驱动参数。
(function (global) {
  'use strict';
  const LIBS = ['vendor/live2d/live2dcubismcore.min.js', 'vendor/live2d/pixi.min.js', 'vendor/live2d/cubism4.min.js'];
  const ZERO = { eye: 1, smile: 0, brow: 0, form: 0, open: 0, ax: 0, ay: 0, az: 0, gx: 0, gy: 0, wink: 0 };
  const LINGER_KEYS = ['eye', 'smile', 'brow', 'form', 'ay'];   // 心情过去以后脸上还留一点的部分（不含看向哪边）
  const desktop = global.langpalDesktop && global.langpalDesktop.stage;
  const params = new URLSearchParams(global.location.search);
  const charId = params.get('c') || 'ame';
  const channel = 'BroadcastChannel' in global ? new BroadcastChannel('langpal-stage') : null;
  const view = document.getElementById('sw-view');

  let cfg = null, app = null, model = null, core = null, physics = null;
  const s = {
    t: 0, x: 0, y: 0, vx: 0, vy: 0, bx: 0, bvx: 0,
    px: 0, py: 0, pointerAt: -1e9, p1x: 0, p1y: 0, p2x: 0, p2y: 0, gzx: 0, gzy: 0,
    attn: null, attnUntil: 0,
    poseName: null, vis: {}, arrived: false, gestureAt: 0, poseUntil: 0, busy: false, tapUntil: 0, bob: 0, bobV: 0,
    mood: 'normal', moodUntil: 0, face: { ...ZERO },
    blinkT: -1, nextBlink: 1.5, blinkSlow: 1, bounce: 0, bounceV: 0, calm: 1, nextFidget: 24,
    home: { x: -0.25, y: 0.0 },                       // 发呆时大致朝哪边：主窗口在她左边
    typingPose: null, sendAt: -9, flashAt: -9, winkUntil: 0, seen: null,
    linger: { mood: 'normal', w: 0, at: 0 },          // 这一轮聊完后心情的余味，几分钟里慢慢淡掉
    waiting: false, idleAt: 0, checks: 0,             // 她说完了、你还没回：隔一阵看一眼手机
    micro: null, nextMicro: 10, lastMicro: '',        // 发呆时不定时的小动作：点头、歪头、瞟一眼、换重心……
    voiceLevel: 0, voiceTone: 0.5, voiceAt: -9, voiceEnv: 0, speaking: false, mouth: 0, beatAt: -9,   // 对口型
  };

  function script(src) {
    return new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src; el.onload = resolve; el.onerror = () => reject(new Error(src));
      document.head.appendChild(el);
    });
  }
  function webgl() {
    try { const c = document.createElement('canvas'); return Boolean(c.getContext('webgl2') || c.getContext('webgl')); } catch (e) { return false; }
  }

  async function boot() {
    const all = await (await fetch('assets/live2d/characters.json', { cache: 'no-cache' })).json();
    cfg = all[charId];
    if (!cfg) throw new Error('unknown character: ' + charId);
    document.title = cfg.title || cfg.name || charId;
    document.getElementById('sw-name').textContent = cfg.title || cfg.name || charId;
    if (cfg.icon) document.getElementById('sw-icon').src = cfg.icon;
    if (!webgl()) throw new Error('no webgl');
    for (const src of LIBS) await script(src);
    const PIXI = global.PIXI;
    app = new PIXI.Application({ backgroundAlpha: 0, antialias: true, autoDensity: true,
      resolution: Math.min(global.devicePixelRatio || 1, 2), width: 10, height: 10 });
    model = await PIXI.live2d.Live2DModel.from(cfg.model, { autoInteract: false });
    core = model.internalModel.coreModel;
    model.internalModel.pose = undefined;            // 手势的显隐由这里自己淡入淡出，不用框架的
    // 物理（头发、马尾、蝴蝶结、袖子、眼睛高光）要等这里把头和眼睛的参数设完再算。框架自己在设之前就算了，
    // 读到的是一段看不见的待机动作：她怎么转头头发都不跟。所以拿过来，在 drive() 最后自己算
    physics = model.internalModel.physics || null;
    model.internalModel.physics = undefined;
    app.stage.addChild(model);
    view.appendChild(app.view);
    model.internalModel.on('beforeModelUpdate', drive);
    new ResizeObserver(layout).observe(view);
    layout();
    document.addEventListener('visibilitychange', () => { if (document.hidden) app.ticker.stop(); else app.ticker.start(); });
    view.addEventListener('pointermove', (e) => point((e.clientX / view.clientWidth) * 2 - 1, -((e.clientY / view.clientHeight) * 2 - 1) + 0.4));
    view.addEventListener('pointerdown', () => { react('surprised', 1.4); setPose(null); });
    if (desktop && desktop.onCursor) desktop.onCursor((c) => point(c.x, c.y));
    document.body.classList.add('ready');
    global.stageReady = true;
    say('hello');                                    // 主窗口收到后把当前场景补发一遍
    setTimeout(() => HANDLERS.greet(), 500);
  }

  function point(x, y) {
    const nx = Math.max(-1, Math.min(1, x)), ny = Math.max(-1, Math.min(1, y));
    if (Math.abs(nx - s.px) + Math.abs(ny - s.py) > 0.004) s.pointerAt = s.t;
    s.px = nx; s.py = ny;
  }

  function layout() {
    if (!app || !model) return;
    const w = view.clientWidth, h = view.clientHeight;
    if (!w || !h) return;
    app.renderer.resize(w, h);
    const mw = model.internalModel.originalWidth, mh = model.internalModel.originalHeight;
    const frame = cfg.frame || {};
    // 窄而高的窗口按宽度取景；矮胖的窗口保证头到腰都在
    const k = Math.min(w / (mw * (frame.width || 0.54)), h / (mh * (frame.minHeight || 0.50)));
    model.scale.set(k);
    model.x = w / 2 - mw * (frame.centerX || 0.5) * k;
    model.y = Math.max(6, h * (frame.top || 0.03));
  }

  function set(id, v) { core.setParameterValueById(id, v); }
  const lerp = (a, b, k) => a + (b - a) * k;

  // 换手势就是最普通的淡入淡出：每个手势是模型里的一个部件（Part），要显示的淡入、其余的淡出；
  // 被它换掉的那只垂着的手臂（和袖子）同时淡出。没有中间动作。新手势淡入时从略低处弹上来一点。
  function part(id, v) { core.setPartOpacityById(id, v); }
  function setPose(name, seconds) {
    if (name && !(cfg.poses || {})[name]) name = null;
    if (name && name !== s.poseName) {
      const g = (cfg.gestures || {})[name] || {};
      s.bob = g.arrive ?? 0.4; s.bobV = 0;
      s.bobK = (g.spring || [])[0] || 170; s.bobC = (g.spring || [])[1] || 15;
    }
    s.poseName = name || null;
    s.poseUntil = name ? s.t + (seconds || 6) : 0;
  }
  // 比心时的「咚咚」两下
  function beat(x) {
    const p = x - Math.floor(x);
    return p < 0.16 ? Math.sin(Math.PI * p / 0.16) : p > 0.24 && p < 0.42 ? 0.7 * Math.sin(Math.PI * (p - 0.24) / 0.18) : 0;
  }

  function drive() {
    const dt = Math.min(app.ticker.deltaMS / 1000, 0.05);
    s.t += dt;
    // 手势到点就放下；还在回消息的话（发完一张贴图）重新拿起手机
    if (s.poseName && s.t > s.poseUntil) setPose(s.busy ? s.typingPose : null, 90);
    const fade = cfg.poseFade || 0.18;
    const used = { armR: 0, armL: 0, sleeveR: 0, sleeveL: 0 };
    let showing = 0;
    for (const [name, p] of Object.entries(cfg.poses || {})) {
      const goal = name === s.poseName ? 1 : 0, was = s.vis[name] || 0;
      // 到了就停：已经全显示还往下减的话，会每隔一帧掉 dt/fade，垂着的手臂一闪一闪地透出来
      const now = goal > was ? Math.min(1, was + dt / fade) : goal < was ? Math.max(0, was - dt / fade) : was;
      s.vis[name] = now; showing += now;
      part(p.part, now);
      for (const side of (p.arms || 'RL')) used['arm' + side] += now;
      for (const side of (p.sleeves || '')) used['sleeve' + side] += now;
    }
    part('PartArmR', 1 - Math.min(1, used.armR)); part('PartArmL', 1 - Math.min(1, used.armL));
    part('PartSleeveR', 1 - Math.min(1, used.sleeveR)); part('PartSleeveL', 1 - Math.min(1, used.sleeveL));
    const cg = (cfg.gestures || {})[s.poseName] || {};
    const arrived = Boolean(s.poseName) && s.vis[s.poseName] >= 0.999;
    if (arrived && !s.arrived) s.gestureAt = s.t;
    s.arrived = arrived;
    // 没人理她的时候，隔一阵自己做个小动作（咬指甲、托下巴、揉眼睛）。刚聊完的心情还在时多挑合心情的；
    // 她说完了你一直没回，就拿起手机看一眼有没有新消息，看了两回还没有就有点不高兴
    const idleNow = !s.busy && !s.poseName && showing <= 0;
    if (idleNow && s.t > s.nextFidget && s.t > s.moodUntil) {
      const cues = cfg.cues || {};
      let list = cues.fidget, hold = 4.2 + Math.random() * 1.6;
      if (s.waiting && s.t - s.idleAt > (cfg.waitCheck || 40) && (cues.waiting || []).length) {
        list = cues.waiting; hold = 3.4; s.checks += 1;
        if (s.checks >= 2) s.linger = { mood: 'pout', w: Math.max(lingerWeight(), 0.35), at: s.t };
        if (s.checks >= 3) s.waiting = false;
      } else if (lingerWeight() > 0.1 && Math.random() < 0.6) {
        list = (cfg.fidgetMood || {})[s.linger.mood] || list;
      }
      setPose(pick(list), hold);
      s.nextFidget = s.t + 30 + Math.random() * 30;
    }
    // 不定时的小动作（一次一个，同一个不连着来；做到一半有事发生也让它做完，免得一下弹回去）
    if (s.micro && s.t - s.micro.at > s.micro.dur) s.micro = null;
    if (idleNow && !s.micro && !s.speaking && s.t > s.nextMicro && !(s.attn && s.t < s.attnUntil) && s.t - s.pointerAt > 3.5) startMicro();
    const mo = microOffsets();
    // 对口型：响度 → 张嘴（张得快、合得慢一点），频谱重心 → 嘴形。在不在「说话」照 airi 的做法：
    // 快起慢落的包络 + 一高一低两道门槛，词和词之间的空当不会让她一下停一下说
    const lv = s.t - s.voiceAt < 0.15 ? s.voiceLevel : 0;
    s.voiceEnv += (lv - s.voiceEnv) * (1 - Math.exp(-dt / (lv > s.voiceEnv ? 0.15 : 0.9)));
    if (!s.speaking && s.voiceEnv >= 0.45) s.speaking = true;
    else if (s.speaking && s.voiceEnv <= 0.3) s.speaking = false;
    const mouthGoal = Math.max(0, Math.min(1, (lv - 0.4) / 0.3));
    s.mouth += (mouthGoal - s.mouth) * (1 - Math.exp(-dt / (mouthGoal > s.mouth ? 0.03 : 0.07)));
    if (mouthGoal > 0.6 && s.mouth < 0.5 && s.t - s.beatAt > 0.3) { s.beatAt = s.t; s.vy -= 0.12 * mouthGoal; }   // 重音上头轻轻一点
    const phone = s.poseName === 'phone';
    // 桌面壳每 60 毫秒才送一次鼠标位置，直接拿去用眼珠会一格一格地跳（看着像抖）：先过两道平滑
    const kp = 1 - Math.exp(-dt / 0.045);
    s.p1x += (s.px - s.p1x) * kp; s.p1y += (s.py - s.p1y) * kp;
    s.p2x += (s.p1x - s.p2x) * kp; s.p2y += (s.p1y - s.p2y) * kp;
    let gx, gy;
    if (s.attn && s.t < s.attnUntil) { gx = s.attn.x; gy = s.attn.y; }
    else if (phone) { gx = 0.05 * Math.sin(s.t * 0.7); gy = -0.45; }
    else if (s.speaking) { gx = 0.08 * Math.sin(s.t * 0.6); gy = 0.04 + 0.04 * Math.sin(s.t * 0.9); }   // 说话时看着你
    else if (s.t - s.pointerAt < 3.5) { gx = s.p2x * 0.85; gy = s.p2y * 0.7; }
    else { gx = s.home.x + 0.26 * Math.sin(s.t * 0.37) + 0.1 * Math.sin(s.t * 0.93 + 1); gy = s.home.y + 0.13 * Math.sin(s.t * 0.51 + 2); }
    // 换看的地方时眼珠也不是一帧跳过去，约 70 毫秒扫过去（像真的眼跳）
    const kg = 1 - Math.exp(-dt / 0.03);
    s.gzx += (gx - s.gzx) * kg; s.gzy += (gy - s.gzy) * kg;
    gx = s.gzx; gy = s.gzy;
    // 手势到位后：它自带的表情盖在心情上面；手贴着脸的手势让头少动一点（calm），不然手在脸上打滑
    const held = arrived && !phone ? cg : {};
    const moodOn = s.t < s.moodUntil;
    const target = { ...ZERO, ...lingerFace(), ...(moodOn ? (cfg.moods || {})[s.mood] || {} : {}), ...(held.face || {}) };
    if (s.t < s.winkUntil) target.wink = 1;
    s.calm = lerp(s.calm, held.calm ?? 1, Math.min(1, dt * 6));
    // 表情上脸要快，心情过去以后慢慢平复
    const k = Math.min(1, dt * (moodOn || held.face || s.t < s.winkUntil ? 7 : 1.8));
    for (const key in ZERO) s.face[key] = lerp(s.face[key], target[key] ?? ZERO[key], key === 'wink' ? Math.min(1, dt * 9) : k);
    const f = s.face;
    gx += mo.gx; gy += mo.gy;
    const hx = (gx + (f.ax + mo.ax) / 30) * s.calm, hy = (gy + (f.ay + mo.ay) / 30) * s.calm;
    s.vx += (60 * (hx - s.x) - 10.5 * s.vx) * dt; s.x += s.vx * dt;
    s.vy += (60 * (hy - s.y) - 10.5 * s.vy) * dt; s.y += s.vy * dt;
    s.bvx += (22 * (s.x - s.bx) - 7 * s.bvx) * dt; s.bx += s.bvx * dt;
    s.bounceV += (-90 * s.bounce - 9 * s.bounceV) * dt; s.bounce += s.bounceV * dt;
    s.bobV += (-(s.bobK || 170) * s.bob - (s.bobC || 15) * s.bobV) * dt; s.bob += s.bobV * dt;
    if (s.blinkT < 0 && s.t > s.nextBlink) s.blinkT = 0;
    let open = 1;
    if (s.blinkT >= 0) {
      s.blinkT += dt / s.blinkSlow;                    // 慢眨眼：同一个形状放慢
      const b = s.blinkT;
      open = b < 0.07 ? 1 - b / 0.07 : b < 0.11 ? 0 : b < 0.26 ? (b - 0.11) / 0.15 : 1;
      if (b >= 0.26) { s.blinkT = -1; s.blinkSlow = 1; s.nextBlink = s.t + 1.8 + Math.random() * 3.6; }
    }
    open = Math.min(open, f.eye);
    // 手上的小动作：捧手机时一下一下点屏幕，其他姿势轻轻晃
    let wiggle;
    const g = phone ? {} : cg;
    if (phone && s.busy) {
      // 每发出去一条按一下「发送」，抬眼看你一下，再接着打下一条
      const beat = (s.t * 5.3) % 1, since = s.t - s.sendAt;
      wiggle = s.t < s.tapUntil && since > 1.0 && (s.t % 4) < 2.9 ? Math.max(0, 1 - Math.abs(beat - 0.25) / 0.25) : 0;
      if (since < 0.3) wiggle = Math.sin(Math.PI * since / 0.3);
    } else if (phone) {
      // 只是看一眼有没有新消息：按亮屏幕那一下
      const age = s.t - s.gestureAt;
      wiggle = arrived && age < 0.45 ? Math.sin(Math.PI * age / 0.45) : 0;
    } else {
      const age = s.t - s.gestureAt;
      const hold = g.hold || 1.6;
      const env = arrived ? Math.min(1, age / 0.15) * Math.max(0, 1 - Math.max(0, age - hold) / 0.7) : 0;
      wiggle = (g.amp ?? 0.6) * env * (g.beat ? beat(age * (g.freq || 1.2)) : Math.sin(age * 2 * Math.PI * (g.freq || 1.2)));
    }
    const moveY = (g.bodyY || 0) * wiggle, moveZ = (g.sway || 0) * wiggle, tilt = (g.tilt || 0) * wiggle;
    set('ParamAngleX', 30 * s.x);
    set('ParamAngleY', 30 * s.y - (phone ? 9 : 0));
    set('ParamAngleZ', -10 * s.x * (0.6 + 0.4 * s.y) + (2.4 * Math.sin(s.t * 0.4) + f.az + mo.az) * s.calm + tilt);
    set('ParamBodyAngleX', 7 * s.bx + mo.bx);
    set('ParamBodyAngleZ', -3.5 * s.bx + 1.6 * Math.sin(s.t * 0.31) + moveZ);
    set('ParamBodyAngleY', 3 * s.y + 10 * s.bounce + (phone ? 2 : 0) + moveY);
    set('ParamEyeBallX', Math.max(-1, Math.min(1, (gx - s.x) * 1.5 + s.x * 0.3 + f.gx + mo.ex)));
    set('ParamEyeBallY', Math.max(-1, Math.min(1, (gy - s.y) * 1.5 + s.y * 0.3 + f.gy)));
    set('ParamEyeLOpen', open); set('ParamEyeROpen', open * (1 - f.wink));    // 眨一只眼：露在刘海外面的右眼
    set('ParamEyeLSmile', f.smile); set('ParamEyeRSmile', Math.max(f.smile, f.wink));
    set('ParamBrowLY', f.brow + mo.brow); set('ParamBrowRY', f.brow + mo.brow);
    set('ParamMouthForm', Math.max(-1, Math.min(1, f.form + (s.speaking ? 0.15 : 0) + (s.voiceTone - 0.45) * 0.9 * s.mouth)));
    set('ParamMouthOpenY', Math.max(f.open, s.mouth));
    set('ParamBreath', Math.min(1, 0.5 - 0.5 * Math.cos(s.t * 2 * Math.PI / 3.6) + mo.breath));
    set('ParamPoseBob', Math.max(-1, Math.min(1, s.bob)));
    set('ParamPoseWiggle', Math.max(-1, Math.min(1, wiggle)));
    if (physics) physics.evaluate(core, Math.min(app.ticker.deltaMS / 1000, 0.1));
  }

  function react(mood, seconds) {
    const moods = cfg.moods || {};
    if (!moods[mood]) mood = 'normal';
    s.mood = mood; s.moodUntil = s.t + (seconds || 6);
    if (moods[mood].bounce) s.bounceV -= 1.6 * moods[mood].bounce;
  }
  function look(x, y, seconds) { s.attn = { x, y }; s.attnUntil = s.t + seconds; }
  function pick(list) { return Array.isArray(list) && list.length ? list[Math.floor(Math.random() * list.length)] : null; }
  function sticker(id) { return id ? ((cfg.stickers || {})[id] || null) : null; }

  // 心情的余味：一轮聊完，这轮的心情按 linger.weight 的比例留在脸上，linger.seconds 秒里慢慢淡掉
  function lingerWeight() {
    if (!s.linger.w) return 0;
    return s.linger.w * Math.max(0, 1 - (s.t - s.linger.at) / ((cfg.linger || {}).seconds || 240));
  }
  function lingerFace() {
    const w = lingerWeight(), m = (cfg.moods || {})[s.linger.mood], out = {};
    if (!(w > 0) || !m) return out;
    for (const key of LINGER_KEYS) if (m[key] != null) out[key] = ZERO[key] + (m[key] - ZERO[key]) * w;
    return out;
  }
  function settle(mood) {
    const w = ((cfg.linger || {}).weight || {})[mood] || 0;
    s.linger = w > 0 ? { mood, w, at: s.t } : { mood: s.linger.mood, w: lingerWeight() * 0.5, at: s.t };
  }

  // 发呆时不定时的小动作。p 是 0→1 的进度，d 是朝哪边（±1）；返回加在头、眼、身体上的偏移
  function swell(p, rise, fall) {
    const x = Math.max(0, Math.min(1, p / rise, (1 - p) / fall));
    return x * x * (3 - 2 * x);
  }
  const MICRO = {
    nod: { dur: 1.3, fn: (p) => ({ ay: -5 * Math.sin(Math.PI * p) }) },
    tilt: { dur: 2.8, fn: (p, d) => ({ az: 5.5 * d * swell(p, 0.25, 0.35), ax: 2 * d * swell(p, 0.25, 0.35) }) },
    glance: { dur: 1.6, fn: (p, d) => ({ ex: 0.55 * d * swell(p, 0.12, 0.25), az: 1.5 * d * swell(p, 0.2, 0.3) }) },
    shift: { dur: 3.2, fn: (p, d) => ({ bx: 4 * d * swell(p, 0.3, 0.35), ax: 2 * d * swell(p, 0.3, 0.35) }) },
    slowblink: { dur: 0.9, start() { s.blinkT = 0; s.blinkSlow = 2.6; }, fn: () => ({}) },
    sigh: { dur: 2.6, fn: (p) => ({ ay: -4.5 * swell(p, 0.3, 0.45), brow: -0.3 * swell(p, 0.2, 0.45), breath: 0.35 * Math.sin(Math.PI * Math.min(1, p / 0.6)) }) },
    peek: { dur: 1.7, fn: (p) => ({ gx: -0.6 * swell(p, 0.18, 0.3), gy: 0.05 * swell(p, 0.18, 0.3) }) },   // 瞄一眼左边的聊天
  };
  function startMicro() {
    const mc = cfg.micro || {};
    const w = { ...(mc.weights || { nod: 1, tilt: 1, glance: 1, shift: 1, slowblink: 1, peek: 0.5 }) };
    if (lingerWeight() > 0.08) Object.assign(w, (mc.byMood || {})[s.linger.mood] || {});
    if (s.waiting) Object.assign(w, mc.waiting || {});
    delete w[s.lastMicro];
    const names = Object.keys(w).filter((n) => MICRO[n] && w[n] > 0);
    const every = mc.every || [8, 18];
    s.nextMicro = s.t + every[0] + Math.random() * (every[1] - every[0]);
    if (!names.length) return;
    let r = Math.random() * names.reduce((a, n) => a + w[n], 0), name = names[names.length - 1];
    for (const n of names) { r -= w[n]; if (r <= 0) { name = n; break; } }
    s.micro = { name, at: s.t, dur: MICRO[name].dur, dir: Math.random() < 0.5 ? -1 : 1 };
    s.lastMicro = name;
    if (MICRO[name].start) MICRO[name].start();
  }
  function microOffsets() {
    const o = { ax: 0, ay: 0, az: 0, gx: 0, gy: 0, ex: 0, bx: 0, brow: 0, breath: 0 };
    if (!s.micro) return o;
    return Object.assign(o, MICRO[s.micro.name].fn(Math.min(1, (s.t - s.micro.at) / s.micro.dur), s.micro.dir));
  }

  // 主窗口在她的左边：聊天记录、输入框都在左侧
  const HANDLERS = {
    greet() { setPose(pick((cfg.cues || {}).greet), 2.6); react('happy', 2.2); look(-0.5, 0.05, 2.2); },
    user_typing() { s.waiting = false; if (!s.busy) look(-0.8, -0.3, 1.6); },
    sent(d) {
      if (s.checks >= 2) { react('happy', 1.6); s.linger = { ...s.linger, w: lingerWeight() * 0.3, at: s.t }; }   // 等了半天，你总算回了
      s.waiting = false; s.checks = 0; s.seen = (d && d.sticker) || null;
      look(-0.85, 0.05, 1.8); s.bounceV -= 0.5;
    },
    read() {                                           // 她看到你的消息了；是贴图的话脸上先有反应
      look(-0.85, 0.0, 1.2); s.blinkT = 0;
      const st = sticker(s.seen); s.seen = null;
      if (st) react(st.seen || st.mood || 'normal', 2.6);
    },
    typing() {
      document.body.classList.add('typing'); s.busy = true; s.waiting = false; s.tapUntil = s.t + 90; s.attn = null;
      s.typingPose = pick((cfg.cues || {}).typing) || 'phone';
      setPose(s.typingPose, 90);
    },
    mood(d) { if (d && d.mood) { s.mood = d.mood; s.moodUntil = s.t + 30; } },
    bubble(d) {                                        // 一条发出去了：按一下发送，抬眼看这边，把这条的心情亮出来
      react((d && d.mood) || s.mood, 7);
      look(-0.4, 0.05, 1.3);
      s.sendAt = s.t;
      const st = sticker(d && d.sticker);              // 发的是贴图：自己也照着贴图比一下
      if (st) {
        if (st.mood) react(st.mood, 7);
        if (st.pose) { setPose(st.pose, st.hold || 2.6); s.flashAt = s.t; }
        if (st.wink) s.winkUntil = s.t + 1.4;
      }
    },
    idle() {                                           // 这一轮说完：收起手机，心情对应的手势摆一下（最后一条是贴图就接着摆贴图那个）
      const was = s.busy;
      document.body.classList.remove('typing');
      s.busy = false; s.tapUntil = 0;
      const keep = s.poseName && s.poseName !== s.typingPose && s.t - s.flashAt < 3;
      const pose = !was ? null : keep ? s.poseName : pick(((cfg.moodPose || {})[s.mood]));
      setPose(pose, 4.5);
      s.moodUntil = Math.max(s.moodUntil, s.t + (pose ? 4.5 : 0));
      if (!pose) s.moodUntil = Math.min(s.moodUntil, s.t + 5);
      if (was) {                                       // 心情留一点在脸上；开始等你回
        settle(s.mood);
        s.waiting = true; s.checks = 0; s.idleAt = s.t;
        s.nextFidget = s.t + (cfg.waitCheck || 40) + Math.random() * 15;
      }
    },
    interrupted() { document.body.classList.remove('typing'); s.busy = false; s.waiting = false; s.tapUntil = 0; setPose(null); react('surprised', 1.6); look(-0.85, 0.1, 1.6); },
    other() { look(-0.8, 0.0, 1.4); },                // 别的角色插话：她也转过去看一眼
    voice(d) {                                         // 主窗口在放声音（听力、朗读、口语课）：每秒 30 次的响度
      s.voiceLevel = Math.max(0, Math.min(1, +(d && d.level) || 0));
      s.voiceTone = d && d.tone != null ? +d.tone : 0.5;
      s.voiceAt = s.t;
    },
    tab(d) {                                           // 她知道你在干什么：读东西时也低头看，上口语课时看着你
      const where = (cfg.tabs || {})[d && d.tab] || (cfg.tabs || {}).default || { x: -0.25, y: 0 };
      s.home = { x: where.x || 0, y: where.y || 0 };
    },
  };

  function say(type, data) { if (channel) channel.postMessage({ from: 'stage', character: charId, type, data: data || null }); }
  if (channel) {
    channel.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.from !== 'app' || !model) return;
      if (m.character && m.character !== charId) return;
      const fn = HANDLERS[m.type];
      if (fn) { s.nextFidget = Math.max(s.nextFidget, s.t + 14); fn(m.data); }   // 有事发生时不做小动作
    };
  }

  // 窗口自己的按钮（桌面壳里才有；浏览器弹窗用浏览器自己的边框）
  document.body.classList.toggle('in-desktop', Boolean(desktop));
  document.getElementById('sw-min')?.addEventListener('click', () => desktop && desktop.minimize());
  document.getElementById('sw-close')?.addEventListener('click', () => { say('dismissed'); if (desktop) desktop.close(); else global.close(); });
  global.addEventListener('pagehide', () => say('closed'));
  global.stageEmit = (type, data) => { const fn = HANDLERS[type]; if (fn && model) fn(data); };   // 测试和调试用
  global.stageState = () => ({ name: s.poseName, shown: { ...s.vis }, mood: s.mood, busy: s.busy, waiting: s.waiting, checks: s.checks,
    speaking: s.speaking, mouth: s.mouth, parts: core ? Object.fromEntries(['PartArmR', 'PartArmL', 'PartSleeveR', 'PartSleeveL', 'PartPose_phone'].map((id) => [id, core.getPartOpacityById(id)])) : null,
    linger: { mood: s.linger.mood, w: lingerWeight() }, micro: s.micro && s.micro.name, wink: s.face.wink, t: s.t });
  global.stageClock = (seconds) => { s.t += seconds; };   // 测试用：跳过一段发呆时间
  // 录介绍视频用：直接摆手势、换心情、给光标位置（和桌面壳传来的光标同一套坐标）
  global.stagePose = (name, seconds) => { if (model) setPose(name, seconds); };
  global.stageReact = (mood, seconds) => { if (model) react(mood, seconds); };
  global.stagePoint = (x, y) => point(x, y);
  // 测试用：每帧真正画出去的参数值（物理算完、画之前）。返回一个函数，调一次取走攒下的 [t, ...值]
  global.stageProbe = (ids) => {
    const rows = [];
    model.internalModel.on('beforeModelUpdate', () => rows.push([s.t, ...ids.map((id) => core.getParameterValueById(id))]));
    return () => rows.splice(0);
  };

  // 模型偶尔会在加载半路上断一下（后端刚起来、文件刚换过）。断了就整页重来，最多两次；还不行才露出像素头像
  const RETRY_KEY = 'lp.stage.retry';
  const tries = () => { try { return Number(sessionStorage.getItem(RETRY_KEY)) || 0; } catch (e) { return 9; } };
  boot().then(() => { try { sessionStorage.removeItem(RETRY_KEY); } catch (e) { /* 记不了就算了 */ } }).catch((e) => {
    global.stageError = String(e && e.message || e);
    console.warn('[stage] ' + global.stageError);
    const n = tries();
    if (n < 2) {
      try { sessionStorage.setItem(RETRY_KEY, String(n + 1)); } catch (err) { document.body.classList.add('failed'); return; }
      setTimeout(() => global.location.reload(), 1500);
      return;
    }
    document.body.classList.add('failed');
  });
})(window);
