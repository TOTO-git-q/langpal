// Offline visual and interaction checks. All APIs and speech recognition mocked.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const js=process.env.LANGPAL_AGENT_JS||path.join(root,'frontend/js/workspace-agent.js');
const css=process.env.LANGPAL_AGENT_CSS||path.join(root,'frontend/css/workspace-agent.css');
let png;
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1280,height:800}});page.setDefaultTimeout(8000);
 png=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=240;c.height=160;const x=c.getContext('2d');x.fillStyle='#d3e2ef';x.fillRect(0,0,240,160);x.fillStyle='#5a829e';x.fillRect(20,25,200,110);x.fillStyle='#f4f8fb';x.fillRect(35,40,170,80);x.fillStyle='#4b70ab';x.font='18px sans-serif';x.fillText('IMAGE TEST',64,86);return c.toDataURL().split(',')[1]}),'base64');
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));let plans=[],uploaded=[];let pendingUpload;let proposalState='pending';let visionOk=true;
 const proposal=()=>({id:'p1',status:proposalState,changes:[{label:'学习目标',before:{preset:'old-course'},after:{preset:'my-n2'}}],created_at:Date.now()/1000,expires_at:Date.now()/1000+(proposalState==='expired'?-1:300),expires_in:300});
 await page.addInitScript(()=>{
   window.speechStarts=0;window.speechStops=0;window.urlsCreated=0;window.urlsRevoked=0;
   const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
   URL.createObjectURL=b=>{urlsCreated++;return create(b)};URL.revokeObjectURL=u=>{urlsRevoked++;revoke(u)};
   window.SpeechRecognition=class {
     constructor(){window.mockSpeech=this;}
     start(){speechStarts++;this.onstart?.();}
     stop(){speechStops++;this.onend?.();}
   };
 });
 await page.route('http://agent.test/**',async route=>{
   const p=new URL(route.request().url()).pathname,method=route.request().method();
   if(p==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:'<html lang="zh-CN"><meta charset="utf-8"><style>*{box-sizing:border-box}html,body,#app-shell,#root{height:100%;margin:0}</style><main id="app-shell"><section id="root"></section></main></html>'});
   if(p.endsWith('workspace-agent.js'))return route.fulfill({contentType:'text/javascript; charset=utf-8',body:await fs.readFile(js,'utf8')});
   if(p.endsWith('/content'))return route.fulfill({contentType:'image/png',body:png});
   if(p.endsWith('.svg'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#604590" d="M12 2 22 12 12 22 2 12Z"/></svg>'});
   const api=p.replace('/api/workspace-agent/','');let data={};
   if(api==='capabilities')data={version:1,conversations:true,attachments:true,images:true,image_input:true,proposals:true,providers:[{id:'claude',label:'Claude',configured:true,vision:visionOk}],main_engine:'claude',default_provider:'claude'};
   if(api==='conversations'&&method==='GET')data={conversations:[{id:'c1',title:'图片与任务'}]};
   if(api==='conversations'&&method==='POST')data={id:'c2',title:'新对话'};
   if(api==='conversations/c1')data={messages:plans.length?[{role:'user',content:'',attachment_ids:uploaded.map(f=>f.id)},{role:'assistant',content:'已处理附件'}]:[],attachments:uploaded};
   if(api.endsWith('/attachments')) {
     if(pendingUpload)await pendingUpload;
     const file={id:'a'+(uploaded.length+1),name:'sample.png',mime:'image/png'};uploaded.push(file);data=file;
   }
   if(api==='plan'){plans.push(JSON.parse(route.request().postData()));data={reply:'已处理附件'};}
   if(api==='proposals')data={proposals:[proposal()]};
   if(api==='proposals/p1')data=proposal();
   if(api==='apply'){proposalState='applied';data={proposal:proposal(),tools:[]};}
   if(api==='undo'){proposalState='undone';data={proposal:proposal(),tools:[]};}
   if(api==='catalog')data={tools:[{id:'reading.style',label:'阅读排版',schema:{properties:{format:{type:'object'}},required:[]}}]};
   if(api==='inspect')data={sources:[]};
   return route.fulfill({json:data});
 });
 await page.goto('http://agent.test/');await page.addStyleTag({path:css});await page.addStyleTag({content:'[hidden]{display:none!important}'}); // 线上由 windose.css 提供
 await page.evaluate(()=>{window.LP={preferences:{get:()=>null},appShell:{switchTab:()=>{}}}});
 await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});await page.addScriptTag({path:path.join(root,'frontend/js/actions.js')});await page.addScriptTag({url:'http://agent.test/js/workspace-agent.js'});await page.evaluate(()=>LP.workspaceAgent.mount(document.querySelector('#root')));
 await page.waitForFunction(()=>!document.querySelector('.workspace-agent-attach').disabled);
 // 默认跟主引擎：输入框下一个小下拉，起始是「跟主引擎」
 assert.equal(await page.locator('.workspace-agent-model').inputValue(),'main');
 assert.equal(await page.locator('.workspace-agent-send').isDisabled(),true);
 const form=page.locator('.workspace-agent-form'),input=page.locator('#workspace-agent-input');
 assert.equal(await input.getAttribute('placeholder'),'想怎么学，直接说');
 assert.equal(await form.locator('details').count(),0);assert.equal(await form.locator('.workspace-agent-connection').count(),0);
 assert.equal(await page.evaluate(()=>speechStarts),0);
 let release;pendingUpload=new Promise(r=>{release=r});
 await page.locator('.workspace-agent-file').setInputFiles({name:'sample.png',mimeType:'image/png',buffer:png});
 await form.locator('.workspace-agent-file-chip.image img').waitFor();
 assert.equal(await page.locator('.workspace-agent-send').isDisabled(),true);
 assert.equal(await form.locator('.workspace-agent-file-chip.image img').evaluate(el=>el.naturalWidth),240);
 release();pendingUpload=null;await page.waitForFunction(()=>!document.querySelector('.workspace-agent-send').disabled);
 // 模型临时不能看图：带着图片就不能发，提示一句
 visionOk=false;await page.evaluate(()=>dispatchEvent(new Event('lp:models-changed')));
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-send').disabled);
 assert.match(await page.locator('.workspace-agent-provider').innerText(),/看不了图/);
 visionOk=true;await page.evaluate(()=>dispatchEvent(new Event('lp:models-changed')));
 await page.waitForFunction(()=>!document.querySelector('.workspace-agent-send').disabled);
 assert.equal(await form.locator('.workspace-agent-file-chip.image img').count(),1);
 const removeSize=await form.locator('.workspace-agent-file-chip.image > button').evaluate(el=>({w:el.getBoundingClientRect().width,h:el.getBoundingClientRect().height}));assert.ok(removeSize.w>=20&&removeSize.h>=20);
 if(process.env.LANGPAL_AGENT_SCREENSHOT) await page.screenshot({path:process.env.LANGPAL_AGENT_SCREENSHOT+'-desktop.png'});
 await page.setViewportSize({width:390,height:760});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 if(process.env.LANGPAL_AGENT_SCREENSHOT)await page.screenshot({path:process.env.LANGPAL_AGENT_SCREENSHOT+'-mobile.png'});
 await input.focus();await page.keyboard.press('Control+Enter');
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-thread').textContent.includes('已处理附件'));
 assert.equal(plans[0].message,'');assert.equal('provider' in plans[0],false);assert.deepEqual(plans[0].attachment_ids,['a1']);
 assert.equal(await page.locator('.workspace-agent-message-file img').count(),1);
 assert.equal(await page.evaluate(()=>urlsRevoked),1);
 await page.getByRole('button',{name:'对话记录',exact:true}).click(); // 对话记录栏默认收起
 await page.getByRole('button',{name:'刷新记录',exact:true}).click();await page.locator('.workspace-agent-message-file img').waitFor();
 await page.locator('.workspace-agent-reuse summary').click();await page.getByRole('button',{name:'选用 · sample.png',exact:true}).click();
 assert.equal(await form.locator('.workspace-agent-file-chip.image img').count(),1);
 await page.getByRole('button',{name:'移除 sample.png',exact:true}).click();
 assert.equal(await page.locator('.workspace-agent-message-file img').count(),1);
 const mic=page.locator('.workspace-agent-mic');
 await mic.click();assert.equal(await page.locator('.confirm-title').innerText(),'用浏览器识别语音？');
 await page.locator('.confirm-danger').click();await page.waitForFunction(()=>speechStarts===1);
 assert.equal(await mic.getAttribute('aria-pressed'),'true');
 await page.evaluate(()=>{const result=[{transcript:'语音草稿'}];result.isFinal=true;mockSpeech.onresult({resultIndex:0,results:[result]})});
 assert.equal(await input.inputValue(),'语音草稿');assert.equal(plans.length,1);
 await mic.click();assert.equal(await page.evaluate(()=>speechStops),1);assert.equal(await mic.getAttribute('aria-pressed'),'false');
 await mic.click();await page.evaluate(()=>mockSpeech.onerror({error:'not-allowed'}));
 assert.match(await page.locator('.workspace-agent-status').innerText(),/麦克风没允许/);
 await mic.click();await page.locator('.workspace-agent-new').click();assert.equal(await mic.getAttribute('aria-pressed'),'false');
 await mic.click();await page.evaluate(()=>document.querySelector('#root').style.display='none');
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-mic').getAttribute('aria-pressed')==='false');
 await page.evaluate(()=>document.querySelector('#root').style.display='');
 await page.getByRole('button',{name:'改过什么',exact:true}).click();
 await page.getByRole('button',{name:'看看',exact:true}).click();
 await page.getByRole('button',{name:'使用此安排',exact:true}).waitFor();
 assert.equal(await page.locator('.workspace-agent-comparison details[open]').count(),0);
 await page.getByRole('button',{name:'使用此安排',exact:true}).click();
 await page.getByRole('button',{name:'撤销',exact:true}).waitFor();
 // A fresh authoritative lookup restores only the currently valid action.
 await page.getByRole('button',{name:'改过什么',exact:true}).click();await page.getByRole('button',{name:'看看',exact:true}).click();
 await page.getByRole('button',{name:'撤销',exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'使用此安排',exact:true}).isVisible(),false);
 await page.getByRole('button',{name:'撤销',exact:true}).click();
 proposalState='expired';await page.getByRole('button',{name:'改过什么',exact:true}).click();await page.getByRole('button',{name:'看看',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-proposal')?.textContent.includes('过期了'));
 assert.equal(await page.getByRole('button',{name:'使用此安排',exact:true}).isVisible(),false);assert.equal(await page.getByRole('button',{name:'撤销',exact:true}).isVisible(),false);
 // 别处「问管家」：带过去的话填进输入框，右侧收起
 await page.evaluate(()=>LP.workspaceAgent.prefill('字号调大一点'));
 assert.match(await input.inputValue(),/字号调大一点/);assert.equal(await page.locator('.workspace-agent-inspector').isVisible(),false);
 assert.deepEqual(errors,[]);
 // Unsupported platforms retain an honest disabled microphone, never invoke permission.
 await page.evaluate(()=>{document.querySelector('#root').style.display='';window.SpeechRecognition=undefined;window.webkitSpeechRecognition=undefined;const another=document.createElement('div');document.body.append(another);LP.workspaceAgent.mount(another);window.unsupportedRoot=another;});
 assert.equal(await page.evaluate(()=>unsupportedRoot.querySelector('.workspace-agent-mic').disabled),true);
 console.log('PASS: Claude-only composer; inline image preview before/after upload; attachment-only keyboard send; persisted image; URL cleanup; reuse/removal; mocked speech consent/start/result/error/stop/navigation; 390px layout');
}finally{await browser.close()}
