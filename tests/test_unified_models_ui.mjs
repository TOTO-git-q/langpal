// Offline regression: 设置 › 模型与账号（Claude / ChatGPT / DeepSeek / 自定义端点，模型和档位读到什么显示什么）
// + ChatGPT 登录（桌面壳 IPC / 没有壳时开浏览器，链接总能复制）+ 课程管家选哪家。所有接口都是 tests/ui/mock-api.mjs 的假数据。
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMock} from './ui/mock-api.mjs';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf','.json':'application/json'};
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true,args:['--mute-audio']});

async function open(mockOptions={},{desktop=false}={}){
 const page=await browser.newPage({viewport:{width:1100,height:800}});page.setDefaultTimeout(8000);
 const errors=[],calls=[];page.on('pageerror',e=>errors.push(String(e)));
 const {handle}=createMock(mockOptions);
 if(desktop)await page.addInitScript(()=>{window.ipcOpened=[];window.langpalDesktop={isDesktop:true,minimize(){},toggleMaximize(){},close(){},openChatGPTLogin:async url=>{window.ipcOpened.push(url);return {opened:true};}};});
 else await page.addInitScript(()=>{window.opened=[];window.open=url=>{window.opened.push(url);return null;};});
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  assert.equal(u.hostname,'models.test','External requests forbidden: '+req.url());
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
 await page.goto('http://models.test/');
 await page.waitForSelector('#jine-messages .jm-row');
 return {page,errors,calls};
}
const models=async page=>{await page.evaluate(()=>LP.appShell.switchTab('settings'));await page.click('[data-settings-tab="models"]');await page.locator('[data-engine-now] strong').waitFor();};
const noOverflow=async page=>{for(const width of [1100,768,390]){await page.setViewportSize({width,height:800});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow at '+width);}await page.setViewportSize({width:1100,height:800});};

try {
 // 1. 模型页：四个引擎、模型和档位来自接口；DeepSeek 的档位是默认列表（虚线）；Claude 有「关闭」
 {
  const {page,errors,calls}=await open({});
  await models(page);
  assert.deepEqual(await page.locator('#f-chat-engine option').evaluateAll(o=>o.map(x=>x.value)),['claude','chatgpt','deepseek','custom']);
  assert.deepEqual(await page.locator('#f-utility-engine option').evaluateAll(o=>o.map(x=>x.value)),['auto','claude','chatgpt','deepseek','custom']);
  await page.waitForFunction(()=>document.querySelector('#f-model-claude').options.length>=3);
  assert.deepEqual(await page.locator('#f-model-claude option').evaluateAll(o=>o.map(x=>x.value)),['sonnet','opus','haiku']);
  assert.deepEqual(await page.locator('#f-reasoning-claude option').evaluateAll(o=>o.map(x=>x.textContent)),['关闭','低','中','高','最高']);
  assert.equal(await page.locator('#f-reasoning-claude').inputValue(),'medium');
  // 换模型 → 档位跟着换成这个模型声明的那些
  await page.selectOption('#f-model-claude','haiku');
  await page.waitForTimeout(150);
  assert.deepEqual(await page.locator('#f-reasoning-claude option').evaluateAll(o=>o.map(x=>x.value)),['off']);
  assert.equal(calls.filter(c=>c.method==='PUT'&&c.path==='/api/settings').at(-1).body.chat_model_claude,'haiku');
  await page.selectOption('#f-model-claude','opus');await page.waitForTimeout(150);
  await page.selectOption('#f-reasoning-claude','xhigh');await page.waitForTimeout(150);
  assert.deepEqual(calls.filter(c=>c.path==='/api/engines/claude/reasoning').at(-1).body,{model:'opus',effort:'xhigh'});
  await page.waitForFunction(()=>document.querySelector('#f-reasoning-deepseek').options.length>1);
  assert.equal(await page.locator('#f-reasoning-deepseek').evaluate(n=>n.classList.contains('guessed')),true);
  assert.equal(await page.locator('#f-reasoning-claude').evaluate(n=>n.classList.contains('guessed')),false);
  // 没配置的自定义端点、没登录的 ChatGPT 都不去读模型
  assert.equal(calls.some(c=>c.path==='/api/engines/custom/models'||c.path==='/api/engines/chatgpt/models'),false);
  assert.equal(await page.locator('[data-read-models=custom]').isDisabled(),true);
  // 密钥只在占位里显示掩码
  assert.equal(await page.locator('#f-deepseek-key').inputValue(),'');
  assert.match(await page.locator('#f-deepseek-key').getAttribute('placeholder'),/^····/);
  await page.locator('[data-usage-panel] .usage-row').first().waitFor();
  await noOverflow(page);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 2. ChatGPT 登录：没有桌面壳 → window.open；链接总能复制；可以取消
 {
  const {page,errors,calls}=await open({});
  await models(page);
  const card=page.locator('[data-engine-block="chatgpt"]');
  await card.getByRole('button',{name:'登录 ChatGPT'}).click();
  await card.locator('[data-gpt="login"]').waitFor();
  assert.match(await card.locator('[data-gpt="link"]').inputValue(),/^http:\/\/127\.0\.0\.1:\d+\/begin\?ticket=/);
  assert.deepEqual(calls.find(c=>c.path==='/api/workspace-agent/siwc/login').body,{approved:true});
  assert.equal((await page.evaluate(()=>window.opened)).length,1);
  assert.equal(await card.locator('[data-gpt="login"]').getAttribute('data-opened'),'false'); // window.open 回 null：链接框标红
  await card.getByRole('button',{name:'取消'}).click();
  await card.getByRole('button',{name:'登录 ChatGPT'}).waitFor();
  assert.ok(calls.some(c=>c.path==='/api/workspace-agent/siwc/cancel'));
  assert.deepEqual(errors,[]);
  await page.close();
 }
 {
  // 有桌面壳 → 走 IPC
  const {page,errors}=await open({},{desktop:true});
  await models(page);
  await page.locator('[data-engine-block="chatgpt"]').getByRole('button',{name:'登录 ChatGPT'}).click();
  await page.waitForFunction(()=>window.ipcOpened.length===1);
  assert.equal(await page.locator('[data-gpt="login"]').getAttribute('data-opened'),'true');
  assert.deepEqual(errors,[]);
  await page.close();
 }
 {
  // 已登录：显示邮箱、模型和档位来自账号
  const {page,errors,calls}=await open({gpt:true});
  await models(page);
  await page.locator('.gpt-who').getByText('p-chan@example.com').waitFor();
  await page.waitForFunction(()=>document.querySelector('#f-model-chatgpt').options.length===2);
  assert.equal(await page.locator('#f-model-chatgpt').inputValue(),'gpt-5.5');
  await page.selectOption('#f-reasoning-chatgpt','high');await page.waitForTimeout(150);
  assert.deepEqual(calls.filter(c=>c.path==='/api/engines/chatgpt/reasoning').at(-1).body,{model:'gpt-5.5',effort:'high'});
  await noOverflow(page);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 3. 降级：醒目，写清主引擎和现在用的
 {
  const {page,errors}=await open({degraded:true});
  await models(page);
  await page.waitForFunction(()=>document.querySelector('[data-engine-now]').classList.contains('degraded'));
  assert.match(await page.locator('[data-engine-now]').innerText(),/现在用[\s\S]*DeepSeek[\s\S]*Claude 用不了/);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 4. 课程管家：默认跟主引擎（请求里不带 provider）；换一家就带上；选中的那家不可用时说一句、不能发
 {
  const {page,errors,calls}=await open({});
  await page.evaluate(()=>LP.appShell.switchTab('workspace-agent'));
  await page.waitForFunction(()=>document.querySelector('.workspace-agent')?.getAttribute('aria-busy')==='false');
  const picker=page.locator('.workspace-agent-model');
  assert.equal(await picker.inputValue(),'main');
  assert.match(await picker.locator('option').first().innerText(),/默认 · Claude/);
  await page.fill('#workspace-agent-input','hi');
  await page.locator('.workspace-agent-send').click();
  await page.waitForFunction(()=>document.querySelector('#workspace-agent-input').value==='');
  assert.equal('provider' in calls.find(c=>c.path==='/api/workspace-agent/plan').body,false);
  await picker.selectOption('chatgpt'); // 还没登录
  assert.match(await page.locator('.workspace-agent-provider').innerText(),/ChatGPT 用不了/);
  assert.equal(await page.locator('.workspace-agent-provider button').innerText(),'去设置');
  await page.fill('#workspace-agent-input','again');
  assert.equal(await page.locator('.workspace-agent-send').isDisabled(),true);
  await picker.selectOption('deepseek');
  assert.equal(await page.locator('.workspace-agent-send').isEnabled(),true);
  await page.locator('.workspace-agent-send').click();
  await page.waitForFunction(()=>document.querySelector('#workspace-agent-input').value==='');
  assert.equal(calls.filter(c=>c.path==='/api/workspace-agent/plan').at(-1).body.provider,'deepseek');
  await noOverflow(page);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log('PASS: four engines, models/levels as read (default list dashed, Claude off), model→levels follow, reasoning POST, no catalog reads for unconfigured engines, masked keys, ChatGPT login via window.open and via desktop IPC with copyable link + cancel, signed-in account models, degraded banner, concierge follows main / explicit provider / blocked unavailable provider, 390/768/1100 widths.');
} finally { await browser.close(); }
