// Offline regression: no live server, model calls or production data writes.
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root = process.env.LANGPAL_SOURCE_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const js = process.env.LANGPAL_AGENT_JS || path.join(root,'frontend/js/workspace-agent.js');
const css = process.env.LANGPAL_AGENT_CSS || path.join(root,'frontend/css/workspace-agent.css');
const browser = await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH || undefined,headless:true});
try {
 const page=await browser.newPage(); page.setDefaultTimeout(8000); const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
 let old=false, fail=false, failUpload=false, requests=[], attachmentCount=0;
 const proposal={id:'preview1',changes:[{label:'字号',before:16,after:19}],expires_in:1800};
 await page.route('http://agent.test/**',async route=>{
   const url=new URL(route.request().url()), method=route.request().method();
   if(url.pathname==='/') return route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><style>html,body,#root{height:100%;margin:0;box-sizing:border-box}*{box-sizing:border-box}</style><div id="root"></div>'});
   if(url.pathname.endsWith('workspace-agent.js')) return route.fulfill({contentType:'text/javascript',body:await fs.readFile(js,'utf8')});
   if(url.pathname.endsWith('reading-pdf.mjs')) return route.fulfill({contentType:'text/javascript',body:`export async function openPDF(file){return {promise:Promise.resolve({numPages:21,destroy:async()=>{}}),destroy:async()=>{}}} export async function pageText(doc,n){return 'PDF page '+n;}`});
   const api=url.pathname.replace('/api/workspace-agent/',''); requests.push({api,method,body:route.request().postData()});
   let data={};
   if(api==='capabilities') {if(old)return route.fulfill({status:404,json:{}}); data={version:1,conversations:true,attachments:true,providers:[{id:'claude',label:'Claude',configured:true,vision:false}],main_engine:'claude',default_provider:'claude'};}
   else if(api==='conversations'&&method==='GET') data={conversations:[{id:'old',title:'已有对话'}]};
   else if(api==='conversations') data={id:'new',title:'新对话'};
   else if(api==='conversations/old') data={conversation:{id:'old'},messages:[{role:'user',content:'保留的问题'},{role:'assistant',content:'保留的回复',result:{proposal}}],attachments:[]};
   else if(api==='conversations/new') data={conversation:{id:'new'},messages:[],attachments:[]};
   else if(api.endsWith('/attachments')) {if(failUpload)return route.fulfill({status:400,json:{detail:'测试上传失败'}}); data={id:'file'+(++attachmentCount),name:'notes.txt',truncated:route.request().postData().includes('PDF page')};}
   else if(api==='plan') {if(fail) { fail=false; return route.fulfill({status:503,json:{detail:'测试请求失败'}}); } data={reply:'已读取需求',route:['visual'],proposal};}
   else if(api==='apply'||api==='undo') data={tools:[]};
   else if(api==='catalog') data={tools:[]};
   else if(api==='inspect') data={sources:[]};
   return route.fulfill({json:data});
 });
 async function mount(){await page.goto('http://agent.test/');await page.addStyleTag({path:css});await page.evaluate(()=>{window.LP={preferences:{get:()=>null},appShell:{switchTab:()=>{}}};});await page.addScriptTag({path:path.join(root,'frontend/js/util.js')});await page.addScriptTag({path:path.join(root,'frontend/js/actions.js')});await page.addScriptTag({url:'http://agent.test/js/workspace-agent.js'});await page.evaluate(()=>LP.workspaceAgent.mount(document.querySelector('#root')));await page.waitForFunction(()=>document.querySelector('.workspace-agent').getAttribute('aria-busy') === 'false');}
 await mount();
 assert.match(await page.locator('.workspace-agent-thread').innerText(),/保留的问题/);
 await page.getByRole('button',{name:'改了什么',exact:true}).click();
 assert.equal(await page.getByRole('button',{name:'使用此安排',exact:true}).isVisible(),false);
 await page.getByRole('button',{name:'对话记录',exact:true}).click(); // 对话记录栏默认收起
 await page.locator('.workspace-agent-new').click();
 await page.locator('.workspace-agent-file').setInputFiles({name:'notes.txt',mimeType:'text/plain',buffer:Buffer.from('A real file')});
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-file-chip')?.dataset.state === 'ready');
 assert.equal(requests.filter(r=>r.api.endsWith('/attachments')).length,1);
 assert.match(requests.find(r=>r.api.endsWith('/attachments')).body,/A real file/);
 await page.locator('#workspace-agent-input').fill('根据附件设置字号');
 fail=true; await page.locator('.workspace-agent-send').click();
 await page.getByRole('button',{name:'重发',exact:true}).waitFor();
 assert.match(await page.locator('.workspace-agent-thread').innerText(),/测试请求失败/);
 assert.equal(await page.locator('#workspace-agent-input').inputValue(),'根据附件设置字号');
 await page.getByRole('button',{name:'重发',exact:true}).click();
 await page.getByRole('button',{name:'使用此安排',exact:true}).waitFor();
 assert.equal(requests.filter(r=>r.api==='apply').length,0);
 const plans=requests.filter(r=>r.api==='plan').map(r=>JSON.parse(r.body));
 assert.equal(plans[0].conversation_id,'new'); assert.deepEqual(plans[0].attachment_ids,['file1']); assert.notEqual(plans[0].request_id,plans[1].request_id);
 await page.getByRole('button',{name:'使用此安排',exact:true}).click();
 await page.getByRole('button',{name:'撤销',exact:true}).waitFor(); await page.getByRole('button',{name:'撤销',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-proposal').textContent.includes('已撤销'));
 await page.locator('.workspace-agent-reuse summary').click();
 await page.getByRole('button',{name:'选用 · notes.txt',exact:true}).click();
 assert.equal(await page.locator('.workspace-agent-file-chip').getAttribute('title'),'notes.txt');
 await page.getByRole('button',{name:'移除 notes.txt',exact:true}).click();
 failUpload=true;
 await page.locator('.workspace-agent-file').setInputFiles({name:'bad.txt',mimeType:'text/plain',buffer:Buffer.from('oops')});
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-file-chip')?.textContent.includes('测试上传失败'));
 assert.equal(await page.locator('.workspace-agent-send').isDisabled(),true);
 await page.getByRole('button',{name:'移除 bad.txt',exact:true}).click();failUpload=false;
 const uploadsBefore=requests.filter(r=>r.api.endsWith('/attachments')).length;
 await page.locator('.workspace-agent-file').setInputFiles({name:'photo.png',mimeType:'image/png',buffer:Buffer.from('unsupported')});
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-file-chip')?.classList.contains('error'));
 assert.equal(requests.filter(r=>r.api.endsWith('/attachments')).length,uploadsBefore);
 await page.getByRole('button',{name:'移除 photo.png',exact:true}).click();
 await page.locator('.workspace-agent-file').setInputFiles({name:'pages.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF test')});
 await page.waitForFunction(()=>document.querySelector('.workspace-agent-file-chip')?.textContent.includes('只读了前一部分'));
 const pdfUpload=requests.filter(r=>r.api.endsWith('/attachments')).at(-1).body;
 assert.match(pdfUpload,/PDF page 20/); assert.doesNotMatch(pdfUpload,/PDF page 21/);
 await page.setViewportSize({width:390,height:760});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 if(process.env.LANGPAL_AGENT_SCREENSHOT) {
   await page.screenshot({path:process.env.LANGPAL_AGENT_SCREENSHOT+'-mobile.png'});
   await page.setViewportSize({width:1280,height:800});
   await page.screenshot({path:process.env.LANGPAL_AGENT_SCREENSHOT+'-desktop.png'});
 }
 old=true; requests=[]; await mount();
 assert.equal(await page.locator('.workspace-agent-attach').isDisabled(),true);
 assert.equal(await page.locator('.workspace-agent-new').isDisabled(),true);
 assert.equal(requests.some(r=>r.method==='POST'),false);
 await page.locator('#workspace-agent-input').fill('普通文字');assert.equal(await page.locator('.workspace-agent-send').isDisabled(),true);
 assert.equal(requests.some(r=>r.api==='plan'),false);
 assert.deepEqual(errors,[]);
 console.log('PASS: canonical multipart attachment, PDF bound, error/remove/retry, persisted history, stale previews, explicit apply/undo, old-server gating, mobile width');
} finally {await browser.close();}
