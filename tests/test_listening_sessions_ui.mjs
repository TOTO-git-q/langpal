// Real Chromium, isolated in-memory HTTP mocks. No live app/provider writes.
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const js=process.env.LANGPAL_LISTENING_JS||path.join(root,'frontend/js/listening.js');
const adapter=process.env.LANGPAL_STUDY_STORAGE_JS||path.join(root,'frontend/js/study-storage.js');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true});
try {
 const page=await browser.newPage({viewport:{width:390,height:844}}), errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 page.on('dialog',dialog=>dialog.accept());
 let notes={text:'',revision:0}, drafts=new Map(), posts=0, failNotes=false, conflictNotes=false, delayRead, oldServer=false;
 const item={id:'saved',language:'en',format:'Test',count:1,status:'ready',created_at:'2026-11-10T12:00:00Z'};
 let graded=false;
 const receipt={score:1,count:1,title:'First result',results:[],script:[{speaker:'A',text:'Secret transcript'}]};
 await page.route('http://listening.test/**',async route=>{
  const request=route.request(), url=new URL(request.url()), method=request.method();
  const respond=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  if(!url.pathname.startsWith('/api/'))return route.fulfill({contentType:'text/html',body:'<main id="root"></main>'});
  if(url.pathname.endsWith('/capabilities'))return oldServer?respond({detail:'Not available'},404):respond({version:1,writable:true});
  if(url.pathname.endsWith('/listening-notes')) {
   if(method==='GET'){if(delayRead)await delayRead; return respond(notes);}
   const body=request.postDataJSON();
   if(failNotes)return respond({detail:'Offline'},503);
   if(conflictNotes&&!body.importOnly)return respond({detail:'Stale revision'},409);
   if(body.importOnly&&notes.revision)return respond({...notes,imported:false,conflict:notes.text!==body.text});
   if(body.revision!==notes.revision)return respond({detail:'Stale revision'},409);
   notes={text:body.text,revision:notes.revision+1};return respond(notes);
  }
  if(url.pathname.endsWith('/listening-draft')){
   if(method==='GET'){const id=url.searchParams.get('id');return respond(drafts.get(id)||{id,draft:null,revision:0});}
   const body=request.postDataJSON(),old=drafts.get(body.id)||{revision:0};
   if(body.importOnly&&old.revision)return respond({...old,imported:false,conflict:false});
   if(body.revision!==old.revision)return respond({detail:'Stale revision'},409);
   const saved={id:body.id,draft:body.draft,revision:old.revision+1};drafts.set(body.id,saved);return respond(saved);
  }
  if(url.pathname.endsWith('/options'))return respond({synthesis:{en:true,ja:true},capabilities:{listening_sessions:!oldServer},formats:[]});
  if(url.pathname.endsWith('/practices'))return respond({items:[item]});
  if(url.pathname.endsWith('/practice/saved'))return respond({...item,receipt:graded?receipt:null});
  if(url.pathname.endsWith('/questions'))return respond({questions:[{prompt:'Question?',choices:['A','B']}]});
  if(url.pathname.endsWith('/grade')){graded=true;return respond(receipt);}
  if(url.pathname.endsWith('/practice')){posts++;return respond({detail:'Storage full; no data deleted'},507);}
  if(url.pathname.endsWith('/audio'))return route.fulfill({status:404});
  if(url.pathname.endsWith('/lines'))return respond({lines:[],dictation:[]});
  if(url.pathname.endsWith('/shape'))return respond({segments:[],duration:0}); // 老练习没有时间轴：退化成普通进度条
  if(url.pathname.endsWith('/play'))return respond({plays:1,replays:0});
  if(url.pathname.endsWith('/causes'))return respond({items:[]});
  if(url.pathname==='/api/learning/settings')return respond({types:{listening:{detail:'细节'}}});
  if(url.pathname==='/api/learning/stats'||url.pathname==='/api/learning/advice')return respond({language:url.searchParams.get('language')});
  throw Error('Unexpected request '+url.pathname);
 });
 await page.goto('http://listening.test/');
 await page.evaluate(()=>{
  localStorage.setItem('jine.listening.notes','legacy shared note');
  localStorage.setItem('jine.listening.drafts.v1',JSON.stringify({saved:{phase:3,selections:[['question-0','1']],time:12,updated:1}}));
 });
 const mount=async()=>{
  await page.evaluate(()=>window.LP={preferences:{get:()=> 'en'},languages:{list:()=>[{tag:'en',label:'English'},{tag:'ja',label:'日本語'}]}});
  await page.addStyleTag({path:path.join(root,'frontend/css/windose.css')});
 await page.addStyleTag({path:path.join(root,'frontend/css/listening.css')});
  await page.addScriptTag({path:adapter});
  await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});
 await page.addScriptTag({path:js});
  await page.evaluate(()=>LP.listening.mount(document.querySelector('#root')));
  await page.waitForFunction(()=>!document.querySelector('.lp-listening-setup button[type=submit]').disabled);
 };
 await mount();
 await page.waitForFunction(()=>document.querySelector('#lp-listening-notes').value==='legacy shared note');
 assert.equal(posts,0);
 assert.equal(await page.locator('.lp-listening-intro, .listen-history-controls, [data-listen="preview"], [data-listen="cue"], [data-listen="recent-cards"]').count(),0);
 assert.equal(await page.locator('details.listen-manage [data-listen="manage-list"]').count(),1);
 {const shown=await page.locator('.lp-recent-row time').first().textContent();const local=await page.evaluate(()=>LP.util.shortDate('2026-11-10T12:00:00Z'));assert.ok(local&&shown.includes(local),shown);assert.doesNotMatch(shown,/UTC/);}
 await page.evaluate(()=>document.querySelector('[data-listen=notes-toggle]').click()); // 首页没有顶栏，随心记开关只在程序里用
 await page.locator('.lp-recent-row').first().click();
 await page.locator('input[value="1"]').waitFor();
 assert.equal(await page.locator('input[value="1"]').isChecked(),true);
 assert.equal((await page.locator('#root').innerText()).includes('Secret transcript'),false);
 await page.evaluate(()=>document.querySelector('audio').dispatchEvent(new Event('loadedmetadata')));
 assert.equal(await page.evaluate(()=>document.querySelector('audio').currentTime),12);
 await page.locator('input[value="0"]').check();
 if(await page.locator('.lp-listening-notes').isHidden())await page.evaluate(()=>document.querySelector('[data-listen=notes-toggle]').click()); // 首页没有顶栏，随心记开关只在程序里用
 await page.locator('#lp-listening-notes').fill('Database note');
 // 存上了不说话：状态回到 ready、文字是空的
 const saved=kind=>page.waitForFunction(k=>{const s=document.querySelector('[data-listen="'+k+'-storage-status"]');return s.dataset.state==='ready'&&s.textContent==='';},kind);
 await saved('notes');
 await saved('draft');
 assert.equal(notes.text,'Database note');assert.deepEqual(drafts.get('saved').draft.answers,[['question-0','0']]);
 assert.equal(await page.evaluate(()=>localStorage.getItem('jine.listening.notes')),'legacy shared note');
 assert.equal(await page.evaluate(()=>JSON.parse(localStorage.getItem('jine.listening.drafts.v1')).saved.selections[0][1]),'1');
 await page.reload();await mount();
 await page.waitForFunction(()=>document.querySelector('#lp-listening-notes').value==='Database note');
 await page.locator('.lp-recent-row').first().click();
 await page.locator('input[value="0"]').waitFor();assert.equal(await page.locator('input[value="0"]').isChecked(),true);
 await page.locator('[data-listen=new-practice]').click();
 await page.locator('.lp-more > summary').click();await page.locator('[data-listen=edit-plan]').click(); // 主题和难度在「⋯」里
 await page.locator('[data-listen="language"]').selectOption('ja');
 // 有没听完的时主按钮是「接着听」；要新的一段从「⋯」里点「听新的」
 await page.waitForFunction(()=>!document.querySelector('[data-listen="fresh"]').hidden);
 await page.locator('.lp-more > summary').click();await page.locator('[data-listen="fresh"]').click();
 await page.waitForFunction(()=>document.querySelector('.lp-listening-status').textContent.includes('Storage full'));
 assert.equal(await page.locator('input[value="0"]').isChecked(),true);
 if(await page.locator('.lp-listening-notes').isHidden())await page.evaluate(()=>document.querySelector('[data-listen=notes-toggle]').click()); // 首页没有顶栏，随心记开关只在程序里用
 failNotes=true;await page.locator('#lp-listening-notes').fill('Pending offline');
 await page.waitForFunction(()=>!document.querySelector('[data-listen="notes-retry"]').hidden);
 assert.equal(notes.text,'Database note');assert.equal(await page.locator('#lp-listening-notes').inputValue(),'Pending offline');
 failNotes=false;await page.locator('[data-listen="notes-retry"]').click();
 await saved('notes');
 assert.equal(notes.text,'Pending offline');
 conflictNotes=true;await page.locator('#lp-listening-notes').fill('Conflicting local edit');
 await page.waitForFunction(()=>!document.querySelector('[data-listen="notes-reload"]').hidden);
 assert.equal(await page.locator('#lp-listening-notes').inputValue(),'Conflicting local edit');assert.equal(notes.text,'Pending offline');
 conflictNotes=false;await page.locator('[data-listen="notes-reload"]').click();await page.locator('.confirm-danger').click(); // 「用另一版」先确认
 await page.waitForFunction(()=>document.querySelector('#lp-listening-notes').value==='Pending offline');
 await page.locator('.lp-listening-questions button').click();
 await page.waitForFunction(()=>!document.querySelector('.lp-listening-review').hidden);
 assert.equal(await page.locator('.lp-listening-status').innerText(),''); // 交卷后不放说明小字
 // Delayed initial read must not overwrite typing that happened after the request.
 let release;delayRead=new Promise(resolve=>release=resolve);
 await page.reload();await mount();
 if(await page.locator('.lp-listening-notes').isHidden())await page.evaluate(()=>document.querySelector('[data-listen=notes-toggle]').click()); // 首页没有顶栏，随心记开关只在程序里用
 await page.locator('#lp-listening-notes').fill('Typed while loading');release();delayRead=null;
 for(let i=0;i<80&&notes.text!=='Typed while loading';i++)await page.waitForTimeout(100); // 存上了界面不说话：看服务端收到没有
 await saved('notes');
 assert.equal(await page.locator('#lp-listening-notes').inputValue(),'Typed while loading');assert.equal(notes.text,'Typed while loading');
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 oldServer=true;await page.reload();await mount();
 await page.waitForFunction(()=>document.querySelector('[data-listen="notes-storage-status"]').textContent.includes('没连上'));
 assert.equal(await page.locator('#lp-listening-notes').inputValue(),'');
 assert.equal(await page.locator('[data-listen="resume"]').count(),0);
 if(await page.locator('.lp-listening-notes').isHidden())await page.evaluate(()=>document.querySelector('[data-listen=notes-toggle]').click()); // 首页没有顶栏，随心记开关只在程序里用
 await page.locator('#lp-listening-notes').fill('Page only');
 assert.equal(notes.text,'Typed while loading');
 assert.match(await page.locator('[data-listen="notes-storage-status"]').innerText(),/没连上/);
 assert.deepEqual(errors,[]);
 console.log('PASS: shared SQLite adapter, one-time legacy import, database-only writes, actual reload, answer/playback restore, failed generation preservation, network retry, CAS conflict, delayed-read edit protection, mobile order/date');
}finally{await browser.close();}
