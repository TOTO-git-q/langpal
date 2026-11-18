// 界面收敛：记住上次的页面；Ctrl+数字切分区、Ctrl+K 回聊天输入框；连续流的主按钮指向今天的下一件；
// 气泡小工具在键盘聚焦时出现；设置里长文本没存时离开要拦；顶栏「⋯」收纳；听力错因回显。
// 整个应用跑在 mock-api 上，不连真后端。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMock} from './ui/mock-api.mjs';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf','.woff2':'font/woff2'};
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true,args:['--mute-audio']});

async function wire(page,mock={}){
 page.setDefaultTimeout(8000);
 const errors=[],calls=[];page.on('pageerror',e=>errors.push(String(e)));
 const {handle}=createMock(mock);
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  if(u.pathname.startsWith('/api/')){
   const body=req.postData();calls.push({method:req.method(),path:u.pathname,query:u.search,body});
   const r=handle(req.url(),req.method(),body);
   if(!r)return route.fulfill({status:404,json:{detail:'mock'}});
   return r.json!==undefined?route.fulfill({status:r.status,json:r.json}):route.fulfill({status:r.status,contentType:r.contentType,body:r.body});
  }
  const file=path.join(root,'frontend',u.pathname==='/'?'index.html':decodeURIComponent(u.pathname));
  try{return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:await fs.readFile(file)});}catch{return route.fulfill({status:404,body:''});}
 });
 return {errors,calls};
}
const active=page=>page.evaluate(()=>document.querySelector('.page-panel.active')?.id);

try {
 // 1. 记住上次的页面（同一个浏览器配置里重开）
 {
  const context=await browser.newContext({viewport:{width:1100,height:760}});
  const page=await context.newPage();const {errors}=await wire(page);
  await page.goto('http://app.test/');await page.waitForSelector('#jine-messages .jm-row');
  await page.evaluate(()=>LP.appShell.switchTab('notebook'));
  await page.waitForSelector('#page-notebook .nb-card');
  await page.reload();await page.waitForFunction(()=>document.querySelector('.page-panel.active')?.id==='page-notebook');
  // 复习分区也记得落在单词本
  await page.evaluate(()=>LP.appShell.switchTab('talk'));await page.evaluate(()=>LP.appShell.switchTab('revise'));
  assert.equal(await active(page),'page-notebook');
  assert.deepEqual(errors,[]);
  await context.close();
 }
 // 2. 键盘：Ctrl+1…5 切分区，Ctrl+K 回聊天并聚焦输入框
 {
  const page=await browser.newPage({viewport:{width:1100,height:760}});const {errors}=await wire(page);
  await page.goto('http://app.test/');await page.waitForSelector('#jine-messages .jm-row');
  await page.keyboard.press('Control+2');assert.equal(await active(page),'page-today');
  await page.keyboard.press('Control+3');assert.equal(await active(page),'page-drill');
  await page.keyboard.press('Control+5');assert.equal(await active(page),'page-settings');
  await page.keyboard.press('Control+k');assert.equal(await active(page),'page-talk');
  await page.waitForFunction(()=>document.activeElement?.id==='jine-input');
  // 顶栏右侧只有拨片（骰子是最后一格）和「⋯」；旧对话、课程、人设卡都在「⋯」里
  assert.equal(await page.locator('#jm-dial #jm-dice').count(),1);
  assert.equal(await page.locator('#jm-archives').isVisible(),false);
  await page.click('#jm-more');assert.equal(await page.locator('#jm-archives').isVisible(),true);
  await page.keyboard.press('Escape');assert.equal(await page.locator('#jm-menu').isHidden(),true);
  assert.equal(await page.evaluate(()=>document.activeElement?.id),'jm-more');
  // 气泡小工具：平时不显示；键盘聚焦到她的气泡时出现
  const row=page.locator('#jine-messages .jm-row:not(.me)').filter({has:page.locator('.jm-tools')}).last();
  assert.equal(await row.locator('.jm-tools').evaluate(n=>getComputedStyle(n).visibility),'hidden');
  await row.locator('.bubble').focus();
  assert.equal(await row.locator('.jm-tools').evaluate(n=>getComputedStyle(n).visibility),'visible');
  // 没发出去的字：刷新后还在
  await page.fill('#jine-input','还没发的一句');
  await page.reload();await page.waitForSelector('#jine-messages .jm-row');
  assert.equal(await page.inputValue('#jine-input'),'还没发的一句');
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 3. 连续流：复习结束，主按钮是今天还没做的下一件（mock：听力没做）；回今天走图标栏
 {
  const page=await browser.newPage({viewport:{width:1100,height:760}});const {errors}=await wire(page,{emptyQueue:true});
  await page.goto('http://app.test/');await page.waitForSelector('#jine-messages .jm-row');
  await page.evaluate(()=>LP.appShell.switchTab('drill'));
  await page.waitForSelector('.rv2-end .next-go[data-next]:not([data-next=""])');
  assert.equal(await page.locator('.rv2-end .next-go').innerText(),'听一段');
  assert.equal(await page.evaluate(()=>document.activeElement?.classList.contains('next-go')),true);
  await page.keyboard.press('Enter');
  assert.equal(await active(page),'page-listening');
  // 今天：第一个没做完的是「下一步」，焦点在它上面，做完的变淡
  await page.evaluate(()=>LP.appShell.switchTab('today'));
  await page.waitForSelector('.lt-step.next');
  assert.equal(await page.locator('.lt-step.next').getAttribute('data-kind'),'review');
  assert.equal(await page.locator('.lt-step.done').count()>=1,true);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 4. 设置里长文本改了没存，切走要拦；选「留下」不走
 {
  const page=await browser.newPage({viewport:{width:1100,height:760}});const {errors}=await wire(page);
  await page.goto('http://app.test/');await page.waitForSelector('#jine-messages .jm-row');
  await page.evaluate(()=>LP.appShell.switchTab('settings'));
  await page.waitForSelector('#f-free-text');
  assert.equal(await page.locator('.save-btn').first().isVisible(),false); // 没改动时保存栏不出现
  await page.fill('#f-free-text','改了一点');
  assert.equal(await page.locator('.save-btn').first().isVisible(),true);
  await page.evaluate(()=>LP.appShell.switchTab('talk'));
  await page.waitForSelector('.confirm-box');
  await page.click('.confirm-box button:has-text("留下")');
  assert.equal(await active(page),'page-settings');
  await page.click('[data-settings-tab="reader"]');
  await page.waitForSelector('.confirm-box');
  await page.click('.confirm-box button:has-text("不保存")');
  await page.waitForFunction(()=>document.querySelector('[data-settings-tab="reader"]').getAttribute('aria-pressed')==='true');
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 5. 听力：重新打开已交卷的练习，已标的错因显示成小签，没标的才问
 {
  const page=await browser.newPage({viewport:{width:1100,height:760}});const {errors,calls}=await wire(page);
  await page.goto('http://app.test/');await page.waitForSelector('#jine-messages .jm-row');
  await page.evaluate(()=>LP.appShell.switchTab('listening'));
  await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])');
  // 首页两栏：最近（对错点阵：已批改实心、没听完空心）和这个月（大数字 + 强弱条）
  await page.waitForSelector('.lp-recent-row .lp-dots i');
  assert.ok(await page.locator('.lp-recent-row .lp-dots i.ok').count()>0);
  assert.ok(await page.locator('.lp-recent-row.pending .lp-dots i.open').count()>0);
  await page.waitForSelector('.lp-month:not([hidden]) .lp-big-number');
  assert.ok(await page.locator('.lp-month .lp-bar').count()>0);
  assert.ok(await page.locator('[data-listen="tags"] .lp-tag').count()>0);
  assert.equal(calls.some(c=>/\/learning\/(stats|advice)$/.test(c.path)&&!/language=/.test(c.query)),false); // 这两个接口都带 language
  // 题型格子：点一格 = 选中并保存安排（同一条保存路径）；卡上文字同步，刷新后仍选中
  await page.waitForSelector('.lp-format-tile[data-format="en_conversation"]');
  await page.click('.lp-format-tile[data-format="en_conversation"]');
  await page.waitForFunction(()=>document.querySelector('[data-listen="plan-detail"]').textContent.startsWith('校园对话'));
  assert.ok(calls.some(c=>c.path==='/api/listening/plans/en'&&JSON.parse(c.body).format==='en_conversation'));
  assert.equal(await page.locator('.lp-format-tile[aria-checked="true"]').getAttribute('data-format'),'en_conversation');
  assert.equal(await page.locator('[data-listen="edit-plan"]').isVisible(),false); // 换题型按钮没了，主题和难度在「⋯」里
  await page.reload();await page.waitForSelector('#page-listening.active .lp-format-tile[aria-checked="true"]');
  assert.equal(await page.locator('.lp-format-tile[aria-checked="true"]').getAttribute('data-format'),'en_conversation');
  const graded=await page.evaluate(async()=>(await (await fetch('/api/listening/practices')).json()).items.find(i=>i.status==='graded')?.id);
  assert.ok(graded,'mock has a graded practice');
  await page.locator('.lp-recent-row[data-id="'+graded+'"]').click();
  await page.waitForSelector('.lp-causes');
  assert.equal(await page.locator('.lp-cause-row').count(),1); // 只问没标的那题
  await page.locator('.lp-cause[data-cause="misjudged"]').click();
  await page.waitForSelector('.lp-cause-tag');
  assert.deepEqual((await page.locator('.lp-cause-tag').allInnerTexts()).map(t=>t.replace(/\s+/g,' ')).sort(),['≋ 没听清','✗ 听懂了答错']);
  assert.ok(calls.some(c=>c.path.endsWith('/causes')&&JSON.parse(c.body).items.length===1));
  // 自绘进度：一句一块（/shape），没有浏览器自带播放条；点块跳到那句开头
  await page.waitForFunction(()=>document.querySelectorAll('.lp-track .lp-seg').length===7);
  assert.equal(await page.evaluate(()=>document.querySelector('.lp-listening-player audio').controls),false);
  assert.equal(await page.locator('.lp-big-play').count(),1);
  await page.locator('.lp-track .lp-seg').nth(2).click();
  assert.ok(Math.abs(await page.evaluate(()=>document.querySelector('.lp-listening-player audio').currentTime)-Number(await page.locator('.lp-track .lp-seg').nth(2).getAttribute('data-start')))<0.2);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log('PASS: remember last page, Ctrl+1-5 / Ctrl+K, topbar ⋯, bubble tools on focus, chat draft kept, continuous-flow next button, today next step, unsaved-change guard, listening causes echo');
} finally { await browser.close(); }
