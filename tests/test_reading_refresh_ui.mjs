import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const shots=process.env.LANGPAL_READING_SCREENSHOTS;
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1120,height:950}}),errors=[],calls=[];
 page.setDefaultTimeout(10000);page.on('pageerror',error=>errors.push(error.message));
 let style={size:17,line_height:1.85,measure:75,font:'serif',theme:'lilac'};
 const sources=[{id:'news',name:'Daily Science',kind:'article',lang:'en',format:'rss',enabled:true,builtin:true},{id:'papers',name:'Open Papers',kind:'paper',format:'json',enabled:true,builtin:false,fields:{},auth:{mode:'none'}}];
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname;
  assert.equal(url.hostname,'reading.test');
  if(p==='/')return route.fulfill({contentType:'text/html;charset=utf-8',body:'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><main id="settings-reader"><h1>阅读</h1><div id="habits"></div><div id="settings"></div></main><section id="sample"><span class="rd-unit">昨日は日本語の本を食べる。</span></section></html>'});
  if(p.startsWith('/frontend/'))return route.fulfill({path:path.join(root,p.slice(1)),contentType:p.endsWith('.css')?'text/css':'text/javascript'});
  calls.push({path:p,method:req.method(),body:req.method()==='GET'?undefined:req.postDataJSON()});
  let data={};
  if(p==='/api/reader/style'){if(req.method()==='PUT')style={...style,...req.postDataJSON()};data=style;}
  if(p==='/api/reader/sources')data={items:sources};
  if(p==='/api/reader/sources/test'){const src=req.postDataJSON().source;data=src.format==='rss'?{ok:true,count:5,items:[1,2,3,4,5].map(i=>({title:'Story '+i,url:'https://example.org/'+i,text:'Summary '+i}))}:{ok:false,count:0,items:[],message:'来源返回的格式与配置不符'};}
  if(p==='/api/reader/zotero/connection')data={port:23119,library:'users/0'};
  if(p==='/api/reader/options')data={sources,formats:[{id:'n1',name:'JLPT N1',language:'ja',builtin:true},{id:'close-reading',name:'Close reading',language:'en',min_length:150,max_length:250,question_count:4,builtin:false}],defaults:{}};
  if(p==='/api/reader/furigana')data={tokens:[{text:'昨日',reading:'きのう',parts:[{text:'昨日',reading:'きのう'}]},{text:'は',reading:'',parts:[{text:'は',reading:''}]},{text:'日本語',reading:'にほんご',parts:[{text:'日本語',reading:'にほんご'}]},{text:'の本を',reading:'',parts:[{text:'の本を',reading:''}]},{text:'食べる',reading:'たべる',parts:[{text:'食',reading:'た'},{text:'べる',reading:''}]},{text:'。',reading:'',parts:[{text:'。',reading:''}]}]};
  return route.fulfill({json:data});
 });
 await page.goto('http://reading.test/');
 for(const css of ['windose.css','reading.css','settings-reading.css'])await page.addStyleTag({url:'http://reading.test/frontend/css/'+css});
 await page.addStyleTag({content:'html,body{margin:0;background:#fcf9fd}#settings-reader{width:min(820px,100%);box-sizing:border-box;padding:30px 24px;margin:auto}#sample{padding:20px;max-width:800px;margin:auto;font:24px/2.3 system-ui}[hidden]{display:none!important}'});
 await page.evaluate(()=>window.LP={languages:{list:()=>[{tag:'en',label:'English'},{tag:'ja',label:'日本語'}],label:t=>({en:'English',ja:'日本語'})[t]||t},workspaceAgent:{prefill:text=>window.delegate=text},appShell:{switchTab:()=>{}}});
 for(const js of ['util.js','reader-style.js','furigana.js','reading-preferences.js','settings-sources.js','settings-reading.js'])await page.addScriptTag({url:'http://reading.test/frontend/js/'+js});
 await page.evaluate(()=>{
  document.querySelector('#habits').innerHTML=LP.readingPreferences.markup;
  LP.settingsReading.mount(document.querySelector('#settings'));
 });
 await page.getByRole('tabpanel').getByText('Daily Science',{exact:true}).waitFor();
 assert.equal(await page.locator('.reading-settings > details').count(),0);
 assert.equal(await page.locator('[data-reader-form=style] input[name=size]').inputValue(),'17');
 await page.locator('[data-reader-form=style] input[name=size]').evaluate(el=>{el.value='21';});
 await page.locator('[data-reader-form=style] input[name=size]').dispatchEvent('input');
 assert.equal(await page.locator('.reading-style-preview').evaluate(el=>el.style.getPropertyValue('--rd-size')),'21px');
 await page.getByRole('button',{name:'保存排版',exact:true}).click();
 await page.getByText('已保存排版',{exact:true}).waitFor();
 assert.equal(style.size,21);
 const widthBefore=await page.locator('.reading-preview-page').evaluate(el=>el.getBoundingClientRect().width);
 await page.locator('[data-reader-form=style] input[name=measure]').evaluate(el=>{el.value='44';el.dispatchEvent(new Event('input',{bubbles:true}));});
 assert((await page.locator('.reading-preview-page').evaluate(el=>el.getBoundingClientRect().width))<widthBefore);
 await page.getByRole('tab',{name:/题型/}).click();
 await page.getByRole('tabpanel').getByText('Close reading',{exact:true}).waitFor();
 await page.getByRole('button',{name:'＋ 自定义题型',exact:true}).click();
 await page.locator('[data-reader-form=format]').waitFor();
 await page.locator('[data-rs=cancel-format]').click();
 await page.getByRole('tab',{name:/来源/}).click();
 // 加来源：先只问地址，试一下就看到抓回来的前三条；内置来源只有开关
 await page.getByRole('tabpanel').getByText('Daily Science').waitFor();
 assert.equal(await page.locator('.src-row').filter({hasText:'Daily Science'}).getByRole('button',{name:'编辑'}).count(),0);
 await page.getByRole('button',{name:'＋ 添加文章来源',exact:true}).click();
 await page.fill('.src-url','https://news.example/feed');
 await page.locator('.src-url-row').getByRole('button',{name:'试一下'}).click();
 await page.waitForSelector('.src-sample');
 assert.equal(await page.locator('.src-sample').count(),3);
 assert.equal(calls.find(c=>c.path==='/api/reader/sources/test').body.source.format,'rss');
 assert.equal(await page.locator('.src-more').evaluate(n=>n.open),false);
 await page.locator('.src-bar').getByRole('button',{name:'取消'}).click();
 await page.getByRole('switch',{name:'汉字注音',exact:true}).check();
 assert.equal(await page.evaluate(()=>localStorage.getItem('jine.reader.furigana')),'true');
 await page.evaluate(()=>LP.furigana.decorate(document.querySelector('#sample .rd-unit')));
 assert.equal(await page.locator('#sample rt').count(),3);
 assert.equal(await page.evaluate(()=>LP.furigana.sourceText(document.querySelector('#sample'))),'昨日は日本語の本を食べる。');
 assert.equal(await page.evaluate(()=>LP.furigana.rangeText(LP.furigana.range(document.querySelector('#sample'),3,3))),'日本語');
 assert.equal(await page.locator('#sample ruby').first().getAttribute('data-surface'),'昨日');
 assert.equal(await page.evaluate(()=>document.querySelector('#sample').textContent.includes('きのう')),true);
 assert.equal(await page.evaluate(()=>LP.furigana.sourceText(document.querySelector('#sample')).includes('きのう')),false);
 if(shots)await page.screenshot({path:path.join(shots,'reading-settings-desktop.png')});
 for(const width of [768,390]) {await page.setViewportSize({width,height:950});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
 if(shots)await page.screenshot({path:path.join(shots,'reading-settings-mobile.png')});
 await page.evaluate(()=>LP.furigana.clear(document.querySelector('#sample .rd-unit')));
 assert.equal(await page.locator('#sample rt').count(),0);
 assert.equal(await page.locator('#sample').innerText(),'昨日は日本語の本を食べる。');
 assert.deepEqual(errors,[]);
 console.log('PASS reading refresh: flat tabs, live style preview, source wizard (address → three samples), custom format editor, persisted furigana, plain-source selection offsets, clearing and 390/768/1120 widths.');
}finally{await browser.close();}
