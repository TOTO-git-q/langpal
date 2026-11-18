import assert from 'node:assert/strict';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const {chromium}=await import(process.env.LANGPAL_PLAYWRIGHT_MODULE||'playwright-core');
const root=process.env.LANGPAL_SOURCE_ROOT||path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const python=process.env.LANGPAL_PYTHON||'python';
const sample='昨日は日本語を勉強しました。\n\n東京で本を読みました。';
const browser=await chromium.launch({executablePath:process.env.LANGPAL_CHROME_PATH,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1050,height:850}}),errors=[];
 page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await page.route('http://reader.test/**',async route=>{
  const req=route.request(),p=new URL(req.url()).pathname;
  if(p==='/api/reader/furigana') {
   const text=req.postDataJSON().text;
   const raw=execFileSync(python,['-c',"import sys,json;sys.path.insert(0,sys.argv[1]);from app.services.furigana import annotate;print(json.dumps({'tokens':annotate(sys.argv[2])}))",path.join(root,'backend'),text],{encoding:'utf8',env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
   return route.fulfill({json:JSON.parse(raw)});
  }
  if(p==='/api/reader/options')return route.fulfill({json:{sources:[],formats:[],defaults:{}}});
  if(p.startsWith('/api/'))return route.fulfill({json:{items:[]}});
  return route.fulfill({contentType:'text/html;charset=utf-8',body:'<!doctype html><html><meta charset="utf-8"><main id="reading-root" style="height:100vh"></main></html>'});
 });
 await page.goto('http://reader.test/');
 for(const css of ['windose.css','reading.css'])await page.addStyleTag({path:path.join(root,'frontend/css/'+css)});
 await page.evaluate(()=>{
  localStorage.setItem('jine.reader.furigana','true');
  window.savedNotes=[];window.wordCalls=[];
  window.LP={preferences:{get:key=>key==='readerLookup'?true:key==='readerLanguage'?'ja':undefined,set:()=>true},languages:{list:()=>[{tag:'ja',label:'日本語'}]},languageDrawer:{create:()=>({open(){}})},
   api:{explainWord:async body=>{wordCalls.push(body);return {lemma:body.lemma,reading:'にほんご',pos:'名詞',meaning_zh:'日语'};}},
   studyStorage:{listDocuments:async()=>[],getNotes:async()=>[],saveDocument:async()=>{},getStatus:()=>({state:'ready'}),saveNote:async(id,note)=>{savedNotes.push(note);return note;}}};
 });
 for(const js of ['util.js','furigana.js','reading.js'])await page.addScriptTag({path:path.join(root,'frontend/js/'+js)});
 await page.evaluate(()=>LP.reading.mount(document.querySelector('main')));
 await page.locator('[data-rd=file]').setInputFiles({name:'日本語.txt',mimeType:'text/plain',buffer:Buffer.from(sample)});
 // 注音由测试里现起的 Python 分词进程给，冷启动一次要十来秒；只放宽这一步的等待
 await page.locator('.rd-prose ruby').first().waitFor({timeout:60000});
 assert.equal(await page.evaluate(()=>LP.furigana.sourceText(document.querySelector('.rd-prose'))),sample.replace('\n\n',''));
 const quote=await page.evaluate(()=>{
  const paragraph=document.querySelector('.rd-prose p'),range=LP.furigana.range(paragraph,3,3),selection=getSelection();selection.removeAllRanges();selection.addRange(range);
  document.querySelector('.rd-body').dispatchEvent(new PointerEvent('pointerup',{bubbles:true}));return LP.furigana.rangeText(range);
 });
 assert.equal(quote,'日本語');
 await page.locator('[data-rd=annotate]').click();
 await page.getByRole('textbox',{name:'批注内容',exact:true}).fill('记住这个词');
 await page.getByRole('button',{name:'保存批注',exact:true}).click();
 await page.waitForFunction(()=>savedNotes.length===1);
 assert.equal(await page.evaluate(()=>savedNotes[0].quote),'日本語');
 assert.deepEqual(await page.evaluate(()=>savedNotes[0].anchor),{paragraph:0,start:3,length:3});
 assert.equal(await page.evaluate(()=>LP.furigana.rangeText([...CSS.highlights.get('jine-notes')][0])),'日本語');
 await page.locator('[data-rd=close-sheet]').click();
 await page.evaluate(()=>getSelection().removeAllRanges());
 await page.locator('ruby[data-surface="日本語"] rb').click();
 await page.waitForFunction(()=>wordCalls.length===1);
 assert.equal(await page.evaluate(()=>wordCalls[0].surface),'日本語');
 assert.equal(await page.evaluate(()=>wordCalls[0].sentence),'昨日は日本語を勉強しました。');
 await page.locator('[data-rd=close-sheet]').click();
 const copy=await page.evaluate(()=>{
  const range=LP.furigana.range(document.querySelector('.rd-prose p'),0,15),selection=getSelection();selection.removeAllRanges();selection.addRange(range);
  const clipboard=new DataTransfer();document.querySelector('.rd-body').dispatchEvent(new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:clipboard}));return clipboard.getData('text/plain');
 });
 assert.equal(copy,'昨日は日本語を勉強しました。');
 await page.locator('[data-rd=furigana]').click();
 await page.waitForFunction(()=>!document.querySelector('.rd-prose rt'));
 assert.equal(await page.locator('[data-rd=furigana]').getAttribute('aria-pressed'),'false');
 assert.equal(await page.evaluate(()=>LP.furigana.rangeText([...CSS.highlights.get('jine-notes')][0])),'日本語');
 assert.deepEqual(errors,[]);
 console.log('PASS real dictionary + full reader: ruby display, lookup source, annotation offsets/highlight, plain-text copy, toggle off and retained notes.');
}finally{await browser.close();}
