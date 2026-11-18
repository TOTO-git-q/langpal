import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root = process.env.LANGPAL_SOURCE_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const assets = path.join(root,'frontend');
const shots = process.env.LANGPAL_MODEL_SCREENSHOT_DIR;
const browser = await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH||undefined,headless:true});
try {
 const page = await browser.newPage({viewport:{width:1160,height:850}});
 page.setDefaultTimeout(10000);
 const errors=[], calls=[];
 let main='deepseek'; let memories=[];
 page.on('pageerror', error=>errors.push(error.message));
 await page.route('**/*', async route=>{
  const url=new URL(route.request().url()), p=url.pathname;
  assert.equal(url.hostname,'jine.test');
  if(p==='/')return route.fulfill({contentType:'text/html;charset=utf-8',body:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><main id="app-shell"><section id="settings-root"></section></main></html>'});
  if(p.startsWith('/frontend/'))return route.fulfill({path:path.join(root,p.slice(1)),contentType:p.endsWith('.css')?'text/css':'text/javascript'});
  if(p.startsWith('/assets/'))return route.fulfill({path:path.join(assets,p.slice(1))}).catch(()=>route.abort());
  calls.push({path:p,method:route.request().method(),body:route.request().postDataJSON()});
  let data={items:[]};
  if(p==='/api/memory'){if(route.request().method()==='POST') {memories.push({id:7,...route.request().postDataJSON()});data=memories.at(-1);} else data={items:memories};}
  if(p==='/api/memory/7'){if(route.request().method()==='DELETE')memories=[];else Object.assign(memories[0],route.request().postDataJSON());data=memories[0]||{ok:true};}
  if(p==='/api/settings'){
   if(route.request().method()==='PUT')main=route.request().postDataJSON().chat_engine||main;
   data={chat_engine:main,deepseek_model:'deepseek-chat',utility_engine:'auto'};
  }
  if(p==='/api/teaching/presets')data={items:[]};
  if(p.startsWith('/api/teaching/settings/'))data={teaching:{mode:'off'}};
  if(p==='/api/engines/status')data={claude:{available:false},deepseek:{configured:true,model:'deepseek-chat'},custom:{configured:false},chat_engine:main,utility_engine:'auto',utility_effective:'deepseek',chat_fallback:'enabled',current_engine:main,degraded:false};
  if(p==='/api/engines/deepseek/models'||p==='/api/engines/custom/models')data={models:[{id:'vendor/model+v2@beta',label:'Returned model'}]};
  return route.fulfill({json:data});
 });
 await page.goto('http://jine.test/');
 const index=await fs.readFile(path.join(root,'frontend/index.html'),'utf8');
 for(const [,href]of index.matchAll(/<link rel="stylesheet" href="([^"]+)"/g))await page.addStyleTag({url:'http://jine.test/frontend/'+href});
 await page.addStyleTag({content:'html,body,#app-shell,#settings-root{height:100%;margin:0}[hidden]{display:none!important}'});
 await page.addScriptTag({url:'http://jine.test/frontend/js/api.js'});
 await page.evaluate(()=>{
  Object.assign(LP,{state:{personas:[{id:1,name:'Test',language:'ja',profile:{interests:[]}}],currentPersonaId:1},getPersona:id=>id===1?{id:1,name:'Test',language:'ja',profile:{interests:[]}}:null,preferences:{get:()=>null,set:()=>true},languages:{list:()=>[{tag:'en',label:'English'}],label:x=>x},toast:()=>{}});
  Object.assign(LP.api,{getMainChat:async()=>({guests:[],fun_languages:[]}),getUsage:async()=>({})});
 });
 for(const js of ['util.js','language-picker.js','language-drawer.js','settings-teaching.js','settings-providers.js','reading-preferences.js','conditions.js','settings-models.js','settings-lore.js','settings-hooks.js','settings-chat-room.js','settings.js','workspace-agent.js'])await page.addScriptTag({url:'http://jine.test/frontend/js/'+js});
 await page.evaluate(()=>LP.settings.mount(document.querySelector('#settings-root')));
 await page.locator('#settings-memory > summary').click();
 await page.evaluate(()=>{LP.api.createMemory=async body=>{window.savedMemoryBody=body;await new Promise(resolve=>{window.releaseMemorySave=resolve;});return {id:9,...body};};});
 await page.locator('#btn-add-memory').click();
 await page.getByRole('textbox',{name:'记忆内容'}).fill('第一次保存');
 await page.locator('#memory-new-form button[type=submit]').click();
 await page.waitForFunction(()=>typeof window.releaseMemorySave==='function');
 await page.locator('#memory-new-dialog').getByRole('button',{name:'取消',exact:true}).click();
 await page.locator('#btn-add-memory').click();
 await page.getByRole('textbox',{name:'记忆内容'}).fill('新的草稿不能被旧请求关掉');
 await page.evaluate(()=>window.releaseMemorySave());
 await page.waitForTimeout(100);
 const observed=await page.evaluate(()=>({open:document.querySelector('#memory-new-dialog').open,text:document.querySelector('#memory-new-form textarea').value,saved:window.savedMemoryBody}));
 console.log(JSON.stringify(observed));
 assert.equal(observed.open,true,'An old successful save closed the new memory draft');
 console.log('PASS async memory draft lifecycle.');
}finally{await browser.close();}