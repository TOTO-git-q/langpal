// Offline control regressions for items 1–6, 8 and 9. APIs are intercepted.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createMock, personas} from './ui/mock-api.mjs';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true,args:['--mute-audio']});
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.ttf':'font/ttf'};

async function open(){
 const page=await browser.newPage({viewport:{width:1160,height:850}});page.setDefaultTimeout(8000);
 const errors=[],calls=[];page.on('pageerror',error=>errors.push(error.message));
 const {handle}=createMock();
 const state={people:structuredClone(personas),languages:[{tag:'ja',label:'日本語'},{tag:'en',label:'English'},{tag:'de',label:'Deutsch'},{tag:'fr',label:'Français'}],
  main:handle('http://qa.test/api/chat/main','GET').json,
  archives:handle('http://qa.test/api/chat/archives','GET').json.items,subscription:'chatgpt',
  mistakes:[{exercise_id:'exercise',item_index:0,language:'en',title:'Reading fixture',question:'Question?',options:['A','B'],answer:0,selected:1}],
  word:{id:91,language:'en',lemma:'word',meaning:'Old meaning',context_sentence:'A word',contexts:[]},
  conversations:[{id:'c1',title:'History fixture'}]};
 state.main.languages=state.languages;
 await page.route('**/*',async route=>{
  const request=route.request(),url=new URL(request.url()),p=url.pathname,method=request.method();
  assert.equal(url.hostname,'qa.test');
  if(!p.startsWith('/api/')){
   try{return route.fulfill({contentType:p==='/'?types['.html']:types[path.extname(p)]||'application/octet-stream',body:await fs.readFile(path.join(root,'frontend',p==='/'?'index.html':decodeURIComponent(p)))});}
   catch{return route.fulfill({status:404,body:''});}
  }
  const body=request.postDataJSON();calls.push({path:p,method,body});
  const send=data=>route.fulfill({json:data});
  if(p==='/api/personas'){
   if(method==='POST'){state.people.push({id:90,...body});return send(state.people.at(-1));}
   return send({items:state.people});
  }
  if(p==='/api/personas/90'&&method==='DELETE'){state.people=state.people.filter(p=>p.id!==90);return send({ok:true});}
  if(p==='/api/chat/main'){
   if(method==='PUT')Object.assign(state.main,body);
   return send({...state.main,languages:state.languages});
  }
  if(p==='/api/chat/main/new'){
   state.archives.push({session_id:state.main.session_id,persona_id:1,persona_name:'Main fixture',count:0});state.main.session_id=99;
   return send({...state.main,languages:state.languages});
  }
  if(p==='/api/chat/main/messages'&&state.main.session_id===99)return send({session_id:99,items:[]});
  if(p==='/api/chat/archives')return send({items:state.archives});
  if(p.startsWith('/api/chat/archives/')&&method==='DELETE'){state.archives=state.archives.filter(a=>a.session_id!==Number(p.split('/').at(-1)));return send({ok:true});}
  if(p==='/api/languages')return send({items:state.languages});
  if(p==='/api/languages/fr'&&method==='DELETE'){state.languages=state.languages.filter(l=>l.tag!=='fr');return send({ok:true});}
  if(p==='/api/reader/errors')return send({items:state.mistakes});
  if(p.startsWith('/api/reading/errors/')&&method==='DELETE'){state.mistakes=[];return send({ok:true});}
  if(p==='/api/vocab/91')return send(state.word);
  if(p==='/api/notebook/91'&&method==='PUT'){Object.assign(state.word,body);return send(state.word);}
  if(p==='/api/settings'&&method==='PUT'&&'listening_subscription'in body)state.subscription=body.listening_subscription;
  if(p==='/api/listening/options')return send({...handle(request.url(),method,request.postData()).json,subscription:state.subscription});
  if(p==='/api/workspace-agent/conversations')return send({conversations:state.conversations});
  if(p==='/api/workspace-agent/conversations/c1'&&method==='DELETE'){state.conversations=[];return send({ok:true});}
  const result=handle(request.url(),method,request.postData());
  if(!result)return route.fulfill({status:404,json:{detail:'Missing fixture'}});
  return result.json!==undefined?route.fulfill({status:result.status,json:result.json}):route.fulfill({status:result.status,contentType:result.contentType,body:result.body});
 });
 await page.goto('http://qa.test/');await page.waitForSelector('#jine-messages .jm-row');
 return {page,state,calls,errors};
}
async function confirm(page,text,yes=true){
 assert.equal(await page.locator('.confirm-title').innerText(),text);
 await page.locator(yes?'.confirm-danger':'.confirm-cancel').click();
}
async function archives(page){await page.click('#jm-more');await page.click('#jm-archives');await page.locator('#jm-archive-panel h2').waitFor();}
const called=(calls,method,p)=>calls.filter(c=>c.method===method&&c.path===p);

try{
 {
  const {page,state,calls,errors}=await open();
  await archives(page);
  assert.equal(await page.getByRole('button',{name:'开新对话',exact:true}).count(),1);
  await page.locator('.jm-archive-row').first().click();
  await page.locator('#jm-archive-bar').waitFor();
  assert.equal(await page.locator('#jine-composer').isVisible(),false);
  await archives(page);
  await page.locator('#jm-archive-panel button[aria-label="删除"]').first().click();
  await confirm(page,'删掉这段？',false);
  assert.equal(called(calls,'DELETE','/api/chat/archives/11').length,0);
  await page.locator('#jm-archive-panel button[aria-label="删除"]').first().click();
  await confirm(page,'删掉这段？');
  await page.waitForFunction(()=>!document.querySelector('#page-talk').classList.contains('archived'));
  assert.equal(called(calls,'DELETE','/api/chat/archives/11').length,1);
  assert.equal(await page.locator('.jm-archive-row').count(),1);
  await page.getByRole('button',{name:'开新对话',exact:true}).click();
  await confirm(page,'开一段新对话？');
  await page.waitForFunction(()=>LP.state.currentSessionId===99);
  await page.waitForFunction(()=>!document.querySelector('#jine-messages .jm-row'));
  assert.equal(called(calls,'POST','/api/chat/main/new').length,1);
  assert.equal(await page.locator('#jm-archive-panel').isHidden(),true);
  assert.equal(await page.locator('#jine-messages .jm-row').count(),0);
  assert.equal(await page.locator('#jine-composer').isVisible(),true);
  state.archives=[];await archives(page);
  assert.equal(await page.locator('#jm-archive-panel').textContent(),'旧对话开新对话');
  assert.deepEqual(errors,[]);await page.close();
 }
 {
  const {page,calls,errors}=await open();
  await page.evaluate(()=>LP.appShell.switchTab('settings'));
  await page.getByRole('button',{name:'+ 新建角色',exact:true}).click();
  await page.fill('#f-name','QA persona');
  await page.locator('.tag-add').click();await page.fill('.tag-add-input','QA interest');await page.press('.tag-add-input','Enter');
  assert.equal(await page.locator('#f-interests .tag-chip').count(),1);
  await page.locator('#persona-form button[type=submit]').click();
  await page.locator('.room-primary button',{hasText:'QA persona'}).waitFor();
  await page.locator('[data-room-more]>summary').click();
  assert.equal(await page.locator('.room-guest strong',{hasText:'QA persona'}).count(),1);
  assert.deepEqual(called(calls,'POST','/api/personas').at(-1).body.profile.interests,['QA interest']);
  await page.locator('#danger-zone > summary').click();
  await page.locator('#btn-delete-persona').click();await page.locator('.confirm-danger').click();
  await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.room-primary button')).some(b=>b.textContent.includes('QA persona')));
  assert.equal(await page.locator('.room-guest strong',{hasText:'QA persona'}).count(),0);
  await page.click('[data-settings-tab="listen"]');
  await page.waitForFunction(()=>!document.querySelector('#f-listening-subscription').disabled);
  assert.equal(await page.locator('#f-listening-subscription').inputValue(),'chatgpt');
  await page.selectOption('#f-listening-subscription','deepseek');
  await page.waitForFunction(()=>!document.querySelector('#f-listening-subscription').disabled);
  assert.equal(called(calls,'PUT','/api/settings').at(-1).body.listening_subscription,'deepseek');
  assert.equal(await page.locator('#f-listening-subscription').inputValue(),'deepseek');
  await page.selectOption('#f-listening-subscription','chatgpt');
  await page.waitForFunction(()=>!document.querySelector('#f-listening-subscription').disabled);
  await page.reload();await page.waitForSelector('#jine-messages .jm-row',{state:'attached'});
  await page.evaluate(()=>LP.appShell.switchTab('settings'));await page.click('[data-settings-tab="listen"]');
  await page.waitForFunction(()=>!document.querySelector('#f-listening-subscription').disabled);
  assert.equal(await page.locator('#f-listening-subscription').inputValue(),'chatgpt');
  assert.deepEqual(errors,[]);await page.close();
 }
 {
  const {page,calls,errors}=await open();
  // Mount the existing settings lists too, then remove from the chat drawer.
  await page.evaluate(()=>LP.appShell.switchTab('settings'));await page.locator('#f-language').waitFor();
  await page.evaluate(()=>LP.appShell.switchTab('talk'));
  await page.click('#jm-more');await page.click('#jm-add-language');
  const drawer=page.locator('.language-drawer[open]');
  assert.equal(await drawer.locator('button[aria-label="移除"]').count(),1);
  await drawer.locator('button[aria-label="移除"]').click();
  await confirm(page,'拿掉「Français」？',false);
  assert.equal(called(calls,'DELETE','/api/languages/fr').length,0);
  await drawer.locator('button[aria-label="移除"]').click();
  await confirm(page,'拿掉「Français」？');
  await page.waitForFunction(()=>!LP.languages.list().some(l=>l.tag==='fr'));
  assert.equal(called(calls,'DELETE','/api/languages/fr').length,1);
  assert.equal(await drawer.locator('[data-languages="known"] [data-language="fr"]').count(),0);
  assert.equal(await drawer.locator('.jine-language-results [data-language="fr"] .jine-language-action').innerText(),'+');
  assert.equal(await page.locator('.jm-dial-opt',{hasText:'Français'}).count(),0);
  assert.equal(await page.locator('#f-language option[value="fr"]').count(),0);
  assert.equal(await page.locator('[data-language-default] option[value="fr"]').count(),0);
  assert.equal(await page.locator('.room-pool button',{hasText:'Français'}).count(),0);
  assert.deepEqual(errors,[]);await page.close();
 }
 {
  const {page,calls,errors}=await open();
  await page.evaluate(()=>LP.appShell.switchTab('review'));
  const entry=page.locator('.rv-entry').filter({hasText:'Question?'});await entry.locator('summary').click();
  await entry.getByRole('button',{name:'删除这题',exact:true}).click();await confirm(page,'删掉这道错题？',false);
  assert.equal(called(calls,'DELETE','/api/reading/errors/exercise%3A0').length,0);
  await entry.getByRole('button',{name:'删除这题',exact:true}).click();await confirm(page,'删掉这道错题？');
  await page.waitForFunction(()=>!Array.from(document.querySelectorAll('.rv-entry')).some(e=>e.textContent.includes('Question?')));
  assert.equal(called(calls,'DELETE','/api/reading/errors/exercise%3A0').length,1);
  await page.evaluate(()=>LP.learning.openVocab(91));
  await page.locator('.lt-vocab-meaning').getByRole('button',{name:'改',exact:true}).click();
  assert.equal(await page.locator('.lt-vocab-meaning input').inputValue(),'Old meaning');
  assert.equal(await page.locator('.lt-vocab-meaning').getByRole('button',{name:'存',exact:true}).count(),1);
  await page.fill('.lt-vocab-meaning input','Cancelled');await page.press('.lt-vocab-meaning input','Escape');
  assert.equal(await page.locator('.lt-vocab').evaluate(d=>d.open),true);
  assert.equal(called(calls,'PUT','/api/notebook/91').length,0);
  await page.locator('.lt-vocab-meaning').getByRole('button',{name:'改',exact:true}).click();
  await page.fill('.lt-vocab-meaning input','New meaning');await page.press('.lt-vocab-meaning input','Enter');
  await page.waitForFunction(()=>document.querySelector('.lt-vocab-meaning')?.textContent==='New meaning改');
  assert.deepEqual(called(calls,'PUT','/api/notebook/91').at(-1).body,{meaning:'New meaning'});
  await page.locator('.lt-vocab-meaning').getByRole('button',{name:'改',exact:true}).click();
  await page.fill('.lt-vocab-meaning input','Discarded');await page.getByRole('button',{name:'取消',exact:true}).click();
  assert.equal(await page.locator('.lt-vocab-meaning').innerText(),'New meaning改');
  await page.locator('.lt-vocab-meaning').getByRole('button',{name:'改',exact:true}).click();
  await page.fill('.lt-vocab-meaning input','Saved by button');
  await page.locator('.lt-vocab-meaning').getByRole('button',{name:'存',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.lt-vocab-meaning')?.textContent==='Saved by button改');
  assert.deepEqual(errors,[]);await page.close();
 }
 {
  const {page,calls,errors}=await open();
  await page.evaluate(()=>LP.appShell.switchTab('workspace-agent'));
  await page.getByRole('button',{name:'对话记录',exact:true}).click();
  const history=page.locator('.workspace-agent-conversation-list');
  await history.getByRole('button',{name:'History fixture',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.workspace-agent-conversation-list [aria-current="true"]'));
  await history.getByRole('button',{name:'删除',exact:true}).click();await confirm(page,'删掉这段对话？',false);
  assert.equal(called(calls,'DELETE','/api/workspace-agent/conversations/c1').length,0);
  await history.getByRole('button',{name:'删除',exact:true}).click();await confirm(page,'删掉这段对话？');
  await page.waitForFunction(()=>!document.querySelector('.workspace-agent-conversation-list button'));
  assert.equal(called(calls,'DELETE','/api/workspace-agent/conversations/c1').length,1);
  assert.equal(await page.locator('.workspace-agent-turn').count(),0);
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('PASS QA controls: archives, personas, languages, tag Enter, reading errors, meanings, listening subscription and concierge deletion.');
}finally{await browser.close();}
