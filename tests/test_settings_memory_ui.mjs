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
 await page.locator('#btn-add-memory').click();
 await page.getByRole('combobox',{name:'记忆类型'}).selectOption('event');
 await page.getByRole('textbox',{name:'记忆内容'}).fill('周五交论文 <b>真实原文</b>');
 await page.locator('#memory-new-form button[type=submit]').click();
 await page.locator('.memory-record .mem-content').getByText('周五交论文 <b>真实原文</b>',{exact:true}).waitFor();
 assert.deepEqual(calls.find(call=>call.path==='/api/memory'&&call.method==='POST').body,{persona_id:1,category:'event',content:'周五交论文 <b>真实原文</b>',active:true});
 assert.equal(await page.locator('.mem-content b').count(),0);
 await page.locator('.memory-record [role=switch]').click();
 assert.equal(await page.locator('.memory-record [role=switch]').getAttribute('aria-checked'),'false');
 await page.locator('.mem-edit').click();
 await page.locator('.mem-content').fill('下周三再看一遍');
 await page.locator('#settings-memory > summary').click();
 await page.waitForFunction(()=>document.querySelector('.mem-content').getAttribute('contenteditable')!=='true');
 await page.evaluate(()=>LP.settings.refresh());
 await page.waitForFunction(()=>document.querySelector('.mem-content')?.textContent==='下周三再看一遍');
 await page.locator('#settings-memory > summary').click();
 if(shots)await page.screenshot({path:path.join(shots,'memory-settings.png')});
 for(const width of [768,390]){
  await page.setViewportSize({width,height:850});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 }
 await page.locator('.mem-del').click();
 await page.waitForFunction(()=>!document.querySelector('.memory-record'));
 await page.getByRole('button',{name:'+ 新建角色',exact:true}).click();
 assert.equal(await page.locator('#btn-add-memory').isDisabled(),true);
 assert.deepEqual(errors,[]);
 console.log('PASS memory settings: create, category, escaped text, toggle, edit/reload, delete, unsaved-role guard, 390/768/1160 widths.');
}finally{await browser.close();}
