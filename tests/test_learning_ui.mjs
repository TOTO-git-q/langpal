// Offline regression for the learning side (docs/LEARNING.md): 今天, the review session keyboard flow, peeking vs answering,
// the three listening stages (no text while listening blind, causes before results), and collecting looked-up words after reading.
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

async function open(mockOptions={}){
 const page=await browser.newPage({viewport:{width:1100,height:760}});page.setDefaultTimeout(8000);
 const errors=[],calls=[];page.on('pageerror',e=>errors.push(String(e)));
 const {handle}=createMock(mockOptions);
 await page.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());
  assert.equal(u.hostname,'learn.test','External requests forbidden: '+req.url());
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
 await page.goto('http://learn.test/');
 await page.waitForSelector('#jine-messages .jm-row');
 return {page,errors,calls};
}
const tab=(page,t)=>page.evaluate(t=>LP.appShell.switchTab(t),t);

try {
 // 1. 学习先落在「今天」；复习 → 输入 → 输出；不出现时间
 {
  const {page,errors}=await open({});
  await tab(page,'study');
  await page.waitForSelector('.lt-step');
  assert.deepEqual(await page.locator('.lt-step').evaluateAll(xs=>xs.map(x=>x.dataset.kind)),['review','listening','reading','output']);
  assert.doesNotMatch(await page.locator('.lt-steps').innerText(),/\d+:\d\d|分钟|连续|上课/);   // 上课是单独一行，不在「输出」格里
  // 难度建议：小箭头，点开才有依据
  assert.equal(await page.locator('.lt-advice-pop').first().isVisible(),false);
  // 做完的块（mock 里阅读做完了）不挂箭头；没做的点开有建议和依据
  assert.equal(await page.locator('.lt-kind-reading .lt-advice').count(),0);
  await page.locator('.lt-kind-listening .lt-advice > summary').click();
  assert.ok((await page.locator('.lt-kind-listening .lt-advice-pop').innerText()).trim().length>0);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 2. 复习会话：空格翻面、1–4 评分；作答卡数字键选、回车下一张；打字卡；偷看 = peeked
 {
  const {page,errors,calls}=await open({});
  await tab(page,'revise');
  await page.waitForSelector('.rv2-vocab');
  assert.equal(await page.locator('.rv2-rate').count(),0);
  await page.keyboard.press(' ');
  await page.waitForSelector('.rv2-rate');
  assert.deepEqual(await page.locator('.rv2-rate').allInnerTexts().then(xs=>xs.map(x=>x.replace(/\s+/g,' ').trim())),['1 10 分钟','2 1 天','3 4 天','4 9 天']);
  assert.deepEqual(calls.find(c=>c.path==='/api/review/cards/1/reveal').body,{});
  await page.keyboard.press('3');
  await page.waitForSelector('.rv2-reading_q');
  assert.equal(calls.find(c=>c.path==='/api/review/cards/1/grade').body.rating,3);
  // 作答卡：按 2 选第二项，服务端判对错；回车下一张
  await page.keyboard.press('2');
  await page.waitForSelector('.rv2-verdict.ok');
  assert.deepEqual(calls.find(c=>c.path==='/api/review/cards/2/reveal').body,{answer:1});
  await page.keyboard.press('Enter');
  await page.waitForSelector('.rv2-type');
  assert.equal('rating' in calls.find(c=>c.path==='/api/review/cards/2/grade').body,false);
  // 打字卡：写假名也算对
  await page.fill('.rv2-type','しんぞう');
  await page.press('.rv2-type','Enter');
  await page.waitForSelector('.rv2-verdict.ok');
  await page.keyboard.press('Enter');
  // 听力卡：不作答直接看答案 = 偷看（reveal 不带答案）
  await page.waitForSelector('.rv2-listening_q');
  assert.equal(await page.locator('.rv2-play').count()>=1,true);
  await page.locator('.rv2-giveup').click();
  await page.waitForSelector('.rv2-verdict.bad');
  assert.deepEqual(calls.find(c=>c.path==='/api/review/cards/4/reveal').body,{});
  await page.keyboard.press('Enter');
  // 句型卡：「想不起来」= gave_up，只能评 1
  await page.waitForSelector('.rv2-pattern');
  await page.locator('.rv2-giveup').click();
  await page.waitForSelector('.rv2-rate');
  assert.deepEqual(calls.find(c=>c.path==='/api/review/cards/5/reveal').body,{gave_up:true});
  assert.equal(await page.locator('.rv2-rate.r3').isDisabled(),true);
  await page.keyboard.press('1');
  await page.waitForSelector('.rv2-end');
  assert.ok(calls.some(c=>c.path==='/api/review/session/end'));
  assert.match(await page.locator('.rv2-end').innerText(),/5[\s\S]*张/);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 3. 听力三段：盲听不出现文字；交卷后先标错因，点完才出对错和精听
 {
  const {page,errors,calls}=await open({});
  await tab(page,'listening');
  await page.waitForSelector('.lp-listening-setup button[type=submit]:not([disabled])');
  await page.evaluate(()=>{document.querySelector('.lp-listening-setup button[type=submit]').dataset.resume='';}); await page.click('.lp-listening-setup button[type=submit]');
  await page.waitForSelector('.lp-big-play');
  const blindText=await page.locator('.lp-listening-player').innerText();
  assert.doesNotMatch(blindText,/library|Excuse/i);
  assert.equal(await page.locator('[data-listen="preview"]').isVisible(),false);
  await page.evaluate(()=>document.querySelector('.lp-listening-player audio').dispatchEvent(new Event('ended')));
  await page.evaluate(()=>document.querySelector('[data-listen="questions"]').click());
  await page.waitForSelector('.lp-listening-questions fieldset');
  await page.locator('.lp-listening-questions fieldset').nth(0).locator('input').nth(1).check();
  await page.locator('.lp-listening-questions fieldset').nth(1).locator('input').nth(0).check();
  await page.click('.lp-listening-questions button[type=submit]');
  await page.waitForSelector('.lp-causes');
  assert.doesNotMatch(await page.locator('.lp-listening-review').innerText(),/Bring your student card/);
  assert.equal(await page.locator('.lp-listening-review .lp-answer').count(),0);
  await page.locator('.lp-cause[data-cause="not_heard"]').click();
  await page.waitForSelector('.lp-line');
  assert.deepEqual(calls.find(c=>c.path.endsWith('/causes')).body,{items:[{index:1,cause:'not_heard'}]});
  assert.ok(await page.locator('.lp-listening-review .lp-answer').count()>0);   // 对的选项直接写出来（✓ 加选项原文）
  // 精听：文字默认盖住，点一句显示一句；听写逐词标
  const first=page.locator('.lp-line-text').first();
  assert.equal(await first.evaluate(n=>getComputedStyle(n).color==='rgba(0, 0, 0, 0)'),true);
  await first.click();
  assert.equal(await first.evaluate(n=>n.classList.contains('shown')),true);
  await page.locator('.lp-line.dictation input').first().fill('The library close early Fridays');
  await page.locator('.lp-line.dictation button[type=submit]').first().click();
  await page.waitForSelector('.lp-word.missing');
  assert.equal(await page.locator('.lp-word.wrong').count(),1);
  // 逐句：每段对白列出它的几句，听写对着单句
  assert.equal(await page.locator('.lp-turn').nth(1).locator('.lp-line').count(),2);
  assert.deepEqual(calls.filter(c=>c.path.endsWith('/dictation')).at(-1).body,{line:2,sentence:1,text:'The library close early Fridays'});
  assert.match(await page.locator('.lp-line.dictation audio').first().getAttribute('src'),/lines\/2\/audio\?sentence=1$/);
  // 随心记三段都在
  assert.equal(await page.locator('#lp-listening-notes').isVisible(),true); // 练习中随心记常驻右侧
  assert.deepEqual(errors,[]);
  await page.close();
 }
 // 4. 阅读：打开文章记遇见；文末「这篇查过的词」多选收进复习
 {
  const {page,errors,calls}=await open({});
  await tab(page,'reading');
  await page.waitForTimeout(400);
  await page.locator('.rd-read').first().click();
  await page.waitForSelector('.rd-end');
  assert.ok(calls.some(c=>c.path==='/api/learning/encounters'));
  await page.click('.rd-lookups > summary');
  await page.waitForSelector('.rd-lookup');
  assert.equal(await page.locator('.rd-lookup.saved input').isDisabled(),true);
  await page.locator('.rd-lookup',{hasText:'milestone'}).locator('input').check();
  await page.locator('.rd-lookups').getByRole('button',{name:'收藏',exact:true}).click();
  await page.waitForSelector('.rd-lookup.saved >> text=milestone');
  const saved=calls.filter(c=>c.method==='POST'&&c.path==='/api/vocab');
  assert.equal(saved.length,1);
  assert.equal(saved[0].body.source_kind,'reading');
  assert.match(saved[0].body.context_sentence,/milestone/);
  assert.deepEqual(errors,[]);
  await page.close();
 }
 console.log('PASS learning: today order + no clock + advice on demand, review keyboard flow (space/1-4/digit/enter), peek vs answer vs gave_up, typed card, end screen + session end, listening blind (no text) → causes before results → covered lines + dictation, reading encounters + looked-up words to review.');
} finally { await browser.close(); }
