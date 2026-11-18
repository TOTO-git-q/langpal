import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
// Set LANGPAL_PLAYWRIGHT_MODULE to an existing Playwright module URL if not installed locally.
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH || undefined,headless:true});
try {
 const page=await browser.newPage(); const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.setContent('<main id="notebook"></main>');
 await page.evaluate(()=>{
  window.pending=[];window.deletes=[];window.toasts=[];window.undos=[];
  const request=(kind,lang)=>new Promise((resolve,reject)=>pending.push({kind,lang,resolve,reject}));
  window.LP={preferences:{get:()=>''},languages:{list:()=>[{tag:'en'},{tag:'de'}]},toast:x=>toasts.push(x),
   // 撤销删除：记下回调，测试里手动撤销或提交
   appShell:{undoable:(msg,h)=>{h.remove();undos.push({msg,...h});},switchTab:t=>{window.switched=t;}},
   api:{
   getVocab:lang=>request('vocab',lang),getPatterns:lang=>request('pattern',lang),
   deleteVocab:id=>new Promise(resolve=>deletes.push({id,resolve})),deletePattern:id=>new Promise(resolve=>deletes.push({id,resolve}))
  }};
 });
 await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});
 await page.addScriptTag({path:path.join(root,'frontend/js/notebook.js')});
 await page.evaluate(()=>LP.notebook.mount(document.querySelector('main')));
 // 加载时是和卡片同形的占位，不写「加载中」
 assert.equal(await page.locator('.nb-skeleton').count(),3);
 await page.click('[data-tab="pattern"]');
 await page.evaluate(()=>pending[1].resolve({items:[{id:2,pattern_name:'Latest pattern',language:'en'}]}));
 await page.waitForFunction(()=>document.querySelector('.nb-word')?.textContent==='Latest pattern');
 await page.evaluate(()=>pending[0].resolve({items:[{id:1,lemma:'STALE WORD',language:'en'}]}));
 assert.equal(await page.locator('.nb-word').innerText(),'Latest pattern');
 assert.equal(await page.locator('#nb-count').innerText(),'1 条');
 await page.click('[data-lang="en"]'); await page.click('[data-lang="de"]');
 await page.evaluate(()=>{pending[3].resolve({items:[{id:3,pattern_name:'German only',language:'de'},{id:4,pattern_name:'Zweite',language:'de'}]});pending[2].reject(new Error('stale failure'));});
 await page.waitForFunction(()=>document.querySelector('.nb-word')?.textContent==='German only');
 assert.deepEqual(await page.evaluate(()=>toasts),[]);
 // 搜索
 await page.fill('#nb-search','zwei');
 assert.equal(await page.locator('#nb-count').innerText(),'1 条');
 await page.fill('#nb-search','');
 // 删除在行内「⋯」里；先拿掉，撤销能放回原位，提交才真的删
 await page.locator('.nb-card').first().locator('summary').click();
 await page.locator('.nb-card').first().locator('.nb-del').click();
 assert.equal(await page.locator('.nb-card').count(),1);
 assert.equal(await page.evaluate(()=>deletes.length),0);
 await page.evaluate(()=>undos[0].restore());
 assert.equal(await page.locator('.nb-word').first().innerText(),'German only');
 await page.locator('.nb-card').first().locator('summary').click();
 await page.locator('.nb-card').first().locator('.nb-del').click();
 await page.evaluate(()=>{void undos[1].commit();});
 assert.equal(await page.evaluate(()=>deletes.length),1);
 await page.evaluate(()=>deletes[0].resolve({ok:true}));
 assert.equal(await page.locator('#nb-count').innerText(),'1 条');
 await page.click('[data-lang="en"]');
 await page.evaluate(()=>pending[4].reject(new Error('offline')));
 await page.waitForFunction(()=>document.querySelector('#nb-count').textContent==='没加载出来');
 assert.equal(await page.locator('#nb-grid').getAttribute('aria-busy'),null);
 await page.click('[data-lang="de"]');
 await page.evaluate(()=>{LP.notebook.mount(document.querySelector('main'));pending[5].resolve({items:[{id:5,pattern_name:'STALE MOUNT'}]});pending[6].resolve({items:[]});});
 await page.waitForFunction(()=>document.querySelector('#nb-count').textContent==='0 条');
 assert.equal(await page.locator('[data-tab="pattern"]').getAttribute('aria-pressed'),'true');
 assert.equal(await page.locator('.nb-card').count(),0);
 // 空状态：一个图标 + 一个动作
 await page.click('[data-go-chat]');
 assert.equal(await page.evaluate(()=>window.switched),'talk');
 assert.deepEqual(errors,[]);
 console.log('PASS: reversed responses, language races, stale error suppression, search, undoable delete, failure state, remount fencing, empty action');
} finally {await browser.close();}
