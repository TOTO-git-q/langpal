// Offline regression for the phase-2 screens: proactive messages in chat, world-book (lore) manager and the 事件 (hooks) settings. Whole app, every /api/** answered by tests/ui/mock-api.mjs.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMock} from './ui/mock-api.mjs';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf','.json':'application/json'};
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true,args:['--mute-audio']});

async function open(mockOptions={},viewport={width:1100,height:760}){
 const page=await browser.newPage({viewport});page.setDefaultTimeout(8000);
 const errors=[],calls=[];page.on('pageerror',e=>errors.push(String(e)));
 const {handle}=createMock(mockOptions);
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  assert.equal(u.hostname,'jine.test','External requests forbidden: '+req.url());
  if(u.pathname.startsWith('/api/')){
   const body=req.postData();calls.push({method:req.method(),path:u.pathname,body:(()=>{try{return JSON.parse(body);}catch{return body;}})()});
   const result=handle(req.url(),req.method(),body);
   if(!result)return route.fulfill({status:404,json:{detail:'mock: 未登记'}});
   return result.json!==undefined?route.fulfill({status:result.status,json:result.json}):route.fulfill({status:result.status,contentType:result.contentType,body:result.body});
  }
  const file=path.join(root,'frontend',u.pathname==='/'?'index.html':decodeURIComponent(u.pathname));
  try{return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:await fs.readFile(file)});}
  catch{return route.fulfill({status:404,body:''});}
 });
 await page.goto('http://jine.test/');
 await page.waitForSelector('#jine-messages .jm-row');
 return {page,errors,calls};
}
const noOverflow=async page=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
const settingsPage=async(page,key)=>{await page.evaluate(()=>LP.appShell.switchTab('settings'));await page.click(`[data-settings-tab="${key}"]`);};

try {
 // 1. 主动消息：她有一条待发 → 红点；打开对话先 fire chat.open，再拉 proactive，消息像平时一样冒出来
 {
  const {page,errors,calls}=await open({proactive:true});
  await page.waitForSelector('#msg-951');
  const fire=calls.find(c=>c.path==='/api/hooks/fire');
  assert.equal(fire.body.event,'chat.open');
  assert.equal('persona_id' in fire.body,false); // 主聊天：不带 persona_id
  assert.equal('first_today' in (fire.body.payload||{}),false); // 后端自己算
  assert.equal(calls.filter(c=>c.path==='/api/chat/proactive').length,1);
  assert.equal(calls.some(c=>c.method==='POST'&&c.path==='/api/chat'),false); // 不是用户发起的一轮
  assert.deepEqual(calls.find(c=>c.path==='/api/chat/proactive').body,{});
  // 不在聊天页时有待发 → 图标栏「聊天」上一个红点，不自动拉
  await page.evaluate(()=>LP.appShell.switchTab('notebook'));
  await page.evaluate(async()=>{await fetch('/api/__mock/pending',{method:'POST'});await LP.jine.refreshPending();});
  await page.locator('.nav-btn[data-tab="talk"] .nav-dot').waitFor();
  assert.equal(calls.filter(c=>c.path==='/api/chat/proactive').length,1);
  await page.evaluate(()=>LP.appShell.switchTab('talk'));
  await page.waitForFunction(()=>!document.querySelector('.nav-btn[data-tab="talk"] .nav-dot'));
  await page.waitForFunction(()=>true);await page.waitForTimeout(400);
  assert.equal(calls.filter(c=>c.path==='/api/chat/proactive').length,2);
  // 同一次运行里 10 分钟内回到聊天页不会再 fire chat.open
  const before=calls.filter(c=>c.path==='/api/hooks/fire').length;
  await page.evaluate(()=>{LP.appShell.switchTab('settings');LP.appShell.switchTab('talk');});
  await page.waitForTimeout(300);
  assert.equal(calls.filter(c=>c.path==='/api/hooks/fire').length,before);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 2. 没有待发：proactive 回 done{empty} 时什么都不画
 {
  const {page,errors,calls}=await open({});
  await page.waitForTimeout(600);
  assert.equal(await page.locator('[id^="msg-95"]').count(),0);
  assert.equal(calls.some(c=>c.path==='/api/chat/proactive'),false);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 3. 世界书
 {
  const {page,errors,calls}=await open({});
  await settingsPage(page,'library');
  await page.click('[data-course-tab="world"]');
  await page.waitForSelector('.lore-entry');
  // 书卡上的开关立即生效
  const firstSwitch=page.locator('.lore-book [role=switch]').first();
  const was=await firstSwitch.isChecked();
  await firstSwitch.click();
  await page.waitForFunction(()=>true);await page.waitForTimeout(200);
  const put=calls.filter(c=>c.method==='PUT'&&/^\/api\/lore\/books\/\d+$/.test(c.path)).at(-1);
  assert.equal(put.body.enabled,!was);
  // 条目：改正文 → 出现保存条 → 保存
  await page.locator('.lore-entry-pick').first().click();
  await page.locator('.lore-entry.open textarea').first().fill('新的正文');
  await page.locator('.lore-savebar').waitFor();
  await page.getByRole('button',{name:'保存这本书',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.lore-savebar')?.hidden!==false);
  const saved=calls.filter(c=>c.method==='PUT'&&/^\/api\/lore\/books\/\d+$/.test(c.path)).at(-1);
  assert.ok(saved.body.book.entries.some(e=>e.content==='新的正文'));
  // 新条目：不带 uid，保存后后端编号；有没保存的修改时按钮是「保存并试一下」，先存再试，结果画在新的试触发框里
  await page.getByRole('button',{name:'+ 新条目',exact:true}).click();
  await page.locator('.lore-entry.open .lore-field').filter({hasText:'标题'}).locator('input').fill('新加的一条');
  await page.fill('.lore-test-bar input','今晚配信要不要早点开始？');
  await page.getByRole('button',{name:'保存并试一下',exact:true}).click();
  await page.waitForSelector('.lore-hit');
  const withNew=calls.filter(c=>c.method==='PUT'&&/^\/api\/lore\/books\/\d+$/.test(c.path)).at(-1);
  assert.equal('uid' in withNew.body.book.entries.find(e=>e.title==='新加的一条'),false);
  assert.ok(withNew.body.book.entries.filter(e=>e.title!=='新加的一条').every(e=>Number.isInteger(e.uid)));
  assert.equal(await page.locator('.lore-test-bar input').inputValue(),'今晚配信要不要早点开始？');
  // 三种注入状态看得出区别；被挡下的长列表在框里滚动
  assert.deepEqual(await page.locator('.lore-injected').evaluateAll(xs=>[...new Set(xs.map(x=>x.dataset.injected))].sort()),['held','system','turn']);
  assert.match(await page.locator('.lore-hit').first().innerText(),/常驻/);
  const miss=await page.locator('.lore-miss-list').evaluate(n=>({scroll:n.scrollHeight>n.clientHeight,overflow:getComputedStyle(n).overflowY,first:n.querySelector('small').textContent}));
  assert.ok(miss.scroll);assert.equal(miss.overflow,'auto');assert.match(miss.first,/条件不满足/);
  // 再存一次：刚才那条已经有 uid 了，要带回去
  // 保存后刚才展开的那条仍然展开
  assert.match(await page.locator('.lore-entry.open .lore-entry-pick').innerText(),/新加的一条/);
  await page.locator('.lore-entry.open textarea').first().fill('改一下');
  await page.getByRole('button',{name:'保存这本书',exact:true}).click();
  await page.waitForTimeout(200);
  const again=calls.filter(c=>c.method==='PUT'&&/^\/api\/lore\/books\/\d+$/.test(c.path)).at(-1);
  assert.ok(Number.isInteger(again.body.book.entries.find(e=>e.title==='新加的一条').uid));
  // 导入失败：后端的中文 detail 原样显示
  await page.setInputFiles('.lore-toolbar input[type=file]',{name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{}')});
  await page.locator('.lore-notice').getByText('没认出这是酒馆世界书或角色卡',{exact:true}).waitFor();
  // 删除要确认
  await page.getByRole('button',{name:'删除',exact:true}).first().click();
  await page.locator('.confirm-box').waitFor();
  await page.keyboard.press('Escape');
  assert.equal(calls.some(c=>c.method==='DELETE'&&c.path.startsWith('/api/lore/books/')),false);
  for(const width of [900,768,390]){await page.setViewportSize({width,height:800});await noOverflow(page);}
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 4. 事件：总开关、自带规则不能删、自定义规则能删、变量和记录
 {
  const {page,errors,calls}=await open({});
  await settingsPage(page,'hooks');
  await page.waitForSelector('.hooks-rule');
  const master=page.locator('[data-hooks="enabled"]');
  assert.equal(await master.isChecked(),true);
  await master.click();await page.waitForTimeout(200);
  assert.equal(calls.find(c=>c.method==='PUT'&&c.path==='/api/settings'&&'hooks_enabled' in c.body).body.hooks_enabled,false);
  // 节流超范围按上限存（后端 0–50，非法 422）
  await page.fill('[data-hooks="cap"]','99');await page.locator('[data-hooks="cap"]').dispatchEvent('change');await page.waitForTimeout(150);
  assert.equal(calls.filter(c=>c.method==='PUT'&&c.path==='/api/settings'&&'hooks_say_daily_cap' in c.body).at(-1).body.hooks_say_daily_cap,50);
  await page.locator('.hooks-rule').first().locator('[role=switch]').click();await page.waitForTimeout(150);
  assert.deepEqual(calls.filter(c=>c.method==='PUT'&&/^\/api\/hooks\/rules\/\d+$/.test(c.path)).at(-1).body,{enabled:false});
  // 自带规则：有「自带」标记，编辑器里没有删除
  const builtin=page.locator('.hooks-rule').filter({has:page.locator('.lore-badge',{hasText:'自带'})}).first();
  await builtin.locator('.hooks-rule-pick').click();
  await page.waitForSelector('.hooks-form');
  assert.equal(await page.locator('.hooks-form-actions').getByRole('button',{name:'删除',exact:true}).count(),0);
  // 保存走 PUT /api/hooks/rules/{id}，不带 id/builtin
  await page.getByRole('button',{name:'保存规则',exact:true}).click();
  await page.waitForTimeout(200);
  const ruleSave=calls.filter(c=>c.method==='PUT'&&/^\/api\/hooks\/rules\/\d+$/.test(c.path)).at(-1);
  assert.ok(ruleSave);assert.equal('id' in ruleSave.body,false);assert.equal('builtin' in ruleSave.body,false);
  // 自定义规则：activate_entry 的条目下拉跟着书走（显示标题，存 uid）
  const custom=page.locator('.hooks-rule').filter({hasNot:page.locator('.lore-badge',{hasText:'自带'})}).first();
  await custom.locator('.hooks-rule-pick').click();
  const entrySel=page.locator('.hooks-form [data-field="uid"]');
  await page.waitForFunction(()=>document.querySelector('.hooks-form [data-field="uid"]')?.options.length>1);
  assert.equal(await entrySel.inputValue(),'1');
  assert.ok((await entrySel.locator('option').allInnerTexts()).includes('配信时间'));
  await page.locator('.hooks-form [data-field="book_id"]').selectOption('2');
  await page.waitForFunction(()=>[...document.querySelector('.hooks-form [data-field="uid"]').options].some(o=>o.text==='电车'));
  await entrySel.selectOption({label:'电车'});
  // 新加 remember 动作：必填没填就拦下
  await page.getByRole('button',{name:'+ 动作',exact:true}).click();
  await page.locator('.hooks-action').last().locator('.hooks-action-head select').selectOption('remember');
  await page.getByRole('button',{name:'保存规则',exact:true}).click();
  await page.locator('.hooks-notice').getByText(/要填/).waitFor();
  await page.locator('.hooks-action').last().locator('textarea').fill('{{date}} 熬夜');
  await page.getByRole('button',{name:'保存规则',exact:true}).click();await page.waitForTimeout(200);
  const customSave=calls.filter(c=>c.method==='PUT'&&c.path==='/api/hooks/rules/8').at(-1).body;
  assert.deepEqual(customSave.actions.find(a=>a.type==='activate_entry'),{type:'activate_entry',book_id:2,uid:1,turns:2});
  assert.deepEqual(customSave.actions.find(a=>a.type==='remember'),{type:'remember',content:'{{date}} 熬夜',category:'event'});
  await custom.locator('.hooks-rule-pick').click();
  await page.locator('.hooks-form-actions').getByRole('button',{name:'删除',exact:true}).click();
  await page.locator('.confirm-box').waitFor();
  await page.locator('.confirm-box').getByRole('button',{name:'删除',exact:true}).click();
  await page.waitForTimeout(200);
  assert.ok(calls.some(c=>c.method==='DELETE'&&/^\/api\/hooks\/rules\/\d+$/.test(c.path)));
  // 变量表和记录都读出来了；记录按后端的原因码显示成人话
  await page.waitForSelector('.hooks-log-row');
  const logText=await page.locator('.hooks-log').innerText();
  assert.match(logText,/没有到期的生词/);assert.match(logText,/变量加减 night_owl/);assert.doesNotMatch(logText,/no_due_vocab|say_min_gap/);
  assert.ok(calls.some(c=>c.method==='GET'&&c.path==='/api/hooks/vars'));
  for(const width of [900,768,390]){await page.setViewportSize({width,height:800});await noOverflow(page);}
  assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log('PASS lore/hooks: proactive chat.open (no persona) + stream + chat-icon dot + 10-min guard, empty proactive draws nothing, evaluator off, lore toggle/edit/save (new entries without uid, uid kept after reload)/save-and-test/injected states/scrolling skipped list/raw import error/delete-confirm, entry picker follows book, hooks master switch, builtin undeletable, rule save body, custom delete with confirm, vars + log, 390/768/900 widths.');
} finally { await browser.close(); }
