import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true,args:['--mute-audio']});
try {
 const page=await browser.newPage({viewport:{width:1100,height:850}}),errors=[];
 page.setDefaultTimeout(8000);page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:'<main id="root"></main>'}));
 await page.goto('http://cleanup.test/');
 const script=async name=>page.addScriptTag({path:path.join(root,'frontend/js',name)});
 await script('util.js');
 await page.evaluate(()=>{
  window.savedName='Stored';window.nameWrites=[];
  Object.assign(LP,{state:{personas:[{id:1,name:'Test',language:'en'}]},languages:{list:()=>[{tag:'en',label:'English'}],label:tag=>tag},api:{
   getMainChat:async()=>({primary_id:1,guests:[],fun_languages:['en']}),getSettings:async()=>({user_name:savedName}),
   putSettings:async patch=>{nameWrites.push(patch);savedName=patch.user_name;return {user_name:savedName};}
  }});
 });
 await script('settings-chat-room.js');
 await page.evaluate(async()=>{window.room=LP.settingsChatRoom.mount(document.querySelector('main'));await room.refresh();});
 const name=page.getByLabel('她怎么叫你',{exact:true});
 assert.equal(await name.inputValue(),'Stored');assert.equal(await name.getAttribute('placeholder'),'ピ');assert.equal(await name.getAttribute('maxlength'),'24');
 assert.equal(await page.locator('.room-line').first().locator('input').getAttribute('id'),'room-user-name');
 await name.fill('  Updated  ');await name.press('Tab');
 await page.waitForFunction(()=>savedName==='Updated');
 await name.fill('Enter');await name.press('Enter');await page.waitForFunction(()=>savedName==='Enter');
 await page.evaluate(()=>room.refresh());assert.equal(await name.inputValue(),'Enter');
 await name.fill('');await name.press('Enter');await page.waitForFunction(()=>savedName==='');
 assert.deepEqual(await page.evaluate(()=>nameWrites),[{user_name:'Updated'},{user_name:'Enter'},{user_name:''}]);
 await page.evaluate(()=>{
  window.lessons={yes:{id:'yes',title:'Ordering food',report:{comment:'Report',scores:{fluency:4,accuracy:3,vocabulary_register:4,pronunciation:2,interaction:4},
    errors:[{said:'I want eat',correct:'I want to eat',reason:'want 后面接 to 加动词原形'}],homework:{task:'Homework task'}},
    transcript:[{role:'teacher',text:'Hi',start:0,duration:90},{role:'student',text:'Hello',start:600,duration:120}]},no:{id:'no',report:null,transcript:[]}};
  window.fetch=async url=>({ok:true,json:async()=>String(url).endsWith('/api/listening/coach')?{url:'http://cleanup.test/',ok:true}:
   String(url).endsWith('/api/speaking/lessons')?[{id:'yes',lang:'en',status:'complete',kind:'lesson',createdAt:new Date().toISOString()},
    {id:'no',lang:'en',status:'active',kind:'lesson',createdAt:new Date(Date.now()-86400000).toISOString()}]:lessons[String(url).split('/').at(-1)]});
 });
 await script('coach.js');await page.evaluate(()=>LP.coach.mount(document.querySelector('main')));
 // 首页：最近一节带平均分，五项里最弱的一项成了小标，错句和作业在「这个月」里
 await page.locator('.lp-recent-row[data-lesson=yes]').waitFor();
 assert.equal(await page.locator('.lp-recent-row[data-lesson=yes] strong').innerText(),'Ordering food');
 assert.equal(await page.locator('.lp-recent-row[data-lesson=yes] .coach-mean').innerText(),'3.4');
 await page.getByText('发音最弱',{exact:true}).waitFor();
 await page.locator('.coach-redo .coach-after',{hasText:'I want to eat'}).waitFor();
 await page.getByText('Homework task',{exact:true}).waitFor();
 assert.deepEqual(await page.locator('.lp-month-numbers strong').allInnerTexts(),['2','12','3.4']);   // 两节、12 分钟、平均分
 assert.deepEqual(await page.locator('.lp-format-tile .lp-format-name').allInnerTexts(),['对话课','跟读']);
 // 点最近的一节：看反馈；换到没有反馈的那节，自动落到字幕
 await page.locator('.lp-recent-row[data-lesson=yes]').click();await page.locator('.coach-record-content').getByText('Report',{exact:true}).waitFor();
 assert.equal(await page.locator('[data-coach-view=feedback]').getAttribute('aria-pressed'),'true');
 await page.getByLabel('选择课时').selectOption('no');
 await page.waitForFunction(()=>document.querySelector('[data-coach-view=feedback]').disabled);
 assert.equal(await page.locator('[data-coach-view=captions]').getAttribute('aria-pressed'),'true');
 await page.getByLabel('选择课时').selectOption('yes');
 await page.waitForFunction(()=>!document.querySelector('[data-coach-view=feedback]').disabled);
 await page.evaluate(()=>{lessons.yes.report=null;LP.coach.refresh();});
 await page.waitForFunction(()=>document.querySelector('[data-coach-view=feedback]').disabled);
 assert.equal(await page.locator('[data-coach-view=feedback]').getAttribute('aria-pressed'),'false');
 await page.getByRole('button',{name:'← 口语'}).click();
 await page.locator('.coach-home:not([hidden]) .lp-format-tile').first().waitFor();
 await page.evaluate(()=>{
  document.querySelector('main').replaceChildren();window.sentenceCalls=[];
  Object.assign(LP,{preferences:{get:key=>key==='readerLookup'?true:undefined,set:()=>{}},languageDrawer:{create:()=>({open(){}})},
   studyStorage:{listDocuments:async()=>[],getNotes:async()=>[],saveDocument:async()=>{},getStatus:()=>({state:'ready'})},
   api:{explainWord:async()=>({lemma:'sample',meaning_zh:'Fixture'}),explainSentence:async body=>{sentenceCalls.push(body);return {};}}});
  window.fetch=async()=>({ok:true,json:async()=>({sources:[],formats:[],defaults:{},items:[]})});
 });
 await page.addStyleTag({path:path.join(root,'frontend/css/reading.css')});await script('reading.js');
 await page.evaluate(()=>LP.reading.mount(document.querySelector('main')));
 await page.locator('[data-rd=file]').setInputFiles({name:'Sample.txt',mimeType:'text/plain',buffer:Buffer.from('A sample sentence.')});
 await page.locator('.rd-prose p').waitFor();
 const selectWord=()=>page.evaluate(()=>{
  const walker=document.createTreeWalker(document.querySelector('.rd-prose p'),NodeFilter.SHOW_TEXT);
  let text;while((text=walker.nextNode())&&!text.textContent.includes('sample')){}
  const start=text.textContent.indexOf('sample'),range=document.createRange();range.setStart(text,start);range.setEnd(text,start+6);
  getSelection().removeAllRanges();getSelection().addRange(range);document.querySelector('.rd-body').dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));
 });
 await selectWord();
 await page.getByRole('button',{name:'解释这句',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'解释句子',exact:true}).count(),0);
 await page.getByRole('button',{name:'解释这句',exact:true}).click();await page.waitForFunction(()=>sentenceCalls.length===1);
 await page.evaluate(()=>{window.sheetClosed=new Promise(resolve=>document.querySelector('[data-rd=close-sheet]').closest('dialog').addEventListener('close',resolve,{once:true}));});
 await page.locator('[data-rd=close-sheet]').click();
 await page.evaluate(()=>sheetClosed);
 await selectWord();
 await page.getByRole('button',{name:'查词',exact:true}).click();await page.getByText('Fixture',{exact:true}).waitFor();
 await page.getByRole('button',{name:'解释这句',exact:true}).click();await page.waitForFunction(()=>sentenceCalls.length===2);
 assert.deepEqual(errors,[]);
 console.log('PASS cleanup: feedback availability and fallback, user name load/blur/Enter/clear, both sentence explanation labels and actions.');
} finally {await browser.close();}
