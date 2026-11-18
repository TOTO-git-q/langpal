// Main-window stage protocol, with offline API and silent, deterministic audio.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMock} from './ui/mock-api.mjs';

const {chromium} = await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root = process.env.LANGPAL_SOURCE_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const types = {'.html':'text/html; charset=utf-8', '.js':'text/javascript', '.mjs':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png', '.ttf':'font/ttf', '.json':'application/json'};
const browser = await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH || undefined, headless:true, args:['--mute-audio']});

async function open(voice, options = {}) {
  const page = await browser.newPage({viewport:{width:1100, height:760}});
  page.setDefaultTimeout(8000);
  const calls = [], errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.addInitScript(value => {
    localStorage.setItem('lp.stage.voice', value);
    // No real media, timing dependency or sound. AudioContext rejects this tap safely.
    window.Audio = class extends EventTarget {
      constructor(src) { super(); this.src = this.currentSrc = src; this.dataset = {}; this.paused = true; }
      async play() {
        this.paused = false;
        this.onplaying?.();
        this.dispatchEvent(new Event('play'));
        queueMicrotask(() => { if (!this.paused) { this.paused = true; this.onended?.(); this.dispatchEvent(new Event('ended')); } });
      }
      pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
      removeAttribute() { this.src = ''; }
      load() {}
    };
  }, voice);
  const {handle} = createMock({solo:true, chatBubbleLimit:1, ...options});
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url());
    assert.equal(url.hostname, 'stage.test', 'External request: ' + req.url());
    if (url.pathname.startsWith('/api/')) {
      const raw = req.postData();
      calls.push({path:url.pathname, method:req.method(), body:raw ? JSON.parse(raw) : null});
      if (url.pathname === '/api/chat/speech/warm' && options.warmFailure) {
        if (options.warmFailure === 'network') return route.abort('failed');
        return route.fulfill({status:options.warmFailure, json:{ok:false}});
      }
      if (/^\/api\/chat\/messages\/\d+\/speech$/.test(url.pathname)) {
        return route.fulfill({contentType:'audio/wav', body:Buffer.from('silent fixture')});
      }
      const result = handle(req.url(), req.method(), raw);
      if (!result) return route.fulfill({status:404, json:{detail:'mock route missing'}});
      return result.json !== undefined ? route.fulfill({status:result.status, json:result.json}) : route.fulfill({status:result.status, contentType:result.contentType, body:result.body});
    }
    const file = path.join(root, 'frontend', url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname));
    try { return route.fulfill({contentType:types[path.extname(file)] || 'application/octet-stream', body:await fs.readFile(file)}); }
    catch { return route.fulfill({status:404, body:''}); }
  });
  await page.goto('http://stage.test/');
  await page.waitForFunction(() => LP.stage.character && LP.state.chatMain?.primary_id);
  await page.waitForSelector('#jine-messages .jm-row');
  await page.evaluate(async warmUnavailable => {
    window.stageEvents = [];
    window.stageChannel = new BroadcastChannel('langpal-stage');
    stageChannel.onmessage = event => { if (event.data.from === 'app') stageEvents.push(event.data); };
    if (warmUnavailable === 'missing') delete LP.api.warmSpeech;
    else if (warmUnavailable === 'throw') LP.api.warmSpeech = () => { throw new Error('unavailable'); };
    stageChannel.postMessage({from:'stage', type:'hello'});
    await LP.appShell.switchTab('today');
    await LP.appShell.ready('today');
  }, options.warmUnavailable);
  await page.waitForFunction(() => stageEvents.some(event => event.type === 'tab'));
  return {page, calls, errors};
}

const say = (page, text) => page.evaluate(text => stageChannel.postMessage({from:'stage', type:'say', data:{text}}), text);
const speechRequests = calls => calls.filter(call => /^\/api\/chat\/messages\/\d+\/speech$/.test(call.path));

try {
  {
    const {page, calls, errors} = await open('0', {chatActions:[{name:'open', arg:'reading'}]});
    await page.evaluate(() => { document.querySelector('#jine-input').value = 'composer draft'; });
    await say(page, '  hello from stage  ');
    await page.waitForFunction(() => stageEvents.some(event => event.type === 'acted'));
    const chats = calls.filter(call => call.path === '/api/chat');
    assert.equal(chats.length, 1);
    assert.equal(chats[0].body.text, 'hello from stage');
    assert.equal(chats[0].body.via, 'stage');
    assert.equal(chats[0].body.scene.tab, 'today');
    assert.equal(chats[0].body.scene.title, '今天');
    assert.equal(await page.inputValue('#jine-input'), 'composer draft');
    assert.equal(await page.locator('#page-reading').evaluate(node => node.classList.contains('active')), true);
    const events = await page.evaluate(() => stageEvents);
    assert.deepEqual(events.find(event => event.type === 'acted').data, {ok:true, label:'▶ 阅读'});
    const bubble = events.find(event => event.type === 'bubble').data;
    assert.deepEqual(Object.keys(bubble).sort(), ['language','message_id','mood','show','speak','sticker','text']);
    assert.equal(bubble.language, 'ja');
    assert.equal(bubble.show, true);
    assert.equal(bubble.speak, false);
    assert.ok(bubble.text);
    assert.equal(speechRequests(calls).length, 0);
    assert.equal(calls.filter(call => call.path === '/api/chat/speech/warm').length, 0);
    assert.deepEqual(await page.evaluate(() => LP.scene.get().actions), ['▶ 阅读']);
    // Reads alone do not consume action outcomes; the next send does.
    assert.deepEqual(await page.evaluate(() => LP.scene.get().actions), ['▶ 阅读']);
    await say(page, 'another');
    await page.waitForFunction(() => stageEvents.filter(event => event.type === 'acted').length === 2);
    assert.deepEqual(calls.filter(call => call.path === '/api/chat')[1].body.scene.actions, ['▶ 阅读']);
    assert.deepEqual(errors, []);
    await page.close();
  }
  {
    const {page, calls, errors} = await open('1');
    await say(page, 'speak this');
    await page.waitForFunction(() => stageEvents.some(event => event.type === 'speech' && event.data.state === 'end'));
    assert.equal(speechRequests(calls).length, 1);
    const states = await page.evaluate(() => stageEvents.filter(event => event.type === 'speech').map(event => event.data));
    assert.deepEqual(states, [{message_id:900, state:'start'}, {message_id:900, state:'end'}]);
    assert.equal(await page.evaluate(() => stageEvents.find(event => event.type === 'bubble').data.speak), true);
    const tabs = await page.evaluate(() => stageEvents.filter(event => event.type === 'tab').length);
    await page.evaluate(() => stageChannel.postMessage({from:'stage', type:'hello'}));
    await page.waitForFunction(count => stageEvents.filter(event => event.type === 'tab').length > count, tabs);
    assert.deepEqual(calls.filter(call => call.path === '/api/chat/speech/warm').map(call => call.body), [{language:'ja'}]);
    assert.deepEqual(errors, []);
    await page.close();
  }
  {
    const {page, calls} = await open('0');
    await page.route('**/api/chat', route => route.fulfill({status:503, json:{detail:'offline'}}));
    await say(page, 'retry me');
    await page.waitForFunction(() => stageEvents.some(event => event.type === 'fail'));
    assert.deepEqual(await page.evaluate(() => stageEvents.find(event => event.type === 'fail').data), {text:'retry me'});
    assert.equal(await page.locator('.jm-row.me.failed .jm-retry').count(), 1);
    const prior = calls.filter(call => call.path === '/api/chat').length;
    await page.evaluate(async () => { LP.state.personas = []; await LP.jine.refreshMain(); });
    await say(page, 'cannot deliver');
    await page.waitForFunction(() => stageEvents.filter(event => event.type === 'fail').length === 2);
    assert.equal(calls.filter(call => call.path === '/api/chat').length, prior);
    await page.close();
  }
  {
    const {page, errors} = await open('0');
    await page.evaluate(() => { LP.appShell.switchTab('settings'); });
    await page.waitForSelector('#f-free-text');
    await page.fill('#f-free-text', '改了一点');
    assert.equal(await page.evaluate(() => LP.appShell.switchTab('talk') === undefined), true);
    await page.waitForSelector('.confirm-box');
    await page.click('.confirm-box button:has-text("留下")');
    assert.equal(await page.locator('#page-settings').evaluate(node => node.classList.contains('active')), true);
    await page.evaluate(() => {
      window.actionResult = null;
      void LP.actions.run('open', 'reading').then(result => { window.actionResult = result; });
    });
    await page.waitForSelector('.confirm-box');
    assert.equal(await page.evaluate(() => actionResult), null);
    await page.click('.confirm-box button:has-text("不保存")');
    await page.waitForFunction(() => actionResult);
    assert.deepEqual(await page.evaluate(() => actionResult), {ok:true, label:'▶ 阅读'});
    assert.deepEqual(errors, []);
    await page.close();
  }
  for (const options of [{warmFailure:404}, {warmFailure:200}, {warmFailure:'network'}, {warmUnavailable:'missing'}, {warmUnavailable:'throw'}]) {
    const {page, errors} = await open('1', options);
    // A second hello round trip also lets the first warm-up settle.
    const tabs = await page.evaluate(() => stageEvents.filter(event => event.type === 'tab').length);
    await page.evaluate(() => stageChannel.postMessage({from:'stage', type:'hello'}));
    await page.waitForFunction(count => stageEvents.filter(event => event.type === 'tab').length > count, tabs);
    await say(page, 'still connected');
    await page.waitForFunction(() => stageEvents.some(event => event.type === 'speech' && event.data.state === 'end'));
    assert.deepEqual(errors, []);
    assert.equal(await page.locator('.toast').count(), 0);
    await page.close();
  }
  console.log('stage bridge UI: OK');
} finally { await browser.close(); }
