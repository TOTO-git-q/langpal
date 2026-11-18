import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root=process.env.LANGPAL_TEST_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH || undefined,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1000,height:760}}), errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('http://localhost:8787/**',r=>r.fulfill({contentType:'text/html',body:'<main id="reading-root"></main>'}));
 await page.goto('http://localhost:8787/');
 await page.addStyleTag({path:path.join(root,'frontend/css/reading.css')});
 await page.evaluate(()=>{
  window.docs=[
   {id:'agent-txt',title:'Agent attachment TXT',source:'workspace-agent',libraryOrigin:'import'},
   {id:'agent-pdf',title:'Agent attachment PDF',source:'workspace-agent',libraryOrigin:'history',_hasFile:true},
   {id:'legacy-file',title:'Legacy file',source:'\u672c\u5730\u6587\u4ef6'},
   {id:'legacy-paste',title:'Legacy paste',scope:'\u7528\u6237\u7c98\u8d34\u6b63\u6587',url:'https://example.org/pasted'},
   {id:'legacy-paste-full',title:'Legacy full paste',scope:'\u7528\u6237\u7c98\u8d34\u5168\u6587'},
   {id:'explicit-import',title:'Explicit import',libraryOrigin:'import',source:'Other'},
   {id:'web',title:'Online article',url:'https://example.org/article'},
   {id:'zotero:key#pdf',title:'Opened Zotero PDF'},
   {id:'explicit-history',title:'Explicit history',libraryOrigin:'history',source:'\u672c\u5730\u6587\u4ef6'},
  ].map((d,i)=>({...d,text:'A short sample paragraph.',lang:'en',openedAt:i+1}));
  window.saves=[];
  window.LP={preferences:{get:()=>undefined,set:()=>{}},languages:{list:()=>[{tag:'en',label:'English'}]},languageDrawer:{create:()=>({open(){}})},
   studyStorage:{listDocuments:async()=>structuredClone(docs),getDocument:async id=>structuredClone(docs.find(d=>d.id===id)),getNotes:async()=>[],getStatus:()=>({state:'ready'}),
    saveDocument:async d=>{saves.push(structuredClone(d));const i=docs.findIndex(x=>x.id===d.id);if(i<0)docs.push(d);else docs[i]=d;}}};
  window.fetch=async url=>({ok:true,json:async()=>url.includes('/options')?{sources:[],formats:[],defaults:{}}:{items:[]}});
 });
 await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});
 await page.addScriptTag({path:path.join(root,'frontend/js/reading.js')});
 await page.evaluate(()=>LP.reading.mount(document.querySelector('main')));
 const rows=page.locator('.rd-file');
 await page.waitForFunction(()=>document.querySelector('.rd-file-list')?.textContent.includes('Legacy file'));
 const list=page.locator('[data-rd="list"]');
 // Count labels via the catalog list, not the preview which repeats selected titles.
 const listText=()=>page.evaluate(()=>document.querySelector('.rd-catalog-index').textContent);
 assert.match(await listText(),/Legacy file/);assert.match(await listText(),/Legacy paste/);assert.match(await listText(),/Legacy full paste/);assert.match(await listText(),/Explicit import/);assert.doesNotMatch(await listText(),/Online article|Opened Zotero|Explicit history|Agent attachment/);
 await page.locator('[data-shelf="history"]').click();
 await page.waitForFunction(()=>document.querySelector('.rd-catalog-index').textContent.includes('Online article'));
 assert.match(await listText(),/Opened Zotero PDF/);assert.match(await listText(),/Explicit history/);assert.doesNotMatch(await listText(),/Legacy file|Legacy paste|Explicit import|Agent attachment/);
 assert.equal(await page.locator('.rd-library-hint').count(),0);
 await page.locator('[data-shelf="import"]').click();
 await page.waitForFunction(()=>document.querySelector('.rd-catalog-index').textContent.includes('Legacy file'));
 await page.getByRole('button',{name:'\u7ee7\u7eed\u8bfb',exact:true}).click();
 await page.waitForFunction(()=>saves.length>0);
 assert.equal(await page.evaluate(()=>saves.at(-1).libraryOrigin),'import');
 await page.locator('[data-rd="back"]').click();
 await page.locator('[data-shelf="history"]').click();
 await page.waitForFunction(()=>document.querySelector('.rd-catalog-index').textContent.includes('Online article'));
 assert.doesNotMatch(await listText(),/Explicit import/);
 await page.locator('[data-rd="file"]').setInputFiles({name:'Fresh.txt',mimeType:'text/plain',buffer:Buffer.from('New imported paragraph.')});
 await page.waitForFunction(()=>saves.some(d=>d.title==='Fresh.txt'));
 assert.equal(await page.evaluate(()=>saves.find(d=>d.title==='Fresh.txt').libraryOrigin),'import');
 await page.locator('[data-rd="back"]').click();
 assert.equal(await page.getByRole('button',{name:'Zotero',exact:true}).count(),1);
 await page.locator('[data-shelf="history"]').click();
 await page.waitForFunction(()=>document.querySelector('.rd-catalog-index').textContent.includes('Online article'));
 await page.getByRole('button',{name:'\u7ee7\u7eed\u8bfb',exact:true}).click();
 await page.waitForFunction(()=>saves.at(-1)?.libraryOrigin==='history');
 await page.locator('[data-rd="back"]').click();
 if(process.env.LANGPAL_SCREENSHOT_DIR) {
  await page.screenshot({path:path.join(process.env.LANGPAL_SCREENSHOT_DIR,'history-desktop.png')});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(process.env.LANGPAL_SCREENSHOT_DIR,'history-mobile.png')});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 assert.equal(await page.evaluate(()=>saves.some(d=>d.source==='workspace-agent')),false);
 assert.equal(await page.evaluate(()=>docs.filter(d=>d.source==='workspace-agent').length),2);
 assert.deepEqual(errors,[]);
 console.log('PASS: imported/history partition, legacy sources, explicit origin precedence, reopen persistence, new file import, Zotero shelf, no runtime errors.');
} finally {await browser.close();}
