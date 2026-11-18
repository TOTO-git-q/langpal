// 错题本只回看：展开看题目、证据、你选的、正确答案、讲解；听力能听原句。练习走「开始复习」，这里不作答、不发写请求。
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root=process.env.LANGPAL_TEST_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH || undefined, headless:true});
try {
 const page=await browser.newPage({viewport:{width:900,height:600}});
 const errors=[]; page.on('pageerror', e=>errors.push(String(e)));
 await page.setContent('<main></main>');
 for (const name of ['windose','apps','review']) await page.addStyleTag({path:path.join(root,`frontend/css/${name}.css`)});
 await page.evaluate(()=>{
  window.calls=[]; window.opened=null;
  const reading={question:'What did Maya do?',options:['She left.','She stayed.','She slept.'],selected:0,answer:1,title:'Reading example',language:'en',paragraph:'Maya stayed until noon.',explanation:'READING EXPLANATION',updated_at:'2026-11-10T09:00:00Z',source_url:'https://example.org/a'};
  const listening={prompt:'Where is the train?',choices:['At platform one.','At platform two.'],selection:0,answer:1,title:'Listening example',language:'en',practice_id:'fixture',evidence:[{line:2,speaker:'A',text:'It leaves from platform two.'}],clips:[{start:0,end:1},{start:1.2,end:2.5}],explanation:'LISTENING EXPLANATION',updated_at:'2026-11-09T09:00:00Z'};
  window.LP={preferences:{get:()=>''},languages:{list:()=>[{tag:'en',label:'English'}]},learning:{openReview:(o)=>{window.opened=o;}}};
  window.fetch=async(url,options)=>{calls.push({url:String(url),method:options?.method||'GET'});return {ok:true,json:async()=>({items:[String(url).includes('/reader/')?reading:listening]})};};
 });
 await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});
 await page.addScriptTag({path:path.join(root,'frontend/js/review.js')});
 await page.evaluate(()=>LP.review.mount(document.querySelector('main')));
 await page.waitForSelector('.rv-entry');
 const reading=page.locator('.rv-entry').filter({hasText:'Reading example'}), listening=page.locator('.rv-entry').filter({hasText:'Listening example'});
 // 时间按本机显示，不出现 UTC
 assert.doesNotMatch(await page.locator('.rv-items').innerText(),/UTC/);
 await reading.locator(':scope > summary').click();
 assert.equal(await reading.locator('.rv-evidence').innerText(),'Maya stayed until noon.');
 assert.ok((await reading.locator('.rv-option.right').innerText()).includes('She stayed.'));
 assert.ok((await reading.locator('.rv-option.wrong').innerText()).includes('She left.'));
 assert.equal(await reading.locator('.rv-explain').innerText(),'READING EXPLANATION');
 // 回看里没有作答控件
 assert.equal(await reading.locator('input, textarea, button[type=submit]').count(),0);
 await listening.locator(':scope > summary').click();
 assert.equal(await listening.locator('.rv-line-play').count(),1);
 assert.ok((await listening.locator('.rv-option.right').innerText()).includes('At platform two.'));
 assert.equal(await listening.locator('audio').getAttribute('src'),'/api/listening/errors/fixture/audio');
 // 练习交给统一复习会话
 await page.locator('[data-kind="reading"]').click();
 await page.waitForSelector('.rv-entry');
 await page.locator('[data-start-review]').click();
 assert.deepEqual(await page.evaluate(()=>window.opened),{kinds:['reading_q']});
 assert.equal(await page.evaluate(()=>calls.some(c=>c.method!=='GET'||/review\/(attempt|state|capabilities)/.test(c.url))),false);
 assert.deepEqual(errors,[]);
 console.log('PASS: mistake notebook is look-back only; practice goes through the review session');
} finally { await browser.close(); }
