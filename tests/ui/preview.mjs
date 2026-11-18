// preview.mjs — 无头截图预览：只托管 frontend/，所有 /api/** 走 mock-api.mjs 的假数据，不依赖真后端。
//
//   node tests/ui/preview.mjs                       # 全部页面 × 1100x760 和 900x600
//   node tests/ui/preview.mjs --only=talk,settings-chat
//   node tests/ui/preview.mjs --size=900x600
//
// 每个场景一份新的假后端（createMock(scene.mock)），场景之间互不影响；scene.mock 可带 {degraded, proactive}。
//
// 截图存到 tests/ui/shots/<宽x高>/<场景>.png；结束时打印控制台报错、横向溢出、未登记的接口。
// Playwright：环境变量 LANGPAL_PLAYWRIGHT_MODULE 指向 playwright-core 的入口（或含 package.json 的目录），
// 浏览器：LANGPAL_CHROME_PATH。都不给时用本机默认位置。端口：LANGPAL_PREVIEW_PORT（默认 8803）。
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createMock } from './mock-api.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, '..', '..');
const frontend = path.join(repo, 'frontend');
const shotsRoot = path.join(here, 'shots');
const port = Number(process.env.LANGPAL_PREVIEW_PORT || 8803);

function loadPlaywright() {
  const hint = process.env.LANGPAL_PLAYWRIGHT_MODULE;
  const candidates = [hint, path.join(repo, 'package.json')].filter(Boolean);
  for (const c of candidates) {
    try {
      const base = c.endsWith('.json') ? c : path.join(c.replace(/^file:\/\/\/?/, ''), 'package.json');
      return createRequire(base)('playwright-core');
    } catch { /* 下一个 */ }
  }
  throw new Error('找不到 playwright-core：设置 LANGPAL_PLAYWRIGHT_MODULE');
}
const chromePath = process.env.LANGPAL_CHROME_PATH
  || path.join(process.env.LOCALAPPDATA || '', 'ms-playwright', 'chromium_headless_shell-1234', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe');

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml', '.json': 'application/json', '.ttf': 'font/ttf',
  '.webp': 'image/webp', '.gif': 'image/gif', '.bcmap': 'application/octet-stream', '.wasm': 'application/wasm' };

function serveStatic() {
  const server = http.createServer((req, res) => {
    const clean = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let file = path.normalize(path.join(frontend, clean === '/' ? 'index.html' : clean));
    if (!file.startsWith(frontend)) { res.writeHead(403).end(); return; }
    fs.readFile(file, (err, data) => {
      if (err) { res.writeHead(404).end(); return; }
      res.writeHead(200, { 'Content-Type': MIME[path.extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-store' });
      res.end(data);
    });
  });
  return new Promise((resolve) => server.listen(port, '127.0.0.1', () => resolve(server)));
}

// ---------- 场景 ----------
const go = (tab) => async (page) => { await page.evaluate((t) => LP.appShell.switchTab(t), tab); await page.waitForTimeout(350); };
const settingsPage = (key) => async (page) => {
  await page.evaluate(() => LP.appShell.switchTab('settings'));
  await page.click(`[data-settings-tab="${key}"]`);
  await page.waitForTimeout(400);
};
const scenes = [
  // 主聊天：主人设 + 在场的副人设（Emma 插过话、Lena 来了）
  { name: 'talk', run: go('talk') },
  { name: 'talk-solo', mock: { solo: true }, run: go('talk') },
  { name: 'talk-wordcard', run: async (page) => {
    await go('talk')(page);
    const tok = page.locator('#jine-messages .tok.clickable').filter({ hasText: 'お願い' }).last();
    await tok.click();
    await page.waitForSelector('#wp-collect-btn');
  } },
  { name: 'talk-furigana', run: async (page) => {
    await page.evaluate(() => LP.furigana.setEnabled(true));
    await go('talk')(page);
    await page.evaluate(() => LP.jine.loadHistory());
    await page.waitForTimeout(400);
  } },
  { name: 'talk-sentence', run: async (page) => {
    await go('talk')(page);
    const row = page.locator('#jine-messages .jm-row').filter({ hasText: 'えっと' }).last();
    await row.hover();
    await row.locator('[data-action="sentence"]').click();
    await page.waitForSelector('#sentence-panel .grammar-card');
    await page.waitForTimeout(300);
  } },
  // 发一条：已读、她说两条、Emma 插一句
  { name: 'talk-send', run: async (page) => {
    await go('talk')(page);
    await page.fill('#jine-input', 'もう一回言って');
    await page.press('#jine-input', 'Enter');
    await page.waitForSelector('#msg-902');
    await page.waitForTimeout(300);
  } },
  // 点名：点顶栏里 Lena 的小头像，输入框前出现 @Lena
  { name: 'talk-mention', run: async (page) => {
    await go('talk')(page);
    await page.click('.jm-guest[aria-label*="Lena"]');
    await page.fill('#jine-input', 'Und morgen?');
    await page.waitForTimeout(200);
  } },
  { name: 'talk-fun', mock: { fun: true }, run: go('talk') },
  { name: 'talk-stickers', run: async (page) => {
    await go('talk')(page);
    await page.click('#jm-sticker-btn');
    await page.waitForSelector('.jm-sticker img');
    await page.waitForTimeout(300);
  } },
  { name: 'talk-archives', run: async (page) => {
    await go('talk')(page);
    await page.click('#jm-more');await page.click('#jm-archives');
    await page.waitForSelector('.jm-archive-row');
    await page.waitForTimeout(200);
  } },
  { name: 'talk-archive-open', run: async (page) => {
    await go('talk')(page);
    await page.click('#jm-more');await page.click('#jm-archives');
    await page.locator('.jm-archive-row').filter({ hasText: 'Emma' }).click();
    await page.waitForSelector('#jm-archive-bar:not([hidden])');
    await page.waitForTimeout(200);
  } },
  // 她有一条待发：进聊天页就像平时一样一条条冒出来（前面没有你的气泡）
  { name: 'talk-proactive', mock: { proactive: true }, run: async (page) => {
    await go('talk')(page);
    await page.waitForSelector('#msg-951', { timeout: 8000 });
    await page.waitForTimeout(300);
  } },
  // 不在聊天页时：图标栏「聊天」上的红点
  { name: 'talk-dot', run: async (page) => {
    await page.evaluate(() => LP.appShell.switchTab('notebook'));
    await page.evaluate(async () => { await fetch('/api/__mock/pending', { method: 'POST' }); await LP.jine.refreshPending(); });
    await page.waitForSelector('.nav-btn[data-tab="talk"] .nav-dot');
  } },
  // 学习：今天、复习会话（自评卡 / 选择卡 / 打字卡 / 听力卡 / 结束画面）、统计、词条详情
  { name: 'today', run: async (page) => { await go('today')(page); await page.waitForSelector('.lt-step'); await page.waitForTimeout(200); } },
  { name: 'today-advice', run: async (page) => { await go('today')(page); await page.waitForSelector('.lt-advice'); await page.locator('.lt-advice > summary').first().click(); await page.waitForTimeout(150); } },
  { name: 'today-stats', run: async (page) => { await go('today')(page); await page.waitForSelector('.lt-stats:not([hidden]) .lt-bar'); await page.locator('.lt-stats').scrollIntoViewIfNeeded(); await page.waitForTimeout(200); } },
  { name: 'drill-front', run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-vocab'); await page.waitForTimeout(150); } },
  { name: 'drill-back', run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-vocab'); await page.keyboard.press(' '); await page.waitForSelector('.rv2-rate'); await page.waitForTimeout(150); } },
  { name: 'drill-choice', run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-vocab'); await page.keyboard.press(' '); await page.waitForSelector('.rv2-rate'); await page.keyboard.press('3'); await page.waitForSelector('.rv2-reading_q'); await page.keyboard.press('1'); await page.waitForSelector('.rv2-verdict'); await page.waitForTimeout(150); } },
  { name: 'drill-type', run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-vocab'); await page.keyboard.press(' '); await page.waitForSelector('.rv2-rate'); await page.keyboard.press('3'); await page.waitForSelector('.rv2-reading_q'); await page.keyboard.press('2'); await page.waitForSelector('.rv2-verdict'); await page.keyboard.press('Enter'); await page.waitForSelector('.rv2-type'); await page.fill('.rv2-type', 'しんぞう'); await page.press('.rv2-type', 'Enter'); await page.waitForSelector('.rv2-verdict'); await page.waitForTimeout(150); } },
  { name: 'drill-listening', run: async (page) => { await go('drill')(page); await page.evaluate(() => LP.learning.openReview({ kinds: ['listening_q'] })); await page.waitForSelector('.rv2-listening_q'); await page.waitForTimeout(150); } },
  { name: 'drill-end', mock: { emptyQueue: true }, run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-end'); await page.waitForTimeout(150); } },
  { name: 'drill-done', run: async (page) => { await go('drill')(page); await page.waitForSelector('.rv2-stage'); for (let i = 0; i < 120 && !(await page.locator('.rv2-end').count()); i++) { await page.evaluate(() => { const s = document.querySelector('.rv2-stage'); const b = s.querySelector('.rv2-rate.r3:not([disabled]), .rv2-next-btn, .rv2-flip, .rv2-option:not([disabled])') || s.querySelector('.rv2-giveup'); b?.click(); }); await page.waitForTimeout(60); } await page.waitForSelector('.rv2-end'); await page.waitForTimeout(150); } },
  { name: 'vocab-detail', run: async (page) => { await go('notebook')(page); await page.locator('.nb-word-open').first().click(); await page.waitForSelector('.lt-contexts li'); await page.waitForTimeout(150); } },
  { name: 'listening-blind', run: async (page) => { await go('listening')(page); await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])'); await page.evaluate(()=>{document.querySelector('.lp-listening-setup button[type=submit]').dataset.resume='';}); await page.click('.lp-listening-setup button[type=submit]'); await page.waitForSelector('.lp-big-play'); await page.waitForTimeout(200); } },
  { name: 'listening-empty', mock: { listeningEmpty: true }, run: async (page) => { await go('listening')(page); await page.waitForSelector('.lp-format-tile'); await page.waitForTimeout(500); } },
  { name: 'listening-questions', run: async (page) => { await go('listening')(page); await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])'); await page.evaluate(()=>{document.querySelector('.lp-listening-setup button[type=submit]').dataset.resume='';}); await page.click('.lp-listening-setup button[type=submit]'); await page.waitForSelector('.lp-big-play'); await page.evaluate(() => document.querySelector('.lp-listening-player audio').dispatchEvent(new Event('ended'))); await page.waitForTimeout(100); await page.evaluate(() => document.querySelector('[data-listen="questions"]').click()); await page.waitForSelector('.lp-listening-questions fieldset'); await page.fill('#lp-listening-notes', 'library — weekend?\nFriday closes early\nstudent card'); await page.waitForTimeout(150); } },
  { name: 'listening-causes', run: async (page) => { await go('listening')(page); await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])'); await page.evaluate(()=>{document.querySelector('.lp-listening-setup button[type=submit]').dataset.resume='';}); await page.click('.lp-listening-setup button[type=submit]'); await page.waitForSelector('[data-listen="questions"]:not([hidden]), .lp-big-play'); await page.evaluate(() => document.querySelector('[data-listen="questions"]').hidden = false); await page.evaluate(() => { const audio = document.querySelector('.lp-listening-player audio'); audio.dispatchEvent(new Event('ended')); }); await page.waitForTimeout(100); await page.evaluate(() => document.querySelector('[data-listen="questions"]').click()); await page.waitForSelector('.lp-listening-questions fieldset'); await page.locator('.lp-listening-questions fieldset').nth(0).locator('input').nth(1).check(); await page.locator('.lp-listening-questions fieldset').nth(1).locator('input').nth(0).check(); await page.click('.lp-listening-questions button[type=submit]'); await page.waitForSelector('.lp-causes'); await page.waitForTimeout(150); } },
  { name: 'listening-close', run: async (page) => { await go('listening')(page); await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])'); await page.evaluate(()=>{document.querySelector('.lp-listening-setup button[type=submit]').dataset.resume='';}); await page.click('.lp-listening-setup button[type=submit]'); await page.waitForSelector('.lp-big-play'); await page.evaluate(() => document.querySelector('.lp-listening-player audio').dispatchEvent(new Event('ended'))); await page.waitForTimeout(100); await page.evaluate(() => document.querySelector('[data-listen="questions"]').click()); await page.waitForSelector('.lp-listening-questions fieldset'); await page.locator('.lp-listening-questions fieldset').nth(0).locator('input').nth(1).check(); await page.locator('.lp-listening-questions fieldset').nth(1).locator('input').nth(0).check(); await page.click('.lp-listening-questions button[type=submit]'); await page.waitForSelector('.lp-cause'); await page.locator('.lp-cause[data-cause="not_heard"]').click(); await page.waitForSelector('.lp-line'); await page.locator('.lp-line.dictation input').first().fill('The library close early Fridays'); await page.locator('.lp-line.dictation button[type=submit]').first().click(); await page.waitForSelector('.lp-word'); await page.locator('.lp-close').scrollIntoViewIfNeeded(); await page.waitForTimeout(200); } },
  { name: 'reading-end', run: async (page) => { await go('reading')(page); await page.waitForTimeout(400); await page.locator('.rd-read').first().click(); await page.waitForSelector('.rd-end'); await page.click('.rd-lookups > summary'); await page.waitForSelector('.rd-lookup'); await page.locator('.rd-end').scrollIntoViewIfNeeded(); await page.waitForTimeout(200); } },
  { name: 'settings-review-plan', run: async (page) => { await settingsPage('review')(page); await page.waitForSelector('#f-review-retention'); await page.evaluate(() => { const r = document.querySelector('#f-review-retention'); r.value = 94; r.dispatchEvent(new Event('input')); }); await page.waitForTimeout(150); } },
  { name: 'reading', run: async (page) => { await go('reading')(page); await page.waitForTimeout(500); } },
  { name: 'reading-article', run: async (page) => {
    await go('reading')(page);
    await page.waitForTimeout(400);
    await page.locator('.rd-read').first().click();
    await page.waitForTimeout(900);
  } },
  { name: 'reading-ask', run: async (page) => {
    await go('reading')(page);
    await page.waitForTimeout(400);
    await page.locator('.rd-read').first().click();
    await page.waitForTimeout(700);
    await page.click('.rd-more > summary'); await page.click('[data-rd="ask"]');
    await page.waitForTimeout(400);
  } },
  { name: 'reading-languages', run: async (page) => {
    await go('reading')(page);
    await page.click('.rd-language-drawer-open');
    await page.waitForTimeout(400);
  } },
  { name: 'reading-shelf', run: async (page) => {
    await go('reading')(page);
    await page.click('[data-view="library"]');
    await page.waitForSelector('.rd-delete');
    await page.waitForTimeout(300);
  } },
  { name: 'reading-shelf-delete', run: async (page) => {
    await go('reading')(page);
    await page.click('[data-view="library"]');
    await page.click('.rd-delete');
    await page.waitForSelector('.confirm-box');
  } },
  { name: 'listening', run: go('listening') },
  { name: 'listening-manage', run: async (page) => {
    await go('listening')(page);
    await page.waitForSelector('.lp-more > summary');
    await page.click('.lp-more > summary');
    await page.click('.listen-manage > summary');
    await page.locator('.listen-manage').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
  } },
  { name: 'listening-edit', run: async (page) => {
    await go('listening')(page);
    await page.click('.lp-more > summary'); await page.click('[data-listen="edit-plan"]');
    await page.click('[data-listen="notes-toggle"]');
    await page.waitForTimeout(300);
  } },
  // 「练习」是嵌入的口语服务页面（iframe，样式归口语服务自己），预览里那个地址是空的
  { name: 'coach', run: async (page) => { await go('coach')(page); await page.waitForTimeout(800); } },
  { name: 'coach-feedback', run: async (page) => { await go('coach')(page); await page.click('[data-coach-view="feedback"]'); await page.waitForTimeout(400); } },
  { name: 'review', run: async (page) => { await go('review')(page); await page.waitForTimeout(400); } },
  { name: 'review-open', run: async (page) => {
    await go('review')(page);
    await page.waitForSelector('.rv-entry summary');
    await page.locator('.rv-entry summary').first().click();
    await page.waitForTimeout(300);
  } },
  { name: 'review-listening', run: async (page) => {
    await go('review')(page);
    await page.waitForSelector('.rv-entry summary');
    await page.locator('.rv-entry summary').nth(1).click();
    await page.waitForTimeout(300);
  } },
  { name: 'notebook', run: go('notebook') },
  { name: 'notebook-pattern', run: async (page) => { await go('notebook')(page); await page.click('[data-tab="pattern"]'); await page.waitForTimeout(300); } },
  { name: 'workspace-agent', run: async (page) => { await go('workspace-agent')(page); await page.waitForTimeout(500); } },
  { name: 'workspace-agent-unavailable', mock: { claudeOut: true }, run: async (page) => { await go('workspace-agent')(page); await page.waitForTimeout(600); } },
  { name: 'workspace-agent-pick', mock: { gpt: true }, run: async (page) => {
    await go('workspace-agent')(page);
    await page.waitForTimeout(500);
    await page.selectOption('.workspace-agent-model', 'chatgpt');
    await page.waitForTimeout(200);
  } },
  { name: 'settings-chat', run: settingsPage('chat') },
  { name: 'settings-chat-room', run: async (page) => {
    await settingsPage('chat')(page);
    await page.click('[data-room-more] > summary'); await page.waitForSelector('.room-guest');
    await page.locator('.room-guest').filter({ hasText: 'Lena' }).scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-voice', run: async (page) => {
    await settingsPage('chat')(page);
    await page.click('#settings-voice > summary');
    await page.locator('#settings-voice').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-memory', run: async (page) => {
    await settingsPage('chat')(page);
    await page.click('#settings-memory > summary');
    await page.locator('#settings-memory').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
  } },
  { name: 'settings-library', run: settingsPage('library') },
  { name: 'settings-lore', run: async (page) => {
    await settingsPage('library')(page);
    await page.click('[data-course-tab="world"]');
    await page.waitForSelector('.lore-entry');
    await page.waitForTimeout(300);
  } },
  { name: 'settings-lore-entry', run: async (page) => {
    await settingsPage('library')(page);
    await page.click('[data-course-tab="world"]');
    await page.waitForSelector('.lore-entry');
    await page.locator('.lore-entry-pick').filter({ hasText: '周四' }).click();
    await page.click('.lore-more > summary');
    await page.locator('.lore-entry.open').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
  } },
  { name: 'settings-lore-conditions', run: async (page) => {
    await settingsPage('library')(page);
    await page.click('[data-course-tab="world"]');
    await page.waitForSelector('.lore-entry');
    await page.locator('.lore-entry-pick').filter({ hasText: '周四' }).click();
    await page.locator('.lore-entry.open .cond-add').click();
    const row = page.locator('.lore-entry.open .cond-row').last();
    await row.locator('.cond-field').selectOption('var.*');
    await row.locator('.cond-name').fill('night_owl');
    await row.locator('.cond-op').selectOption('>=');
    await row.locator('.cond-value input').fill('3');
    await page.locator('.lore-entry.open .cond-editor').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-lore-test', run: async (page) => {
    await settingsPage('library')(page);
    await page.click('[data-course-tab="world"]');
    await page.waitForSelector('.lore-test');
    await page.fill('.lore-test-bar input', '今晚配信要不要早点开始？終電に乗れるかな');
    await page.click('.lore-test-bar button');
    await page.waitForSelector('.lore-hit');
    await page.locator('.lore-test').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-lore-import', run: async (page) => {
    await settingsPage('library')(page);
    await page.click('[data-course-tab="world"]');
    await page.waitForSelector('.lore-toolbar');
    await page.setInputFiles('.lore-toolbar input[type=file]', { name: 'school.json', mimeType: 'application/json', buffer: Buffer.from('{"entries":{}}') });
    await page.waitForSelector('.lore-warnings:not([hidden])');
    await page.waitForTimeout(200);
  } },
  { name: 'settings-hooks', run: async (page) => { await settingsPage('hooks')(page); await page.waitForSelector('.hooks-rule'); await page.waitForTimeout(300); } },
  { name: 'settings-hooks-edit', run: async (page) => {
    await settingsPage('hooks')(page);
    await page.waitForSelector('.hooks-rule');
    await page.locator('.hooks-rule-pick').filter({ hasText: '熬夜计数' }).click();
    await page.waitForSelector('.hooks-form [data-field="uid"] option:nth-child(2)', { state: 'attached' });
    await page.locator('.hooks-action').last().scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-hooks-macros', run: async (page) => {
    await settingsPage('hooks')(page);
    await page.waitForSelector('.hooks-rule');
    await page.locator('.hooks-rule-pick').first().click();
    await page.click('.hooks-action .hooks-macros > summary');
    await page.locator('.hooks-action').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-hooks-vars', run: async (page) => {
    await settingsPage('hooks')(page);
    await page.waitForSelector('.hooks-log-row');
    await page.locator('.hooks-log').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-reader', run: settingsPage('reader') },
  { name: 'settings-sources', run: async (page) => {
    await settingsPage('reader')(page);
    await page.locator('.src-row').first().scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-source-new', run: async (page) => {
    await settingsPage('reader')(page);
    await page.locator('.src-add').first().click();
    await page.fill('.src-url', 'https://news.example/feed');
    await page.click('.src-url-row .primary');
    await page.waitForSelector('.src-sample');
    await page.locator('.src-editor').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-source-json', run: async (page) => {
    await settingsPage('reader')(page);
    await page.locator('.src-add').first().click();
    await page.fill('.src-url', 'https://api.example/v1/stories');
    await page.click('.src-url-row .primary');
    await page.waitForSelector('.src-sample', { timeout: 15000 });
    await page.click('.src-more > summary');
    await page.locator('.src-editor').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
  { name: 'settings-zotero', run: async (page) => {
    await settingsPage('reader')(page);
    await page.click('[data-reading-tab="zotero"]');
    await page.click('[data-zot="test"]');
    await page.waitForSelector('[data-zot="state"][data-tone="ok"]');
    await page.locator('.zot').scrollIntoViewIfNeeded();
  } },
  { name: 'reading-zotero', run: async (page) => {
    await go('reading')(page);
    await page.click('[data-view="library"]');
    await page.click('[data-shelf="zotero"]');
    await page.waitForTimeout(600);
  } },
  { name: 'settings-listen', run: settingsPage('listen') },
  { name: 'settings-speak', run: settingsPage('speak') },
  { name: 'settings-review', run: settingsPage('review') },
  { name: 'settings-models', run: async (page) => { await settingsPage('models')(page); await page.waitForTimeout(300); } },
  { name: 'settings-models-degraded', mock: { degraded: true }, run: async (page) => { await settingsPage('models')(page); await page.waitForTimeout(300); } },
  { name: 'settings-models-accounts', mock: { gpt: true }, run: async (page) => {
    await settingsPage('models')(page);
    await page.waitForSelector('[data-engine-block="chatgpt"] .gpt-who');
    await page.locator('.engine-cards').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
  } },
  { name: 'settings-models-gpt-login', run: async (page) => {
    await settingsPage('models')(page);
    await page.evaluate(() => { window.open = () => null; });
    await page.click('.gpt-login-btn');
    await page.waitForSelector('[data-gpt="login"]:not([hidden])');
    await page.locator('[data-engine-block="chatgpt"]').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
  } },
];

// 横向溢出：页面级横向滚动条 + 任何超出视口右边缘的可见元素
async function overflowReport(page) {
  return page.evaluate(() => {
    const out = [];
    const doc = document.documentElement;
    if (doc.scrollWidth > doc.clientWidth + 1) out.push(`document scrollWidth ${doc.scrollWidth} > ${doc.clientWidth}`);
    const vw = window.innerWidth;
    for (const el of document.querySelectorAll('#app-shell *, #word-popover *, #sentence-panel.open *')) {
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.right > vw + 1 && getComputedStyle(el).position !== 'fixed') {
        // 被祖先 overflow 裁掉的不算（例如横向滚动的 tab 条）
        let clipped = false;
        for (let p = el.parentElement; p; p = p.parentElement) {
          const s = getComputedStyle(p);
          if (/(auto|scroll|hidden|clip)/.test(s.overflowX) && p.getBoundingClientRect().right <= vw + 1) { clipped = true; break; }
        }
        if (!clipped) out.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}.${[...el.classList].join('.')} right=${Math.round(r.right)}`);
      }
      if (out.length > 8) break;
    }
    // 横向滚动条：可滚动区域内容比容器宽
    for (const el of document.querySelectorAll('#app-page *')) {
      const s = getComputedStyle(el);
      if (/(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        out.push(`h-scroll ${el.tagName.toLowerCase()}.${[...el.classList].join('.')} ${el.scrollWidth}>${el.clientWidth}`);
      }
      if (out.length > 12) break;
    }
    return out;
  });
}

// 第一屏可见、可点的控件数（按钮、链接、输入、下拉、折叠头、带 role 的按钮），用来比改前改后
async function countControls(page) {
  return page.evaluate(() => {
    const vw = innerWidth, vh = innerHeight;
    const sel = 'button, a[href], input:not([type=hidden]), select, textarea, summary, [role=button], [role=radio], [role=tab], [role=switch]';
    let n = 0, primary = 0;
    for (const el of document.querySelectorAll(sel)) {
      if (el.closest('[hidden], [inert]')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2 || r.bottom <= 0 || r.right <= 0 || r.top >= vh || r.left >= vw) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || Number(cs.opacity) === 0 || cs.pointerEvents === 'none') continue;
      const hit = document.elementFromPoint(Math.min(vw - 1, Math.max(0, r.left + r.width / 2)), Math.min(vh - 1, Math.max(0, r.top + r.height / 2)));
      if (hit && !el.contains(hit) && !hit.contains(el) && !(el.tagName === 'INPUT' && hit.tagName === 'LABEL')) continue;
      n += 1;
    }
    return n;
  });
}

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')));
  const only = args.only ? new Set(args.only.split(',')) : null;
  const counts = {};
  const sizes = (args.size ? [args.size] : ['1100x760', '900x600']).map((s) => s.split('x').map(Number));
  const { chromium } = loadPlaywright();
  const server = await serveStatic();
  const browser = await chromium.launch({ executablePath: chromePath, headless: true, args: ['--mute-audio'] });
  const unknown = new Set();
  const problems = [];
  try {
    for (const [w, h] of sizes) {
      const dir = path.join(shotsRoot, `${w}x${h}`);
      fs.mkdirSync(dir, { recursive: true });
      for (const scene of scenes) {
        if (only && !only.has(scene.name)) continue;
        const context = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
        page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console: ' + msg.text()); });
        const { handle } = createMock(scene.mock || {});
        await page.route('**/api/**', async (route) => {
          const req = route.request();
          const result = handle(req.url(), req.method(), req.postData());
          if (!result) { unknown.add(`${req.method()} ${new URL(req.url()).pathname}`); await route.fulfill({ status: 404, json: { detail: 'mock: 未登记' } }); return; }
          if (result.json !== undefined) await route.fulfill({ status: result.status, json: result.json });
          else await route.fulfill({ status: result.status, contentType: result.contentType, body: result.body });
        });
        await page.goto(`http://127.0.0.1:${port}/index.html`);
        await page.waitForSelector('#jine-messages .jm-row, #jine-messages .jine-empty');
        await page.waitForTimeout(300);
        try {
          await scene.run(page);
        } catch (e) {
          errors.push('scene: ' + e.message.split('\n')[0]);
        }
        await page.screenshot({ path: path.join(dir, scene.name + '.png') });
        if (args.count) counts[`${w}x${h}/${scene.name}`] = await countControls(page);
        const overflow = await overflowReport(page);
        // 404 的预期接口（mock 故意未登记的）不算页面报错
        const real = errors.filter((e) => !/Failed to load resource: the server responded with a status of 404/.test(e));
        if (real.length || overflow.length) problems.push({ scene: `${w}x${h}/${scene.name}`, errors: real, overflow });
        await context.close();
      }
    }
  } finally {
    await browser.close();
    server.close();
  }
  for (const p of problems) {
    console.log(`\n[${p.scene}]`);
    p.errors.forEach((e) => console.log('  ERR ' + e));
    p.overflow.forEach((e) => console.log('  OVERFLOW ' + e));
  }
  if (args.count) fs.writeFileSync(args.count, JSON.stringify(counts, null, 1));
  if (unknown.size) console.log('\n未登记的接口：\n  ' + [...unknown].sort().join('\n  '));
  console.log(`\n截图：${shotsRoot}`);
  if (!problems.length) console.log('无控制台报错、无横向溢出。');
}

main().catch((e) => { console.error(e); process.exit(1); });
