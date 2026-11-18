// Offline regression for the single main chat (docs/MAIN-CHAT.md): no contact list, read marks, lead + chime speakers,
// naming a guest, the language dial and the dice, stickers, archives (read-only), and jumping back to a sentence.
// Whole app; every /api/** is answered by tests/ui/mock-api.mjs.
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
  assert.equal(u.hostname,'chat.test','External requests forbidden: '+req.url());
  if(u.pathname.startsWith('/api/')){
   const body=req.postData();calls.push({method:req.method(),path:u.pathname,query:u.search,body:(()=>{try{return JSON.parse(body);}catch{return body;}})()});
   const result=handle(req.url(),req.method(),body);
   if(!result)return route.fulfill({status:404,json:{detail:'mock: 未登记'}});
   return result.json!==undefined?route.fulfill({status:result.status,json:result.json}):route.fulfill({status:result.status,contentType:result.contentType,body:result.body});
  }
  const file=path.join(root,'frontend',u.pathname==='/'?'index.html':decodeURIComponent(u.pathname));
  try{return route.fulfill({contentType:types[path.extname(file)]||'application/octet-stream',body:await fs.readFile(file)});}
  catch{return route.fulfill({status:404,body:''});}
 });
 await page.goto('http://chat.test/');
 await page.waitForSelector('#jine-messages .jm-row');
 return {page,errors,calls};
}
const noOverflow=async page=>{for(const width of [1100,900,768,390]){await page.setViewportSize({width,height:760});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'overflow at '+width);}await page.setViewportSize({width:1100,height:760});};

try {
 {
  const {page,errors,calls}=await open({});
  // 没有联系人列；主人设在顶栏，在场的副人设是小头像
  assert.equal(await page.locator('.jine-contact, .jine-contacts').count(),0);
  assert.match(await page.locator('#jm-name').innerText(),/糖糖/);
  assert.equal(await page.locator('.jm-guest').count(),2);
  assert.ok(calls.some(c=>c.path==='/api/chat/main/messages'));
  // 同一个人连发只有第一条带头像和尾巴；你的消息有「已读」
  const rows=await page.locator('#jine-messages .jm-row').evaluateAll(xs=>xs.map(x=>({first:x.classList.contains('first'),who:x.dataset.speaker})));
  for(let i=1;i<rows.length;i++)if(rows[i].who===rows[i-1].who)assert.equal(rows[i].first,false);
  assert.ok(await page.locator('.jm-row.me .jm-read:not([hidden])').count()>0);
  // 气泡最大宽度不超过对话区的 60%，对话区限宽居中
  const widths=await page.evaluate(()=>{const list=document.querySelector('#jine-messages').getBoundingClientRect().width;return [...document.querySelectorAll('.jm-stack')].map(s=>s.getBoundingClientRect().width/list);});
  assert.ok(Math.max(...widths)<=0.61);
  // 发一条：先画出来，read 事件给它标已读；主讲两条、Emma 插一句
  await page.fill('#jine-input','もう一回言って');
  await page.press('#jine-input','Enter');
  await page.waitForSelector('#msg-902');
  assert.deepEqual(calls.find(c=>c.path==='/api/chat').body,{text:'もう一回言って',scene:{tab:'talk',title:'聊天',language:null,text:'',actions:[]}});
  assert.equal(await page.locator('#msg-1001 .jm-read').isHidden(),false);
  assert.equal(await page.locator('#msg-902').getAttribute('data-speaker'),'p2');
  assert.equal(await page.locator('#msg-902').evaluate(n=>n.classList.contains('first')),true);
  assert.match(await page.locator('#msg-902 .jm-name').innerText(),/Emma/);
  await page.waitForFunction(()=>document.querySelector('#jm-status').textContent==='在线');
  // 点名：点 Lena 的小头像，下一条带 to，发完自动取消
  await page.click('.jm-guest[aria-label*="Lena"]');
  assert.equal(await page.locator('#jm-to').isVisible(),true);
  await page.fill('#jine-input','Und du?');
  await page.press('#jine-input','Enter');
  await page.waitForFunction(()=>document.querySelector('#jm-to').hidden);
  assert.deepEqual(calls.filter(c=>c.path==='/api/chat').at(-1).body,{text:'Und du?',to:3,scene:{tab:'talk',title:'聊天',language:null,text:'',actions:[]}});
  // 语言拨片、骰子：各发一个 PUT /api/chat/main，只带那一个字段
  await page.locator('.jm-dial-opt',{hasText:'English'}).click();
  await page.waitForTimeout(150);
  assert.deepEqual(calls.filter(c=>c.method==='PUT'&&c.path==='/api/chat/main').at(-1).body,{language:'en'});
  assert.equal(await page.locator('.jm-dial-opt[aria-checked="true"]').innerText(),'English');
  await page.click('#jm-dice');await page.waitForTimeout(150);
  assert.deepEqual(calls.filter(c=>c.method==='PUT'&&c.path==='/api/chat/main').at(-1).body,{fun:true});
  assert.equal(await page.locator('.jm-dial').evaluate(n=>n.classList.contains('fun')),true);
  // 贴图：抽屉里点一个就发，贴图不带气泡
  await page.click('#jm-sticker-btn');
  await page.locator('.jm-sticker').first().click();
  await page.waitForTimeout(200);
  assert.equal(calls.filter(c=>c.path==='/api/chat').at(-1).body.sticker,'cho_peace');
  assert.equal(await page.locator('#jm-stickers').isHidden(),true);
  assert.ok(await page.locator('.jm-row.me .jm-stamp').count()>=1);
  await noOverflow(page);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 {
  // 旧对话：只读浏览，没有输入框；回到主聊天
  const {page,errors}=await open({});
  await page.click('#jm-more');await page.click('#jm-archives');
  await page.locator('.jm-archive-row',{hasText:'Emma'}).click();
  await page.waitForSelector('#jm-archive-bar:not([hidden])');
  assert.equal(await page.locator('#jine-composer').isHidden(),true);
  assert.match(await page.locator('#jine-messages').innerText(),/Hi Emma/);
  await page.click('#jm-archive-back');
  await page.waitForSelector('#jine-composer:not([hidden])');
  // 单词本「回到原句」：主聊天里的和旧对话里的都能跳到
  assert.equal(await page.evaluate(()=>LP.jine.openMessage(30,105)),true);
  assert.equal(await page.evaluate(()=>LP.jine.openMessage(12,202)),true);
  assert.equal(await page.locator('#jm-archive-bar').isHidden(),false);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 {
  // 朗读：她的消息念出来并交给角色窗口对口型；别的角色的朗读不对口型；移上按钮先预热，再点一次停
  const {page,errors}=await open({});
  const rate=8000,n=rate*0.6,wav=Buffer.alloc(44+n*2);
  wav.write('RIFF',0);wav.writeUInt32LE(36+n*2,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);
  wav.writeUInt32LE(rate,24);wav.writeUInt32LE(rate*2,28);wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(n*2,40);
  for(let i=0;i<n;i++)wav.writeInt16LE(Math.round(8000*Math.sin(i/rate*2*Math.PI*220)),44+i*2);
  const spoken=[];
  await page.route('**/api/chat/messages/*/speech',r=>{spoken.push(r.request().url());return r.fulfill({contentType:'audio/wav',body:wav});});
  await page.route('**/api/chat/messages/*/speech/warm',r=>{spoken.push(r.request().url());return r.fulfill({status:202,json:{ok:true}});});
  await page.evaluate(()=>{window.__voices=[];const orig=LP.stage.voice;LP.stage.voice=(a)=>{window.__voices.push(a.dataset.voice);return orig(a);};});
  const hers=page.locator('#jine-messages .jm-row:not(.me)[data-speaker="p1"]').filter({has:page.locator('[data-action="speak"]')}).last();
  await hers.hover();
  const btn=hers.locator('[data-action="speak"]');
  await btn.hover();
  await page.waitForTimeout(150);
  assert.ok(spoken.some(u=>u.endsWith('/speech/warm')),'hovering 朗读 warms the voice');
  await btn.click();
  await page.waitForFunction(b=>b.textContent==='停',await btn.elementHandle());
  assert.ok(spoken.some(u=>u.endsWith('/speech')));
  assert.deepEqual(await page.evaluate(()=>window.__voices),['stage']);
  await page.waitForFunction(b=>b.textContent==='朗读',await btn.elementHandle(),{timeout:4000});   // 念完自己复原
  await btn.click();await page.waitForFunction(b=>b.textContent==='停',await btn.elementHandle());
  await btn.click();assert.equal(await btn.innerText(),'朗读');                                      // 再点一次就停
  // 别的角色（Emma）的消息：念，但不对口型
  await page.fill('#jine-input','もう一回言って');await page.press('#jine-input','Enter');await page.waitForSelector('#msg-902');
  await page.locator('#msg-902').hover();
  await page.locator('#msg-902 [data-action="speak"]').click();
  await page.waitForFunction(()=>window.__voices.length===3);
  assert.equal(await page.evaluate(()=>window.__voices.at(-1)),'off');
  assert.deepEqual(errors,[]);
  await page.close();
 }
 {
  // 只有主人设：顶栏没有副人设头像
  const {page,errors}=await open({solo:true});
  assert.equal(await page.locator('.jm-guest').count(),0);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log('PASS main chat: no contact list, grouped rows, bubble width cap, read marks, lead + chime speakers, naming a guest (to), dial and dice PUTs, sticker send, archives read-only, jump to sentence in main and archive, read aloud (warm, play, stop; only her own voice goes to the character window), solo topbar, 390–1100 widths.');
} finally { await browser.close(); }
