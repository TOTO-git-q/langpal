// Isolated Chrome + simulated SQLite API. Never contacts the running LangPal service.
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root = process.env.LANGPAL_SOURCE_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const adapter = process.env.LANGPAL_STORAGE_JS || path.join(root, 'frontend/js/study-storage.js');
const reading = process.env.LANGPAL_READING_JS || path.join(root, 'frontend/js/reading.js');
const browser = await chromium.launch({executablePath: process.env.LANGPAL_CHROME_PATH || undefined, headless: true});
try {
 const page = await browser.newPage(); const errors = [];
 page.on('pageerror', error => errors.push(String(error)));
 const validDraft = d => d && typeof d === 'object' && !Array.isArray(d)
  && Number.isInteger(d.phase ?? 0) && (d.phase ?? 0) >= 0 && (d.phase ?? 0) <= 4
  && typeof (d.time ?? 0) === 'number' && Number.isFinite(d.time ?? 0) && (d.time ?? 0) >= 0
  && (d.answers === undefined || (typeof d.answers === 'object' && d.answers !== null));
 const records = new Map(), notes = new Map(); let noteText = {text:'',revision:0}, drafts = new Map(), fail = false, imports = 0;
 await page.route('http://storage.test/**', async route => {
  const req = route.request(), url = new URL(req.url()), p = url.pathname;
  const send = (data, status=200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(data)});
  if (!p.startsWith('/api/')) return route.fulfill({contentType:'text/html',body:'<main id="reading-root"></main>'});
  if (p === '/api/reader/options') return send({sources:[],formats:[],defaults:{}});
  if (p === '/api/study-storage/capabilities') return send(fail ? {} : {version:1,writable:true}, fail ? 404 : 200);
  if (p.endsWith('/documents')) return send({documents:[...records.values()]});
  if (p.endsWith('/document') && req.method() === 'GET') return records.has(url.searchParams.get('id')) ? send(records.get(url.searchParams.get('id'))) : send({},404);
  if (p.endsWith('/document') && req.method() === 'POST') {
   const form = await new Response(req.postDataBuffer(), {headers:{'Content-Type':req.headers()['content-type']}}).formData();
   const metadata = JSON.parse(form.get('metadata')), revision = Number(form.get('revision')), importing=form.get('importOnly')==='true';
   const old=records.get(metadata.id); if(importing) imports++;
   if(old && importing) return send({...old,imported:false,conflict:JSON.stringify(old.metadata)!==JSON.stringify(metadata)});
   if(revision!==(old?.revision||0)) return send({detail:'Conflict; not saved'},409);
   const row={metadata,revision:revision+1,hasFile:!!form.get('file')||!!old?.hasFile}; records.set(metadata.id,row); return send(row);
  }
  if(p.endsWith('/document/file')) return route.fulfill({contentType:'application/pdf',body:Buffer.from('%PDF-test')});
  if(p.endsWith('/annotations')) return send({annotations:[...(notes.get(url.searchParams.get('documentId'))?.values()||[])]});
  if(p.endsWith('/annotation') && req.method()==='DELETE') {
   const group=notes.get(url.searchParams.get('documentId')), id=url.searchParams.get('id');
   assert.equal(Number(url.searchParams.get('revision')),group.get(id).revision);
   group.delete(id);return send({id,deleted:true});
  }
  if(p.endsWith('/annotation')) {const b=req.postDataJSON(); const group=notes.get(b.documentId)||new Map();notes.set(b.documentId,group);const old=group.get(b.annotation.id);if(old&&b.importOnly)return send({...old,conflict:false});if((old?.revision||0)!==b.revision)return send({},409);const n={...b.annotation,revision:b.revision+1};group.set(n.id,n);return send(n);}
  if(p.endsWith('/listening-notes')) {if(req.method()==='GET')return send(noteText);const b=req.postDataJSON();if(b.importOnly&&noteText.revision)return send({...noteText,conflict:noteText.text!==b.text});noteText={text:b.text,revision:noteText.revision+1};return send(noteText);}
  if(p.endsWith('/listening-draft')) {const b=req.method()==='GET'?{id:url.searchParams.get('id')}:req.postDataJSON();if(req.method()==='GET')return send(drafts.get(b.id)||{id:b.id,draft:null,revision:0});
   // Same rules as backend/app/services/study_storage.py state_data('listening-draft') — kept inline so the test needs no Python env.
   if(!validDraft(b.draft)) return send({detail:'Invalid draft'},422);
   const row={id:b.id,draft:b.draft,revision:1};drafts.set(b.id,row);return send(row);}
  if(p.endsWith('/export')) return route.fulfill({contentType:'application/zip',body:'zip-backup'});
  if(p.endsWith('/restore')) return send({restored:1,conflicts:1});
  return send({detail:'Unexpected request '+p},500);
 });
 await page.goto('http://storage.test/');
 await page.evaluate(async()=>{
  await new Promise((resolve,reject)=>{const r=indexedDB.open('jine-reader',1);r.onupgradeneeded=()=>{r.result.createObjectStore('documents',{keyPath:'id'});r.result.createObjectStore('notes',{keyPath:'id'});};r.onsuccess=()=>{const db=r.result,tx=db.transaction(['documents','notes'],'readwrite');tx.objectStore('documents').put({id:'https://example.org/a?b=1#文',title:'Legacy text',text:'A sentence. Another sentence.',page:1,lang:'en'});tx.objectStore('documents').put({id:'pdf',title:'PDF',blob:new Blob(['%PDF-test'],{type:'application/pdf'}),lang:'en'});tx.objectStore('notes').put({id:'https://example.org/a?b=1#文',items:[{id:'old-note',text:'Prior annotation',page:1,rect:{x:1,y:2}}]});tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);};});
  localStorage.setItem('jine.listening.notes','Original note');localStorage.setItem('jine.listening.drafts.v1',JSON.stringify({p:{selections:[['question-0','1']],time:12,phase:'questions'}}));
 });
 const load = async()=>{await page.addScriptTag({path:adapter});await page.evaluate(()=>LP.studyStorage.ready());};
 await load(); assert.equal(imports,2);assert.equal(noteText.text,'Original note');assert.deepEqual(drafts.get('p').draft.answers,[['question-0','1']]);
 assert.equal(drafts.get('p').draft.phase,3);
 await page.evaluate(()=>{localStorage.removeItem('jine.study-storage.import.v1');localStorage.setItem('jine.listening.drafts.v1',JSON.stringify({missing:{selections:[['question-0','0']]},zero:{phase:0,time:0,answers:[]},named:{phase:'listen',time:1,answers:{'question-1':'0'}},badPhase:{phase:'unknown'},badAnswers:{phase:1,answers:'bad'},badTime:{phase:2,time:-1},afterInvalid:{phase:4,time:8,answers:[]}}));});
 await page.reload();await load();
 assert.equal(drafts.get('missing').draft.phase,0);assert.equal(drafts.get('zero').draft.phase,0);assert.equal(drafts.get('named').draft.phase,1);assert.equal(drafts.get('afterInvalid').draft.phase,4);
 assert.equal(drafts.has('badPhase'),false);assert.equal(drafts.has('badAnswers'),false);assert.equal(drafts.has('badTime'),false);
 assert.match(await page.evaluate(()=>LP.studyStorage.getStatus().message),/项旧记录没搬过来/);
 assert.match(await page.evaluate(()=>localStorage.getItem('jine.listening.drafts.v1')),/badAnswers/);
 const importedCount=imports;
 assert.equal(await page.evaluate(()=>localStorage.getItem('jine.listening.notes')),'Original note');
 assert.equal(await page.evaluate(async()=>{const d=await LP.studyStorage.getDocument('pdf');return d.blob.size;}),9);
 await page.evaluate(async()=>{const s=LP.studyStorage;const d=await s.getDocument('https://example.org/a?b=1#文');d.page=2;await s.saveDocument(d);await s.saveNote(d.id,{id:'new',text:'Saved note',page:2});});
 await page.reload();await load();assert.equal(imports,importedCount);
 assert.equal(await page.evaluate(async()=>(await LP.studyStorage.getDocument('https://example.org/a?b=1#文')).page),2);
 assert.equal(await page.evaluate(async()=>(await LP.studyStorage.getNotes('https://example.org/a?b=1#文')).length),2);
 // Mount the actual reader; saved notes survive a new document load and note edits.
 await page.evaluate(()=>{LP.preferences={get:()=>undefined};LP.languages={list:()=>[{tag:'en',label:'English'}],label:()=> 'English'};LP.languageDrawer={create:()=>({open(){}})};});
 await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});await page.addScriptTag({path:reading});await page.evaluate(()=>LP.reading.mount(document.querySelector('main')));
 await page.getByRole('button',{name:'书架',exact:true}).click();await page.getByRole('button',{name:'已读',exact:true}).click();await page.getByRole('button',{name:'继续读',exact:true}).first().waitFor();await page.getByRole('button',{name:'继续读',exact:true}).first().click();
 await page.waitForFunction(()=>document.querySelector('[data-rd="storage-status"]').dataset.unsaved==='false');
 await page.locator('.rd-more summary').click();await page.locator('[data-rd="notes"]').click();
 await page.getByText('Prior annotation',{exact:true}).waitFor();
 const note=page.locator('.rd-note').filter({has:page.getByText('Prior annotation',{exact:true})});
 await note.getByRole('button',{name:'删除',exact:true}).click();
 assert.equal(await page.locator('.confirm-title').innerText(),'删掉这条批注？');
 await page.locator('.confirm-cancel').click();
 assert.equal(await note.count(),1);
 await note.getByRole('button',{name:'删除',exact:true}).click();
 await page.locator('.confirm-danger').click();
 await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.rd-note')).some(n=>n.textContent.includes('Prior annotation')));
 assert.equal(notes.get('https://example.org/a?b=1#文').has('old-note'),false);
 // Simulate a concurrent writer. Do not overwrite with stale revision.
 const id='https://example.org/a?b=1#文';records.get(id).revision++;
 const conflict=await page.evaluate(async()=>{try{await LP.studyStorage.saveDocument({id:'https://example.org/a?b=1#文',title:'stale'});return false;}catch(e){return e.status===409;}});assert.equal(conflict,true);
 assert.equal(records.get(id).metadata.title,'Legacy text');
 assert.equal(await page.evaluate(async()=>(await LP.studyStorage.exportArchive()).size),10);
 assert.equal(await page.evaluate(async()=>(await LP.studyStorage.restoreArchive(new Blob(['archive']))).conflicts),1);
 records.get(id).metadata.title='Canonical edited title';
 await page.evaluate(()=>localStorage.removeItem('jine.study-storage.import.v1'));
 await page.reload();await load();
 assert.equal(await page.evaluate(()=>LP.studyStorage.getStatus().state),'warning');
 assert.equal(records.get(id).metadata.title,'Canonical edited title');
 assert.equal(await page.evaluate(()=>new Promise(resolve=>{const r=indexedDB.open('jine-reader');r.onsuccess=()=>{const db=r.result,tx=db.transaction('documents'),q=tx.objectStore('documents').get('https://example.org/a?b=1#文');q.onsuccess=()=>resolve(q.result.title);tx.oncomplete=()=>db.close();};})),'Legacy text');
 // Old service never starts writes or silently reverts to IndexedDB.
 await page.reload();fail=true;await page.addScriptTag({path:adapter});
 assert.equal(await page.evaluate(async()=>{try{await LP.studyStorage.ready();return false;}catch{return LP.studyStorage.getStatus().state==='unavailable';}}),true);
 assert.deepEqual(errors,[]);
 console.log('PASS: Chrome reader, migration, original backup, reload persistence, PDF bytes, notes, stale conflicts, old-service unavailable');
} finally {await browser.close();}
