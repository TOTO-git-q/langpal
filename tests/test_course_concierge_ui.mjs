import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium} = await import(process.env.LANGPAL_PLAYWRIGHT_MODULE || 'playwright-core');
const root = process.env.LANGPAL_SOURCE_ROOT || path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const shots = process.env.LANGPAL_COURSE_SCREENSHOTS;
const unit = {id:'transfer',title:'伝える',can_do:'伝えたいことを自然に説明する'};
const outlines = [
  {version:3,id:'jlpt-n1',title:'JLPT N1',language:'ja',units:[unit,{...unit,id:'reason',title:'理由をつなぐ'}]},
  {version:3,id:'jlpt-n2',title:'JLPT N2',language:'ja',units:[{...unit,id:'n2-unit'}]},
  {version:3,id:'toefl',title:'TOEFL',language:'en',units:[{...unit,id:'english-unit'}]},
];
for (const outline of outlines) outline.sections = [{id:'chat',title:'写作',venue:'chat',lessons:outline.units.map(unit=>unit.id)}];
let courses = {ja:{mode:'off'},en:{mode:'off'}};
const world = {id:1,name:'雨的日常',enabled:true,scope:'attached',book:{version:2,settings:{},entries:[{uid:1,title:'雨天',content:'喜欢雨后的街道。',keys:['雨'],enabled:true},{uid:2,title:'咖啡店',content:'经常去街角的咖啡店。',keys:[],constant:true,enabled:true}]}};
const plans = {ja:{format:'ja_gist',difficulty:'default',topic:''},en:{format:'auto',difficulty:'default',topic:''}};
const calls = [], errors = [];
const browser = await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH,headless:true});
try {
  const page = await browser.newPage({viewport:{width:1280,height:940}}); page.setDefaultTimeout(10000);
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname;
    assert.equal(url.hostname,'course.test');
    if(p === '/') return route.fulfill({contentType:'text/html;charset=utf-8',body:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><main id="app-shell"><section id="settings-root"></section><section id="agent-root" hidden></section><section id="listen-root" hidden></section><button id="chat-course">选择课程</button></main></html>'});
    if(p.startsWith('/frontend/')) return route.fulfill({path:path.join(root,p.slice(1)),contentType:p.endsWith('.css')?'text/css':'text/javascript'});
    if(p.startsWith('/assets/')) return route.fulfill({path:path.join(root,'frontend',p.slice(1))});
    const body = request.method() === 'GET' ? null : request.postDataJSON(); calls.push({path:p,method:request.method(),body});
    let data = {items:[]};
    assert.equal(/siwc|chatgpt|world-books/.test(p), false, 'retired endpoint ' + p);
    if(p === '/api/settings') data = {chat_engine:'claude',utility_engine:'auto'};
    if(p === '/api/engines/status') data = {claude:{available:true,model:'sonnet'},deepseek:{configured:false},custom:{configured:false},chat_engine:'claude',utility_engine:'auto',utility_effective:'claude',chat_fallback:'enabled',current_engine:'claude',degraded:false};
    if(p === '/api/hooks/meta') data = {events:[],actions:[],macros:[],condition_fields:[]};
    if(p === '/api/teaching/presets') data = {items:outlines};
    if(p.startsWith('/api/teaching/settings/')) {
      const lang = p.split('/').at(-1);
      if(body) courses[lang] = structuredClone(body);
      data = {language:lang,teaching:{...courses[lang],preset_id:courses[lang].preset},progress:{active:courses[lang].mode==='ambient',course:null,counts:{points:0,known:0},units:[],next:null,lesson:null}};
    }
    if(p === '/api/lore/books') data = {items:[{id:world.id,name:world.name,enabled:world.enabled,scope:world.scope,entry_count:world.book.entries.length,attached_persona_ids:[]}]};
    if(p === '/api/lore/books/1') { if(request.method() === 'PUT') Object.assign(world, body); data = world; }
    if(p.endsWith('/capabilities')) data = {version:3,conversations:true,attachments:true,proposals:true,images:true,image_input:true,providers:[{id:'claude',label:'Claude',configured:true,vision:true},{id:'deepseek',label:'DeepSeek',configured:true,vision:false}],main_engine:'claude',default_provider:'claude',available:true};
    if(p.endsWith('/conversations')) data = body ? {id:'c1',title:'选择课程'} : {conversations:[]};
    if(p.endsWith('/plan')) data = {reply:'把日语的聊天课程设为 JLPT N1，按课程目标自然练习。',route:['curriculum'],proposal:{id:'p1',expires_in:1800,changes:[{tool:'course.set',label:'日语课程',before:courses.ja,after:{mode:'ambient',preset:'jlpt-n1'}}]}};
    if(p.endsWith('/apply')) { courses.ja = {mode:'ambient',preset:'jlpt-n1'}; data = {status:'applied',tools:['course.set']}; }
    if(p === '/api/listening/options') data = {subscription:'claude',capabilities:{practice_difficulty:true,listening_sessions:true},synthesis:{en:true,ja:true},formats:[{id:'ja_gist',language:'ja',label:'概要理解'},{id:'en_talk',language:'en',label:'学术讲解'}],difficulties:[{id:'default',label:'跟随课程'},{id:'foundation',label:'基础'},{id:'challenge',label:'挑战'}],plans};
    if(p === '/api/listening/practices') data = {items:[]};
    if(p.startsWith('/api/listening/plans/')) { const lang = p.split('/').at(-1); plans[lang] = body; data = body; }
    if(p === '/api/listening/practice') return route.fulfill({status:503,json:{detail:'模拟出题连接失败，请重试。'}});
    return route.fulfill({json:data});
  });
  await page.goto('http://course.test/');
  const index = await fs.readFile(path.join(root,'frontend/index.html'),'utf8');
  for(const [,href] of index.matchAll(/<link rel="stylesheet" href="([^"]+)"/g)) await page.addStyleTag({url:'http://course.test/frontend/'+href});
  await page.addStyleTag({content:'html,body,#app-shell{height:100%;margin:0}#settings-root,#agent-root,#listen-root{height:100%}[hidden]{display:none!important}#chat-course{position:fixed;right:20px;bottom:10px;z-index:10}'});
  await page.addScriptTag({url:'http://course.test/frontend/js/api.js'});
  await page.evaluate(() => {
    const prefs = {chatLanguage:'ja',listeningLanguage:'ja'};
    Object.assign(LP,{state:{personas:[]},getPersona:()=>null,preferences:{get:key=>prefs[key],set:(key,value)=>{prefs[key]=value;return true;}},languages:{list:()=>[{tag:'ja',label:'日本語'},{tag:'en',label:'English'}],label:tag=>({ja:'日本語',en:'English'})[tag]||tag},toast:()=>{},studyStorage:{ready:async()=>{},getStatus:()=>({state:'ready'}),getListeningNotes:async()=>({text:'',revision:0}),saveListeningNotes:async()=>({revision:1})}});
    LP.appShell = {switchTab:tab=>{
      for(const [id,name] of [['settings-root','settings'],['agent-root','workspace-agent'],['listen-root','listening']]) document.getElementById(id).hidden = name !== tab;
      if(tab === 'workspace-agent') LP.workspaceAgent.mount(document.getElementById('agent-root'));
    },reloadPersonas:async()=>{}};
    Object.assign(LP.api,{getMainChat:async()=>({guests:[],fun_languages:[]}),getUsage:async()=>({})});
  });
  for(const js of ['util.js','actions.js','language-picker.js','language-drawer.js','settings-teaching.js','settings-providers.js','reading-preferences.js','conditions.js','settings-models.js','settings-lore.js','settings-hooks.js','settings-chat-room.js','settings.js','workspace-agent.js','listening.js']) await page.addScriptTag({url:'http://course.test/frontend/js/'+js});
  await page.evaluate(() => {
    LP.settings.mount(document.getElementById('settings-root')); LP.settings.open('library');
    const button = document.getElementById('chat-course');
    const paint = () => LP.settingsTeaching.paintChatButton(button,'ja'); document.addEventListener('lp:teaching-settings',paint); paint();
  });
  await page.getByRole('button',{name:'让管家做一门备考课',exact:true}).waitFor();
  assert.equal(await page.locator('[data-open-agent-library]').count(),0);
  // A settings handoff mounts the concierge before filling its composer.
  await page.getByRole('button',{name:'让管家做一门备考课',exact:true}).click();
  await page.waitForFunction(() => !document.querySelector('.workspace-agent-send').disabled);
  await page.locator('#workspace-agent-input').fill('把日语默认课程设为 JLPT N1，在聊天中练习。');
  assert.equal(await page.locator('.workspace-agent-library').count(),0);
  assert.equal(await page.getByRole('heading',{name:'课程管家',exact:true}).count(),1);
  await page.getByRole('button',{name:'发送',exact:true}).click();
  await page.getByRole('button',{name:'使用此安排'}).click();
  await page.getByText('已应用',{exact:true}).waitFor();
  await page.waitForFunction(() => document.getElementById('chat-course').textContent.includes('JLPT N1'));
  assert.equal(courses.ja.mode,'ambient');
  assert.equal(await page.locator('.workspace-agent-inspector').isHidden(),true);
  if(shots) await page.screenshot({path:path.join(shots,'concierge-conversation.png')});
  await page.locator('#chat-course').click();
  await page.getByRole('button',{name:/JLPT N2/}).click();
  await page.waitForFunction(() => document.getElementById('chat-course').textContent.includes('JLPT N2'));
  assert.equal(courses.ja.preset,'jlpt-n2');
  await page.evaluate(() => LP.settings.open('library'));
  // 世界书：改一条再保存，另一条原样带回去
  await page.locator('[data-course-tab=world]').click();
  await page.locator('.lore-entry-pick').filter({hasText:'雨天'}).click();
  await page.locator('.lore-entry.open textarea').first().fill('雨の日は、喫茶店で本を読む。');
  await page.getByRole('button',{name:'保存这本书',exact:true}).click();
  await page.waitForFunction(() => document.querySelector('.lore-savebar')?.hidden);
  await page.waitForTimeout(200);
  assert.equal(world.book.entries[0].content,'雨の日は、喫茶店で本を読む。');
  assert.equal(world.book.entries[1].content,'经常去街角的咖啡店。');
  assert.equal(world.book.entries[1].constant,true);
  await page.evaluate(() => { LP.appShell.switchTab('listening'); LP.listening.mount(document.getElementById('listen-root')); });
  const begin = page.getByRole('button',{name:'开始听',exact:true}); await begin.waitFor();
  await page.waitForFunction(() => !document.querySelector('.lp-listening-setup button[type=submit]').disabled);
  assert.equal(await page.locator('[data-listen=plan-fields]').isHidden(),true);
  assert.equal(await page.locator('.lp-listening-history').isHidden(),true);
  assert.equal(await page.locator('.lp-listening-notes').isHidden(),true);
  if(shots) await page.screenshot({path:path.join(shots,'listening-start.png')});
  await page.locator('.lp-more > summary').click();await page.locator('[data-listen=edit-plan]').click(); // 主题和难度在「⋯」里
  await page.locator('[data-listen=difficulty]').selectOption('foundation');
  await page.locator('[data-listen=topic]').fill('雨天的书店');
  await page.locator('[data-listen=save-plan]').click();
  await page.waitForFunction(() => document.querySelector('[data-listen=plan-fields]').hidden);
  assert.deepEqual(plans.ja,{format:'ja_gist',difficulty:'foundation',topic:'雨天的书店'});
  await begin.click(); await page.getByText('模拟出题连接失败，请重试。',{exact:true}).waitFor();
  assert.deepEqual(calls.find(item=>item.path==='/api/listening/practice').body,{language:'ja',format:'ja_gist',difficulty:'foundation',topic:'雨天的书店'});
  for(const view of ['settings','workspace-agent','listening']) {
    await page.evaluate(view=>LP.appShell.switchTab(view),view);
    for(const width of [1280,768,390]) {
      await page.setViewportSize({width,height:940});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,view+' overflow '+width);
      if(shots && width===390) await page.screenshot({path:path.join(shots,view+'-390.png')});
    }
  }
  assert.deepEqual(errors,[]);
  console.log('PASS concierge: chat proposal apply, default-course picker, world preservation, listening plan persistence, failure recovery, 390/768/1280 widths.');
} finally { await browser.close(); }
